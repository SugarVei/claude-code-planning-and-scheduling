"""
数据加载器模块
Data Loader Module

提供从JSON/CSV文件加载调度问题数据的功能，支持论文中的示例数据。
"""

import json
import os
import numpy as np
from typing import Dict, Optional, Tuple
from .problem import SchedulingProblem


class DataLoader:
    """
    数据加载器类
    
    支持从JSON文件加载调度问题实例，包括：
    - 加工时间矩阵
    - 序列相关设置时间矩阵
    - 能耗参数
    - 工人参数
    """
    
    @staticmethod
    def load_example1_5jobs() -> SchedulingProblem:
        """
        加载论文示例1：5工件3阶段简化案例
        
        用于验证解码正确性，速度等级=1，技能等级=1，运输时间=0
        """
        n_jobs = 5
        n_stages = 3
        machines_per_stage = [2, 2, 2]
        n_speed_levels = 1
        n_skill_levels = 1
        max_machines = max(machines_per_stage)
        
        # 加工时间 PT[job][stage][machine][speed]
        # 根据论文表1数据
        processing_time = np.zeros((n_jobs, n_stages, max_machines, n_speed_levels))
        
        # 阶段1: 机器1, 机器2
        pt_stage1 = [[6, 8], [5, 7], [9, 6], [4, 6], [7, 5]]  # A,B,C,D,E
        # 阶段2: 机器3, 机器4 (在代码中索引为0,1)
        pt_stage2 = [[5, 7], [6, 8], [7, 5], [5, 7], [4, 6]]
        # 阶段3: 机器5, 机器6
        pt_stage3 = [[7, 9], [4, 6], [8, 5], [3, 5], [9, 7]]
        
        for job in range(n_jobs):
            processing_time[job, 0, 0, 0] = pt_stage1[job][0]
            processing_time[job, 0, 1, 0] = pt_stage1[job][1]
            processing_time[job, 1, 0, 0] = pt_stage2[job][0]
            processing_time[job, 1, 1, 0] = pt_stage2[job][1]
            processing_time[job, 2, 0, 0] = pt_stage3[job][0]
            processing_time[job, 2, 1, 0] = pt_stage3[job][1]
        
        # 序列相关设置时间 Setup[stage][machine][job_prev][job_next]
        setup_time = np.zeros((n_stages, max_machines, n_jobs, n_jobs))
        
        # 阶段1/机器1 (表2-1)
        setup_s1m1 = [
            [0, 2, 3, 3, 1],
            [2, 0, 2, 1, 3],
            [0, 2, 0, 0, 2],
            [3, 1, 3, 0, 0],
            [1, 0, 2, 0, 0]
        ]
        # 阶段1/机器2 (表2-2)
        setup_s1m2 = [
            [0, 3, 2, 4, 1],
            [1, 0, 3, 1, 2],
            [0, 1, 0, 1, 3],
            [4, 2, 2, 0, 1],
            [2, 1, 1, 0, 0]
        ]
        # 阶段2/机器3 (表3-1)
        setup_s2m1 = [
            [0, 1, 1, 3, 1],
            [4, 0, 2, 1, 3],
            [3, 2, 0, 3, 1],
            [4, 1, 2, 0, 2],
            [4, 3, 3, 2, 0]
        ]
        # 阶段2/机器4 (表3-2)
        setup_s2m2 = [
            [0, 2, 2, 3, 1],
            [3, 0, 3, 2, 2],
            [2, 1, 0, 4, 2],
            [5, 2, 3, 0, 3],
            [3, 4, 2, 1, 0]
        ]
        # 阶段3/机器5 (表4-1)
        setup_s3m1 = [
            [0, 0, 0, 2, 2],
            [1, 0, 2, 1, 2],
            [0, 2, 0, 0, 2],
            [0, 1, 0, 0, 0],
            [1, 2, 1, 0, 0]
        ]
        # 阶段3/机器6 (表4-2)
        setup_s3m2 = [
            [0, 1, 0, 1, 2],
            [0, 0, 1, 1, 1],
            [1, 1, 0, 1, 1],
            [0, 2, 0, 0, 1],
            [2, 1, 2, 0, 0]
        ]
        
        for i in range(n_jobs):
            for j in range(n_jobs):
                setup_time[0, 0, i, j] = setup_s1m1[i][j]
                setup_time[0, 1, i, j] = setup_s1m2[i][j]
                setup_time[1, 0, i, j] = setup_s2m1[i][j]
                setup_time[1, 1, i, j] = setup_s2m2[i][j]
                setup_time[2, 0, i, j] = setup_s3m1[i][j]
                setup_time[2, 1, i, j] = setup_s3m2[i][j]
        
        # 运输时间 = 0 (简化案例)
        transport_time = np.array([0, 0])
        
        # 能耗参数 = 0 (简化案例，用于验证解码正确性)
        processing_power = np.zeros((n_stages, max_machines, n_speed_levels))
        setup_power = np.zeros((n_stages, max_machines))
        idle_power = np.zeros((n_stages, max_machines))
        
        # 工人参数 (简化)
        skill_wages = np.array([150.0])
        skill_compatibility = np.array([0])
        workers_available = np.array([10])
        
        return SchedulingProblem(
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
            transport_power=0.0,
            aux_power=0.0,
            skill_wages=skill_wages,
            skill_compatibility=skill_compatibility,
            workers_available=workers_available,
            shift_duration=480.0
        )
    
    @staticmethod
    def load_example2_15jobs(seed: Optional[int] = 42) -> SchedulingProblem:
        """
        加载论文示例2：15工件3阶段真实案例
        
        包含3速度等级、3技能等级、完整能耗参数
        """
        n_jobs = 15
        n_stages = 3
        machines_per_stage = [3, 3, 3]
        n_speed_levels = 3
        n_skill_levels = 3
        max_machines = max(machines_per_stage)
        
        if seed is not None:
            np.random.seed(seed)
        
        # 加工时间 PT[job][stage][machine][speed]
        # 基础时间 15-45 分钟，速度越高时间越短
        processing_time = np.zeros((n_jobs, n_stages, max_machines, n_speed_levels))
        for job in range(n_jobs):
            for stage in range(n_stages):
                for machine in range(machines_per_stage[stage]):
                    base_time = np.random.randint(15, 46)
                    for speed in range(n_speed_levels):
                        # 低速100%, 中速75%, 高速50%
                        speed_factor = 1.0 - 0.25 * speed
                        processing_time[job, stage, machine, speed] = max(5, int(base_time * speed_factor))
        
        # 序列相关设置时间 Setup[stage][machine][job_prev][job_next]
        setup_time = np.zeros((n_stages, max_machines, n_jobs, n_jobs))
        for stage in range(n_stages):
            for machine in range(machines_per_stage[stage]):
                for i in range(n_jobs):
                    for j in range(n_jobs):
                        if i == j:
                            setup_time[stage, machine, i, j] = 0
                        else:
                            setup_time[stage, machine, i, j] = np.random.randint(2, 8)
        
        # 运输时间
        transport_time = np.array([3, 3])
        
        # 能耗参数 (按论文表格)
        # 加工功率 pe[stage][machine][speed]
        processing_power = np.array([
            # Stage 1
            [[3.5, 5.5, 8.0], [4.0, 6.0, 8.5], [3.8, 5.8, 8.2]],
            # Stage 2
            [[4.2, 6.5, 9.0], [3.8, 5.5, 7.8], [4.0, 6.0, 8.5]],
            # Stage 3
            [[3.5, 5.2, 7.5], [4.0, 6.0, 8.8], [3.6, 5.5, 8.0]]
        ])
        
        # 换模功率 se[stage][machine]
        setup_power = np.array([
            [2.5, 2.8, 2.6],
            [3.0, 2.6, 2.8],
            [2.4, 2.8, 2.5]
        ])
        
        # 空闲功率 ie[stage][machine]
        idle_power = np.array([
            [0.5, 0.6, 0.55],
            [0.6, 0.5, 0.55],
            [0.5, 0.6, 0.5]
        ])
        
        # 工人参数
        # Level A: 150元/班, 7人可用, 只能操作速度0
        # Level B: 225元/班, 5人可用, 可操作速度0-1
        # Level C: 300元/班, 3人可用, 可操作速度0-2
        skill_wages = np.array([150.0, 225.0, 300.0])
        skill_compatibility = np.array([0, 1, 2])  # 技能等级i可操作的最大速度
        workers_available = np.array([7, 5, 3])
        
        return SchedulingProblem(
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
            transport_power=0.5,
            aux_power=1.0,
            skill_wages=skill_wages,
            skill_compatibility=skill_compatibility,
            workers_available=workers_available,
            shift_duration=480.0
        )
    
    @staticmethod
    def load_from_json(filepath: str) -> SchedulingProblem:
        """
        从JSON文件加载调度问题实例
        
        Args:
            filepath: JSON文件路径
            
        Returns:
            SchedulingProblem实例
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        n_jobs = data['n_jobs']
        n_stages = data['n_stages']
        machines_per_stage = data['machines_per_stage']
        n_speed_levels = data.get('n_speed_levels', 3)
        n_skill_levels = data.get('n_skill_levels', 3)
        max_machines = max(machines_per_stage)
        
        # 加工时间
        if 'processing_time' in data and 'data' in data['processing_time']:
            pt_data = data['processing_time']['data']
            processing_time = np.array(pt_data)
        else:
            # 随机生成
            processing_time = np.zeros((n_jobs, n_stages, max_machines, n_speed_levels))
            for job in range(n_jobs):
                for stage in range(n_stages):
                    for machine in range(machines_per_stage[stage]):
                        base_time = np.random.randint(10, 50)
                        for speed in range(n_speed_levels):
                            speed_factor = 1.0 - 0.25 * speed
                            processing_time[job, stage, machine, speed] = max(1, int(base_time * speed_factor))
        
        # 设置时间
        setup_time = np.zeros((n_stages, max_machines, n_jobs, n_jobs))
        if 'setup_time' in data:
            st_data = data['setup_time']
            for stage in range(n_stages):
                for machine in range(machines_per_stage[stage]):
                    key = f'stage{stage+1}_machine{machine+1}'
                    if key in st_data:
                        for i in range(n_jobs):
                            for j in range(n_jobs):
                                setup_time[stage, machine, i, j] = st_data[key][i][j]
        
        # 运输时间
        transport_time = np.array(data.get('transport_time', [0] * (n_stages - 1)))
        
        # 能耗参数
        energy_params = data.get('energy_params', {})
        processing_power = np.zeros((n_stages, max_machines, n_speed_levels))
        setup_power = np.zeros((n_stages, max_machines))
        idle_power = np.zeros((n_stages, max_machines))
        transport_power = float(energy_params.get('transport_power', 0.5))
        aux_power = float(energy_params.get('aux_power', 1.0))
        
        # 工人参数
        worker_params = data.get('worker_params', {})
        skill_wages = np.array(worker_params.get('skill_wages', [150 * (1 + 0.5 * i) for i in range(n_skill_levels)]))
        workers_available = np.array(worker_params.get('workers_available', [5 - i for i in range(n_skill_levels)]))
        skill_compatibility = np.array([i for i in range(n_skill_levels)])
        
        shift_duration = float(data.get('shift_duration', 480.0))
        
        return SchedulingProblem(
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
            skill_wages=skill_wages,
            skill_compatibility=skill_compatibility,
            workers_available=workers_available,
            shift_duration=shift_duration
        )
