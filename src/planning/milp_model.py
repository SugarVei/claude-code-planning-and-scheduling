"""泛化计划层 MILP（论文第 3 章滚动时域计划模型，完全由 ProblemData 驱动）。

模型结构（docs/SYSTEM_DESIGN.md §2.1 / §6 Stage 2）：
  决策变量：q_{p,t}^plan ≥0 整数（生产量）、Y_{p,t}^plan ∈{0,1}（在产/设置
            状态指示）、U_{p,t}（启动，启动逻辑约束下自动取 max{0, Y_t−Y_{t−1}}）、
            Inv、Back ≥0（库存/欠交）、OT_{j,t} ∈[0, OT^max]（加班）。
  约束：    需求平衡；产能（名义 Cap^nom 或通道2反馈的 Cap^eff + 加班）；
            启动逻辑 q ≤ M·Y、U ≥ Y_t − Y_{t−1}；
            通道3不可行组合割 Σ_{p∈C} Y_{p,t_C} ≤ |C|−1（式5-9 形式，
            仅作用于割生成周期，A11 口径）；
            期末闭合：窗口含 T_max 时 Back_{p,T_max}=0（A13"T_max 末全部
            Back=0"口径；真不可行由保护处理移出订单解除，Stage 4）。
  目标：    min Σ h_p·Inv + b_p·Back + g_p·U + κ_C·OT + Σ Δc_{p,t}·q
            （末项为通道1成本修正的调度风险惩罚项）。

口径说明（由金标 V-toy-1 预期轨迹反推确定，与论文式(3-x) 的最终核对留待
论文作者确认；各条推导互为交叉验证）：
  1) g_p 按"启动"计费（U 变量）且窗口起点冷启动（y_prev 缺省 0，不跨窗口
     继承在产状态）。反证：
     - 若按在产周期计费：τ=2 的 C4 会并批推迟至 t=3（省一次 g_C > 欠交罚），
       连锁导致 τ=3 变为"移B"，违反 A11"预计移C(72<112)"；且 τ=1"移3B(24)
       与移2C(24)二者接近"不再成立（移C需额外整期设置费）；
     - 若跨窗口继承在产状态：τ=3 计划层可用 1 件 A 的"保运行"生产免费保持
       A 在产，A 成为缓冲产品使 {B,C} 结构冲突消失，A10 割判据不再触发；
     - 窗口冷启动下 τ=3 割后比较中三个产品的启动费在两方案中完全对称抵消，
       决策差恰为纯欠交罚 72 vs 112，与金标算式逐字一致。
  2) 目标不含 c_p·q 项：滚动窗口内该项会使"推迟生产省成本"成为伪最优，
     与金标 τ=1 k=0 输出 q=(12,8,5) 矛盾；c_p 仅用于 Δc 上界（δ^max·c_p，
     反馈层）与成本报告；
  3) 期末闭合约束见上；不含 T_max 的窗口欠交为软约束（逐期计罚）。
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


@dataclass
class PlanningSolution:
    """计划层解：q^plan、Y^plan 及状态量、目标值与成本分解。"""

    q: dict[str, dict[int, int]]        # q_{p,t}^plan
    y: dict[str, dict[int, int]]        # Y_{p,t}^plan（在产指示）
    startup: dict[str, dict[int, int]]  # U_{p,t}（启动）
    inv: dict[str, dict[int, float]]    # Inv_{p,t}
    back: dict[str, dict[int, float]]   # Back_{p,t}
    ot: dict[int, dict[int, float]]     # OT_{j,t}
    objective: float
    cost_breakdown: dict[str, float]    # holding/backlog/startup/overtime/risk
    status: str


def _new_solver() -> pywraplp.Solver:
    for name in ("SCIP", "CBC"):
        solver = pywraplp.Solver.CreateSolver(name)
        if solver is not None:
            return solver
    raise RuntimeError("无可用 MILP 求解器（需要 ortools 提供的 SCIP 或 CBC）")


def _q_upper_bound(problem: ProblemData, inputs: PlanningInputs, p: str, t: int) -> int:
    """q_{p,t} 的产能型上界（启动逻辑大 M）：各阶段 (产能+加班上限)/单位占用 取最小。"""
    bounds = []
    for j in problem.stages:
        cap = max(problem.capacity[j][t], inputs.cap_eff.get((j, t), 0.0))
        bounds.append((cap + problem.ot_max) / problem.proc_time[p][j])
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
    ot = {
        (j, t): solver.NumVar(0, problem.ot_max, f"OT_{j}_{t}")
        for j in problem.stages
        for t in window
    }

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

    # ── 产能（通道2 Cap^eff 覆盖名义产能）+ 加班 ──
    for j in problem.stages:
        for t in window:
            cap = inputs.cap_eff.get((j, t), problem.capacity[j][t])
            solver.Add(
                solver.Sum(problem.proc_time[p][j] * q[p, t] for p in products)
                <= cap + ot[j, t]
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

    # ── 期末闭合：窗口含 T_max 时 Back_{p,T_max}=0 ──
    if problem.t_max in window:
        for p in products:
            solver.Add(back[p, problem.t_max] == 0)

    # ── 目标 ──
    holding = solver.Sum(problem.cost_inv[p] * inv[p, t] for p in products for t in window)
    backlog = solver.Sum(problem.cost_back[p] * back[p, t] for p in products for t in window)
    startup = solver.Sum(problem.cost_setup[p] * u[p, t] for p in products for t in window)
    overtime = solver.Sum(problem.kappa_c * ot[j, t] for j in problem.stages for t in window)
    risk = solver.Sum(
        inputs.delta_c.get((p, t), 0.0) * q[p, t] for p in products for t in window
    )
    solver.Minimize(holding + backlog + startup + overtime + risk)

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
        ot={j: {t: _val(ot[j, t]) for t in window} for j in problem.stages},
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
            "overtime": sum(
                problem.kappa_c * _val(ot[j, t]) for j in problem.stages for t in window
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
            if load > cap + sol.ot[j][t] + tol:
                violations.append(f"产能违反 j={j} t={t} 负荷={load} > {cap}+OT")
            if sol.ot[j][t] > problem.ot_max + tol:
                violations.append(f"加班超上限 j={j} t={t}")

    for combo, t_cut in inputs.cuts:
        if t_cut in window:
            active = sum(sol.y[p][t_cut] for p in combo)
            if active > len(combo) - 1:
                violations.append(f"割约束违反 C={set(combo)} t={t_cut}")

    if problem.t_max in window:
        for p in problem.products:
            if sol.back[p][problem.t_max] > tol:
                violations.append(f"期末闭合违反 Back[{p}][{problem.t_max}]>0")

    return violations
