"""models/decoder.py

将四矩阵编码 (M-Q-V-W) 解码为实际调度，并计算三目标：
1) F1: Makespan (最大完工时间)
2) F2: Labor Cost (人工成本) —— 机器-工人绑定、按标准工期计薪
3) F3: Energy Consumption (能耗) —— 加工/换模/空闲/运输/辅助 五类能耗

与论文/模型一致的语义约束：
- W 为“机器绑定工人技能”，同一阶段同一机器必须一致（Solution.repair 负责保证）。
- 工人数量约束体现为“每个技能等级可同时上岗的机器数量”，不应在解码阶段模拟工人跨机器的占用时间。
  解码时间轴由工件先后约束与机器顺序约束决定。
"""

from __future__ import annotations

import numpy as np
from typing import Dict, List, Tuple
from collections import defaultdict

from .problem import SchedulingProblem
from .solution import Solution


class Decoder:
    """调度解码器"""

    def __init__(self, problem: SchedulingProblem):
        self.problem = problem

    @staticmethod
    def _build_machine_skill_map(solution: Solution) -> Dict[Tuple[int, int], int]:
        """(stage, machine) -> skill

        repair 后理论上同一机器技能一致。这里取该机上所有工件的 max 以增强鲁棒性。
        """
        n_jobs, n_stages = solution.n_jobs, solution.n_stages
        omega = {}
        for j in range(n_stages):
            for i in range(n_jobs):
                f = int(solution.machine_assign[i, j])
                key = (j, f)
                w = int(solution.worker_skill[i, j])
                omega[key] = w if key not in omega else max(omega[key], w)
        return omega

    @staticmethod
    def _assign_worker_indices(omega: Dict[Tuple[int, int], int]) -> Dict[Tuple[int, int], int]:
        """给每个 (stage, machine) 分配该技能等级内部的 worker_idx（用于可视化与统计）。"""
        by_skill = defaultdict(list)
        for (j, f), w in omega.items():
            by_skill[w].append((j, f))
        worker_idx = {}
        for w, machines in by_skill.items():
            machines_sorted = sorted(machines)
            for k, key in enumerate(machines_sorted):
                worker_idx[key] = k
        return worker_idx

    def decode(self, solution: Solution) -> Tuple[float, float, float]:
        """解码并计算目标值。"""
        problem = self.problem
        n_jobs, n_stages = problem.n_jobs, problem.n_stages

        # 时间追踪
        job_completion = np.zeros((n_jobs, n_stages), dtype=float)
        machine_available = defaultdict(lambda: defaultdict(float))   # stage -> machine -> time
        machine_last_job = defaultdict(lambda: defaultdict(lambda: -1))

        # 能耗追踪
        total_processing_energy = 0.0
        total_setup_energy = 0.0
        total_transport_energy = 0.0

        # 机器使用情况: (stage, machine) -> dict
        machine_usage = defaultdict(lambda: {
            'skill': 0, 'used': False, 'proc_time': 0.0, 'setup_time': 0.0
        })

        omega = self._build_machine_skill_map(solution)

        # 逐阶段解码
        for stage in range(n_stages):
            # 该阶段按机器聚合队列
            machine_queues = defaultdict(list)
            for job in range(n_jobs):
                f = int(solution.machine_assign[job, stage])
                q = int(solution.sequence_priority[job, stage])
                machine_queues[f].append((q, job))

            for f in machine_queues:
                machine_queues[f].sort(key=lambda x: x[0])

            # 逐机排程
            for machine in range(int(problem.machines_per_stage[stage])):
                queue = machine_queues.get(machine, [])
                for _, job in queue:
                    speed = int(solution.speed_level[job, stage])
                    skill = int(solution.worker_skill[job, stage])

                    proc_time = float(problem.get_processing_time(job, stage, machine, speed))
                    prev_job = int(machine_last_job[stage][machine])
                    setup_time = float(problem.get_setup_time(stage, machine, prev_job, job))

                    if stage == 0:
                        job_ready = 0.0
                        transport_t = 0.0
                    else:
                        transport_t = float(problem.get_transport_time(stage - 1))
                        job_ready = float(job_completion[job, stage - 1] + transport_t)
                        total_transport_energy += float(problem.transport_power) * transport_t / 60.0

                    machine_ready = float(machine_available[stage][machine])
                    start_time = max(job_ready, machine_ready)
                    processing_start = start_time + setup_time
                    end_time = processing_start + proc_time

                    # 更新时间
                    job_completion[job, stage] = end_time
                    machine_available[stage][machine] = end_time
                    machine_last_job[stage][machine] = job

                    # 记录使用情况
                    machine_usage[(stage, machine)]['used'] = True
                    machine_usage[(stage, machine)]['skill'] = max(machine_usage[(stage, machine)]['skill'], skill)
                    machine_usage[(stage, machine)]['proc_time'] += proc_time
                    machine_usage[(stage, machine)]['setup_time'] += setup_time

                    # 能耗
                    proc_power = float(problem.get_processing_power(stage, machine, speed))
                    total_processing_energy += proc_power * proc_time / 60.0

                    setup_power = float(problem.get_setup_power(stage, machine))
                    total_setup_energy += setup_power * setup_time / 60.0

        # F1: makespan
        makespan = float(np.max(job_completion[:, -1])) if n_jobs > 0 else 0.0

        # F2: labor cost（每台使用机器配一名工人，工资由 ω[j,f] 决定）
        total_labor_cost = 0.0
        for (stage, machine), usage in machine_usage.items():
            if not usage['used']:
                continue
            skill = int(omega.get((stage, machine), usage['skill']))
            total_labor_cost += float(problem.get_wage(skill))

        # F3: energy
        total_idle_energy = 0.0
        for (stage, machine), usage in machine_usage.items():
            if not usage['used']:
                continue
            idle_time = makespan - usage['proc_time'] - usage['setup_time']
            if idle_time > 0:
                idle_power = float(problem.get_idle_power(stage, machine))
                total_idle_energy += idle_power * idle_time / 60.0

        total_aux_energy = float(problem.aux_power) * makespan / 60.0
        total_energy = total_processing_energy + total_setup_energy + total_idle_energy + total_transport_energy + total_aux_energy

        solution.objectives = (makespan, total_labor_cost, total_energy)
        return solution.objectives

    def decode_with_schedule(self, solution: Solution) -> Tuple[Tuple[float, float, float], Dict]:
        """解码并返回详细调度信息（用于甘特图）。"""
        problem = self.problem
        n_jobs, n_stages = problem.n_jobs, problem.n_stages

        schedule = {
            'operations': [],
            'machine_utilization': {},
            'job_completion': {},
            'machine_workers': {},
            'energy_breakdown': {},
        }

        job_completion = np.zeros((n_jobs, n_stages), dtype=float)
        machine_available = defaultdict(lambda: defaultdict(float))
        machine_last_job = defaultdict(lambda: defaultdict(lambda: -1))

        total_processing_energy = 0.0
        total_setup_energy = 0.0
        total_transport_energy = 0.0

        machine_usage = defaultdict(lambda: {'skill': 0, 'used': False, 'proc_time': 0.0, 'setup_time': 0.0})

        omega = self._build_machine_skill_map(solution)
        worker_idx_map = self._assign_worker_indices(omega)

        for stage in range(n_stages):
            machine_queues = defaultdict(list)
            for job in range(n_jobs):
                machine = int(solution.machine_assign[job, stage])
                priority = int(solution.sequence_priority[job, stage])
                machine_queues[machine].append((priority, job))

            for machine in machine_queues:
                machine_queues[machine].sort(key=lambda x: x[0])

            for machine in range(int(problem.machines_per_stage[stage])):
                queue = machine_queues.get(machine, [])
                machine_ops = []

                for priority, job in queue:
                    speed = int(solution.speed_level[job, stage])
                    skill = int(solution.worker_skill[job, stage])

                    proc_time = float(problem.get_processing_time(job, stage, machine, speed))
                    prev_job = int(machine_last_job[stage][machine])
                    setup_time = float(problem.get_setup_time(stage, machine, prev_job, job))

                    if stage == 0:
                        job_ready = 0.0
                        transport_t = 0.0
                    else:
                        transport_t = float(problem.get_transport_time(stage - 1))
                        job_ready = float(job_completion[job, stage - 1] + transport_t)
                        total_transport_energy += float(problem.transport_power) * transport_t / 60.0

                    machine_ready = float(machine_available[stage][machine])
                    start_time = max(job_ready, machine_ready)
                    processing_start = start_time + setup_time
                    end_time = processing_start + proc_time

                    job_completion[job, stage] = end_time
                    machine_available[stage][machine] = end_time
                    machine_last_job[stage][machine] = job

                    machine_usage[(stage, machine)]['used'] = True
                    machine_usage[(stage, machine)]['skill'] = max(machine_usage[(stage, machine)]['skill'], skill)
                    machine_usage[(stage, machine)]['proc_time'] += proc_time
                    machine_usage[(stage, machine)]['setup_time'] += setup_time

                    op_info = {
                        'job': job,
                        'stage': stage,
                        'machine': machine,
                        'start': start_time,
                        'setup_end': processing_start,
                        'end': end_time,
                        'processing_time': proc_time,
                        'setup_time': setup_time,
                        'transport_time': transport_t,
                        'speed': speed,
                        'skill': skill,
                        'worker_idx': int(worker_idx_map.get((stage, machine), 0)),
                        'priority': priority
                    }
                    schedule['operations'].append(op_info)
                    machine_ops.append(op_info)

                    proc_power = float(problem.get_processing_power(stage, machine, speed))
                    total_processing_energy += proc_power * proc_time / 60.0
                    setup_power = float(problem.get_setup_power(stage, machine))
                    total_setup_energy += setup_power * setup_time / 60.0

                schedule['machine_utilization'][(stage, machine)] = machine_ops

        makespan = float(np.max(job_completion[:, -1])) if n_jobs > 0 else 0.0

        total_labor_cost = 0.0
        for (stage, machine), usage in machine_usage.items():
            if not usage['used']:
                continue
            skill = int(omega.get((stage, machine), usage['skill']))
            wage = float(problem.get_wage(skill))
            total_labor_cost += wage
            schedule['machine_workers'][(stage, machine)] = {'skill': skill, 'wage': wage}

        total_idle_energy = 0.0
        for (stage, machine), usage in machine_usage.items():
            if usage['used']:
                idle_time = makespan - usage['proc_time'] - usage['setup_time']
                if idle_time > 0:
                    idle_power = float(problem.get_idle_power(stage, machine))
                    total_idle_energy += idle_power * idle_time / 60.0

        total_aux_energy = float(problem.aux_power) * makespan / 60.0
        total_energy = total_processing_energy + total_setup_energy + total_idle_energy + total_transport_energy + total_aux_energy

        schedule['energy_breakdown'] = {
            'processing': total_processing_energy,
            'setup': total_setup_energy,
            'idle': total_idle_energy,
            'transport': total_transport_energy,
            'auxiliary': total_aux_energy,
            'total': total_energy
        }

        for job in range(n_jobs):
            schedule['job_completion'][job] = float(job_completion[job, -1])

        solution.objectives = (makespan, total_labor_cost, total_energy)
        return solution.objectives, schedule

    def evaluate_population(self, population: List[Solution]) -> None:
        for sol in population:
            if sol.objectives is None:
                self.decode(sol)


def normalize_objectives(solutions: List[Solution]) -> np.ndarray:
    """归一化目标函数值（用于 VNS/MOSA 标量化）。"""
    if not solutions:
        return np.array([])

    objectives = np.array([s.objectives for s in solutions if s.objectives is not None], dtype=float)
    if len(objectives) == 0:
        return np.array([])

    min_vals = objectives.min(axis=0)
    max_vals = objectives.max(axis=0)

    ranges = max_vals - min_vals
    ranges[ranges == 0] = 1.0

    return (objectives - min_vals) / ranges
