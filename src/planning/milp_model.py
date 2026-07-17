"""泛化计划层 MILP（论文式(3-4)~(3-14)，完全由 ProblemData 驱动）。

与论文的对应（已对照论文正文核实）：
  决策变量（表3-3）：q_{p,t}^plan ≥0 整数、Y_{p,t}^plan ∈{0,1}（是否安排
            生产）、Inv、Back ≥0；计划层【无加班变量】（加班属于调度层，
            OT=max{0,C_max−T^avail}，式5-4）。另引入辅助变量 U_{p,t}（启动，
            见下方口径偏差 2）。
  约束：    需求平衡式(3-9)；生产状态联结 q ≤ R·Y 式(3-10)；有效产能反馈
            约束式(3-11)（硬约束，Cap^eff 覆盖名义产能，通道2）；
            不可行组合割式(3-12) Σ_{p∈C} Y_{p,t_C} ≤ |C|−1（仅作用于割
            生成周期 τ，通道3）；变量域式(3-14)；
            期末闭合：窗口含 T_max 时 Back_{p,T_max}=0（见口径偏差 3）。
  目标：    式(3-4)~(3-8) 为 min Σ(c_p+Δc_{p,t})q + Σh·Inv + Σb·Back
            + Σg_p·Y_{p,t}；本实现为 min Σh·Inv + Σb·Back + Σg_p·U
            + ΣΔc_{p,t}·q（通道1成本修正项，式3-5 的反馈部分）。

与论文正文的三处刻意偏差（金标 V-toy-1 硬断言强制，"先验证后回写"口径；
每条均有反证与测试锁定）：
  1) 省略 c_p·q 常数项：论文无显式"需求最终必须满足"约束，字面模型下
     "整窗不生产"（欠交罚 12×10×3=360 < 生产 700）成为伪最优，直接违反
     金标 τ=1 k=0 输出 q=(12,8,5) 与 A13；在"需求终须满足"的解空间内
     Σc_p·q 为常数，省略不改变最优解，且规避该病态。
  2) g_p 按"启动"计费（U ≥ Y_t − Y_{t−1}，窗口起点冷启动 y_prev=0）而非
     式(3-8) 字面的逐期计费。反证（逐期计费下金标至少三处被破坏）：
     - τ=2 的 C4 将并批推迟至 t=3（省一次 g_C=150 > 欠交罚 48），τ=3 时
       C 需求变为 10 件 → 负荷 530>480，割判据②负荷排除被触发，A10 的
       "②不排除"路径不再成立；
     - 且移C欠交罚变为 120>112 → 改移B，违反 A11"预计移C(72<112)"；
     - τ=1 k=1"移3B(24)与移2C(24)二者接近"不成立（移C 需加整期 g_C=150）。
     窗口冷启动下 τ=3 割后两方案启动费完全对称抵消，决策差恰为纯欠交罚
     72 vs 112，与金标算式逐字一致；跨窗口继承在产状态同样被否证
     （1 件 A"保运行"即可充当缓冲产品使 {B,C} 冲突消失，A10 失效）。
  3) 期末闭合 Back_{p,T_max}=0：与偏差 1 同源（论文缺需求满足锚点），
     对应 A13"T_max 末全部 Back=0"；真不可行由保护处理移出订单解除
     （算法5-1 第23~32行，Stage 4）。不含 T_max 的窗口欠交仍为软约束。
回写建议（供论文作者定夺，不改正文是实现无法两全）：§3.3 目标函数处
补启动变量定义或说明 g_p 按连续生产段计费；§3.4 或 §3.5 补"计划期末
需求必须满足"条款。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ortools.linear_solver import pywraplp

from src.data.problem_data import ProblemData


@dataclass(frozen=True)
class PlanningInputs:
    """单个滚动周期 τ、单次反馈迭代 k 的计划层输入（由滚动控制器组装）。"""

    window: tuple[int, ...]                 # R_τ 窗口内计划周期（连续）
    demand: dict[str, dict[int, int]]       # D_{p,t}^{(τ)}（式3-3 聚合）
    inv0: dict[str, float] = field(default_factory=dict)   # 窗口起点库存
    back0: dict[str, float] = field(default_factory=dict)  # 窗口起点欠交
    y_prev: dict[str, int] = field(default_factory=dict)   # 窗口前一周期在产状态（金标口径：窗口冷启动，缺省 0）
    delta_c: dict[tuple[str, int], float] = field(default_factory=dict)  # Δc_{p,t}（通道1）
    cap_eff: dict[tuple[int, int], float] = field(default_factory=dict)  # Cap^eff_{j,t}（通道2）
    cuts: tuple[tuple[frozenset[str], int], ...] = ()       # 不可行组合割 (C, t)（通道3）
    relax_terminal: bool = False   # True=松弛期末闭合（割+闭合冲突致不可行时的保护回退）


@dataclass
class PlanningSolution:
    """计划层解：q^plan、Y^plan 及状态量、目标值与成本分解。"""

    q: dict[str, dict[int, int]]        # q_{p,t}^plan
    y: dict[str, dict[int, int]]        # Y_{p,t}^plan（在产指示）
    startup: dict[str, dict[int, int]]  # U_{p,t}（启动）
    inv: dict[str, dict[int, float]]    # Inv_{p,t}
    back: dict[str, dict[int, float]]   # Back_{p,t}
    objective: float
    cost_breakdown: dict[str, float]    # holding/backlog/startup/risk
    status: str


def _new_solver() -> pywraplp.Solver:
    for name in ("SCIP", "CBC"):
        solver = pywraplp.Solver.CreateSolver(name)
        if solver is not None:
            return solver
    raise RuntimeError("无可用 MILP 求解器（需要 ortools 提供的 SCIP 或 CBC）")


def _q_upper_bound(problem: ProblemData, inputs: PlanningInputs, p: str, t: int) -> int:
    """R_{p,t}（式3-10 的允许范围上界）：各阶段 产能/单位占用 取最小。"""
    bounds = []
    for j in problem.stages:
        cap = max(problem.capacity[j][t], inputs.cap_eff.get((j, t), 0.0))
        bounds.append(cap / problem.proc_time[p][j])
    return int(min(bounds))


def solve_planning(problem: ProblemData, inputs: PlanningInputs) -> PlanningSolution:
    """求解一次计划层 MILP；无可行解时抛 ValueError（由上层保护处理接管）。"""
    solver = _new_solver()
    products = problem.products
    window = list(inputs.window)
    demand = inputs.demand

    # ── 变量 ──
    q, y, u, inv, back = {}, {}, {}, {}, {}
    for p in products:
        for t in window:
            q[p, t] = solver.IntVar(0, _q_upper_bound(problem, inputs, p, t), f"q_{p}_{t}")
            y[p, t] = solver.BoolVar(f"Y_{p}_{t}")
            u[p, t] = solver.NumVar(0, 1, f"U_{p}_{t}")
            inv[p, t] = solver.NumVar(0, solver.infinity(), f"Inv_{p}_{t}")
            back[p, t] = solver.NumVar(0, solver.infinity(), f"Back_{p}_{t}")

    # ── 需求平衡：Inv_t − Back_t = Inv_{t−1} − Back_{t−1} + q_t − D_t ──
    for p in products:
        for idx, t in enumerate(window):
            if idx == 0:
                prev = inputs.inv0.get(p, 0.0) - inputs.back0.get(p, 0.0)
            else:
                t_prev = window[idx - 1]
                prev = inv[p, t_prev] - back[p, t_prev]
            d = demand.get(p, {}).get(t, 0)
            solver.Add(inv[p, t] - back[p, t] == prev + q[p, t] - d)

    # ── 有效产能反馈约束 式(3-11)：硬约束，Cap^eff 覆盖名义产能（通道2）──
    for j in problem.stages:
        for t in window:
            cap = inputs.cap_eff.get((j, t), problem.capacity[j][t])
            solver.Add(
                solver.Sum(problem.proc_time[p][j] * q[p, t] for p in products) <= cap
            )

    # ── 启动逻辑：q ≤ M·Y；U ≥ Y_t − Y_{t−1} ──
    for p in products:
        for idx, t in enumerate(window):
            solver.Add(q[p, t] <= _q_upper_bound(problem, inputs, p, t) * y[p, t])
            y_prev = inputs.y_prev.get(p, 0) if idx == 0 else y[p, window[idx - 1]]
            solver.Add(u[p, t] >= y[p, t] - y_prev)

    # ── 通道3：不可行组合割 Σ_{p∈C} Y_{p,t_C} ≤ |C|−1（仅作用于 t_C）──
    for combo, t_cut in inputs.cuts:
        if t_cut in window:
            solver.Add(solver.Sum(y[p, t_cut] for p in combo) <= len(combo) - 1)

    # ── 期末闭合：窗口含 T_max 时 Back_{p,T_max}=0（可松弛，见口径偏差3）──
    if problem.t_max in window and not inputs.relax_terminal:
        for p in products:
            solver.Add(back[p, problem.t_max] == 0)

    # ── 目标 ──
    holding = solver.Sum(problem.cost_inv[p] * inv[p, t] for p in products for t in window)
    backlog = solver.Sum(problem.cost_back[p] * back[p, t] for p in products for t in window)
    startup = solver.Sum(problem.cost_setup[p] * u[p, t] for p in products for t in window)
    risk = solver.Sum(
        inputs.delta_c.get((p, t), 0.0) * q[p, t] for p in products for t in window
    )
    objective = holding + backlog + startup + risk
    if inputs.relax_terminal and problem.t_max in window:
        # 松弛模式字典序：先最小化期末欠交总量（"只移出装不下的"，保护处理
        # 语义；否则口径偏差1的"不产省启动费"病态在无闭合锚点时复活），
        # 再在该上界下优化原目标
        terminal_back = solver.Sum(back[p, problem.t_max] for p in products)
        solver.Minimize(terminal_back)
        status = solver.Solve()
        if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
            raise ValueError(f"计划层 MILP 无可行解（solver status={status}）")
        solver.Add(terminal_back <= terminal_back.solution_value() + 1e-6)
    solver.Minimize(objective)

    status = solver.Solve()
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        raise ValueError(f"计划层 MILP 无可行解（solver status={status}）")

    def _val(var) -> float:
        return var.solution_value()

    sol = PlanningSolution(
        q={p: {t: round(_val(q[p, t])) for t in window} for p in products},
        y={p: {t: round(_val(y[p, t])) for t in window} for p in products},
        startup={p: {t: round(_val(u[p, t])) for t in window} for p in products},
        inv={p: {t: _val(inv[p, t]) for t in window} for p in products},
        back={p: {t: _val(back[p, t]) for t in window} for p in products},
        objective=solver.Objective().Value(),
        cost_breakdown={
            "holding": sum(
                problem.cost_inv[p] * _val(inv[p, t]) for p in products for t in window
            ),
            "backlog": sum(
                problem.cost_back[p] * _val(back[p, t]) for p in products for t in window
            ),
            "startup": sum(
                problem.cost_setup[p] * _val(u[p, t]) for p in products for t in window
            ),
            "risk": sum(
                inputs.delta_c.get((p, t), 0.0) * _val(q[p, t])
                for p in products
                for t in window
            ),
        },
        status="OPTIMAL" if status == pywraplp.Solver.OPTIMAL else "FEASIBLE",
    )
    return sol


def verify_solution(
    problem: ProblemData,
    inputs: PlanningInputs,
    sol: PlanningSolution,
    tol: float = 1e-6,
) -> list[str]:
    """约束结构自检：对解逐条复核约束，返回违反项列表（空 = 通过）。"""
    violations: list[str] = []
    window = list(inputs.window)

    for p in problem.products:
        for idx, t in enumerate(window):
            if idx == 0:
                prev = inputs.inv0.get(p, 0.0) - inputs.back0.get(p, 0.0)
            else:
                tp = window[idx - 1]
                prev = sol.inv[p][tp] - sol.back[p][tp]
            d = inputs.demand.get(p, {}).get(t, 0)
            residual = (sol.inv[p][t] - sol.back[p][t]) - (prev + sol.q[p][t] - d)
            if abs(residual) > tol:
                violations.append(f"需求平衡违反 p={p} t={t} 残差={residual}")
            if sol.q[p][t] > 0 and sol.y[p][t] != 1:
                violations.append(f"启动逻辑违反 q>0 但 Y=0：p={p} t={t}")
            y_prev = (
                inputs.y_prev.get(p, 0) if idx == 0 else sol.y[p][window[idx - 1]]
            )
            if sol.startup[p][t] < sol.y[p][t] - y_prev - tol:
                violations.append(f"启动逻辑违反 U < Y_t − Y_prev：p={p} t={t}")

    for j in problem.stages:
        for t in window:
            load = sum(problem.proc_time[p][j] * sol.q[p][t] for p in problem.products)
            cap = inputs.cap_eff.get((j, t), problem.capacity[j][t])
            if load > cap + tol:
                violations.append(f"产能违反 j={j} t={t} 负荷={load} > {cap}")

    for combo, t_cut in inputs.cuts:
        if t_cut in window:
            active = sum(sol.y[p][t_cut] for p in combo)
            if active > len(combo) - 1:
                violations.append(f"割约束违反 C={set(combo)} t={t_cut}")

    if problem.t_max in window and not inputs.relax_terminal:
        for p in problem.products:
            if sol.back[p][problem.t_max] > tol:
                violations.append(f"期末闭合违反 Back[{p}][{problem.t_max}]>0")

    return violations
