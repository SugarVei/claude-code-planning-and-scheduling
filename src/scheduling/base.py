"""调度层公共结构：解表示、SchedulerAdapter 抽象接口、可接受度与非支配工具。

口径（与论文/金标对齐）：
  - OT_τ = max{0, C_max − T^avail}（4.8.2 节）；
  - ρ = 1 − min{1, OT/OT^max}（金标 A04 口径；论文 §5.3.1 只给出 ρ 语义，
    显式公式编号在工作簿中记为"式(5-15)"，与论文正文编号存在错位，
    实现以金标算式为准）；
  - Θ_{j,τ}^{sdst}（式5-4）= 阶段 j 全部机器上相邻工件设置时间之和，
    含虚拟工件初始设置 S_0,i（I+ = I ∪ {0}，式4-3/5-4 口径）；
  - 能耗量纲统一为 kW·min（金标 '0_说明'）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from src.data.lot_sizing import Job
from src.data.problem_data import ProblemData


@dataclass(frozen=True)
class Operation:
    """一道已排产工序（工件 i 在阶段 j 上的执行记录）。"""

    job_id: str      # 工件（子批）编号
    product: str     # 所属产品族 φ(i)
    stage: int       # 阶段 j
    machine: str     # 机器名（如 M21）
    gear: int        # 速度档位 s（1 起）
    skill: int       # 该机器配备工人技能等级 α（1 起）
    start: float     # 设置开始时刻
    setup_end: float # 设置结束/加工开始时刻
    end: float       # 完工时刻 CT_{i,j}
    setup_time: float


@dataclass
class ScheduleSolution:
    """调度层一个解（论文口径统计量 + 完整工序表）。"""

    cmax: float                     # C_max,τ
    lc: float                       # LC_τ（式4-8）
    energy: float                   # E_τ（式4-11，kW·min）
    theta_stage: dict[int, float]   # Θ_{j,τ}^{sdst}（式5-4，含初始设置）
    ot: float                       # OT_τ = max{0, C_max − T^avail}
    rho: float                      # 调度可接受度（金标 A04 算式）
    operations: list[Operation] = field(default_factory=list)
    energy_breakdown: dict[str, float] = field(default_factory=dict)  # PE/SE/IE/TE/AE

    @property
    def theta_total(self) -> float:
        """Θ_τ^sdst = Σ_j Θ_{j,τ}^sdst。"""
        return sum(self.theta_stage.values())

    @property
    def objectives(self) -> tuple[float, float, float]:
        """三目标 (C_max, LC, E)。"""
        return (self.cmax, self.lc, self.energy)


def overtime(problem: ProblemData, cmax: float) -> float:
    """OT = max{0, C_max − T^avail}（4.8.2 节）。"""
    return max(0.0, cmax - problem.t_avail)


def acceptability(problem: ProblemData, cmax: float) -> float:
    """ρ = 1 − min{1, OT/OT^max}（金标 A04 口径）。"""
    if problem.ot_max <= 0:
        return 1.0 if cmax <= problem.t_avail else 0.0
    return 1.0 - min(1.0, overtime(problem, cmax) / problem.ot_max)


def is_feasible_flag(problem: ProblemData, rho: float) -> int:
    """Feas = 1{ρ ≥ ρ_min}（式3-17 下方定义）。"""
    return 1 if rho >= problem.rho_min else 0


def dominates(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    """目标向量支配：a 各分量 ≤ b 且至少一个严格小（最小化）。"""
    return all(x <= y for x, y in zip(a, b)) and any(x < y for x, y in zip(a, b))


def nondominated_filter(solutions: list[ScheduleSolution]) -> list[ScheduleSolution]:
    """按三目标 (C_max, LC, E) 过滤出非支配子集（去除重复目标向量）。"""
    result: list[ScheduleSolution] = []
    seen: set[tuple[float, float, float]] = set()
    for s in solutions:
        if s.objectives in seen:
            continue
        if any(dominates(o.objectives, s.objectives) for o in solutions):
            continue
        seen.add(s.objectives)
        result.append(s)
    return result


class SchedulerAdapter(Protocol):
    """调度求解器统一接口：输入工件集合 I_τ^sch，输出非支配解集 Ω_τ^ND。"""

    def solve(
        self, problem: ProblemData, jobs: list[Job], tau: int, seed: int | None = None
    ) -> list[ScheduleSolution]:
        """对滚动周期 τ 的工件集合求解，返回论文口径统计的非支配解集。"""
        ...
