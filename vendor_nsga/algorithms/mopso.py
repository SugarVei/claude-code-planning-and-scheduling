# -*- coding: utf-8 -*-
"""
MOPSO 多目标粒子群优化算法（离散版）
Multi-Objective Particle Swarm Optimization (Discrete Version)

基于学习的离散位置更新策略，适用于四矩阵编码。
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
from algorithms.operators import mutation_single


class MOPSO:
    """
    MOPSO 离散多目标粒子群优化算法
    
    使用基于学习的离散位置更新：
    - 每个基因位置以一定概率从 current/pbest/leader 继承
    - 使用外部仓库存储非支配解
    - 使用拥挤距离进行 leader 选择
    
    Attributes:
        problem: 调度问题实例
        swarm_size: 粒子群大小
        max_iterations: 最大迭代次数
        w: 惯性权重（表8: 0.5）
        c1: 认知系数（表8: 1.5）
        c2: 社会系数（表8: 1.5）
        repository_size: 外部仓库大小（表8: 100）
        mutation_prob: 变异概率（表8: 0.1）
    """
    
    def __init__(self,
                 problem: SchedulingProblem,
                 swarm_size: int = 50,
                 max_iterations: int = 100,
                 w: float = 0.5,
                 c1: float = 1.5,
                 c2: float = 1.5,
                 repository_size: int = 100,
                 mutation_prob: float = 0.1,
                 seed: Optional[int] = None):
        """
        初始化 MOPSO 算法
        
        Args:
            problem: 调度问题实例
            swarm_size: 粒子群大小
            max_iterations: 最大迭代次数
            w: 惯性权重
            c1: 认知系数
            c2: 社会系数
            repository_size: 仓库大小
            mutation_prob: 变异概率
            seed: 随机种子
        """
        self.problem = problem
        self.swarm_size = swarm_size
        self.max_iterations = max_iterations
        self.w = w
        self.c1 = c1
        self.c2 = c2
        self.repository_size = repository_size
        self.mutation_prob = mutation_prob
        
        self.decoder = Decoder(problem)
        
        # 粒子群
        self.swarm: List[Solution] = []
        self.pbest: List[Solution] = []  # 个体历史最优
        
        # 外部仓库
        self.repository: List[Solution] = []
        
        # 收敛历史
        self.convergence_history = {
            'iteration': [],
            'best_makespan': [],
            'best_labor_cost': [],
            'best_energy': [],
            'repository_size': []
        }
        
        # 随机数生成器
        self.seed = seed
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        else:
            self.rng = np.random.default_rng()
        
        # 回调函数
        self.progress_callback: Optional[Callable[[int, int, str], None]] = None
        
        # 归一化选择概率
        total = w + c1 + c2
        self.p_current = w / total
        self.p_pbest = c1 / total
        self.p_leader = c2 / total
    
    def set_progress_callback(self, callback: Callable[[int, int, str], None]):
        """设置进度回调函数"""
        self.progress_callback = callback
    
    def _initialize_swarm(self):
        """初始化粒子群"""
        self.swarm = []
        self.pbest = []
        
        for _ in range(self.swarm_size):
            particle = Solution.generate_random(self.problem)
            particle.repair(self.problem)
            self.decoder.decode(particle)
            
            self.swarm.append(particle)
            self.pbest.append(particle.copy())
            
            # 更新仓库
            self._update_repository(particle)
    
    def _update_repository(self, solution: Solution):
        """
        更新外部仓库
        
        添加非支配解，移除被支配的解
        """
        if solution.objectives is None:
            return
        
        # 检查是否被仓库中任何解支配
        is_dominated = False
        dominated_indices = []
        
        for i, archived in enumerate(self.repository):
            if archived.dominates(solution):
                is_dominated = True
                break
            elif solution.dominates(archived):
                dominated_indices.append(i)
        
        if is_dominated:
            return
        
        # 移除被新解支配的解
        for i in reversed(dominated_indices):
            self.repository.pop(i)
        
        # 添加新解
        self.repository.append(solution.copy())
        
        # 如果仓库满，按拥挤距离截断
        if len(self.repository) > self.repository_size:
            self._truncate_repository()
    
    def _truncate_repository(self):
        """按拥挤距离截断仓库"""
        self._calculate_crowding_distance(self.repository)
        self.repository.sort(key=lambda x: x.crowding_distance, reverse=True)
        self.repository = self.repository[:self.repository_size]
    
    def _calculate_crowding_distance(self, solutions: List[Solution]):
        """计算拥挤距离"""
        n = len(solutions)
        if n <= 2:
            for s in solutions:
                s.crowding_distance = float('inf')
            return
        
        for s in solutions:
            s.crowding_distance = 0.0
        
        for obj_idx in range(3):
            sorted_solutions = sorted(solutions, key=lambda x: x.objectives[obj_idx])
            
            sorted_solutions[0].crowding_distance = float('inf')
            sorted_solutions[-1].crowding_distance = float('inf')
            
            obj_min = sorted_solutions[0].objectives[obj_idx]
            obj_max = sorted_solutions[-1].objectives[obj_idx]
            obj_range = obj_max - obj_min
            
            if obj_range == 0:
                continue
            
            for k in range(1, n - 1):
                distance = (sorted_solutions[k + 1].objectives[obj_idx] -
                           sorted_solutions[k - 1].objectives[obj_idx]) / obj_range
                sorted_solutions[k].crowding_distance += distance
    
    def _select_leader(self) -> Solution:
        """
        选择 leader（全局最优引导者）
        
        使用轮盘赌基于拥挤距离选择
        """
        if not self.repository:
            return self.swarm[0]
        
        # 如果仓库只有一个解，直接返回
        if len(self.repository) == 1:
            return self.repository[0]
        
        self._calculate_crowding_distance(self.repository)
        
        # 使用拥挤距离作为选择概率
        crowding = np.array([s.crowding_distance for s in self.repository])
        
        # 处理 inf 值：用有限最大值的2倍替换
        finite_vals = crowding[np.isfinite(crowding)]
        if len(finite_vals) == 0:
            # 所有值都是 inf，使用均匀分布
            idx = self.rng.integers(0, len(self.repository))
            return self.repository[idx]
        
        max_finite = finite_vals.max() if len(finite_vals) > 0 else 1.0
        crowding = np.where(np.isinf(crowding), max_finite * 2 + 1, crowding)
        crowding = crowding + 1e-6
        
        probs = crowding / crowding.sum()
        
        # 确保没有 NaN
        if np.any(np.isnan(probs)):
            idx = self.rng.integers(0, len(self.repository))
            return self.repository[idx]
        
        idx = self.rng.choice(len(self.repository), p=probs)
        
        return self.repository[idx]
    
    def _update_particle(self, particle: Solution, pbest: Solution, leader: Solution) -> Solution:
        """
        离散位置更新
        
        每个基因位置以概率从 current/pbest/leader 继承
        """
        new_particle = particle.copy()
        
        for job in range(self.problem.n_jobs):
            for stage in range(self.problem.n_stages):
                r = self.rng.random()
                
                if r < self.p_current:
                    # 保持当前（惯性）
                    pass
                elif r < self.p_current + self.p_pbest:
                    # 学习 pbest（认知）
                    new_particle.machine_assign[job, stage] = pbest.machine_assign[job, stage]
                    new_particle.sequence_priority[job, stage] = pbest.sequence_priority[job, stage]
                    new_particle.speed_level[job, stage] = pbest.speed_level[job, stage]
                    new_particle.worker_skill[job, stage] = pbest.worker_skill[job, stage]
                else:
                    # 学习 leader（社会）
                    new_particle.machine_assign[job, stage] = leader.machine_assign[job, stage]
                    new_particle.sequence_priority[job, stage] = leader.sequence_priority[job, stage]
                    new_particle.speed_level[job, stage] = leader.speed_level[job, stage]
                    new_particle.worker_skill[job, stage] = leader.worker_skill[job, stage]
        
        # 变异
        if self.rng.random() < self.mutation_prob:
            new_particle = mutation_single(new_particle, self.rng, self.problem)
        
        new_particle.objectives = None
        new_particle.repair(self.problem)
        self.decoder.decode(new_particle)
        
        return new_particle
    
    def _update_pbest(self, idx: int, new_particle: Solution):
        """更新个体历史最优"""
        old_pbest = self.pbest[idx]
        
        # 如果新粒子支配旧 pbest，更新
        if new_particle.dominates(old_pbest):
            self.pbest[idx] = new_particle.copy()
        # 如果互不支配，随机选择
        elif not old_pbest.dominates(new_particle):
            if self.rng.random() < 0.5:
                self.pbest[idx] = new_particle.copy()
    
    def _record_convergence(self, iteration: int):
        """记录收敛历史"""
        if self.repository:
            objectives = np.array([s.objectives for s in self.repository])
            self.convergence_history['iteration'].append(iteration)
            self.convergence_history['best_makespan'].append(objectives[:, 0].min())
            self.convergence_history['best_labor_cost'].append(objectives[:, 1].min())
            self.convergence_history['best_energy'].append(objectives[:, 2].min())
            self.convergence_history['repository_size'].append(len(self.repository))
    
    def run(self) -> List[Solution]:
        """
        运行 MOPSO 算法
        
        Returns:
            Pareto 最优解集（仓库）
        """
        if self.progress_callback:
            self.progress_callback(0, self.max_iterations, "MOPSO 正在初始化...")
        
        # 初始化
        self._initialize_swarm()
        
        for iteration in range(self.max_iterations):
            if self.progress_callback:
                self.progress_callback(iteration + 1, self.max_iterations,
                                       f"MOPSO 迭代 {iteration + 1}/{self.max_iterations}")
            
            for i in range(self.swarm_size):
                # 选择 leader
                leader = self._select_leader()
                
                # 更新粒子位置
                new_particle = self._update_particle(
                    self.swarm[i], self.pbest[i], leader
                )
                
                # 更新 pbest
                self._update_pbest(i, new_particle)
                
                # 更新粒子
                self.swarm[i] = new_particle
                
                # 更新仓库
                self._update_repository(new_particle)
            
            # 记录收敛
            self._record_convergence(iteration)
        
        if self.progress_callback:
            self.progress_callback(self.max_iterations, self.max_iterations,
                                   f"MOPSO 完成，仓库包含 {len(self.repository)} 个解")
        
        return self.repository
    
    def get_convergence_data(self) -> Dict[str, List[float]]:
        """获取收敛历史数据"""
        return self.convergence_history
