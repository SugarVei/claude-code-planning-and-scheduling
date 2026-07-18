"""ProblemData：与论文符号一一映射的数据类（docs/SYSTEM_DESIGN.md §5）。

索引纪律（V-toy 金标工作簿口径，为权威）：
  - 加工阶段用 j ∈ J（工作簿 '1_系统与算法参数'：J = 1=SMT, 2=DIP, 3=组装）；
  - 速度档位用 s ∈ S（三档，θ_s 速度时间系数）；
  - 技能等级用 α ∈ L（向下兼容：等级 α 的工人可操作档位 s ≤ α）；
  - 计划周期 t 与滚动周期 τ 严格区分：静态字段按 t 索引，
    工人可用性按 τ 索引（缺勤是滚动周期属性），需求由订单流按式(3-3)
    在给定 τ 下聚合（动态到达语义，见 demand_at）。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Order:
    """订单 o（'4_订单流'）：经式(3-3)按到达周期聚合为 D_{p,t}^{(τ)}。"""

    order_id: str        # 订单编号 o
    product: str         # 产品族 p(o)
    quantity: int        # 数量 Q_o
    due_period: int      # 交付周期 d(o)
    arrival_period: int  # 到达周期（进入 O_τ^new 的滚动周期）


@dataclass(frozen=True)
class EnergyParams:
    """能耗参数（'3_调度层数据' 表三）；目标 E 口径：功率(kW)×时间(min)=kW·min。"""

    power_proc: dict[int, float]  # pe_{j,f,s}：各速度档位加工功率 kW（V-toy 全机器同）
    power_setup: float            # se_{j,f}：准备功率 kW
    power_idle: float             # ie_{j,f}：空闲功率 kW
    energy_transport: float       # te：单位运输能耗 kW·min/min
    power_aux: float              # ae：单位时间辅助能耗 kW


@dataclass(frozen=True)
class ProblemData:
    """集成生产计划与调度问题的全部输入数据（字段注释 = 论文符号）。"""

    # ── 集合维度 ──
    products: list[str]             # p ∈ P 产品族
    periods: list[int]              # t ∈ T 计划周期（1..T_max 连续）
    stages: list[int]               # j ∈ J 加工阶段
    stage_names: dict[int, str]     # 阶段名称（如 1=SMT）
    machines: dict[int, list[str]]  # m ∈ M_j 各阶段并行机
    speed_gears: list[int]          # s ∈ S 速度档位
    skill_levels: list[int]         # α ∈ L 技能等级（向下兼容 s ≤ α）

    # ── 计划层参数 ──
    cost_prod: dict[str, float]        # c_p 单位生产成本
    cost_inv: dict[str, float]         # h_p 单位库存持有成本
    cost_back: dict[str, float]        # b_p 单位延期惩罚成本
    cost_setup: dict[str, float]       # g_p 启动成本
    lot_size_max: dict[str, int]       # U_p^lot 最大子批批量（子批化映射规则用）
    capacity: dict[int, dict[int, float]]  # Cap_{j,t}^nom 名义产能（机器时间口径 min）
    init_inventory: dict[str, float]   # 期初库存（V-toy 从零启动 = 0）
    t_avail: float                     # T_t^avail 周期标准可用工时 min
    ot_max: float                      # OT_t^max 最大加班时长 min
    orders: list[Order]                # 订单流（式(3-3) 聚合为 D_{p,t}^{(τ)}）

    # ── 调度层参数 ──
    proc_time: dict[str, dict[int, float]]  # pt^unit_{p,j} 档位1基准单件加工时间（= a_{p,j}）
    speed_factor: dict[int, float]          # θ_s 速度时间系数（PT = 基准 × θ_s）
    sdst: dict[str, dict[str, float]]       # S_{i,i',j,f} SDST 矩阵（产品族级，同族=0）
    initial_setup: dict[str, float]         # S_0,i 虚拟工件初始设置
    worker_wage: dict[int, float]           # S_α 班次工资（元）
    worker_available: dict[int, dict[int, int]]  # 各技能等级在滚动周期 τ 的可用人数
    transport_time: float                   # T_(i,j-1,j,w,f) 运输时间（V-toy 全部 5 min）
    energy: EnergyParams                    # 能耗参数（目标 E 用）

    # ── 滚动与反馈参数 ──
    horizon_window: int                # H_w 滚动窗口长度
    horizon_freeze: int                # H_f 冻结长度
    k_max: int                         # K_max 最大反馈迭代次数
    epsilon_converge: float            # ε_P 目标改善阈值
    feedback_weights: tuple[float, float, float]  # (ω_C, ω_L, ω_E) 代表解归一化权重
    gamma: float                       # γ 成本反馈阻尼
    delta_max: float                   # δ^max 成本反馈上界系数（Δc ≤ δ^max·c_p）
    n_restart: int                     # N_restart 割生成重启次数
    kappa_c: float                     # κ_C 折算系数-加班（元/min）
    kappa_l: float                     # κ_L 折算系数-人力增量
    kappa_e: float                     # κ_E 折算系数-能耗增量（元/(kW·min)）
    kappa_s: float                     # κ_S 折算系数-SDST（元/min）
    rho_min: float                     # ρ_min 调度可接受度阈值

    @property
    def t_max(self) -> int:
        """T_max 最大计划周期。"""
        return max(self.periods)

    def demand_at(self, tau: int) -> dict[str, dict[int, int]]:
        """式(3-3)：到达周期 ≤ τ 的订单按 (产品, 交付周期) 聚合为 D_{p,t}^{(τ)}。"""
        demand = {p: {t: 0 for t in self.periods} for p in self.products}
        for o in self.orders:
            if o.arrival_period <= tau:
                demand[o.product][o.due_period] += o.quantity
        return demand

    def setup_time(self, prev: str | None, nxt: str) -> float:
        """SDST 查表：prev=None 为虚拟工件初始设置 S_0,i；同族=0；异族查矩阵。"""
        if prev is None:
            return self.initial_setup[nxt]
        if prev == nxt:
            return 0.0
        return self.sdst[prev][nxt]
