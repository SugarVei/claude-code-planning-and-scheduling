"""指标计算与批量实验（Stage 6 (c)(d)）。

指标（滚动全程累计）：
  总成本 = 库存 + 延期 + 设置（Stage 6 任务口径，不含生产变动成本；
  设置按"当期有产则计一次 g_p"报告口径）；调度可行率 = 有工件周期中
  冻结方案可接受（ρ≥ρ_min 且 C_max≤T^avail）的比例；平均反馈迭代次数
  = k* 均值；订单准时率 = 交付期内累计供给覆盖到该订单的比例（族内按
  交付期先后 FIFO 覆盖；数据无"关键订单"标记，故对全部订单统计）；
  加班时长 = Σ_τ OT(冻结方案)。
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from src.data.problem_data import ProblemData
from src.experiments.schemes import run_scheme
from src.feedback.channels import FeedbackConfig
from src.rolling.controller import RollingResult, run_rolling
from src.scheduling.base import SchedulerAdapter


@dataclass(frozen=True)
class SchemeMetrics:
    """一次完整滚动运行的指标汇总。"""

    label: str
    holding_cost: float
    backlog_cost: float
    setup_cost: float
    total_cost: float          # 库存+延期+设置
    feasible_rate: float       # 调度可行率
    avg_iterations: float      # 平均反馈迭代次数 k*
    on_time_rate: float        # 订单准时率
    total_overtime: float      # Σ OT
    terminal_backlog: float    # T_max 末欠交总量


def order_on_time_rate(problem: ProblemData, result: RollingResult) -> float:
    """订单准时：族内按（交付期, 订单号）FIFO，交付期末累计供给 ≥ 累计需求。"""
    frozen = {pr.tau: pr.frozen_q for pr in result.periods}
    on_time = 0
    for p in problem.products:
        orders_p = sorted(
            (o for o in problem.orders if o.product == p),
            key=lambda o: (o.due_period, o.order_id),
        )
        cum_demand = 0.0
        for o in orders_p:
            cum_demand += o.quantity
            supply = problem.init_inventory[p] + sum(
                frozen[t][p] for t in problem.periods if t <= o.due_period
            )
            if supply >= cum_demand - 1e-9:
                on_time += 1
    return on_time / len(problem.orders)


def compute_metrics(
    problem: ProblemData, result: RollingResult, label: str
) -> SchemeMetrics:
    holding = sum(
        problem.cost_inv[p] * pr.inv_after[p]
        for pr in result.periods
        for p in problem.products
    )
    backlog = sum(
        problem.cost_back[p] * pr.back_after[p]
        for pr in result.periods
        for p in problem.products
    )
    setup = sum(
        problem.cost_setup[p]
        for pr in result.periods
        for p in problem.products
        if pr.frozen_q.get(p, 0) > 0
    )
    with_jobs = [pr for pr in result.periods if any(pr.frozen_q.values())]
    feasible = [
        pr
        for pr in with_jobs
        if pr.schedule.rho >= problem.rho_min
        and pr.schedule.cmax <= problem.t_avail + 1e-9
    ]
    return SchemeMetrics(
        label=label,
        holding_cost=holding,
        backlog_cost=backlog,
        setup_cost=setup,
        total_cost=holding + backlog + setup,
        feasible_rate=len(feasible) / len(with_jobs) if with_jobs else 1.0,
        avg_iterations=sum(pr.k_star for pr in result.periods) / len(result.periods),
        on_time_rate=order_on_time_rate(problem, result),
        total_overtime=sum(pr.schedule.ot for pr in result.periods),
        terminal_backlog=sum(result.terminal_back.values()),
    )


def run_scheme_comparison(
    problem: ProblemData, scheduler: SchedulerAdapter, base_seed: int = 0
) -> tuple[dict[str, RollingResult], dict[str, SchemeMetrics]]:
    """方案 A~D 对比（表5-1 数据源）。"""
    results, metrics = {}, {}
    for scheme in ("A", "B", "C", "D"):
        results[scheme] = run_scheme(problem, scheduler, scheme, base_seed)
        metrics[scheme] = compute_metrics(problem, results[scheme], f"方案{scheme}")
    return results, metrics


ABLATION_CONFIGS: dict[str, FeedbackConfig] = {
    "完整三通道": FeedbackConfig(),
    "去成本修正": FeedbackConfig(cost_correction=False),
    "去有效产能": FeedbackConfig(effective_capacity=False),
    "去不可行割": FeedbackConfig(infeasible_cuts=False),
}


def run_ablation(
    problem: ProblemData, scheduler: SchedulerAdapter, base_seed: int = 0
) -> dict[str, SchemeMetrics]:
    """单通道消融（表5-2 数据源）：FeedbackConfig 一键配置。"""
    return {
        label: compute_metrics(
            problem,
            run_rolling(problem, scheduler, config, base_seed=base_seed),
            label,
        )
        for label, config in ABLATION_CONFIGS.items()
    }


def run_weight_sensitivity(
    problem: ProblemData,
    scheduler: SchedulerAdapter,
    weight_sets: list[tuple[float, float, float]],
    base_seed: int = 0,
) -> dict[str, SchemeMetrics]:
    """代表解权重敏感性（表5-3 数据源）：替换 (ω_C,ω_L,ω_E) 重跑方案 C。"""
    out = {}
    for w in weight_sets:
        label = f"ω=({w[0]:.2f},{w[1]:.2f},{w[2]:.2f})"
        variant = dataclasses.replace(problem, feedback_weights=w)
        out[label] = compute_metrics(
            variant,
            run_rolling(variant, scheduler, FeedbackConfig(), base_seed=base_seed),
            label,
        )
    return out
