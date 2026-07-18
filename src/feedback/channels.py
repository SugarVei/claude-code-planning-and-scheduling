"""三通道反馈折算（论文 §5.2.1：式5-1~5-5）+ 三通道独立开关 FeedbackConfig。

通道1 成本修正 Δc（式5-1~5-3，金标增量口径）：
  L_p（式5-1）= 代表解中产品 p 全阶段加工时间和；χ_p（式5-2）= 负荷占比；
  Δĉ_p = χ_p/(q_p+ε) × [κ_C·OT + κ_L·max{0,LC−LC_base} + κ_E·max{0,E−E_base}
         + κ_S·Θ]（κ_L/κ_E 作用于相对 k=0 基线的增量，金标 '1_系统与算法参数'
         注记与 A06 口径；论文式(5-3) 字面为全量，以金标为准）；
  Δc^(k+1) = (1−γ)·Δc^(k) + γ·Δĉ，且 ≤ δ^max·c_p（阻尼与封顶，A06）。
通道2 有效产能（式5-5）：
  η_τ^skill = min{1, 当期可用工人总数 / 全车间机器总数}（金标 τ=2 机关定义式：
  4/5=0.8）；Cap_j^eff,(k+1) = max{0, Cap_j^nom·η − Θ_j^{sdst,*(k)}}。
通道3 不可行组合割：见 src/feedback/cuts.py（三步判据+加班型守卫）。
"""
from __future__ import annotations

from dataclasses import dataclass

from src.data.problem_data import ProblemData
from src.scheduling.base import ScheduleSolution

_EPS = 1e-9


@dataclass(frozen=True)
class FeedbackConfig:
    """三通道独立开关（消融实验直接使用，docs/SYSTEM_DESIGN.md §4）。"""

    cost_correction: bool = True     # 通道1：成本修正 Δc
    effective_capacity: bool = True  # 通道2：有效产能 Cap^eff
    infeasible_cuts: bool = True     # 通道3：不可行组合割 Δℋ


@dataclass(frozen=True)
class ChannelComputation:
    """一次反馈迭代的通道1/2折算记录（无论是否被应用都完整记录）。"""

    chi: dict[str, float]           # χ_{p,τ}（式5-2），Σ=1（活跃产品上）
    lc_inc: float                   # max{0, LC − LC_base}
    e_inc: float                    # max{0, E − E_base}
    pooled_cost: float              # κ_C·OT + κ_L·lc_inc + κ_E·e_inc + κ_S·Θ
    delta_c_hat: dict[str, float]   # Δĉ_{p}（式5-3）
    delta_c_next: dict[str, float]  # Δc^{(k+1)}（阻尼+封顶后）
    eta: float                      # η_τ^skill
    cap_eff_next: dict[int, float]  # Cap_j^eff,(k+1)（式5-5）


def compute_channels(
    problem: ProblemData,
    tau: int,
    q_tau: dict[str, int],
    rep: ScheduleSolution,
    prev_delta_c: dict[str, float],
    lc_base: float,
    e_base: float,
) -> ChannelComputation:
    """按式(5-1)~(5-5) 折算通道1/2 的下一轮参数。"""
    # 式(5-1)：L_p = 代表解中产品 p 的全阶段加工时间（工序表 processing 段）
    load: dict[str, float] = {p: 0.0 for p in problem.products}
    for op in rep.operations:
        load[op.product] += op.end - op.setup_end
    total = sum(load.values()) + _EPS
    chi = {p: load[p] / total for p in problem.products}

    # 式(5-3)：周期级聚合代价 → 产品-周期粒度（κ_L/κ_E 增量口径）
    lc_inc = max(0.0, rep.lc - lc_base)
    e_inc = max(0.0, rep.energy - e_base)
    pooled = (
        problem.kappa_c * rep.ot
        + problem.kappa_l * lc_inc
        + problem.kappa_e * e_inc
        + problem.kappa_s * rep.theta_total
    )
    delta_c_hat = {
        p: chi[p] / (q_tau.get(p, 0) + _EPS) * pooled for p in problem.products
    }
    # 阻尼与封顶（A06）：Δc^(k+1) = (1−γ)Δc^(k) + γΔĉ ≤ δ^max·c_p
    delta_c_next = {
        p: min(
            (1 - problem.gamma) * prev_delta_c.get(p, 0.0)
            + problem.gamma * delta_c_hat[p],
            problem.delta_max * problem.cost_prod[p],
        )
        for p in problem.products
    }

    # 式(5-5)：η 定义式 + 有效产能
    total_machines = sum(len(ms) for ms in problem.machines.values())
    workers = sum(problem.worker_available[a][tau] for a in problem.skill_levels)
    eta = min(1.0, workers / total_machines)
    cap_eff_next = {
        j: max(0.0, problem.capacity[j][tau] * eta - rep.theta_stage.get(j, 0.0))
        for j in problem.stages
    }
    return ChannelComputation(
        chi=chi,
        lc_inc=lc_inc,
        e_inc=e_inc,
        pooled_cost=pooled,
        delta_c_hat=delta_c_hat,
        delta_c_next=delta_c_next,
        eta=eta,
        cap_eff_next=cap_eff_next,
    )
