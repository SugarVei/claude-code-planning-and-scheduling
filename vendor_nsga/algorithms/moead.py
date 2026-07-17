# -*- coding: utf-8 -*-
"""
MOEA/D 多目标分解进化算法
Multi-Objective Evolutionary Algorithm based on Decomposition

使用 Tchebycheff 分解函数，基于邻域子问题更新策略。
参数参考 Yue2025 表8。
"""

import numpy as np
from typing import List, Tuple, Optional, Callable, Dict
from copy import deepcopy

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.problem import SchedulingProblem
from models.solution import Solution
from models.decoder import Decoder
from algorithms.operators import (
    apply_crossover_with_probability,
    apply_mutation_with_probability,
    mutation_single
)


class MOEAD:
    """
    MOEA/D 多目标分解进化算法
    
    使用 Tchebycheff 分解方法将多目标问题分解为多个标量子问题，
    通过邻域协作进行优化。
    
    Attributes:
        problem: 调度问题实例
        pop_size: 种群大小（等于权重向量数量）
        n_generations: 进化代数
        neighborhood_size: 邻域大小 T（表8: 40）
        delta: 从邻域/全种群选择父代的概率（0.9）
        nr: 每个新解最多替换邻域中 nr 个解（2）
        crossover_prob: 交叉概率（表8: 0.8）
        mutation_prob: 变异概率（表8: 0.15）
    """
    
    def __init__(self,
                 problem: SchedulingProblem,
                 pop_size: int = 50,
                 n_generations: int = 100,
                 neighborhood_size: int = 40,
                 delta: float = 0.9,
                 nr: int = 2,
                 crossover_prob: float = 0.8,
                 mutation_prob: float = 0.15,
                 seed: Optional[int] = None):
        """
        初始化 MOEA/D 算法
        
        Args:
            problem: 调度问题实例
            pop_size: 种群大小
            n_generations: 进化代数
            neighborhood_size: 邻域大小 T
            delta: 邻域选择概率
            nr: 最大替换数
            crossover_prob: 交叉概率
            mutation_prob: 变异概率
            seed: 随机种子
        """
        self.problem = problem
        self.pop_size = pop_size
        self.n_generations = n_generations
        self.neighborhood_size = min(neighborhood_size, pop_size)
        self.delta = delta
        self.nr = nr
        self.crossover_prob = crossover_prob
        self.mutation_prob = mutation_prob
        
        self.decoder = Decoder(problem)
        self.population: List[Solution] = []
        
        # 权重向量和邻域
        self.weights: np.ndarray = None
        self.neighbors: np.ndarray = None  # 每个子问题的邻域索引
        
        # 理想点 z* (各目标最小值)
        self.ideal_point: np.ndarray = np.array([np.inf, np.inf, np.inf])
        
        # 收敛历史
        self.convergence_history = {
            'generation': [],
            'best_makespan': [],
            'best_labor_cost': [],
            'best_energy': [],
            'n_pareto': []
        }
        
        # 随机数生成器
        self.seed = seed
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        else:
            self.rng = np.random.default_rng()
        
        # 回调函数
        self.progress_callback: Optional[Callable[[int, int, str], None]] = None
    
    def set_progress_callback(self, callback: Callable[[int, int, str], None]):
        """设置进度回调函数"""
        self.progress_callback = callback
    
    def _generate_weight_vectors(self) -> np.ndarray:
        """
        生成均匀分布的权重向量（三目标）
        
        使用简化的网格方法生成权重向量。
        """
        weights = []
        H = int(np.ceil(np.sqrt(self.pop_size)))  # 网格划分数
        
        for i in range(H + 1):
            for j in range(H + 1 - i):
                k = H - i - j
                w = np.array([i, j, k]) / H
                weights.append(w)
                if len(weights) >= self.pop_size:
                    break
            if len(weights) >= self.pop_size:
                break
        
        # 如果不够，添加随机权重
        while len(weights) < self.pop_size:
            w = self.rng.random(3)
            w = w / w.sum()
            weights.append(w)
        
        return np.array(weights[:self.pop_size])
    
    def _compute_neighbors(self):
        """
        为每个子问题计算 T 个最近邻
        """
        n = len(self.weights)
        distances = np.zeros((n, n))
        
        for i in range(n):
            for j in range(n):
                distances[i, j] = np.linalg.norm(self.weights[i] - self.weights[j])
        
        self.neighbors = np.zeros((n, self.neighborhood_size), dtype=int)
        for i in range(n):
            sorted_indices = np.argsort(distances[i])
            self.neighbors[i] = sorted_indices[:self.neighborhood_size]
    
    def _initialize_population(self):
        """初始化种群"""
        self.population = []
        for _ in range(self.pop_size):
            solution = Solution.generate_random(self.problem)
            solution.repair(self.problem)
            self.decoder.decode(solution)
            self.population.append(solution)
            
            # 更新理想点
            self._update_ideal_point(solution)
    
    def _update_ideal_point(self, solution: Solution):
        """更新理想点"""
        if solution.objectives is not None:
            for j in range(3):
                if solution.objectives[j] < self.ideal_point[j]:
                    self.ideal_point[j] = solution.objectives[j]
    
    def _tchebycheff(self, solution: Solution, weight: np.ndarray) -> float:
        """
        Tchebycheff 分解函数
        
        g(x|w, z*) = max_{j} { w_j * |f_j(x) - z*_j| }
        """
        if solution.objectives is None:
            return float('inf')
        
        obj = np.array(solution.objectives)
        
        # 避免除零
        weight = np.maximum(weight, 1e-6)
        
        # Tchebycheff
        diffs = weight * np.abs(obj - self.ideal_point)
        return np.max(diffs)
    
    def _select_parents(self, subproblem_idx: int) -> Tuple[int, int]:
        """
        选择父代索引
        
        以概率 delta 从邻域选择，否则从全种群选择
        """
        if self.rng.random() < self.delta:
            # 从邻域选择
            pool = self.neighbors[subproblem_idx]
        else:
            # 从全种群选择
            pool = np.arange(self.pop_size)
        
        idx1, idx2 = self.rng.choice(pool, size=2, replace=False)
        return int(idx1), int(idx2)
    
    def _update_neighbors(self, subproblem_idx: int, new_solution: Solution):
        """
        用新解更新邻域中的解（最多 nr 个）
        """
        updated_count = 0
        neighbor_indices = self.neighbors[subproblem_idx].copy()
        self.rng.shuffle(neighbor_indices)
        
        for j in neighbor_indices:
            if updated_count >= self.nr:
                break
            
            g_new = self._tchebycheff(new_solution, self.weights[j])
            g_old = self._tchebycheff(self.population[j], self.weights[j])
            
            if g_new < g_old:
                self.population[j] = new_solution.copy()
                updated_count += 1
    
    def _get_pareto_front(self) -> List[Solution]:
        """从当前种群中提取非支配解"""
        n = len(self.population)
        is_dominated = [False] * n
        
        for i in range(n):
            if is_dominated[i]:
                continue
            for j in range(n):
                if i == j or is_dominated[j]:
                    continue
                if self.population[j].dominates(self.population[i]):
                    is_dominated[i] = True
                    break
        
        return [self.population[i] for i in range(n) if not is_dominated[i]]
    
    def _record_convergence(self, generation: int):
        """记录收敛历史"""
        pf = self._get_pareto_front()
        
        if pf:
            objectives = np.array([s.objectives for s in pf])
            self.convergence_history['generation'].append(generation)
            self.convergence_history['best_makespan'].append(objectives[:, 0].min())
            self.convergence_history['best_labor_cost'].append(objectives[:, 1].min())
            self.convergence_history['best_energy'].append(objectives[:, 2].min())
            self.convergence_history['n_pareto'].append(len(pf))
    
    def run(self) -> List[Solution]:
        """
        运行 MOEA/D 算法
        
        Returns:
            Pareto 最优解集
        """
        # 初始化权重向量和邻域
        if self.progress_callback:
            self.progress_callback(0, self.n_generations, "MOEA/D 正在初始化...")
        
        self.weights = self._generate_weight_vectors()
        self._compute_neighbors()
        self._initialize_population()
        
        # 主循环
        for gen in range(self.n_generations):
            if self.progress_callback:
                self.progress_callback(gen + 1, self.n_generations,
                                       f"MOEA/D 第 {gen + 1}/{self.n_generations} 代")
            
            for i in range(self.pop_size):
                # 选择父代
                p1_idx, p2_idx = self._select_parents(i)
                parent1 = self.population[p1_idx]
                parent2 = self.population[p2_idx]
                
                # 交叉
                child = apply_crossover_with_probability(
                    parent1, parent2, self.crossover_prob, 
                    self.rng, self.problem, self.decoder
                )
                
                # 变异
                child = apply_mutation_with_probability(
                    child, self.mutation_prob,
                    self.rng, self.problem, self.decoder
                )
                
                # 更新理想点
                self._update_ideal_point(child)
                
                # 更新邻域
                self._update_neighbors(i, child)
            
            # 记录收敛
            self._record_convergence(gen)
        
        # 返回 Pareto 前沿
        pf = self._get_pareto_front()
        
        if self.progress_callback:
            self.progress_callback(self.n_generations, self.n_generations,
                                   f"MOEA/D 完成，找到 {len(pf)} 个 Pareto 解")
        
        return pf
    
    def get_convergence_data(self) -> Dict[str, List[float]]:
        """获取收敛历史数据"""
        return self.convergence_history
