# -*- coding: utf-8 -*-
"""
统一算子库
Unified Operators Library

为所有多目标优化算法提供基于四矩阵编码的交叉、变异和邻域生成算子。
"""

import numpy as np
from typing import List, Tuple, Optional, TYPE_CHECKING
from copy import deepcopy
import random

if TYPE_CHECKING:
    from models.problem import SchedulingProblem
    from models.solution import Solution
    from models.decoder import Decoder



def four_matrix_sx_crossover(
    parent1: 'Solution',
    parent2: 'Solution',
    rng: np.random.Generator,
    problem: 'SchedulingProblem',
    decoder: 'Decoder'
) -> 'Solution':
    """
    四矩阵交换序列交叉 (4M-SX Crossover)

    严格基于 Guan et al. (2023) 提出的 Swap Crossover (SX, Algorithm 1)，
    适配到四矩阵编码 (M, Q, V, W) 的多目标调度问题。

    核心思想：
    1) 随机选择一个阶段 s。
    2) 在阶段 s 上，用 argsort(sequence_priority[:, s]) 提取两个父代的
       工件排列 π_A 和 π_B。
    3) 构建 swap-path：令 C ← A，逐位对比 π_C 与 π_B，若不同则找到目标
       元素在 π_C 中的位置并执行交换。每次交换同步修改 C 在阶段 s 上的
       四矩阵值 (M, Q, V, W)，保持编码语义一致。
    4) 每次交换后 repair + decode + 评估，将中间解加入候选池。
    5) 执行双向路径（A→B 和 B→A），收集所有中间解。
    6) 用非支配排序 + 拥挤度距离从候选池中选出两个最优子代。

    与原始 SX 的关键区别：
    - 原始 SX 针对单序列编码，本实现适配四矩阵编码。
    - 交换操作作用于选定阶段的四矩阵列值，而非整行。
    - 单目标贪心（"better than A"）扩展为多目标候选池选择。

    Returns:
        1 最佳子代 (最优的候选解，已 repair 且已 decode)。
    """
    n_jobs = int(problem.n_jobs)
    n_stages = int(problem.n_stages)

    def hash_solution(sol):
        return hash(sol.machine_assign.tobytes()) ^ hash(sol.sequence_priority.tobytes()) ^ hash(sol.speed_level.tobytes()) ^ hash(sol.worker_skill.tobytes())

    # ---- 安全兜底：如果不足以操作则直接返回父代副本 ----
    if n_jobs <= 1:
        c1 = parent1.copy()
        if c1.repair(problem) is None:
            c1 = parent1.copy()
            c1.repair(problem)
        decoder.decode(c1)
        return c1

    # ---- 阶段选择 ----
    target_stage = int(rng.integers(0, n_stages))

    def get_permutation(sol, stage):
        """提取某阶段上工件的排列（稳定排序，工件初始索引为第二关键字）"""
        priorities = sol.sequence_priority[:, stage]
        # np.lexsort 返回按传入键名升序排列的索引，后传入的为第一关键字
        return list(np.lexsort((np.arange(n_jobs), priorities)))

    def apply_stage_swap(sol, job_a, job_b, stage):
        """交换两个工件在指定阶段上的四矩阵值（M, Q, V, W）"""
        # M: machine_assign
        sol.machine_assign[job_a, stage], sol.machine_assign[job_b, stage] = \
            int(sol.machine_assign[job_b, stage]), int(sol.machine_assign[job_a, stage])
        # Q: sequence_priority
        sol.sequence_priority[job_a, stage], sol.sequence_priority[job_b, stage] = \
            int(sol.sequence_priority[job_b, stage]), int(sol.sequence_priority[job_a, stage])
        # V: speed_level
        sol.speed_level[job_a, stage], sol.speed_level[job_b, stage] = \
            int(sol.speed_level[job_b, stage]), int(sol.speed_level[job_a, stage])
        # W: worker_skill
        sol.worker_skill[job_a, stage], sol.worker_skill[job_b, stage] = \
            int(sol.worker_skill[job_b, stage]), int(sol.worker_skill[job_a, stage])

    def crowding_distance_map(sols):
        """计算拥挤度距离，返回 {id(sol): cd_value}"""
        if len(sols) <= 2:
            return {id(s): float('inf') for s in sols}
        objs = np.array([s.objectives for s in sols], dtype=float)
        cd = np.zeros(len(sols), dtype=float)
        for m in range(objs.shape[1]):
            order = np.argsort(objs[:, m])
            cd[order[0]] = np.inf
            cd[order[-1]] = np.inf
            fmin, fmax = objs[order[0], m], objs[order[-1], m]
            if fmax - fmin == 0:
                continue
            for k in range(1, len(sols) - 1):
                if np.isinf(cd[order[k]]):
                    continue
                cd[order[k]] += (objs[order[k + 1], m] - objs[order[k - 1], m]) / (fmax - fmin)
        return {id(sols[i]): float(cd[i]) for i in range(len(sols))}

    def phi_score(sol, ref):
        """加权标量化评分（用于无非支配解时的备选排序）"""
        objs = np.array([s.objectives for s in ref], dtype=float)
        mn = objs.min(axis=0)
        mx = objs.max(axis=0)
        rng_ = np.where(mx - mn == 0, 1.0, mx - mn)
        z = (np.array(sol.objectives, dtype=float) - mn) / rng_
        w = np.array([1/3, 1/3, 1/3], dtype=float)
        return float(np.dot(w, z))

    seen_keys = set()
    candidates = []

    def gen_swap_path(p_from, p_to):
        """双向 Swap-path 遍历，并利用去重集合筛选"""
        pi_target = get_permutation(p_to, target_stage)

        cur = p_from.copy()
        
        # 必须先修复并解码评估再求哈希并入池
        if cur.repair(problem) is not None:
            decoder.decode(cur)
            init_key = hash_solution(cur)
            if init_key not in seen_keys:
                candidates.append(cur)
                seen_keys.add(init_key)

        pi_cur = get_permutation(cur, target_stage)
        # 建立"工件 → 当前位置"的反向索引
        pos = {job: idx for idx, job in enumerate(pi_cur)}

        for i in range(n_jobs):
            target_job = pi_target[i]
            current_job = pi_cur[i]
            if current_job == target_job:
                continue

            # 找到 target_job 在 π_cur 中的位置 j
            j = pos[target_job]

            # 交换 π_cur 中位置 i 和 j 的工件
            job_a = pi_cur[i]  # = current_job
            job_b = pi_cur[j]  # = target_job
            pi_cur[i], pi_cur[j] = pi_cur[j], pi_cur[i]
            pos[job_a] = j
            pos[job_b] = i

            # 在 cur 的副本上执行四矩阵交换
            nxt = cur.copy()
            apply_stage_swap(nxt, job_a, job_b, target_stage)
            nxt.objectives = None

            if nxt.repair(problem) is not None:
                decoder.decode(nxt)
                nxt_key = hash_solution(nxt)

                if nxt_key not in seen_keys:
                    candidates.append(nxt)
                    seen_keys.add(nxt_key)
            cur = nxt

    # 双向路径搜索
    gen_swap_path(parent1, parent2)
    gen_swap_path(parent2, parent1)

    # ---- 安全兜底：若候选池为空，返回父代副本 ----
    if len(candidates) == 0:
        c1 = parent1.copy()
        if c1.repair(problem) is None:
            c1 = parent1.copy(); c1.repair(problem)
        decoder.decode(c1)
        return c1

    if len(candidates) == 1:
        return candidates[0]

    # ---- 非支配排序 + 拥挤度选择 1 个子代 ----
    def nondominated_set(sols):
        nd = []
        for s in sols:
            dominated = False
            for t in sols:
                if t is s:
                    continue
                if t.dominates(s):
                    dominated = True
                    break
            if not dominated:
                nd.append(s)
        return nd

    nd = nondominated_set(candidates)

    if len(nd) >= 2:
        cd = crowding_distance_map(nd)
        nd_sorted = sorted(nd, key=lambda s: cd.get(id(s), 0.0), reverse=True)
        return nd_sorted[0]

    if len(nd) == 1:
        return nd[0]

    # 无非支配解：按 φ 最小选 1 个
    candidates_sorted = sorted(candidates, key=lambda s: phi_score(s, candidates))
    return candidates_sorted[0]



def mutation_single(
    solution: 'Solution',
    rng: np.random.Generator,
    problem: 'SchedulingProblem'
) -> 'Solution':
    """
    单点变异
    
    随机选择一个 (job, stage) 位置，然后随机选择四矩阵中的一个进行变异。
    
    Args:
        solution: 待变异的解
        rng: numpy 随机数生成器
        problem: 调度问题实例
        
    Returns:
        变异后的解（已修复，未评估）
    """
    mutant = solution.copy()
    
    job = rng.integers(0, problem.n_jobs)
    stage = rng.integers(0, problem.n_stages)
    
    # 随机选择变异类型
    mutation_type = rng.choice(['machine', 'priority', 'speed', 'skill'])
    
    if mutation_type == 'machine':
        n_machines = problem.machines_per_stage[stage]
        if n_machines > 1:
            current = mutant.machine_assign[job, stage]
            new_machine = rng.integers(0, n_machines)
            while new_machine == current and n_machines > 1:
                new_machine = rng.integers(0, n_machines)
            mutant.machine_assign[job, stage] = new_machine
            
    elif mutation_type == 'priority':
        # 与另一个随机工件交换优先级
        if problem.n_jobs > 1:
            other_job = rng.integers(0, problem.n_jobs)
            while other_job == job:
                other_job = rng.integers(0, problem.n_jobs)
            mutant.sequence_priority[job, stage], mutant.sequence_priority[other_job, stage] = \
                mutant.sequence_priority[other_job, stage], mutant.sequence_priority[job, stage]
                
    elif mutation_type == 'speed':
        current = mutant.speed_level[job, stage]
        delta = rng.choice([-1, 1])
        new_speed = max(0, min(problem.n_speed_levels - 1, current + delta))
        mutant.speed_level[job, stage] = new_speed
        
    else:  # skill
        current = mutant.worker_skill[job, stage]
        delta = rng.choice([-1, 1])
        new_skill = max(0, min(problem.n_skill_levels - 1, current + delta))
        mutant.worker_skill[job, stage] = new_skill
    
    mutant.objectives = None
    mutant2 = mutant.repair(problem)
    if mutant2 is None:
        # 修复失败：回退到原解（等价于本次不变异）
        mutant2 = solution.copy()
    mutant2.objectives = None
    return mutant2


def mutation_multi(
    solution: 'Solution',
    rng: np.random.Generator,
    problem: 'SchedulingProblem',
    k: int = 3
) -> 'Solution':
    """
    多点变异
    
    连续执行 k 次单点变异。
    
    Args:
        solution: 待变异的解
        rng: numpy 随机数生成器
        problem: 调度问题实例
        k: 变异次数
        
    Returns:
        变异后的解（已修复，未评估）
    """
    mutant = solution.copy()
    
    for _ in range(k):
        mutant = mutation_single(mutant, rng, problem)
    
    return mutant


def mutation_inversion(
    solution: 'Solution',
    rng: np.random.Generator,
    problem: 'SchedulingProblem'
) -> 'Solution':
    """
    反转变异
    
    对某个阶段的序列进行片段反转，同步应用到四矩阵。
    
    Args:
        solution: 待变异的解
        rng: numpy 随机数生成器
        problem: 调度问题实例
        
    Returns:
        变异后的解（已修复，未评估）
    """
    mutant = solution.copy()
    
    stage = rng.integers(0, problem.n_stages)
    n_jobs = problem.n_jobs
    
    if n_jobs < 3:
        return mutant
    
    # 按当前 sequence_priority 得到排序
    priorities = mutant.sequence_priority[:, stage]
    order = np.argsort(priorities)
    
    # 随机选择反转区间 [i, j]
    i = rng.integers(0, n_jobs - 1)
    j = rng.integers(i + 1, n_jobs)
    
    # 反转区间
    reversed_segment = order[i:j+1][::-1]
    new_order = np.concatenate([order[:i], reversed_segment, order[j+1:]])
    
    # 根据新顺序重新赋值 priority
    for rank, job_idx in enumerate(new_order):
        mutant.sequence_priority[job_idx, stage] = rank
    
    mutant.objectives = None
    mutant2 = mutant.repair(problem)
    if mutant2 is None:
        mutant2 = solution.copy()
    mutant2.objectives = None
    return mutant2


def simple_neighbor(
    solution: 'Solution',
    rng: np.random.Generator,
    problem: 'SchedulingProblem',
    mode: Optional[str] = None
) -> 'Solution':
    """
    简单邻域生成
    
    为 MOSA(use_vns=False) 提供邻域候选。随机选择一种变异方式生成邻居。
    
    Args:
        solution: 当前解
        rng: numpy 随机数生成器
        problem: 调度问题实例
        mode: 变异模式 ('single', 'multi', 'inversion')，None 则随机选择
        
    Returns:
        邻域解（已修复，未评估）
    """
    if mode is None:
        mode = rng.choice(['single', 'multi', 'inversion'])
    
    if mode == 'single':
        return mutation_single(solution, rng, problem)
    elif mode == 'multi':
        return mutation_multi(solution, rng, problem, k=3)
    else:  # inversion
        return mutation_inversion(solution, rng, problem)


def apply_crossover_with_probability(
    parent1: 'Solution',
    parent2: 'Solution',
    crossover_prob: float,
    rng: np.random.Generator,
    problem: 'SchedulingProblem',
    decoder: 'Decoder'
) -> 'Solution':
    """
    带概率的交叉操作
    
    Args:
        parent1: 父代1
        parent2: 父代2
        crossover_prob: 交叉概率
        rng: numpy 随机数生成器
        problem: 调度问题实例
        decoder: 解码器
        
    Returns:
        child: 返回 1 个子代
    """
    if rng.random() > crossover_prob:
        c1 = parent1.copy()
        if c1.objectives is None:
            decoder.decode(c1)
        return c1
    
    return four_matrix_sx_crossover(parent1, parent2, rng, problem, decoder)


def apply_mutation_with_probability(
    solution: 'Solution',
    mutation_prob: float,
    rng: np.random.Generator,
    problem: 'SchedulingProblem',
    decoder: 'Decoder'
) -> 'Solution':
    """
    带概率的变异操作
    
    Args:
        solution: 待变异的解
        mutation_prob: 变异概率
        rng: numpy 随机数生成器
        problem: 调度问题实例
        decoder: 解码器
        
    Returns:
        变异后的解
    """
    if rng.random() > mutation_prob:
        return solution
    
    # 随机选择变异类型
    mutation_type = rng.choice(['single', 'multi', 'inversion'])
    
    if mutation_type == 'single':
        mutant = mutation_single(solution, rng, problem)
    elif mutation_type == 'multi':
        mutant = mutation_multi(solution, rng, problem)
    else:
        mutant = mutation_inversion(solution, rng, problem)
    
    decoder.decode(mutant)
    return mutant
