"""
VNS 变邻域搜索算法模块 (标准学术版)
Variable Neighborhood Search Algorithm (Standard Academic Version)

基于四矩阵编码设计了 5 个不同结构的邻域算子，用于实现标准 VNS 搜索流程。
"""

import numpy as np
from typing import List, Tuple, Optional, Callable
import random
from copy import deepcopy

from models.problem import SchedulingProblem
from models.solution import Solution
from models.decoder import Decoder


class VNS:
    """
    标准变邻域搜索算法 (VNS)
    
    采用 5 种基于四矩阵编码的邻域结构：
    N1: 机器重新分配 (针对机器矩阵)
    N2: 工序插入 (针对序列优先级矩阵)
    N3: 速度与技能同步变异 (针对速度与技能矩阵)
    N4: 关键阶段工件交换 (中等强度)
    N5: 工件级全决策重访 (抖动算子/Shaking)
    """
    
    def __init__(self,
                 problem: SchedulingProblem,
                 max_iters: int = 100,
                 seed: Optional[int] = None):
        self.problem = problem
        self.max_iters = max_iters
        self.decoder = Decoder(problem)
        
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)

    # ------------------ 邻域结构设计 ------------------

    def neighborhood_N1(self, sol: Solution) -> Solution:
        """N1: 机器重新分配 - 优化负载平衡"""
        neighbor = sol.copy()
        job = random.randint(0, self.problem.n_jobs - 1)
        stage = random.randint(0, self.problem.n_stages - 1)
        
        n_machines = self.problem.machines_per_stage[stage]
        if n_machines > 1:
            current_m = neighbor.machine_assign[job, stage]
            new_m = current_m
            while new_m == current_m:
                new_m = random.randint(0, n_machines - 1)
            neighbor.machine_assign[job, stage] = new_m
        
        neighbor.objectives = None
        return neighbor

    def neighborhood_N2(self, sol: Solution) -> Solution:
        """N2: 工序插入 - 优化加工顺序"""
        neighbor = sol.copy()
        job = random.randint(0, self.problem.n_jobs - 1)
        stage = random.randint(0, self.problem.n_stages - 1)
        
        # 随机分配一个新的优先级，从而改变在该机器队列中的位置
        neighbor.sequence_priority[job, stage] = random.randint(0, 1000)
        
        neighbor.objectives = None
        return neighbor

    def neighborhood_N3(self, sol: Solution) -> Solution:
        """N3: 速度-技能同步变更 - 优化能耗与人工均衡"""
        neighbor = sol.copy()
        job = random.randint(0, self.problem.n_jobs - 1)
        stage = random.randint(0, self.problem.n_stages - 1)
        
        # 变更速度
        n_speeds = self.problem.n_speed_levels
        if n_speeds > 1:
            curr_v = neighbor.speed_level[job, stage]
            new_v = (curr_v + random.choice([-1, 1])) % n_speeds
            neighbor.speed_level[job, stage] = new_v
            # 同步修复技能等级 (确保技能 >= 速度)
            if neighbor.worker_skill[job, stage] < new_v:
                neighbor.worker_skill[job, stage] = new_v
                
        neighbor.objectives = None
        return neighbor

    def neighborhood_N4(self, sol: Solution) -> Solution:
        """N4: 关键阶段工件对换 - 较强力扰动"""
        neighbor = sol.copy()
        stage = random.randint(0, self.problem.n_stages - 1)
        
        if self.problem.n_jobs >= 2:
            j1, j2 = random.sample(range(self.problem.n_jobs), 2)
            # 交换在某阶段的所有决策
            neighbor.machine_assign[j1, stage], neighbor.machine_assign[j2, stage] = \
                neighbor.machine_assign[j2, stage], neighbor.machine_assign[j1, stage]
            neighbor.sequence_priority[j1, stage], neighbor.sequence_priority[j2, stage] = \
                neighbor.sequence_priority[j2, stage], neighbor.sequence_priority[j1, stage]
            neighbor.speed_level[j1, stage], neighbor.speed_level[j2, stage] = \
                neighbor.speed_level[j2, stage], neighbor.speed_level[j1, stage]
            neighbor.worker_skill[j1, stage], neighbor.worker_skill[j2, stage] = \
                neighbor.worker_skill[j2, stage], neighbor.worker_skill[j1, stage]
                
        neighbor.objectives = None
        return neighbor

    def neighborhood_N5(self, sol: Solution) -> Solution:
        """N5: 工件级重塑 (Shaking) - 最大化搜索范围"""
        neighbor = sol.copy()
        job = random.randint(0, self.problem.n_jobs - 1)
        
        for s in range(self.problem.n_stages):
            n_m = self.problem.machines_per_stage[s]
            neighbor.machine_assign[job, s] = random.randint(0, n_m - 1)
            neighbor.sequence_priority[job, s] = random.randint(0, 1000)
            v = random.randint(0, self.problem.n_speed_levels - 1)
            neighbor.speed_level[job, s] = v
            neighbor.worker_skill[job, s] = random.randint(v, self.problem.n_skill_levels - 1)
            
        neighbor.objectives = None
        return neighbor

    def run(self, initial_sol: Solution) -> Solution:
        """
        标准 VNS 运行流程
        
        由于是多目标优化，此处的“改改进”判定由 Pareto 支配关系决定。
        """
        current_sol = initial_sol.copy()
        if current_sol.objectives is None:
            self.decoder.decode(current_sol)
            
        neighborhoods = [
            self.neighborhood_N1, 
            self.neighborhood_N2, 
            self.neighborhood_N3, 
            self.neighborhood_N4, 
            self.neighborhood_N5
        ]
        
        for _ in range(self.max_iters):
            k = 0
            while k < len(neighborhoods):
                # 1. Shaking (抖动) - 随机从邻域生成一个邻居
                neighbor = neighborhoods[k](current_sol)
                neighbor.repair(self.problem)
                self.decoder.decode(neighbor)
                
                # 2. Local Search - 此处简化为直接比较 (基本版 VNS)
                # 如果邻居能够支配当前解，或者与当前解互不支配且概率接受 (多样性)
                if neighbor.dominates(current_sol):
                    current_sol = neighbor
                    k = 0 # 发现改进，重置邻域
                else:
                    k += 1 # 无改进，尝试更大的邻域
                    
        return current_sol
