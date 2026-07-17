"""通道3：不可行组合割的三步生成判据（§5.2.1/式5-6）+ 割池生命周期（式5-10）。

三步判据（金标 '8_P1判据歧义' 确定的可计算口径）：
  ① 重启检验：N_restart 次不同随机种子求解，全部无可接受代表解
     （Ω^acc=∅，即代表解走兜底分支）才继续；任一重启可接受 → 不生成割；
  ② 负荷排除：若任一阶段聚合负荷 Σ_p a_{p,j}·q_p 超过当前 Cap^eff_{j,τ}
     → 负荷型不可行，改走通道1/2，不生成割；
  ②′ 加班型排除守卫（§2.2，P1 建议规则）：若最优重启的代表解
     OT^{*,(k)} ≤ OT^max（等价 ρ^{*,(k)} > 0）→ 加班可覆盖，判加班型，
     仅走通道1/2，不进入单产品移除测试；
  ③ 单产品移除测试：对每个活跃产品 p，移除其全部子批后重排产，若变为
     可接受则 p ∈ S；S ≠ ∅ → 生成割 C = S（式5-9：Σ_{p∈C} Y_{p,τ} ≤ |C|−1）。

V-toy-1 预期：τ=1（OT≈29~90 ≤ 120）在 ②′ 被排除，不生成割；
τ=3（OT ≥ 198 > 120）进入 ③，S={B,C} → 割 Y_B+Y_C ≤ 1。

割池（式5-10 与清零机制）：周期内累积（并集去重），冻结后清空——
ℋ_{τ+1}^{inf,(0)} = ∅，不跨周期继承（论文 §5.2.2 工程观察）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.data.lot_sizing import build_jobs
from src.data.problem_data import ProblemData
from src.feedback.representative import select_representative
from src.scheduling.base import SchedulerAdapter


@dataclass(frozen=True)
class CutDecision:
    """三步判据的结论与全部中间量（供验证报告/论文 §5.2.1 回填）。"""

    generated: bool
    combo: frozenset[str]        # 生成的割组合 C（未生成时为空）
    reason: str                  # acceptable | load_type | overtime_type | structural | no_single_removal
    diagnostics: dict            # restarts/loads/removal 中间量


def evaluate_cut_criterion(
    problem: ProblemData,
    tau: int,
    q_tau: dict[str, int],
    scheduler: SchedulerAdapter,
    cap_eff_row: dict[int, float] | None = None,
    seeds: list[int] | None = None,
) -> CutDecision:
    """对当前待冻结周期 τ 的计划量 q_τ 执行三步割生成判据。"""
    seeds = seeds if seeds is not None else list(range(1, problem.n_restart + 1))
    cap_row = {
        j: (cap_eff_row or {}).get(j, problem.capacity[j][tau])
        for j in problem.stages
    }
    active = [p for p in problem.products if q_tau.get(p, 0) > 0]
    jobs = build_jobs(problem, q_tau)
    diag: dict = {"tau": tau, "q_tau": dict(q_tau), "seeds": list(seeds)}

    # ── ① N_restart 重启检验 ──
    restarts = []
    for s in seeds:
        front = scheduler.solve(problem, jobs, tau, seed=s)
        rep = select_representative(problem, front)
        restarts.append(
            {
                "seed": s,
                "cmax": rep.solution.cmax,
                "ot": rep.solution.ot,
                "rho": rep.solution.rho,
                "fallback": rep.is_fallback,
            }
        )
    diag["restarts"] = restarts
    if any(not r["fallback"] for r in restarts):
        return CutDecision(False, frozenset(), "acceptable", diag)

    # ── ② 负荷排除 ──
    loads = {
        j: sum(problem.proc_time[p][j] * q_tau.get(p, 0) for p in active)
        for j in problem.stages
    }
    diag["stage_loads"] = loads
    diag["cap_eff_row"] = cap_row
    if any(loads[j] > cap_row[j] + 1e-9 for j in problem.stages):
        return CutDecision(False, frozenset(), "load_type", diag)

    # ── ②′ 加班型排除守卫（§2.2）──
    best_ot = min(r["ot"] for r in restarts)
    diag["best_ot"] = best_ot
    diag["ot_max"] = problem.ot_max
    if best_ot <= problem.ot_max:
        return CutDecision(False, frozenset(), "overtime_type", diag)

    # ── ③ 单产品移除测试 ──
    removal: dict[str, dict] = {}
    s_set: set[str] = set()
    for p in active:
        q_without = {**q_tau, p: 0}
        jobs_without = build_jobs(problem, q_without)
        if not jobs_without:
            removal[p] = {"acceptable": True, "cmax": 0.0}
            s_set.add(p)
            continue
        front = scheduler.solve(problem, jobs_without, tau, seed=seeds[0])
        rep = select_representative(problem, front)
        removal[p] = {
            "acceptable": not rep.is_fallback,
            "cmax": rep.solution.cmax,
            "rho": rep.solution.rho,
        }
        if not rep.is_fallback:
            s_set.add(p)
    diag["removal_tests"] = removal
    if s_set:
        return CutDecision(True, frozenset(s_set), "structural", diag)
    return CutDecision(False, frozenset(), "no_single_removal", diag)


@dataclass
class InfeasibleCutPool:
    """ℋ_τ^{inf,(k)}：周期内累积（式5-10），冻结后清空（ℋ_{τ+1}^{inf,(0)}=∅）。"""

    _combos: set[frozenset[str]] = field(default_factory=set)

    def accumulate(self, delta: set[frozenset[str]]) -> None:
        """式(5-10)：ℋ^{(k+1)} = ℋ^{(k)} ∪ Δℋ^{(k)}（并集，天然去重）。"""
        self._combos |= delta

    def cuts_for(self, tau: int) -> tuple[tuple[frozenset[str], int], ...]:
        """转为计划层 PlanningInputs.cuts 形式：割仅作用于当前周期 τ（式5-9）。"""
        return tuple((combo, tau) for combo in sorted(self._combos, key=sorted))

    def clear_after_freeze(self) -> None:
        """周期冻结后清空——不可行组合不跨周期继承。"""
        self._combos.clear()

    def __len__(self) -> int:
        return len(self._combos)
