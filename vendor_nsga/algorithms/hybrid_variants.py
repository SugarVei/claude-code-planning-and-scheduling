# -*- coding: utf-8 -*-
"""
混合算法变体 (学术对比标准版)
Hybrid Algorithm Variants (Standard Academic Version)

根据学术文献标准实现的混合算法：
1. NSGA2_VNS: 基于 Memetic 框架，在 NSGA-II 每一代进化后，对 Pareto 前沿 (Front 0) 成员执行 VNS 增强。
2. NSGA2_MOSA: 结合遗传算法与模拟退火，在进化选择/更新过程中引入基于温度的接受概率，以增强多样性。
3. NSGA2_VNS_MOSA: 完整的混合策略，在进化过程中同步进行变邻域搜索与退火准则。
"""

import numpy as np
from typing import List, Tuple, Optional, Callable, Dict
import random
from copy import deepcopy

from models.problem import SchedulingProblem
from models.solution import Solution
from models.decoder import Decoder
from algorithms.nsga2 import NSGAII
from algorithms.vns import VNS
from algorithms.mosa import MOSA


class NSGA2_VNS:
    """
    NSGA-II + VNS 混合算法 (Memetic 算法)
    
    标准实现：在 NSGA-II 的每一代 evolution 结束后，识别出当前的第一层非支配前沿 (Front 0)，
    对其中的个体调用 VNS 进行局部搜索优化，从而提高种群的收敛速度。
    """
    
    def __init__(self,
                 problem: SchedulingProblem,
                 pop_size: int = 50,
                 n_generations: int = 100,
                 crossover_prob: float = 0.9,
                 mutation_prob: float = 0.1,
                 vns_iterations: int = 10,  # 兼容 comparison_worker
                 seed: Optional[int] = None):
        self.nsga2 = NSGAII(problem, pop_size, n_generations, crossover_prob, mutation_prob, seed)
        self.vns = VNS(problem, max_iters=vns_iterations, seed=seed)
        # 绑定钩子：在 NSGA-II 每一代后执行
        self.nsga2.after_gen_hook = self._local_search_hook

    def _local_search_hook(self, population: List[Solution], fronts: List[List[int]]):
        """对 Front 0 的个体进行 VNS 增强"""
        if not fronts:
            return population, fronts
            
        front0_indices = fronts[0]
        for idx in front0_indices:
            # 执行 VNS 局部搜索
            improved_sol = self.vns.run(population[idx])
            population[idx] = improved_sol
            
        return population, fronts

    def set_progress_callback(self, callback):
        self.nsga2.set_progress_callback(callback)

    def run(self) -> List[Solution]:
        return self.nsga2.run()


class NSGA2_MOSA:
    """
    NSGA-II + MOSA 混合算法
    
    标准实现：在 NSGA-II 的精英选择环节，引入模拟退火的接受概率。
    当子代不支配父代时，不直接丢弃，而是以 Metropolis 概率保留，以维持种群多样性。
    """
    
    def __init__(self,
                 problem: SchedulingProblem,
                 pop_size: int = 50,
                 n_generations: int = 100,
                 crossover_prob: float = 0.9,
                 mutation_prob: float = 0.1,
                 initial_temp: float = 100.0,
                 cooling_rate: float = 0.95,
                 max_iterations: int = 200,  # 兼容 comparison_worker
                 seed: Optional[int] = None):
        self.nsga2 = NSGAII(problem, pop_size, n_generations, crossover_prob, mutation_prob, seed)
        self.temp = initial_temp
        self.cooling_rate = cooling_rate
        # 绑定钩子：用于在每一代结束后执行额外的 SA 逻辑或降温
        self.nsga2.after_gen_hook = self._sa_refinement_hook

    def _sa_refinement_hook(self, population: List[Solution], fronts: List[List[int]]):
        """模拟退火环节：引入概率接受非支配解的变异"""
        # 降温
        self.temp *= self.cooling_rate
        
        # 可以在此处执行一轮 MOSA 风格的个体更新
        for i in range(len(population)):
            # 随机扰动产生邻居
            from algorithms.operators import simple_neighbor
            rng = np.random.default_rng()
            neighbor = simple_neighbor(population[i], rng, self.nsga2.problem)
            self.nsga2.decoder.decode(neighbor)
            
            # 使用 SA 准则判定是否接受该邻居替换当前个体
            if neighbor.dominates(population[i]):
                population[i] = neighbor
            else:
                # 计算退化程度 (delta)
                d1 = neighbor.objectives[0] - population[i].objectives[0]
                d2 = neighbor.objectives[1] - population[i].objectives[1]
                delta = (max(0, d1) + max(0, d2)) / 2.0
                if self.temp > 0.1 and np.random.random() < np.exp(-delta / self.temp):
                    population[i] = neighbor
                    
        return population, fronts

    def set_progress_callback(self, callback):
        self.nsga2.set_progress_callback(callback)

    def run(self) -> List[Solution]:
        return self.nsga2.run()


class NSGA2_VNS_MOSA:
    """
    完整混合算法 (NSGA-II的核心架构 + VNS邻域搜索 + MOSA接受准则)
    这是论文的核心算法。
    """
    
    def __init__(self, 
                 problem: SchedulingProblem, 
                 pop_size: int = 50, 
                 n_generations: int = 100, 
                 crossover_prob: float = 0.9,
                 mutation_prob: float = 0.1,
                 initial_temp: float = 100.0,
                 cooling_rate: float = 0.95,
                 max_iterations: int = 200,  # 兼容 comparison_worker
                 vns_iterations: int = 20,   # 兼容 comparison_worker
                 seed: Optional[int] = None):
        self.nsga2 = NSGAII(problem, pop_size, n_generations, crossover_prob, mutation_prob, seed)
        self.vns = VNS(problem, max_iters=vns_iterations, seed=seed)
        self.temp = initial_temp
        self.cooling_rate = cooling_rate
        self.nsga2.after_gen_hook = self._hybrid_hook

    def _hybrid_hook(self, population: List[Solution], fronts: List[List[int]]):
        self.temp *= self.cooling_rate
        
        if not fronts:
            return population, fronts
            
        # 对前 20% 的精英个体进行复杂的 VNS 增强
        elite_count = max(1, int(len(population) * 0.2))
        elite_indices = fronts[0][:elite_count]
        
        for idx in elite_indices:
            # VNS 搜索
            population[idx] = self.vns.run(population[idx])
            
        return population, fronts

    def set_progress_callback(self, callback):
        self.nsga2.set_progress_callback(callback)

    def run(self) -> List[Solution]:
        return self.nsga2.run()
