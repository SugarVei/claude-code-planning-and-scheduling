"""
解决方案编码模块
Solution Encoding Module

使用四矩阵编码方案表示调度解决方案:
1. 机器分配矩阵 (machine_assign)
2. 序列优先级矩阵 (sequence_priority)  
3. 速度等级矩阵 (speed_level)
4. 工人技能矩阵 (worker_skill)
"""

import numpy as np
from typing import Tuple, Optional, TYPE_CHECKING
from copy import deepcopy

if TYPE_CHECKING:
    from .problem import SchedulingProblem


class Solution:
    """
    调度解决方案类 - 四矩阵编码
    
    Attributes:
        machine_assign: 机器分配矩阵 [job, stage] -> machine_id
        sequence_priority: 序列优先级矩阵 [job, stage] -> priority_value
        speed_level: 速度等级矩阵 [job, stage] -> speed_level
        worker_skill: 工人技能矩阵 [job, stage] -> skill_level
        
        objectives: 目标函数值 (makespan, labor_cost, energy)
        rank: Pareto排名 (用于NSGA-II)
        crowding_distance: 拥挤度距离 (用于NSGA-II)
    """
    
    def __init__(self, 
                 n_jobs: int, 
                 n_stages: int,
                 machine_assign: Optional[np.ndarray] = None,
                 sequence_priority: Optional[np.ndarray] = None,
                 speed_level: Optional[np.ndarray] = None,
                 worker_skill: Optional[np.ndarray] = None):
        """
        初始化解决方案
        
        Args:
            n_jobs: 工件数量
            n_stages: 阶段数量
            machine_assign: 机器分配矩阵，None则创建空矩阵
            sequence_priority: 序列优先级矩阵
            speed_level: 速度等级矩阵
            worker_skill: 工人技能矩阵
        """
        self.n_jobs = n_jobs
        self.n_stages = n_stages
        
        # 四矩阵编码
        self.machine_assign = machine_assign if machine_assign is not None else np.zeros((n_jobs, n_stages), dtype=int)
        self.sequence_priority = sequence_priority if sequence_priority is not None else np.zeros((n_jobs, n_stages), dtype=int)
        self.speed_level = speed_level if speed_level is not None else np.zeros((n_jobs, n_stages), dtype=int)
        self.worker_skill = worker_skill if worker_skill is not None else np.zeros((n_jobs, n_stages), dtype=int)
        
        # 目标函数值: (makespan, labor_cost, energy)
        self.objectives: Optional[Tuple[float, float, float]] = None
        
        # NSGA-II 相关属性
        self.rank: int = 0  # Pareto排名
        self.crowding_distance: float = 0.0  # 拥挤度距离
        
        # 可行性标志
        self.is_feasible: bool = True
        self.feasibility_violations: list = []
    
    @classmethod
    def generate_random(cls, problem: 'SchedulingProblem', seed: Optional[int] = None) -> 'Solution':
        """
        根据问题定义随机生成一个可行解
        
        Args:
            problem: 调度问题实例
            seed: 随机种子
            
        Returns:
            Solution: 随机生成的解决方案
        """
        if seed is not None:
            np.random.seed(seed)
        
        n_jobs = problem.n_jobs
        n_stages = problem.n_stages
        
        # 初始化四矩阵
        machine_assign = np.zeros((n_jobs, n_stages), dtype=int)
        sequence_priority = np.zeros((n_jobs, n_stages), dtype=int)
        speed_level = np.zeros((n_jobs, n_stages), dtype=int)
        worker_skill = np.zeros((n_jobs, n_stages), dtype=int)
        
        for job in range(n_jobs):
            for stage in range(n_stages):
                # 随机选择机器 (在该阶段可用机器范围内)
                n_machines = problem.machines_per_stage[stage]
                machine_assign[job, stage] = np.random.randint(0, n_machines)
                
                # 随机序列优先级 (用于确定同一机器上操作的顺序)
                sequence_priority[job, stage] = np.random.randint(0, 1000)
                
                # 随机速度等级
                speed = np.random.randint(0, problem.n_speed_levels)
                speed_level[job, stage] = speed
                
                # 选择可以操作该速度的最低技能工人 (降低成本)
                # 技能等级必须 >= 速度等级
                min_skill = speed
                if min_skill < problem.n_skill_levels:
                    worker_skill[job, stage] = min_skill
                else:
                    worker_skill[job, stage] = problem.n_skill_levels - 1
        
        solution = cls(
            n_jobs=n_jobs,
            n_stages=n_stages,
            machine_assign=machine_assign,
            sequence_priority=sequence_priority,
            speed_level=speed_level,
            worker_skill=worker_skill
        )
        
        return solution
    
    def copy(self) -> 'Solution':
        """创建解决方案的深拷贝"""
        new_solution = Solution(
            n_jobs=self.n_jobs,
            n_stages=self.n_stages,
            machine_assign=self.machine_assign.copy(),
            sequence_priority=self.sequence_priority.copy(),
            speed_level=self.speed_level.copy(),
            worker_skill=self.worker_skill.copy()
        )
        new_solution.objectives = self.objectives
        new_solution.rank = self.rank
        new_solution.crowding_distance = self.crowding_distance
        new_solution.is_feasible = self.is_feasible
        new_solution.feasibility_violations = self.feasibility_violations.copy()
        return new_solution
    
    def get_operation(self, job: int, stage: int) -> Tuple[int, int, int, int]:
        """
        获取指定操作的所有决策变量
        
        Returns:
            (machine, priority, speed, skill)
        """
        return (
            self.machine_assign[job, stage],
            self.sequence_priority[job, stage],
            self.speed_level[job, stage],
            self.worker_skill[job, stage]
        )
    
    def set_operation(self, job: int, stage: int, 
                      machine: int, priority: int, speed: int, skill: int):
        """设置指定操作的所有决策变量"""
        self.machine_assign[job, stage] = machine
        self.sequence_priority[job, stage] = priority
        self.speed_level[job, stage] = speed
        self.worker_skill[job, stage] = skill
        # 清除缓存的目标函数值
        self.objectives = None
    
    def dominates(self, other: 'Solution') -> bool:
        """
        检查当前解是否支配另一个解 (Pareto支配)
        
        一个解支配另一个解当且仅当:
        1. 在所有目标上都不比另一个差
        2. 在至少一个目标上严格更好
        
        注意: 所有目标都是最小化目标
        """
        if self.objectives is None or other.objectives is None:
            return False
        
        at_least_equal = True
        at_least_one_better = False
        
        for i in range(3):  # 三个目标
            if self.objectives[i] > other.objectives[i]:
                at_least_equal = False
                break
            elif self.objectives[i] < other.objectives[i]:
                at_least_one_better = True
        
        return at_least_equal and at_least_one_better
    
    def check_feasibility(self, problem: 'SchedulingProblem') -> Tuple[bool, list]:
        """
        检查解决方案的可行性
        
        Args:
            problem: 调度问题实例
            
        Returns:
            (is_feasible, violations): 是否可行及违约列表
        """
        violations = []
        
        for job in range(self.n_jobs):
            for stage in range(self.n_stages):
                machine = self.machine_assign[job, stage]
                speed = self.speed_level[job, stage]
                skill = self.worker_skill[job, stage]
                
                # 检查机器分配是否在有效范围内
                if machine >= problem.machines_per_stage[stage]:
                    violations.append(f"工件{job}阶段{stage}: 机器{machine}超出范围")
                
                # 检查速度等级是否在有效范围内
                if speed >= problem.n_speed_levels:
                    violations.append(f"工件{job}阶段{stage}: 速度{speed}超出范围")
                
                # 检查技能等级是否足够操作该速度
                if not problem.can_operate(skill, speed):
                    violations.append(f"工件{job}阶段{stage}: 技能{skill}不能操作速度{speed}")
        
        self.is_feasible = len(violations) == 0
        self.feasibility_violations = violations
        return self.is_feasible, violations
    

    def check_paper_constraints(self, problem: 'SchedulingProblem') -> Tuple[bool, dict]:
        """按论文语义检查关键约束（用于审计与单元测试）。

        覆盖：
        1) 人机绑定：同一(stage, machine) 上所有工序的 worker_skill 必须一致，视为 ω[j,f]
        2) 速度-技能兼容：对任意(i,j)，必须满足 can_operate(W_ij, V_ij)
        3) 可用性：按“启用机器数”计数，各技能等级启用机器数不得超过 workers_available
        4) 最低可行技能一致性：对任一启用机器，ω[j,f] 应等于 maxV_on_machine 的最低可行技能
           （若问题实例定义为“技能>=速度即可操作”，则该最低可行技能等于 maxV；否则以 can_operate 为准）

        Returns:
            (ok, details): ok 为是否全部通过；details 给出分项通过情况与计数/违约信息
        """
        details = {
            "binding_ok": True,
            "compatibility_ok": True,
            "availability_ok": True,
            "min_skill_ok": True,
            "binding_violations": 0,
            "compatibility_violations": 0,
            "availability_violations": 0,
            "min_skill_violations": 0,
        }

        n_jobs, n_stages = self.n_jobs, self.n_stages
        max_machines = max(problem.machines_per_stage)

        # ---- 1) 人机绑定一致性：每台机器只能一个技能值 ω ----
        omega = np.full((n_stages, max_machines), fill_value=-1, dtype=int)
        used = np.zeros((n_stages, max_machines), dtype=bool)

        for i in range(n_jobs):
            for j in range(n_stages):
                f = int(self.machine_assign[i, j])
                if f < 0 or f >= int(problem.machines_per_stage[j]):
                    continue
                used[j, f] = True
                w = int(self.worker_skill[i, j])
                if omega[j, f] == -1:
                    omega[j, f] = w
                elif omega[j, f] != w:
                    details["binding_ok"] = False
                    details["binding_violations"] += 1

        # ---- 2) 速度-技能兼容 ----
        for i in range(n_jobs):
            for j in range(n_stages):
                v = int(self.speed_level[i, j])
                w = int(self.worker_skill[i, j])
                if not problem.can_operate(w, v):
                    details["compatibility_ok"] = False
                    details["compatibility_violations"] += 1

        # ---- 3) 可用性（按启用机器计数） ----
        if problem.workers_available is not None:
            n_skill = int(problem.n_skill_levels)
            machine_count = np.zeros(n_skill, dtype=int)
            for j in range(n_stages):
                for f in range(int(problem.machines_per_stage[j])):
                    if used[j, f]:
                        w = int(omega[j, f])
                        if 0 <= w < n_skill:
                            machine_count[w] += 1
            for skill in range(n_skill):
                avail = int(problem.workers_available[skill])
                if machine_count[skill] > avail:
                    details["availability_ok"] = False
                    details["availability_violations"] += (machine_count[skill] - avail)

        # ---- 4) ω 必须是 maxV 的最低可行技能 ----
        maxV = np.full((n_stages, max_machines), fill_value=-1, dtype=int)
        for i in range(n_jobs):
            for j in range(n_stages):
                f = int(self.machine_assign[i, j])
                if f < 0 or f >= int(problem.machines_per_stage[j]):
                    continue
                v = int(self.speed_level[i, j])
                if v > maxV[j, f]:
                    maxV[j, f] = v

        def min_skill_for_speed(speed: int) -> Optional[int]:
            for skill in range(int(problem.n_skill_levels)):
                if problem.can_operate(skill, speed):
                    return int(skill)
            return None

        for j in range(n_stages):
            for f in range(int(problem.machines_per_stage[j])):
                if not used[j, f]:
                    continue
                ms = min_skill_for_speed(int(maxV[j, f]))
                if ms is None:
                    details["min_skill_ok"] = False
                    details["min_skill_violations"] += 1
                    continue
                if int(omega[j, f]) != int(ms):
                    details["min_skill_ok"] = False
                    details["min_skill_violations"] += 1

        ok = (details["binding_ok"] and details["compatibility_ok"] and
              details["availability_ok"] and details["min_skill_ok"])
        return ok, details

    def repair(self, problem: 'SchedulingProblem') -> Optional['Solution']:
        """
        可行性修复（逐条对照论文伪代码的实现版本）

        论文中的修复顺序为：
        A) 修复“编码取值合法”
        B) 修复“人机绑定”（同一阶段同一机器的 W 必须一致，且取该机任务最大速度对应的最低可行技能）
        C) 修复“技能–速度兼容”（V 必须可由该机工人技能操作）
        D) 修复“全局人力可用性”（按“启用机器数”计数，不是按时间占用）

        关键约定：
        - 若任一阶段在上述步骤中无法修复，则视为修复失败，返回 None（并记录 violations），
          上层算法应直接丢弃该候选解（不进入候选集/种群）。
        """
        self.feasibility_violations = []
        n_jobs, n_stages = self.n_jobs, self.n_stages

        # ------------------------------------------------------------
        # A) 编码取值合法
        # ------------------------------------------------------------
        for j in range(n_stages):
            m_j = int(problem.machines_per_stage[j])
            for i in range(n_jobs):
                # 机器合法
                if self.machine_assign[i, j] < 0 or self.machine_assign[i, j] >= m_j:
                    if m_j <= 0:
                        self.machine_assign[i, j] = 0
                    else:
                        self.machine_assign[i, j] = int(np.random.randint(0, m_j))

                # 速度合法
                if self.speed_level[i, j] < 0 or self.speed_level[i, j] >= problem.n_speed_levels:
                    self.speed_level[i, j] = int(np.random.randint(0, problem.n_speed_levels))

                # 技能合法
                if self.worker_skill[i, j] < 0 or self.worker_skill[i, j] >= problem.n_skill_levels:
                    self.worker_skill[i, j] = int(np.random.randint(0, problem.n_skill_levels))

                # 排序键合法（只需可排序）
                if self.sequence_priority[i, j] < 0:
                    self.sequence_priority[i, j] = int(np.random.randint(0, 1000))

        # 辅助：给定速度 s，返回最低可行技能 α（若不存在返回 None）
        def min_feasible_skill_for_speed(speed: int) -> Optional[int]:
            for skill in range(int(problem.n_skill_levels)):
                if problem.can_operate(skill, speed):
                    return int(skill)
            return None

        # 辅助：给定技能 α，返回该技能可操作的最大速度等级（若不存在返回 -1）
        def max_speed_for_skill(skill: int) -> int:
            max_s = -1
            for s in range(int(problem.n_speed_levels)):
                if problem.can_operate(skill, s):
                    max_s = s
            return int(max_s)

        # ------------------------------------------------------------
        # B) 人机绑定修复：对每个 (stage, machine) 计算 ω[j,f] 并同步到所有 W[i,j]
        #    ω[j,f] = max_speed_on_machine 的最低可行技能
        # ------------------------------------------------------------
        # omega_map: (j,f) -> omega_skill
        omega_map: dict[tuple[int, int], int] = {}

        for j in range(n_stages):
            m_j = int(problem.machines_per_stage[j])
            for f in range(m_j):
                idx = np.where(self.machine_assign[:, j] == f)[0]
                if idx.size == 0:
                    continue

                smax = int(np.max(self.speed_level[idx, j]))
                omega = min_feasible_skill_for_speed(smax)

                # 若不存在可操作该速度的技能：按论文精神，尝试降速；若仍不行则失败
                if omega is None:
                    max_skill = int(problem.n_skill_levels) - 1
                    s_cap = max_speed_for_skill(max_skill)
                    if s_cap < 0:
                        self.feasibility_violations.append(
                            f"修复失败(B): 无任何技能可操作任何速度, stage={j}, machine={f}"
                        )
                        self.is_feasible = False
                        return None

                    # 将该机速度降到 s_cap，再重新计算 omega
                    self.speed_level[idx, j] = np.minimum(self.speed_level[idx, j], s_cap)
                    smax = int(np.max(self.speed_level[idx, j]))
                    omega = min_feasible_skill_for_speed(smax)

                if omega is None:
                    self.feasibility_violations.append(
                        f"修复失败(B): 无法为最大速度 smax={smax} 分配可行技能, stage={j}, machine={f}"
                    )
                    self.is_feasible = False
                    return None

                omega_map[(j, f)] = int(omega)
                self.worker_skill[idx, j] = int(omega)  # 强制该机所有工序 W 一致

        # ------------------------------------------------------------
        # C) 技能–速度兼容修复：对任意工序保证 can_operate(W, V)
        #    由于 B 已按该机最大速度设置 ω，通常应天然满足；但在后续可用性修复中可能降级，仍需检查。
        # ------------------------------------------------------------
        for j in range(n_stages):
            for i in range(n_jobs):
                speed = int(self.speed_level[i, j])
                skill = int(self.worker_skill[i, j])
                if problem.can_operate(skill, speed):
                    continue

                # 方案1：提升技能到最低可行
                new_skill = min_feasible_skill_for_speed(speed)
                if new_skill is not None:
                    # 注意：机器绑定 → 同机所有工序必须一起提升到 new_skill（可能引发可用性压力，交给 D 处理）
                    f = int(self.machine_assign[i, j])
                    idx = np.where(self.machine_assign[:, j] == f)[0]
                    self.worker_skill[idx, j] = int(new_skill)
                    omega_map[(j, f)] = int(new_skill)
                    continue

                # 方案2：降速到该技能可操作的最大速度
                s_cap = max_speed_for_skill(skill)
                if s_cap >= 0:
                    self.speed_level[i, j] = int(s_cap)
                else:
                    self.feasibility_violations.append(
                        f"修复失败(C): skill={skill} 无法操作任何速度, job={i}, stage={j}"
                    )
                    self.is_feasible = False
                    return None

        # 兼容修复后，重新按最大速度生成一次 omega（保持“最低可行技能”语义）
        omega_map = {}
        for j in range(n_stages):
            m_j = int(problem.machines_per_stage[j])
            for f in range(m_j):
                idx = np.where(self.machine_assign[:, j] == f)[0]
                if idx.size == 0:
                    continue
                smax = int(np.max(self.speed_level[idx, j]))
                omega = min_feasible_skill_for_speed(smax)
                if omega is None:
                    self.feasibility_violations.append(
                        f"修复失败(C): 兼容修复后仍无可行技能, stage={j}, machine={f}, smax={smax}"
                    )
                    self.is_feasible = False
                    return None
                omega_map[(j, f)] = int(omega)
                self.worker_skill[idx, j] = int(omega)

        # ------------------------------------------------------------
        # D) 全局人力可用性修复：按“启用机器数”计数
        # ------------------------------------------------------------
        if problem.workers_available is not None:
            available = np.array(problem.workers_available, dtype=int)
            if available.size < int(problem.n_skill_levels):
                available = np.pad(available, (0, int(problem.n_skill_levels) - available.size), constant_values=0)

            def skill_count(omega_dict: dict[tuple[int, int], int]) -> np.ndarray:
                cnt = np.zeros(int(problem.n_skill_levels), dtype=int)
                for (_, _), w in omega_dict.items():
                    if 0 <= int(w) < int(problem.n_skill_levels):
                        cnt[int(w)] += 1
                return cnt

            def try_downgrade_machine(j: int, f: int, new_w: int) -> bool:
                """将 (j,f) 的 ω 降级到 new_w，并保证该机所有工序速度不超过 new_w。"""
                idx = np.where(self.machine_assign[:, j] == f)[0]
                if idx.size == 0:
                    return False
                if new_w < 0:
                    return False
                self.worker_skill[idx, j] = int(new_w)
                self.speed_level[idx, j] = np.minimum(self.speed_level[idx, j], int(new_w))
                omega_map[(j, f)] = int(new_w)
                return True

            # 最多若干轮：先降级技能，再必要时通过“迁移关机”减少启用机器数
            for _round in range(8):
                cnt = skill_count(omega_map)
                overflow = cnt - available
                if np.all(overflow <= 0):
                    break

                fixed = False

                # 1) 优先通过降级解决（从高到低）
                for alpha in range(int(problem.n_skill_levels) - 1, 0, -1):
                    while overflow[alpha] > 0:
                        machines_alpha = [(j, f) for (j, f), w in omega_map.items() if int(w) == alpha]
                        if not machines_alpha:
                            break
                        j, f = machines_alpha[int(np.random.randint(0, len(machines_alpha)))]
                        if try_downgrade_machine(j, f, alpha - 1):
                            fixed = True
                        cnt = skill_count(omega_map)
                        overflow = cnt - available
                        if np.all(overflow <= 0):
                            break

                if np.all(overflow <= 0):
                    break

                # 2) 若仍溢出：尝试“迁移使机器空载”以减少启用机器数
                #    选择一个溢出等级的机器，将其上全部工件迁移到同阶段其它机器；迁移后该机不再计入 omega_map
                migrated = False
                cnt = skill_count(omega_map)
                overflow = cnt - available
                for alpha in range(int(problem.n_skill_levels) - 1, -1, -1):
                    if overflow[alpha] <= 0:
                        continue
                    cand_machines = [(j, f) for (j, f), w in omega_map.items() if int(w) == alpha]
                    np.random.shuffle(cand_machines)
                    for j, f in cand_machines:
                        jobs_on = np.where(self.machine_assign[:, j] == f)[0]
                        if jobs_on.size == 0:
                            omega_map.pop((j, f), None)
                            migrated = True
                            break
                        m_j = int(problem.machines_per_stage[j])
                        other = [x for x in range(m_j) if x != f]
                        if not other:
                            continue
                        # 逐工件迁移（随机目标机器）
                        for i in jobs_on:
                            new_f = int(np.random.choice(other))
                            self.machine_assign[i, j] = new_f
                            self.sequence_priority[i, j] = int(np.random.randint(0, 1000))
                        # 迁移后该机空载
                        omega_map.pop((j, f), None)
                        migrated = True
                        break
                    if migrated:
                        break

                if not (fixed or migrated):
                    break  # 本轮无法进一步修复

                # 迁移/降级后：重新按“最大速度→最低可行技能”生成 omega_map 并同步 W，确保机器绑定仍成立
                omega_map = {}
                for j in range(n_stages):
                    m_j = int(problem.machines_per_stage[j])
                    for f in range(m_j):
                        idx = np.where(self.machine_assign[:, j] == f)[0]
                        if idx.size == 0:
                            continue
                        smax = int(np.max(self.speed_level[idx, j]))
                        omega = min_feasible_skill_for_speed(smax)
                        if omega is None:
                            self.feasibility_violations.append(
                                f"修复失败(D): 迁移/降级后仍无可行技能, stage={j}, machine={f}, smax={smax}"
                            )
                            self.is_feasible = False
                            return None
                        omega_map[(j, f)] = int(omega)
                        self.worker_skill[idx, j] = int(omega)
                        # 保守保证速度不超过技能（即使 can_operate 不是单调，也避免越界）
                        self.speed_level[idx, j] = np.minimum(self.speed_level[idx, j], int(omega))

            # 终检可用性
            cnt = np.zeros(int(problem.n_skill_levels), dtype=int)
            for (_, _), w in omega_map.items():
                if 0 <= int(w) < int(problem.n_skill_levels):
                    cnt[int(w)] += 1
            if np.any(cnt > available):
                self.feasibility_violations.append("修复失败(D): 全局人力可用性约束无法满足")
                self.is_feasible = False
                return None

        # 最终一致性：再做一次机器绑定（保证 W 唯一且为最低可行技能）
        omega_map = {}
        for j in range(n_stages):
            m_j = int(problem.machines_per_stage[j])
            for f in range(m_j):
                idx = np.where(self.machine_assign[:, j] == f)[0]
                if idx.size == 0:
                    continue
                smax = int(np.max(self.speed_level[idx, j]))
                omega = min_feasible_skill_for_speed(smax)
                if omega is None:
                    self.feasibility_violations.append(
                        f"终检失败: stage={j}, machine={f}, smax={smax}"
                    )
                    self.is_feasible = False
                    return None
                omega_map[(j, f)] = int(omega)
                self.worker_skill[idx, j] = int(omega)
                if not np.all([problem.can_operate(int(omega), int(v)) for v in self.speed_level[idx, j]]):
                    # 最后兜底：直接把速度压到 omega
                    self.speed_level[idx, j] = np.minimum(self.speed_level[idx, j], int(omega))

        self.is_feasible = True
        self.objectives = None
        return self

    def get_makespan(self) -> float:
        """获取最大完工时间目标值"""
        return self.objectives[0] if self.objectives else float('inf')
    
    def get_labor_cost(self) -> float:
        """获取人工成本目标值"""
        return self.objectives[1] if self.objectives else float('inf')
    
    def get_energy(self) -> float:
        """获取能耗目标值"""
        return self.objectives[2] if self.objectives else float('inf')
    
    def get_weighted_sum(self, weights: Tuple[float, float, float] = (1.0, 1.0, 1.0)) -> float:
        """
        计算加权和 (用于标量化)
        
        Args:
            weights: 三个目标的权重 (w1, w2, w3)
            
        Returns:
            加权和值
        """
        if self.objectives is None:
            return float('inf')
        return sum(w * obj for w, obj in zip(weights, self.objectives))
    
    def __repr__(self) -> str:
        obj_str = f"({self.objectives[0]:.2f}, {self.objectives[1]:.2f}, {self.objectives[2]:.2f})" if self.objectives else "未评估"
        return f"Solution(n_jobs={self.n_jobs}, n_stages={self.n_stages}, objectives={obj_str}, rank={self.rank})"
    
    def __lt__(self, other: 'Solution') -> bool:
        """用于排序 - 先按rank排序，再按拥挤度排序"""
        if self.rank != other.rank:
            return self.rank < other.rank
        return self.crowding_distance > other.crowding_distance
