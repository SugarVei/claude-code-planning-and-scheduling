"""
NSGA-II 算法模块
Non-dominated Sorting Genetic Algorithm II

实现多目标进化优化算法，用于生成Pareto最优解集。
"""

import numpy as np
from typing import List, Tuple, Optional, Callable
from copy import deepcopy
import random

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.problem import SchedulingProblem
from models.solution import Solution
from models.decoder import Decoder
from algorithms.operators import four_matrix_sx_crossover


class NSGAII:
    """
    NSGA-II 非支配排序遗传算法
    
    用于多目标优化问题，输出Pareto最优解集。
    """
    
    def __init__(self, 
                 problem: SchedulingProblem,
                 pop_size: int = 50,
                 n_generations: int = 100,
                 crossover_prob: float = 0.9,
                 mutation_prob: float = 0.1,
                 seed: Optional[int] = None):
        """
        初始化NSGA-II算法
        
        Args:
            problem: 调度问题实例
            pop_size: 种群大小
            n_generations: 进化代数
            crossover_prob: 交叉概率
            mutation_prob: 变异概率
            seed: 随机种子
        """
        self.problem = problem
        self.pop_size = pop_size
        self.n_generations = n_generations
        self.crossover_prob = crossover_prob
        self.mutation_prob = mutation_prob
        
        self.decoder = Decoder(problem)
        self.population: List[Solution] = []
        self.rng = np.random.default_rng(seed)
        
        # 收敛历史记录
        self.convergence_history = {
            'generation': [],
            'best_makespan': [],
            'best_labor_cost': [],
            'best_energy': [],
            'avg_makespan': [],
            'avg_labor_cost': [],
            'avg_energy': [],
            'n_pareto': []  # Pareto前沿解的数量
        }
        
        # 回调函数 (用于UI进度更新)
        self.progress_callback: Optional[Callable[[int, int, str], None]] = None
        self.after_gen_hook: Optional[Callable] = None
        
        if seed is not None:
            np.random.seed(seed)
            random.seed(seed)
    
    def set_progress_callback(self, callback: Callable[[int, int, str], None]):
        """
        设置进度回调函数
        
        Args:
            callback: 回调函数 (current_gen, total_gen, message)
        """
        self.progress_callback = callback
    
    def initialize_population(self) -> List[Solution]:
        """
        初始化种群

        说明：repair() 可能返回 None（修复失败）。这里采用“生成→修复→成功才纳入”的策略，
        避免将修复失败个体带入 NSGA-II 的评价与排序。
        """
        population: List[Solution] = []
        tries = 0
        max_tries = self.pop_size * 50  # 防止极端情况下死循环

        while len(population) < self.pop_size and tries < max_tries:
            tries += 1
            sol = Solution.generate_random(self.problem)
            sol = sol.repair(self.problem)
            if sol is None:
                continue
            self.decoder.decode(sol)
            population.append(sol)

        # 兜底：若极端情况下仍不足，则继续尝试直至补齐
        while len(population) < self.pop_size:
            sol = Solution.generate_random(self.problem)
            sol = sol.repair(self.problem)
            if sol is None:
                continue
            self.decoder.decode(sol)
            population.append(sol)

        return population
    def non_dominated_sort(self, population: List[Solution]) -> List[List[int]]:
        """
        非支配排序
    
        将种群分为多个非支配前沿层级。
    
        Args:
            population: 种群
        
        Returns:
            fronts: 前沿列表，每个前沿是解的索引列表
        """
        n = len(population)
    
        # 支配计数和被支配集合
        domination_count = [0] * n  # 支配该解的解的数量
        dominated_solutions = [[] for _ in range(n)]  # 该解支配的解集合
    
        fronts = [[]]  # 前沿层级
    
        # 计算支配关系
        for i in range(n):
            for j in range(i + 1, n):
                if population[i].dominates(population[j]):
                    dominated_solutions[i].append(j)
                    domination_count[j] += 1
                elif population[j].dominates(population[i]):
                    dominated_solutions[j].append(i)
                    domination_count[i] += 1
    
        # 第一前沿 (非支配解)
        for i in range(n):
            if domination_count[i] == 0:
                population[i].rank = 0
                fronts[0].append(i)
    
        # 如果第一前沿为空 (不应该发生)，将所有解放入第一前沿
        if not fronts[0]:
            for i in range(n):
                population[i].rank = 0
                fronts[0].append(i)
            return fronts
    
        # 后续前沿
        current_front = 0
        while current_front < len(fronts) and fronts[current_front]:
            next_front = []
            for i in fronts[current_front]:
                for j in dominated_solutions[i]:
                    domination_count[j] -= 1
                    if domination_count[j] == 0:
                        population[j].rank = current_front + 1
                        next_front.append(j)
        
            current_front += 1
            if next_front:
                fronts.append(next_front)
    
        # 过滤空前沿
        fronts = [f for f in fronts if f]
    
        return fronts
    
    def calculate_crowding_distance(self, population: List[Solution], front: List[int]) -> None:
        """
        计算拥挤度距离
    
        Args:
            population: 种群
            front: 当前前沿的解索引列表
        """
        if len(front) <= 2:
            for i in front:
                population[i].crowding_distance = float('inf')
            return
    
        # 初始化拥挤度
        for i in front:
            population[i].crowding_distance = 0.0
    
        # 对每个目标计算拥挤度
        n_objectives = 3  # makespan, labor_cost, energy
    
        for obj_idx in range(n_objectives):
            # 按该目标排序
            sorted_front = sorted(front, key=lambda x: population[x].objectives[obj_idx])
        
            # 边界解拥挤度设为无穷大
            population[sorted_front[0]].crowding_distance = float('inf')
            population[sorted_front[-1]].crowding_distance = float('inf')
        
            # 目标值范围
            obj_min = population[sorted_front[0]].objectives[obj_idx]
            obj_max = population[sorted_front[-1]].objectives[obj_idx]
            obj_range = obj_max - obj_min
        
            if obj_range == 0:
                continue
        
            # 计算中间解的拥挤度
            for k in range(1, len(sorted_front) - 1):
                curr_idx = sorted_front[k]
                prev_idx = sorted_front[k - 1]
                next_idx = sorted_front[k + 1]
            
                distance = (population[next_idx].objectives[obj_idx] - 
                           population[prev_idx].objectives[obj_idx]) / obj_range
            
                population[curr_idx].crowding_distance += distance
    
    def tournament_selection(self, population: List[Solution]) -> Solution:
        """
        锦标赛选择
    
        选择两个随机个体，返回较优者（rank低或拥挤度高）。
    
        Returns:
            选中的解
        """
        idx1, idx2 = random.sample(range(len(population)), 2)
        sol1, sol2 = population[idx1], population[idx2]
    
        # 优先选择rank低的
        if sol1.rank < sol2.rank:
            return sol1.copy()
        elif sol2.rank < sol1.rank:
            return sol2.copy()
        # rank相同时选择拥挤度高的
        elif sol1.crowding_distance > sol2.crowding_distance:
            return sol1.copy()
        else:
            return sol2.copy()
    
    def crossover(self, parent1: Solution, parent2: Solution) -> Tuple[Solution, Solution]:
        """
        交叉操作 - 四矩阵交换序列交叉 (4M-SX)
    
        基于 Guan et al. (2023) 的 Swap Crossover，适配四矩阵编码。
        在随机选定的阶段上构建 swap-path，逐步交换两个工件的四矩阵值，
        收集中间解候选池，用非支配排序+拥挤度选出两个子代。
    
        Args:
            parent1: 父代1
            parent2: 父代2
        
        Returns:
            (child1, child2): 两个子代（已 repair 且已 decode）
        """
        if random.random() > self.crossover_prob:
            c1, c2 = parent1.copy(), parent2.copy()
            if c1.objectives is None:
                self.decoder.decode(c1)
            if c2.objectives is None:
                self.decoder.decode(c2)
            return c1, c2
    
        child1 = four_matrix_sx_crossover(
            parent1, parent2, self.rng, self.problem, self.decoder
        )
        child2 = four_matrix_sx_crossover(
            parent1, parent2, self.rng, self.problem, self.decoder
        )
        return child1, child2
    
    def mutate(self, solution: Solution) -> Solution:
        """
        变异操作
    
        包含三种变异类型:
        1. 单操作变异 - 改变一个操作的机器/速度/工人
        2. 工件级变异 - 改变一个工件所有阶段的决策
        3. 序列变异 - 交换序列优先级
    
        Args:
            solution: 待变异的解
        
        Returns:
            变异后的解
        """
        if random.random() > self.mutation_prob:
            return solution
    
        # 随机选择变异类型
        mutation_type = random.choice(['operation', 'job', 'sequence'])
    
        n_jobs = self.problem.n_jobs
        n_stages = self.problem.n_stages
    
        if mutation_type == 'operation':
            # 单操作变异
            job = random.randint(0, n_jobs - 1)
            stage = random.randint(0, n_stages - 1)
        
            # 随机改变机器
            n_machines = self.problem.machines_per_stage[stage]
            solution.machine_assign[job, stage] = random.randint(0, n_machines - 1)
        
            # 随机改变速度
            new_speed = random.randint(0, self.problem.n_speed_levels - 1)
            solution.speed_level[job, stage] = new_speed
        
            # 确保工人技能匹配速度
            solution.worker_skill[job, stage] = new_speed
        
        elif mutation_type == 'job':
            # 工件级变异
            job = random.randint(0, n_jobs - 1)
        
            for stage in range(n_stages):
                n_machines = self.problem.machines_per_stage[stage]
                solution.machine_assign[job, stage] = random.randint(0, n_machines - 1)
            
                new_speed = random.randint(0, self.problem.n_speed_levels - 1)
                solution.speed_level[job, stage] = new_speed
                solution.worker_skill[job, stage] = new_speed
            
        else:  # sequence
            # 序列变异 - 在同一机器上交换两个操作的优先级
            stage = random.randint(0, n_stages - 1)
        
            if n_jobs >= 2:
                job1, job2 = random.sample(range(n_jobs), 2)
                solution.sequence_priority[job1, stage], solution.sequence_priority[job2, stage] = \
                    solution.sequence_priority[job2, stage], solution.sequence_priority[job1, stage]
    
        solution.objectives = None
        return solution
    
    def create_offspring(self, population: List[Solution]) -> List[Solution]:
        """
        创建子代种群

        注意：
        - crossover (4M-SX) 内部已完成 repair + decode，返回的子代是完整评估的解。
        - mutate 之后需要重新 repair + decode。
        - repair() 可能返回 None（修复失败），修复失败的子代将被丢弃并重新生成。
        """
        offspring: List[Solution] = []

        safeguard = 0
        max_loops = self.pop_size * 100  # 防止极端情况下死循环

        while len(offspring) < self.pop_size and safeguard < max_loops:
            safeguard += 1

            # 选择父代
            parent1 = self.tournament_selection(population)
            parent2 = self.tournament_selection(population)

            # 交叉 (4M-SX，内部已 repair + decode，连续执行两次获取两个子代)
            child1, child2 = self.crossover(parent1, parent2)

            # 变异（变异后需重新 repair + decode）
            child1 = self.mutate(child1)
            child2 = self.mutate(child2)

            # 修复并评估（失败者丢弃）
            child1 = child1.repair(self.problem)
            if child1 is not None:
                self.decoder.decode(child1)
                offspring.append(child1)
                if len(offspring) >= self.pop_size:
                    break

            child2 = child2.repair(self.problem)
            if child2 is not None:
                self.decoder.decode(child2)
                offspring.append(child2)

        return offspring[: self.pop_size]
    def select_next_generation(self, combined: List[Solution]) -> List[Solution]:
        """
        选择下一代种群 (精英策略)
    
        Args:
            combined: 父代+子代的合并种群
        
        Returns:
            下一代种群
        """
        # 非支配排序
        fronts = self.non_dominated_sort(combined)
    
        # 计算拥挤度
        for front in fronts:
            self.calculate_crowding_distance(combined, front)
    
        # 选择下一代
        next_generation = []
    
        for front in fronts:
            if len(next_generation) + len(front) <= self.pop_size:
                # 整个前沿都可以加入
                for i in front:
                    next_generation.append(combined[i])
            else:
                # 需要根据拥挤度选择
                remaining = self.pop_size - len(next_generation)
                sorted_front = sorted(front, 
                                      key=lambda x: combined[x].crowding_distance, 
                                      reverse=True)
                for i in sorted_front[:remaining]:
                    next_generation.append(combined[i])
                break
    
        return next_generation
    
    def record_convergence(self, generation: int, population: List[Solution], fronts: List[List[int]]):
        """
        记录收敛历史
    
        Args:
            generation: 当前代数
            population: 当前种群
            fronts: 非支配前沿
        """
        objectives = np.array([s.objectives for s in population])
    
        self.convergence_history['generation'].append(generation)
        self.convergence_history['best_makespan'].append(objectives[:, 0].min())
        self.convergence_history['best_labor_cost'].append(objectives[:, 1].min())
        self.convergence_history['best_energy'].append(objectives[:, 2].min())
        self.convergence_history['avg_makespan'].append(objectives[:, 0].mean())
        self.convergence_history['avg_labor_cost'].append(objectives[:, 1].mean())
        self.convergence_history['avg_energy'].append(objectives[:, 2].mean())
        self.convergence_history['n_pareto'].append(len(fronts[0]) if fronts else 0)
    
    def run(self) -> List[Solution]:
        """
        运行NSGA-II算法
    
        Returns:
            Pareto最优解集
        """
        # 初始化种群
        if self.progress_callback:
            self.progress_callback(0, self.n_generations, "正在初始化种群...")
    
        self.population = self.initialize_population()
    
        # 进化循环
        for gen in range(self.n_generations):
            if self.progress_callback:
                self.progress_callback(gen + 1, self.n_generations, 
                                       f"NSGA-II 第 {gen + 1}/{self.n_generations} 代")
        
            # 非支配排序
            fronts = self.non_dominated_sort(self.population)
        
            # 计算拥挤度
            for front in fronts:
                self.calculate_crowding_distance(self.population, front)
        
            # 记录收敛历史
            self.record_convergence(gen, self.population, fronts)
        
            # --- 钩子：每代结束后执行局部增强 (如 VNS) ---
            if hasattr(self, 'after_gen_hook') and self.after_gen_hook:
                self.population, fronts = self.after_gen_hook(self.population, fronts)

            # 创建子代
            offspring = self.create_offspring(self.population)
        
            # 合并父代和子代
            combined = self.population + offspring
        
            # 选择下一代
            self.population = self.select_next_generation(combined)
    
        # 最终非支配排序
        fronts = self.non_dominated_sort(self.population)
    
        # 返回Pareto前沿解
        pareto_solutions = [self.population[i] for i in fronts[0]]
    
        if self.progress_callback:
            self.progress_callback(self.n_generations, self.n_generations, 
                                   f"NSGA-II 完成，找到 {len(pareto_solutions)} 个Pareto解")
    
        return pareto_solutions
    
    def get_pareto_front(self) -> List[Solution]:
        """
        获取当前种群的Pareto前沿
    
        Returns:
            Pareto解列表
        """
        fronts = self.non_dominated_sort(self.population)
        return [self.population[i] for i in fronts[0]]
    
    def get_convergence_data(self) -> dict:
        """
        获取收敛历史数据
    
        Returns:
            收敛历史字典
        """
        return self.convergence_history