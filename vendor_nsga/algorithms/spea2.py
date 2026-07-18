# -*- coding: utf-8 -*-
"""
SPEA2 强度 Pareto 进化算法
Strength Pareto Evolutionary Algorithm 2

使用强度值、原始适应度和密度估计进行选择。
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
    apply_mutation_with_probability
)


class SPEA2:
    """
    SPEA2 强度 Pareto 进化算法
    
    特点：
    - 使用强度值 (Strength) 和原始适应度 (Raw Fitness)
    - 基于 k-th 近邻的密度估计
    - 档案截断策略
    
    Attributes:
        problem: 调度问题实例
        pop_size: 种群大小
        archive_size: 档案大小（表8: 100）
        n_generations: 进化代数
        crossover_prob: 交叉概率（表8: 0.8）
        mutation_prob: 变异概率（表8: 0.15）
    """
    
    def __init__(self,
                 problem: SchedulingProblem,
                 pop_size: int = 50,
                 archive_size: int = 100,
                 n_generations: int = 100,
                 crossover_prob: float = 0.8,
                 mutation_prob: float = 0.15,
                 seed: Optional[int] = None):
        """
        初始化 SPEA2 算法
        
        Args:
            problem: 调度问题实例
            pop_size: 种群大小
            archive_size: 档案大小
            n_generations: 进化代数
            crossover_prob: 交叉概率
            mutation_prob: 变异概率
            seed: 随机种子
        """
        self.problem = problem
        self.pop_size = pop_size
        self.archive_size = archive_size
        self.n_generations = n_generations
        self.crossover_prob = crossover_prob
        self.mutation_prob = mutation_prob
        
        self.decoder = Decoder(problem)
        self.population: List[Solution] = []
        self.archive: List[Solution] = []
        
        # 收敛历史
        self.convergence_history = {
            'generation': [],
            'best_makespan': [],
            'best_labor_cost': [],
            'best_energy': [],
            'archive_size': []
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
    
    def _initialize_population(self):
        """初始化种群"""
        self.population = []
        for _ in range(self.pop_size):
            solution = Solution.generate_random(self.problem)
            solution.repair(self.problem)
            self.decoder.decode(solution)
            self.population.append(solution)
    
    def _compute_strength(self, combined: List[Solution]) -> np.ndarray:
        """
        计算强度值 S(i)
        
        S(i) = 被个体 i 支配的个体数量
        """
        n = len(combined)
        strength = np.zeros(n)
        
        for i in range(n):
            for j in range(n):
                if i != j and combined[i].dominates(combined[j]):
                    strength[i] += 1
        
        return strength
    
    def _compute_raw_fitness(self, combined: List[Solution], strength: np.ndarray) -> np.ndarray:
        """
        计算原始适应度 R(i)
        
        R(i) = sum of S(j) for all j that dominate i
        """
        n = len(combined)
        raw_fitness = np.zeros(n)
        
        for i in range(n):
            for j in range(n):
                if i != j and combined[j].dominates(combined[i]):
                    raw_fitness[i] += strength[j]
        
        return raw_fitness
    
    def _compute_density(self, combined: List[Solution]) -> np.ndarray:
        """
        计算密度 D(i) 使用 k-th 近邻
        
        D(i) = 1 / (σ_k + 2)，其中 σ_k 是到第 k 个近邻的距离
        """
        n = len(combined)
        k = int(np.sqrt(n))  # k-th 近邻
        
        # 计算距离矩阵
        objectives = np.array([s.objectives for s in combined])
        distances = np.zeros((n, n))
        
        for i in range(n):
            for j in range(n):
                if i != j:
                    distances[i, j] = np.linalg.norm(objectives[i] - objectives[j])
                else:
                    distances[i, j] = np.inf
        
        # 计算密度
        density = np.zeros(n)
        for i in range(n):
            sorted_distances = np.sort(distances[i])
            sigma_k = sorted_distances[min(k, n - 1)]
            density[i] = 1.0 / (sigma_k + 2.0)
        
        return density
    
    def _compute_fitness(self, combined: List[Solution]) -> np.ndarray:
        """
        计算总适应度 F(i) = R(i) + D(i)
        
        适应度越低越好
        """
        strength = self._compute_strength(combined)
        raw_fitness = self._compute_raw_fitness(combined, strength)
        density = self._compute_density(combined)
        
        return raw_fitness + density
    
    def _environmental_selection(self, combined: List[Solution], fitness: np.ndarray) -> List[Solution]:
        """
        环境选择：选择下一代档案
        
        1. 选择所有 F(i) < 1 的非支配解
        2. 如果不足，从支配解中按适应度选择补足
        3. 如果过多，使用截断策略
        """
        n = len(combined)
        
        # 选择非支配解（F < 1）
        non_dominated_indices = [i for i in range(n) if fitness[i] < 1.0]
        
        if len(non_dominated_indices) == self.archive_size:
            return [combined[i].copy() for i in non_dominated_indices]
        
        elif len(non_dominated_indices) < self.archive_size:
            # 需要从支配解中补充
            dominated_indices = [i for i in range(n) if fitness[i] >= 1.0]
            dominated_indices.sort(key=lambda x: fitness[x])
            
            need = self.archive_size - len(non_dominated_indices)
            selected = non_dominated_indices + dominated_indices[:need]
            return [combined[i].copy() for i in selected]
        
        else:
            # 需要截断
            return self._truncate(combined, non_dominated_indices)
    
    def _truncate(self, combined: List[Solution], indices: List[int]) -> List[Solution]:
        """
        截断策略：移除距离最近的个体
        """
        remaining = list(indices)
        
        while len(remaining) > self.archive_size:
            # 计算剩余个体间的距离
            objectives = np.array([combined[i].objectives for i in remaining])
            n = len(remaining)
            distances = np.zeros((n, n))
            
            for i in range(n):
                for j in range(n):
                    if i != j:
                        distances[i, j] = np.linalg.norm(objectives[i] - objectives[j])
                    else:
                        distances[i, j] = np.inf
            
            # 找到具有最小距离的个体
            min_distances = distances.min(axis=1)
            to_remove = np.argmin(min_distances)
            remaining.pop(to_remove)
        
        return [combined[i].copy() for i in remaining]
    
    def _binary_tournament(self, fitness: np.ndarray, pool_indices: List[int]) -> int:
        """二元锦标赛选择"""
        idx1, idx2 = self.rng.choice(pool_indices, size=2, replace=False)
        return idx1 if fitness[idx1] < fitness[idx2] else idx2
    
    def _record_convergence(self, generation: int):
        """记录收敛历史"""
        if self.archive:
            objectives = np.array([s.objectives for s in self.archive])
            self.convergence_history['generation'].append(generation)
            self.convergence_history['best_makespan'].append(objectives[:, 0].min())
            self.convergence_history['best_labor_cost'].append(objectives[:, 1].min())
            self.convergence_history['best_energy'].append(objectives[:, 2].min())
            self.convergence_history['archive_size'].append(len(self.archive))
    
    def run(self) -> List[Solution]:
        """
        运行 SPEA2 算法
        
        Returns:
            Pareto 最优解集（档案）
        """
        if self.progress_callback:
            self.progress_callback(0, self.n_generations, "SPEA2 正在初始化...")
        
        # 初始化
        self._initialize_population()
        self.archive = []
        
        for gen in range(self.n_generations):
            if self.progress_callback:
                self.progress_callback(gen + 1, self.n_generations,
                                       f"SPEA2 第 {gen + 1}/{self.n_generations} 代")
            
            # 合并种群和档案
            combined = self.population + self.archive
            
            # 计算适应度
            fitness = self._compute_fitness(combined)
            
            # 环境选择
            self.archive = self._environmental_selection(combined, fitness)
            
            # 记录收敛
            self._record_convergence(gen)
            
            # 生成新种群（交配选择）
            archive_fitness = self._compute_fitness(self.archive)
            archive_indices = list(range(len(self.archive)))
            
            new_population = []
            while len(new_population) < self.pop_size:
                # 锦标赛选择
                p1_idx = self._binary_tournament(archive_fitness, archive_indices)
                p2_idx = self._binary_tournament(archive_fitness, archive_indices)
                
                parent1 = self.archive[p1_idx]
                parent2 = self.archive[p2_idx]
                
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
                
                new_population.append(child)
            
            self.population = new_population
        
        if self.progress_callback:
            self.progress_callback(self.n_generations, self.n_generations,
                                   f"SPEA2 完成，档案包含 {len(self.archive)} 个解")
        
        return self.archive
    
    def get_convergence_data(self) -> Dict[str, List[float]]:
        """获取收敛历史数据"""
        return self.convergence_history
