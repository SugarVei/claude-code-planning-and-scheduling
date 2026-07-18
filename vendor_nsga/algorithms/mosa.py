"""
MOSA 多目标模拟退火算法模块 (标准学术版)
Multi-Objective Simulated Annealing Algorithm (Standard Academic Version)

实现了标准的多目标模拟退火流程，包含降温进度表、Metropolis 准则以及外部存档管理。
"""

import numpy as np
from typing import List, Tuple, Optional, Callable
import random
import math
from copy import deepcopy

from models.problem import SchedulingProblem
from models.solution import Solution
from models.decoder import Decoder


class MOSA:
    """
    标准多目标模拟退火算法 (MOSA)
    
    算法核心：
    1. Metropolis 准则扩展到多目标：
       - 若新解支配旧解，接受；
       - 若旧解支配新解，以 exp(-delta/T) 接受；
       - 若互不支配，以恒定高概率接受。
    2. 外部存档 (External Archive) 记录非支配解集。
    """
    
    def __init__(self,
                 problem: SchedulingProblem,
                 initial_temp: float = 100.0,
                 cooling_rate: float = 0.95,
                 final_temp: float = 0.1,
                 max_iterations: int = 200,
                 seed: Optional[int] = None):
        self.problem = problem
        self.initial_temp = initial_temp
        self.cooling_rate = cooling_rate
        self.final_temp = final_temp
        self.max_iterations = max_iterations
        self.decoder = Decoder(problem)
        
        # 外部存档
        self.archive: List[Solution] = []
        
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)

    def _update_archive(self, sol: Solution):
        """更新 Pareto 存档"""
        if sol.objectives is None:
            self.decoder.decode(sol)
            
        new_archive = []
        is_dominated = False
        
        for archived in self.archive:
            if archived.dominates(sol):
                is_dominated = True
                new_archive.append(archived)
            elif sol.dominates(archived):
                continue # 丢弃被新解支配的
            else:
                new_archive.append(archived)
                
        if not is_dominated:
            new_archive.append(sol.copy())
            
        self.archive = new_archive

    def _calculate_p_accept(self, current: Solution, neighbor: Solution, temp: float) -> bool:
        """多目标环境下的计算接受概率"""
        if neighbor.dominates(current):
            return True
        elif current.dominates(neighbor):
            # 计算目标退化的加权程度 (简化的 delta)
            d1 = neighbor.objectives[0] - current.objectives[0]
            d2 = neighbor.objectives[1] - current.objectives[1]
            d3 = neighbor.objectives[2] - current.objectives[2]
            # 这里的delta取平均退化程度或加权和
            delta = (max(0, d1) + max(0, d2) + max(0, d3)) / 3.0
            prob = math.exp(-delta / temp)
            return random.random() < prob
        else:
            # 互不支配，默认以较高概率接受以保证搜索广度
            return random.random() < 0.8

    def run(self, initial_archive: Optional[List[Solution]] = None) -> List[Solution]:
        """执行标准 MOSA 流程"""
        # 初始化解
        if initial_archive:
            self.archive = [s.copy() for s in initial_archive]
            current_sol = random.choice(self.archive).copy()
        else:
            current_sol = Solution.generate_random(self.problem)
            current_sol.repair(self.problem)
            self.decoder.decode(current_sol)
            self.archive = [current_sol.copy()]

        temp = self.initial_temp
        
        # 导入算子
        from algorithms.operators import simple_neighbor
        rng = np.random.default_rng()

        for _ in range(self.max_iterations):
            if temp <= self.final_temp:
                break
                
            # 产生邻居
            neighbor = simple_neighbor(current_sol, rng, self.problem)
            neighbor.repair(self.problem)
            self.decoder.decode(neighbor)
            
            # 判定接受
            if self._calculate_p_accept(current_sol, neighbor, temp):
                current_sol = neighbor
                self._update_archive(neighbor)
                
            # 降温
            temp *= self.cooling_rate
            
        return self.archive
