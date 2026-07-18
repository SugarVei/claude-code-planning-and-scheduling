"""
调度问题定义模块
Scheduling Problem Definition Module

定义调度问题的所有参数和数据结构，支持手动输入和自动生成数据。
包含序列相关换模时间、运输时间和五类能耗参数。
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class SchedulingProblem:
    """
    调度问题类 - 存储所有问题参数
    
    基本参数:
        n_jobs: 工件数量
        n_stages: 阶段数量
        machines_per_stage: 每个阶段的机器数量列表
        n_speed_levels: 速度等级数量 (例如: 0=低速, 1=中速, 2=高速)
        n_skill_levels: 工人技能等级数量
        
    时间参数:
        processing_time: 加工时间矩阵 [job][stage][machine][speed] -> time (分钟)
        setup_time: 序列相关换模时间 [stage][machine][job_prev][job_next] -> time (分钟)
        transport_time: 阶段间运输时间 [stage] -> time (分钟), 表示从stage到stage+1的运输时间
        
    能耗参数 (五类能耗):
        processing_power: 加工功率 [stage][machine][speed] -> power (kW)
        setup_power: 换模功率 [stage][machine] -> power (kW)
        idle_power: 空闲功率 [stage][machine] -> power (kW)
        transport_power: 运输功率 (kW), 统一值
        aux_power: 辅助设备功率 (kW), 统一值
        
    人力参数:
        skill_wages: 技能等级工资 [skill] -> 标准工期工资 (元/班次)
        skill_compatibility: 技能等级可操作的最大速度 [skill] -> max_speed
        workers_available: 各技能等级可用工人数 [skill] -> count
        
    其他:
        shift_duration: 班次时长(分钟), 默认480分钟(8小时)
    """
    
    # 基本参数
    n_jobs: int
    n_stages: int
    machines_per_stage: List[int]
    n_speed_levels: int = 3
    n_skill_levels: int = 3
    
    # 时间参数
    processing_time: np.ndarray = field(default=None)  # [job, stage, machine, speed]
    setup_time: np.ndarray = field(default=None)       # [stage, machine, job_prev, job_next]
    transport_time: np.ndarray = field(default=None)   # [stage] (从stage到stage+1)
    
    # 能耗参数 (五类)
    processing_power: np.ndarray = field(default=None)  # [stage, machine, speed] (kW) - 加工功率
    setup_power: np.ndarray = field(default=None)       # [stage, machine] (kW) - 换模功率
    idle_power: np.ndarray = field(default=None)        # [stage, machine] (kW) - 空闲功率
    transport_power: float = 0.5                        # (kW) - 运输功率
    aux_power: float = 1.0                              # (kW) - 辅助功率
    
    # 保留旧字段兼容性 (energy_rate 现改为 processing_power)
    energy_rate: np.ndarray = field(default=None)       # 兼容旧代码
    
    # 人力参数
    skill_wages: np.ndarray = field(default=None)       # [skill] 标准工期工资
    skill_compatibility: np.ndarray = field(default=None)
    workers_available: np.ndarray = field(default=None)
    
    # 其他
    shift_duration: float = 480.0  # 班次时长(分钟)
    
    def __post_init__(self):
        """初始化后检查数据完整性"""
        if len(self.machines_per_stage) != self.n_stages:
            raise ValueError(f"machines_per_stage长度({len(self.machines_per_stage)})必须等于n_stages({self.n_stages})")
        
        # 如果设置了 energy_rate 但没有 processing_power，则复制
        if self.processing_power is None and self.energy_rate is not None:
            self.processing_power = self.energy_rate
        
        # 确保 skill_wages 正确初始化
        if self.skill_wages is None or len(self.skill_wages) < self.n_skill_levels:
            base_wage = 150
            self.skill_wages = np.array([base_wage * (1 + 0.5 * i) for i in range(self.n_skill_levels)])
        
        # 确保 skill_compatibility 正确初始化
        if self.skill_compatibility is None or len(self.skill_compatibility) < self.n_skill_levels:
            self.skill_compatibility = np.array([i for i in range(self.n_skill_levels)])
        
        # 确保 workers_available 正确初始化
        if self.workers_available is None or len(self.workers_available) < self.n_skill_levels:
            self.workers_available = np.array([5 - i for i in range(self.n_skill_levels)])
    
    @classmethod
    def generate_random(cls, 
                        n_jobs: int = 10, 
                        n_stages: int = 5,
                        machines_per_stage: Optional[List[int]] = None,
                        n_speed_levels: int = 3,
                        n_skill_levels: int = 3,
                        workers_available: Optional[List[int]] = None,
                        seed: Optional[int] = None) -> 'SchedulingProblem':
        """
        生成随机但逻辑一致的调度问题数据
        
        生成规则:
        - 加工时间: 10-60分钟基准，高速更快
        - 换模时间: 2-10分钟，同工件无需换模
        - 运输时间: 1-5分钟
        - 能耗: 加工 > 换模 > 运输 > 辅助 > 空闲
        - 工资: 高技能工人工资更高
        """
        if seed is not None:
            np.random.seed(seed)
        
        # 如果未指定每阶段机器数，随机生成2-4台
        if machines_per_stage is None:
            machines_per_stage = [np.random.randint(2, 5) for _ in range(n_stages)]
        
        max_machines = max(machines_per_stage)
        
        # ===== 生成加工时间矩阵 =====
        processing_time = np.zeros((n_jobs, n_stages, max_machines, n_speed_levels))
        for job in range(n_jobs):
            for stage in range(n_stages):
                for machine in range(machines_per_stage[stage]):
                    base_time = np.random.randint(10, 61)  # 基础加工时间10-60分钟
                    for speed in range(n_speed_levels):
                        # 速度越高，时间越短: 低速100%, 中速75%, 高速50%
                        speed_factor = 1.0 - 0.25 * speed
                        processing_time[job, stage, machine, speed] = max(1, int(base_time * speed_factor))
        
        # ===== 生成序列相关换模时间 =====
        setup_time = np.zeros((n_stages, max_machines, n_jobs, n_jobs))
        for stage in range(n_stages):
            for machine in range(machines_per_stage[stage]):
                for j1 in range(n_jobs):
                    for j2 in range(n_jobs):
                        if j1 == j2:
                            setup_time[stage, machine, j1, j2] = 0  # 同工件无换模
                        else:
                            setup_time[stage, machine, j1, j2] = np.random.randint(2, 11)  # 2-10分钟
        
        # ===== 生成运输时间 =====
        transport_time = np.array([np.random.randint(1, 6) for _ in range(n_stages)])  # 1-5分钟
        
        # ===== 生成五类能耗功率 =====
        # 规则: 加工 > 换模 > 运输 > 辅助 > 空闲
        
        # 加工功率: 2-10 kW, 速度越高功率越大
        processing_power = np.zeros((n_stages, max_machines, n_speed_levels))
        for stage in range(n_stages):
            for machine in range(machines_per_stage[stage]):
                base_power = np.random.uniform(3.0, 8.0)
                for speed in range(n_speed_levels):
                    # 速度越高，功率越大: 低速100%, 中速150%, 高速220%
                    power_factor = 1.0 + 0.6 * speed
                    processing_power[stage, machine, speed] = base_power * power_factor
        
        # 换模功率: 加工功率的60-80%
        setup_power = np.zeros((n_stages, max_machines))
        for stage in range(n_stages):
            for machine in range(machines_per_stage[stage]):
                setup_power[stage, machine] = processing_power[stage, machine, 0] * np.random.uniform(0.6, 0.8)
        
        # 空闲功率: 加工功率的10-20%
        idle_power = np.zeros((n_stages, max_machines))
        for stage in range(n_stages):
            for machine in range(machines_per_stage[stage]):
                idle_power[stage, machine] = processing_power[stage, machine, 0] * np.random.uniform(0.1, 0.2)
        
        # 运输功率和辅助功率
        transport_power = np.random.uniform(0.3, 0.8)  # 0.3-0.8 kW
        aux_power = np.random.uniform(0.5, 1.5)        # 0.5-1.5 kW
        
        # ===== 生成工人相关参数 =====
        # 技能工资: 按标准工期(班次)计薪，高技能工资更高
        base_wage = 150  # 基础工资150元/班次
        skill_wages = np.array([base_wage * (1 + 0.5 * i) for i in range(n_skill_levels)])
        
        # 技能等级可操作的最大速度: 等级i可操作速度0~i
        skill_compatibility = np.array([i for i in range(n_skill_levels)])
        
        # 各技能等级可用工人数（优先使用传入值）
        if workers_available is not None:
            workers_available_arr = np.array(workers_available)
        else:
            workers_available_arr = np.array([
                np.random.randint(4, 8),   # 低技能工人: 4-7人
                np.random.randint(3, 6),   # 中技能工人: 3-5人
                np.random.randint(2, 4)    # 高技能工人: 2-3人
            ])
            if n_skill_levels > 3:
                extra_workers = [np.random.randint(1, 3) for _ in range(n_skill_levels - 3)]
                workers_available_arr = np.concatenate([workers_available_arr, extra_workers])
            elif n_skill_levels < 3:
                workers_available_arr = workers_available_arr[:n_skill_levels]
        
        return cls(
            n_jobs=n_jobs,
            n_stages=n_stages,
            machines_per_stage=machines_per_stage,
            n_speed_levels=n_speed_levels,
            n_skill_levels=n_skill_levels,
            processing_time=processing_time,
            setup_time=setup_time,
            transport_time=transport_time,
            processing_power=processing_power,
            setup_power=setup_power,
            idle_power=idle_power,
            transport_power=transport_power,
            aux_power=aux_power,
            energy_rate=processing_power,  # 兼容旧代码
            skill_wages=skill_wages,
            skill_compatibility=skill_compatibility,
            workers_available=workers_available_arr
        )
    
    def get_processing_time(self, job: int, stage: int, machine: int, speed: int) -> float:
        """获取指定操作的加工时间"""
        return self.processing_time[job, stage, machine, speed]
    
    def get_setup_time(self, stage: int, machine: int, job_prev: int, job_next: int) -> float:
        """获取序列相关的换模时间"""
        if self.setup_time is None:
            return 0.0
        if job_prev < 0:  # 第一个工件无需换模
            return 0.0
        return self.setup_time[stage, machine, job_prev, job_next]
    
    def get_transport_time(self, stage: int) -> float:
        """获取从指定阶段到下一阶段的运输时间"""
        if self.transport_time is None:
            return 0.0
        if stage >= self.n_stages - 1:
            return 0.0
        return self.transport_time[stage]
    
    def get_processing_power(self, stage: int, machine: int, speed: int) -> float:
        """获取加工功率 (kW)"""
        if self.processing_power is not None:
            return self.processing_power[stage, machine, speed]
        if self.energy_rate is not None:
            return self.energy_rate[stage, machine, speed]
        return 5.0  # 默认值
    
    def get_setup_power(self, stage: int, machine: int) -> float:
        """获取换模功率 (kW)"""
        if self.setup_power is not None:
            return self.setup_power[stage, machine]
        return 3.0  # 默认值
    
    def get_idle_power(self, stage: int, machine: int) -> float:
        """获取空闲功率 (kW)"""
        if self.idle_power is not None:
            return self.idle_power[stage, machine]
        return 0.5  # 默认值
    
    def get_energy_rate(self, stage: int, machine: int, speed: int) -> float:
        """获取能耗率 (兼容旧接口)"""
        return self.get_processing_power(stage, machine, speed)
    
    def get_wage(self, skill: int) -> float:
        """获取指定技能等级的标准工期工资 (元/班次)"""
        if self.skill_wages is None or len(self.skill_wages) == 0:
            return 150.0 * (1 + 0.5 * skill)  # 默认计算
        # 确保索引在范围内
        skill = min(skill, len(self.skill_wages) - 1)
        return self.skill_wages[skill]
    
    def can_operate(self, skill: int, speed: int) -> bool:
        """检查指定技能等级的工人是否可以操作指定速度"""
        return self.skill_compatibility[skill] >= speed
    
    def get_total_operations(self) -> int:
        """获取总操作数"""
        return self.n_jobs * self.n_stages
    
    def get_total_machines(self) -> int:
        """获取总机器数"""
        return sum(self.machines_per_stage)
    
    def validate(self) -> Tuple[bool, List[str]]:
        """
        验证问题数据的完整性和一致性
        
        Returns:
            (is_valid, error_messages): 是否有效及错误信息列表
        """
        errors = []
        
        if self.processing_time is None:
            errors.append("加工时间矩阵未设置")
        
        if self.processing_power is None and self.energy_rate is None:
            errors.append("加工功率矩阵未设置")
            
        if self.skill_wages is None:
            errors.append("技能工资未设置")
            
        if self.workers_available is None:
            errors.append("可用工人数未设置")
        
        # 检查加工时间是否全为正数
        if self.processing_time is not None:
            if np.any(self.processing_time < 0):
                errors.append("存在负的加工时间")
                
        # 检查功率是否全为正数
        if self.processing_power is not None:
            if np.any(self.processing_power < 0):
                errors.append("存在负的加工功率")
        
        return len(errors) == 0, errors
    
    def summary(self) -> str:
        """返回问题的摘要信息"""
        total_machines = sum(self.machines_per_stage)
        total_workers = sum(self.workers_available) if self.workers_available is not None else 0
        
        return f"""调度问题摘要:
- 工件数: {self.n_jobs}
- 阶段数: {self.n_stages}
- 总机器数: {total_machines}
- 每阶段机器数: {self.machines_per_stage}
- 速度等级数: {self.n_speed_levels}
- 技能等级数: {self.n_skill_levels}
- 总可用工人数: {total_workers}
- 班次时长: {self.shift_duration}分钟
- 运输功率: {self.transport_power:.2f} kW
- 辅助功率: {self.aux_power:.2f} kW
"""
