"""滚动主循环（算法5-1：计划 → 子批化 → 调度 → 反馈 → 冻结/滚动）。

完全由 ProblemData 驱动：H_w、H_f(=1，式3-15)、K_max、ε_P、N_restart、
权重、κ、γ、δ^max、ρ_min 全部来自数据；调度器经 SchedulerAdapter 注入。

单滚动周期 τ 流程（§3.5.2/式3-16）：
  k=0..K_max：
    计划层 MILP（窗口 R_τ，式3-30；反馈参数仅更新 t=τ 项，t>τ 沿用上轮，
    式5-7/5-8 口径=A08）→ 子批化（式3-25/3-26）→ N_restart 次重启调度 →
    合并前沿取代表解（§5.3）→ 反馈折算（通道1/2 无论冻结与否均计算记录，
    A07 口径）→ 冻结四条件核查（式3-19~3-22，k=0 稳定性默认满足=A09）：
      通过 → 冻结；k=K_max 且必要条件(3-19)(3-20)成立 → 强制冻结（3-23
      保护条件：不以 K_max 冻结不可行方案）；k=K_max 且不可接受 →
      K_max 保护处理（算法5-1 第23~32行：按 b_p 升序/β 降序逐子批移出
      并重排，直至可接受；移出量经式3-9 化为欠交，订单登记 O^unfin）；
      否则按 FeedbackConfig 应用三通道反馈进入 k+1。
  冻结后：式(3-9) 状态更新（正库存先冲抵欠交）；割池清空（ℋ_{τ+1}^{(0)}=∅）。

通道开关：FeedbackConfig 三通道独立开关；被禁用的通道在将要生效时
写日志明确记录（验收要求）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.data.lot_sizing import build_jobs
from src.data.problem_data import ProblemData
from src.feedback.channels import ChannelComputation, FeedbackConfig, compute_channels
from src.feedback.cuts import CutDecision, InfeasibleCutPool, evaluate_cut_criterion
from src.feedback.protection import kmax_removal_order, update_state
from src.feedback.representative import RepresentativeResult, select_representative
from src.planning.milp_model import PlanningInputs, PlanningSolution, solve_planning
from src.scheduling.base import (
    ScheduleSolution,
    SchedulerAdapter,
    is_feasible_flag,
    nondominated_filter,
)

logger = logging.getLogger("rolling")


def _empty_schedule(problem: ProblemData) -> ScheduleSolution:
    """当期无工件时的空调度（平凡可接受）。"""
    return ScheduleSolution(
        cmax=0.0,
        lc=0.0,
        energy=0.0,
        theta_stage={j: 0.0 for j in problem.stages},
        ot=0.0,
        rho=1.0,
    )


@dataclass
class FreezeCheck:
    """冻结四条件核查记录（式3-19~3-22，A09）。"""

    feas_ok: bool          # (3-19) Feas=1
    cmax_ok: bool          # (3-20) C_max ≤ T^avail
    no_new_cuts: bool      # (3-21) Δℋ^(k)=∅
    stable: bool           # (3-22) |ΔZ|/(1+|Z|) ≤ ε_P（k=0 默认满足）
    frozen: bool
    kmax_forced: bool = False  # (3-23)：K_max 时必要条件成立、稳定性豁免


@dataclass
class IterationRecord:
    """一次反馈迭代 k 的完整记录。"""

    tau: int
    k: int
    plan_inputs: PlanningInputs
    plan: PlanningSolution
    q_tau: dict[str, int]
    restart_reps: list[RepresentativeResult]
    representative: RepresentativeResult | None  # 合并前沿上的代表解（无工件时 None）
    schedule: ScheduleSolution
    feas: int
    channels: ChannelComputation | None          # 通道1/2 折算记录（计算必做）
    cut_decision: CutDecision | None             # 通道3判据（仅不可接受时评估）
    new_cuts: frozenset                          # 本轮 Δℋ^(k)
    freeze: FreezeCheck


@dataclass
class PeriodResult:
    """一个滚动周期 τ 的冻结结果。"""

    tau: int
    iterations: list[IterationRecord]
    k_star: int
    frozen_q: dict[str, int]
    schedule: ScheduleSolution
    protection_events: list[tuple[str, int]]  # K_max 保护移出的 (产品, 子批量)
    unfin_orders: set[str]                    # O_τ^unfin（订单编号，不重复计数）
    inv_after: dict[str, float]
    back_after: dict[str, float]


@dataclass
class RollingResult:
    """全滚动过程结果。"""

    periods: list[PeriodResult] = field(default_factory=list)

    def period(self, tau: int) -> PeriodResult:
        return next(p for p in self.periods if p.tau == tau)

    @property
    def terminal_back(self) -> dict[str, float]:
        return self.periods[-1].back_after

    @property
    def terminal_inv(self) -> dict[str, float]:
        return self.periods[-1].inv_after


def run_rolling(
    problem: ProblemData,
    scheduler: SchedulerAdapter,
    config: FeedbackConfig = FeedbackConfig(),
    base_seed: int = 0,
    force_freeze_k0: bool = False,
) -> RollingResult:
    """执行完整滚动闭环（τ = 1..T_max，H_f=1 逐周期冻结）。

    force_freeze_k0=True：k=0 计划无条件冻结（不做反馈迭代与保护处理），
    即实验方案 B"滚动但无反馈"；通常与全关 FeedbackConfig 搭配。
    """
    inv = {p: float(problem.init_inventory[p]) for p in problem.products}
    back = {p: 0.0 for p in problem.products}
    result = RollingResult()

    for tau in problem.periods:
        window = tuple(
            range(tau, min(tau + problem.horizon_window - 1, problem.t_max) + 1)
        )
        demand = problem.demand_at(tau)  # D^{(τ)}（式3-3，动态到达）
        pool = InfeasibleCutPool()
        delta_c: dict[tuple[str, int], float] = {}   # 仅 (p, τ) 项被更新（A08）
        cap_eff: dict[tuple[int, int], float] = {}   # 仅 (j, τ) 项被更新（A08）
        prev_delta_c_tau = {p: 0.0 for p in problem.products}
        lc_base: float | None = None
        e_base: float | None = None
        prev_z: float | None = None
        iterations: list[IterationRecord] = []
        protection_events: list[tuple[str, int]] = []
        unfin: set[str] = set()
        frozen_record: IterationRecord | None = None

        for k in range(0, problem.k_max + 1):
            inputs = PlanningInputs(
                window=window,
                demand=demand,
                inv0=dict(inv),
                back0=dict(back),
                delta_c=dict(delta_c),
                cap_eff=dict(cap_eff),
                cuts=pool.cuts_for(tau),
            )
            plan = solve_planning(problem, inputs)
            q_tau = {p: plan.q[p][tau] for p in problem.products}
            jobs = build_jobs(problem, q_tau)

            seeds = [base_seed * 1009 + tau * 101 + k * 11 + r for r in range(problem.n_restart)]
            if jobs:
                fronts = [scheduler.solve(problem, jobs, tau, seed=s) for s in seeds]
                restart_reps = [select_representative(problem, f) for f in fronts]
                union = nondominated_filter([s for f in fronts for s in f])
                rep = select_representative(problem, union)
                sched = rep.solution
            else:
                fronts, restart_reps, rep = [], [], None
                sched = _empty_schedule(problem)
            feas = is_feasible_flag(problem, sched.rho)

            # ── 反馈折算（通道1/2）：无论是否冻结都计算并记录（A07 口径）──
            if lc_base is None:
                lc_base, e_base = sched.lc, sched.energy  # k=0 增量基线
            channels = compute_channels(
                problem, tau, q_tau, sched, prev_delta_c_tau, lc_base, e_base
            )

            # ── 通道3：仅在无可接受解时评估三步判据 ──
            cut_decision: CutDecision | None = None
            new_cuts: frozenset = frozenset()
            unacceptable = rep is None or rep.is_fallback
            if jobs and unacceptable:
                if config.infeasible_cuts:
                    cut_decision = evaluate_cut_criterion(
                        problem,
                        tau,
                        q_tau,
                        scheduler,
                        cap_eff_row={
                            j: cap_eff.get((j, tau), problem.capacity[j][tau])
                            for j in problem.stages
                        },
                        seeds=seeds,
                        restart_reps=restart_reps,
                    )
                    if cut_decision.generated:
                        existing = {c for c, _ in pool.cuts_for(tau)}
                        new_cuts = frozenset({cut_decision.combo} - existing)
                else:
                    logger.info("τ=%d k=%d：通道3(不可行组合割)已禁用，跳过割判据", tau, k)

            # ── 冻结四条件（式3-19~3-22；k=0 稳定性默认满足）──
            z = plan.objective
            stable = True if prev_z is None else (
                abs(z - prev_z) / (1 + abs(prev_z)) <= problem.epsilon_converge
            )
            feas_ok = feas == 1
            cmax_ok = sched.cmax <= problem.t_avail + 1e-9
            no_new_cuts = len(new_cuts) == 0
            frozen = feas_ok and cmax_ok and no_new_cuts and stable
            kmax_forced = False
            if not frozen and k == problem.k_max and feas_ok and cmax_ok and no_new_cuts:
                # (3-23)：K_max 保护条件——必要条件成立时强制冻结（稳定性豁免）
                frozen, kmax_forced = True, True

            record = IterationRecord(
                tau=tau, k=k, plan_inputs=inputs, plan=plan, q_tau=dict(q_tau),
                restart_reps=restart_reps, representative=rep, schedule=sched,
                feas=feas, channels=channels, cut_decision=cut_decision,
                new_cuts=new_cuts,
                freeze=FreezeCheck(feas_ok, cmax_ok, no_new_cuts, stable, frozen, kmax_forced),
            )
            iterations.append(record)
            if force_freeze_k0:
                record.freeze.frozen = True
                frozen_record = record
                break
            if frozen:
                frozen_record = record
                break
            if k == problem.k_max:
                break  # 仍不可接受 → 转 K_max 保护处理

            # ── 应用反馈进入 k+1 ──
            # §3.5.3：仅当调度不可接受时反馈返回计划层（可接受但未稳定时
            # 参数保持不变，下一轮复核即稳定）。
            # 通道按诊断类型分派（金标 '5_预期行为轨迹'/'8_P1判据歧义' 口径）：
            # 结构型（本轮新生成割）→ 仅通道3；加班/负荷型 → 通道1+2。
            if not (feas_ok and cmax_ok):
                if new_cuts:
                    pool.accumulate(set(new_cuts))  # 结构型：割修正可行域
                else:
                    if config.cost_correction:
                        for p in problem.products:
                            delta_c[(p, tau)] = channels.delta_c_next[p]
                        prev_delta_c_tau = dict(channels.delta_c_next)
                    else:
                        logger.info("τ=%d k=%d：通道1(成本修正Δc)已禁用，跳过更新", tau, k)
                    if config.effective_capacity:
                        for j in problem.stages:
                            cap_eff[(j, tau)] = channels.cap_eff_next[j]
                    else:
                        logger.info("τ=%d k=%d：通道2(有效产能Cap^eff)已禁用，跳过更新", tau, k)
            prev_z = z

        # ── K_max 保护处理（算法5-1 第23~32行）──
        if frozen_record is None:
            last = iterations[-1]
            q_tau = dict(last.q_tau)
            sched = last.schedule
            logger.warning("τ=%d：k=K_max=%d 仍不可接受，触发保护处理", tau, problem.k_max)
            for product, lot in kmax_removal_order(problem, q_tau):
                q_tau[product] -= lot
                protection_events.append((product, lot))
                jobs = build_jobs(problem, q_tau)
                if not jobs:
                    sched = _empty_schedule(problem)
                    break
                front = scheduler.solve(problem, jobs, tau, seed=base_seed * 1009 + tau * 101 + 999)
                rep = select_representative(problem, front)
                sched = rep.solution
                if (not rep.is_fallback) and sched.cmax <= problem.t_avail + 1e-9:
                    break  # 移出后可接受 → 冻结
            frozen_q = q_tau
            k_star = problem.k_max
        else:
            frozen_q = frozen_record.q_tau
            sched = frozen_record.schedule
            k_star = frozen_record.k

        # ── 冻结执行 → 式(3-9) 状态更新 → 滚动 ──
        demand_tau = {p: demand[p][tau] for p in problem.products}
        inv, back = update_state(problem, inv, back, frozen_q, demand_tau)
        # 保护处理移出的量形成欠交 → 登记未完成订单（由迟到期订单向前覆盖）
        for product in {p for p, _ in protection_events}:
            unfin |= _register_unfin(problem, product, tau, back[product])
        pool.clear_after_freeze()  # ℋ_{τ+1}^{inf,(0)} = ∅

        result.periods.append(
            PeriodResult(
                tau=tau, iterations=iterations, k_star=k_star, frozen_q=frozen_q,
                schedule=sched, protection_events=protection_events,
                unfin_orders=unfin, inv_after=dict(inv), back_after=dict(back),
            )
        )
    return result


def _register_unfin(
    problem: ProblemData, product: str, tau: int, back_amount: float
) -> set[str]:
    """O^unfin 登记：产品 product 截至 τ 的欠交量由交付期最晚的订单向前覆盖，
    登记订单编号（集合语义，不重复计数）。"""
    if back_amount <= 0:
        return set()
    candidates = [
        o
        for o in problem.orders
        if o.product == product and o.arrival_period <= tau and o.due_period <= tau
    ]
    candidates.sort(key=lambda o: (o.due_period, o.order_id), reverse=True)
    registered: set[str] = set()
    remaining = back_amount
    for o in candidates:
        if remaining <= 0:
            break
        registered.add(o.order_id)
        remaining -= o.quantity
    return registered
