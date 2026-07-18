"""子批化映射（论文 4.8.1 节）：q^plan → 调度工件集合 I^sch。

拆分规则（与金标 A01 及变体 V2 口径一致）：n_p = ⌈q_p / U_p^lot⌉ 个子批，
前 n_p−1 批为满批 U_p^lot，末批为余量（自然形成 β(i) 降序）。
工件加工时间 PT_{i,j,s} = β(i) × pt^unit_{p,j} × θ_s。
"""
from __future__ import annotations

from dataclasses import dataclass

from .problem_data import ProblemData


@dataclass(frozen=True)
class Job:
    """调度工件 i：产品 p 的一个子批，β(i) 为子批批量。"""

    job_id: str   # 如 "A1"
    product: str  # p
    size: int     # β(i)


def split_lots(quantity: int, lot_max: int) -> list[int]:
    """按 U_p^lot 满批拆分：⌈q/U⌉ 个子批，末批为余量（q≤0 时无子批）。"""
    if quantity <= 0:
        return []
    full, rem = divmod(quantity, lot_max)
    return [lot_max] * full + ([rem] if rem else [])


def build_jobs(problem: ProblemData, q_plan: dict[str, int]) -> list[Job]:
    """子批化映射 q^plan → I^sch：按产品序生成子批工件（编号 p1..pn）。"""
    jobs: list[Job] = []
    for p in problem.products:
        sizes = split_lots(q_plan.get(p, 0), problem.lot_size_max[p])
        for idx, size in enumerate(sizes, start=1):
            jobs.append(Job(job_id=f"{p}{idx}", product=p, size=size))
    return jobs


def processing_time(problem: ProblemData, job: Job, stage: int, gear: int) -> float:
    """PT_{i,j,s} = β(i) × pt^unit_{p,j} × θ_s（4.8.1 节映射）。"""
    return job.size * problem.proc_time[job.product][stage] * problem.speed_factor[gear]
