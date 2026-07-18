"""实验方案 A~D（docs/SYSTEM_DESIGN.md §6 Stage 6 (b)）。

  A 传统两阶段：τ=1 一次性全期计划（仅当时已知订单），逐期执行与排产，
    不滚动重规划、无反馈——动态到达订单只进入状态核算，暴露静态计划缺陷；
  B 滚动无反馈：逐期滚动重规划（含动态订单），k=0 计划无条件冻结；
  C 完整三通道：滚动 + 三通道反馈闭环（本文机制）；
  D 消融：去成本修正通道（FeedbackConfig(cost_correction=False)）。
"""
from __future__ import annotations

from src.data.lot_sizing import build_jobs
from src.data.problem_data import ProblemData
from src.feedback.channels import FeedbackConfig
from src.feedback.representative import select_representative
from src.planning.milp_model import PlanningInputs, solve_planning
from src.rolling.controller import (
    PeriodResult,
    RollingResult,
    _empty_schedule,
    run_rolling,
)
from src.scheduling.base import SchedulerAdapter, nondominated_filter
from src.feedback.protection import update_state

SCHEMES = ("A", "B", "C", "D")


def run_scheme_a(
    problem: ProblemData, scheduler: SchedulerAdapter, base_seed: int = 0
) -> RollingResult:
    """方案 A：静态全期计划一次求解，逐期执行，无重规划无反馈。"""
    inputs = PlanningInputs(
        window=tuple(problem.periods), demand=problem.demand_at(1)
    )
    plan = solve_planning(problem, inputs)
    inv = {p: float(problem.init_inventory[p]) for p in problem.products}
    back = {p: 0.0 for p in problem.products}
    result = RollingResult()
    for tau in problem.periods:
        q_tau = {p: plan.q[p][tau] for p in problem.products}
        jobs = build_jobs(problem, q_tau)
        if jobs:
            front = scheduler.solve(
                problem, jobs, tau, seed=base_seed * 1009 + tau * 101
            )
            sched = select_representative(problem, nondominated_filter(front)).solution
        else:
            sched = _empty_schedule(problem)
        demand_tau = {
            p: problem.demand_at(tau)[p][tau] for p in problem.products
        }  # 实际到达需求进入状态核算
        inv, back = update_state(problem, inv, back, q_tau, demand_tau)
        result.periods.append(
            PeriodResult(
                tau=tau, iterations=[], k_star=0, frozen_q=q_tau, schedule=sched,
                protection_events=[], unfin_orders=set(),
                inv_after=dict(inv), back_after=dict(back),
            )
        )
    return result


def run_scheme(
    problem: ProblemData,
    scheduler: SchedulerAdapter,
    scheme: str,
    base_seed: int = 0,
) -> RollingResult:
    """按方案代号运行（A/B/C/D）。"""
    if scheme == "A":
        return run_scheme_a(problem, scheduler, base_seed)
    if scheme == "B":
        return run_rolling(
            problem, scheduler, FeedbackConfig(False, False, False),
            base_seed=base_seed, force_freeze_k0=True,
        )
    if scheme == "C":
        return run_rolling(problem, scheduler, FeedbackConfig(), base_seed=base_seed)
    if scheme == "D":
        return run_rolling(
            problem, scheduler, FeedbackConfig(cost_correction=False),
            base_seed=base_seed,
        )
    raise ValueError(f"未知方案 {scheme}（可选 A/B/C/D）")
