# -*- coding: utf-8 -*-
"""
算法包
Algorithms Package

汇总本研究使用的全部多目标元启发式算法：
- NSGAII: 基线 NSGA-II（Deb 等, 2002）
- MOSA: 多目标模拟退火
- VNS: 变邻域搜索
- MOEAD: 基于 Tchebycheff 分解的 MOEA/D
- SPEA2: 强度 Pareto 进化算法 2
- MOPSO: 多目标粒子群（离散版）
- NSGA2_VNS / NSGA2_MOSA: 用于消融实验的两种混合变体
- NSGA2_VNS_MOSA: 本文提出的三模块混合主算法
"""

from .nsga2 import NSGAII
from .mosa import MOSA
from .vns import VNS
from .moead import MOEAD
from .spea2 import SPEA2
from .mopso import MOPSO
from .hybrid_variants import NSGA2_VNS, NSGA2_MOSA, NSGA2_VNS_MOSA

__all__ = [
    'NSGAII', 'MOSA', 'VNS',
    'MOEAD', 'SPEA2', 'MOPSO',
    'NSGA2_VNS', 'NSGA2_MOSA', 'NSGA2_VNS_MOSA'
]
