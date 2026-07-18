"""vendor_nsga/ 真实 NSGA-II-VNS-MOSA 适配器（论文主算法，硬性约束"真算法唯一"）。

策略：真算法搜索 + 论文口径重评。
  - 搜索：原样调用 vendor_nsga/algorithms/nsga2_vns_mosa.py::NSGA2_VNS_MOSA
    （四矩阵编码 M-Q-V-W、4M-SX 交叉、VNS 邻域、MOSA 档案），不改一行；
  - 重评：vendor 解码器与论文口径存在三处度量差异（无虚拟工件初始设置
    S_0,i、能耗按 kWh、空闲能耗按全程 makespan 而非机器占用区间），
    故将 vendor 输出解的四矩阵翻译为排队表后，交由
    src/scheduling/evaluate.py 按论文式(4-1)~(4-16)/(5-4) 重演统计；
    重评后再做一次非支配过滤（度量口径变化可能破坏原非支配性）。

索引映射（vendor 0 起 ↔ 本系统 1 起）：
  阶段 j: stages[jj]；速度 s = 档位索引+1；技能 α = 等级索引+1；
  机器: problem.machines[j][f]；工件 i: jobs[i]。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from src.data.lot_sizing import Job
from src.data.problem_data import ProblemData
from src.scheduling.base import ScheduleSolution, nondominated_filter
from src.scheduling.evaluate import evaluate_schedule

VENDOR_ROOT = Path(__file__).resolve().parents[2] / "vendor_nsga"
if str(VENDOR_ROOT) not in sys.path:
    sys.path.insert(0, str(VENDOR_ROOT))

from algorithms.nsga2_vns_mosa import NSGA2_VNS_MOSA  # noqa: E402
from models.problem import SchedulingProblem  # noqa: E402


def build_vendor_problem(
    problem: ProblemData, jobs: list[Job], tau: int
) -> SchedulingProblem:
    """把 ProblemData + 工件集合翻译为 vendor 的 SchedulingProblem。"""
    n_jobs = len(jobs)
    stages = problem.stages
    n_stages = len(stages)
    machines_per_stage = [len(problem.machines[j]) for j in stages]
    max_m = max(machines_per_stage)
    n_gears = len(problem.speed_gears)
    n_levels = len(problem.skill_levels)

    processing_time = np.zeros((n_jobs, n_stages, max_m, n_gears))
    for i, job in enumerate(jobs):
        for jj, stage in enumerate(stages):
            for f in range(machines_per_stage[jj]):
                for si, gear in enumerate(problem.speed_gears):
                    processing_time[i, jj, f, si] = (
                        job.size
                        * problem.proc_time[job.product][stage]
                        * problem.speed_factor[gear]
                    )

    setup_time = np.zeros((n_stages, max_m, n_jobs, n_jobs))
    for jj in range(n_stages):
        for f in range(machines_per_stage[jj]):
            for i, ji in enumerate(jobs):
                for i2, ji2 in enumerate(jobs):
                    if i != i2:
                        setup_time[jj, f, i, i2] = problem.setup_time(
                            ji.product, ji2.product
                        )

    transport_time = np.full(n_stages, float(problem.transport_time))
    processing_power = np.zeros((n_stages, max_m, n_gears))
    for jj in range(n_stages):
        for f in range(machines_per_stage[jj]):
            for si, gear in enumerate(problem.speed_gears):
                processing_power[jj, f, si] = problem.energy.power_proc[gear]
    setup_power = np.full((n_stages, max_m), float(problem.energy.power_setup))
    idle_power = np.full((n_stages, max_m), float(problem.energy.power_idle))

    return SchedulingProblem(
        n_jobs=n_jobs,
        n_stages=n_stages,
        machines_per_stage=machines_per_stage,
        n_speed_levels=n_gears,
        n_skill_levels=n_levels,
        processing_time=processing_time,
        setup_time=setup_time,
        transport_time=transport_time,
        processing_power=processing_power,
        setup_power=setup_power,
        idle_power=idle_power,
        transport_power=float(problem.energy.energy_transport),
        aux_power=float(problem.energy.power_aux),
        skill_wages=np.array(
            [problem.worker_wage[l] for l in problem.skill_levels], dtype=float
        ),
        skill_compatibility=np.arange(n_levels),  # 等级索引 l 可开档位索引 ≤ l（向下兼容）
        workers_available=np.array(
            [problem.worker_available[l][tau] for l in problem.skill_levels], dtype=int
        ),
        shift_duration=float(problem.t_avail),
    )


def _to_schedule(
    problem: ProblemData, jobs: list[Job], tau: int, vendor_solution
) -> ScheduleSolution:
    """vendor 四矩阵 → 排队表/分配表 → 论文口径重评。"""
    stages = problem.stages
    assignment: dict[tuple[str, int], tuple[str, int, int]] = {}
    sequence: dict[tuple[int, str], list[str]] = {}
    for jj, stage in enumerate(stages):
        queues: dict[int, list[tuple[int, int]]] = {}
        for i, job in enumerate(jobs):
            f = int(vendor_solution.machine_assign[i, jj])
            gear = problem.speed_gears[int(vendor_solution.speed_level[i, jj])]
            skill = problem.skill_levels[int(vendor_solution.worker_skill[i, jj])]
            machine = problem.machines[stage][f]
            assignment[(job.job_id, stage)] = (machine, gear, skill)
            queues.setdefault(f, []).append(
                (int(vendor_solution.sequence_priority[i, jj]), i)
            )
        for f, queue in queues.items():
            queue.sort(key=lambda t: t[0])  # 与 vendor 解码一致：优先级升序（稳定）
            sequence[(stage, problem.machines[stage][f])] = [
                jobs[i].job_id for _, i in queue
            ]
    return evaluate_schedule(problem, jobs, tau, assignment, sequence)


class VendorNsgaScheduler:
    """SchedulerAdapter 实现：真实 NSGA-II-VNS-MOSA + 论文口径重评。"""

    def __init__(
        self,
        pop_size: int = 48,
        n_generations: int = 30,
        mosa_layers: int = 8,
        rp_size: int = 16,
        ap_size: int = 60,
        vns_max_iters: int = 3,
    ):
        self.pop_size = pop_size
        self.n_generations = n_generations
        self.mosa_layers = mosa_layers
        self.rp_size = rp_size
        self.ap_size = ap_size
        self.vns_max_iters = vns_max_iters

    def solve(
        self, problem: ProblemData, jobs: list[Job], tau: int, seed: int | None = None
    ) -> list[ScheduleSolution]:
        if not jobs:
            return []
        vendor_problem = build_vendor_problem(problem, jobs, tau)
        algo = NSGA2_VNS_MOSA(
            vendor_problem,
            pop_size=self.pop_size,
            n_generations=self.n_generations,
            mosa_layers=self.mosa_layers,
            rp_size=self.rp_size,
            ap_size=self.ap_size,
            vns_max_iters=self.vns_max_iters,
            seed=seed,
        )
        archive = algo.run()
        solutions = [_to_schedule(problem, jobs, tau, s) for s in archive]
        return nondominated_filter(solutions)
