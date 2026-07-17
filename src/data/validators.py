"""ProblemData 完整性校验（docs/SYSTEM_DESIGN.md §4 validators）。

只校验数据自身的结构合法性（维度一致、非负、口径约束）；
业务可行性（产能是否充足等）由计划层/调度层判定，不在此处。
"""
from __future__ import annotations

from .problem_data import ProblemData


def validate_problem_data(p: ProblemData) -> None:
    """全量校验；发现问题时汇总为一个 ValueError 抛出。"""
    errors: list[str] = []

    # ── 集合维度 ──
    if not p.products or len(set(p.products)) != len(p.products):
        errors.append("products 须非空且唯一")
    if p.periods != list(range(1, len(p.periods) + 1)):
        errors.append("periods 须为从 1 起连续的计划周期序列")
    if not p.stages or len(set(p.stages)) != len(p.stages):
        errors.append("stages 须非空且唯一")
    if set(p.machines) != set(p.stages):
        errors.append("machines 键须覆盖全部阶段")
    else:
        if any(not ms for ms in p.machines.values()):
            errors.append("每个阶段至少配置一台机器")
        all_machines = [m for ms in p.machines.values() for m in ms]
        if len(set(all_machines)) != len(all_machines):
            errors.append("机器编号须全局唯一")
    if set(p.speed_factor) != set(p.speed_gears):
        errors.append("speed_factor(θ_s) 键须与速度档位一致")
    elif any(v <= 0 for v in p.speed_factor.values()):
        errors.append("θ_s 须为正")

    # ── 技能与工人 ──
    if set(p.worker_wage) != set(p.skill_levels):
        errors.append("worker_wage(S_α) 键须与技能等级一致")
    if set(p.worker_available) != set(p.skill_levels):
        errors.append("worker_available 键须与技能等级一致")
    else:
        for level, avail in p.worker_available.items():
            if set(avail) != set(p.periods):
                errors.append(f"worker_available[α={level}] 须覆盖全部滚动周期")
            elif any(not isinstance(v, int) or v < 0 for v in avail.values()):
                errors.append(f"worker_available[α={level}] 须为非负整数")

    # ── 计划层参数 ──
    for name, d in [
        ("cost_prod(c_p)", p.cost_prod),
        ("cost_inv(h_p)", p.cost_inv),
        ("cost_back(b_p)", p.cost_back),
        ("cost_setup(g_p)", p.cost_setup),
        ("init_inventory", p.init_inventory),
    ]:
        if set(d) != set(p.products):
            errors.append(f"{name} 键须与产品一致")
        elif any(v < 0 for v in d.values()):
            errors.append(f"{name} 须非负")
    if set(p.lot_size_max) != set(p.products):
        errors.append("lot_size_max(U_p^lot) 键须与产品一致")
    elif any(not isinstance(v, int) or v < 1 for v in p.lot_size_max.values()):
        errors.append("U_p^lot 须为 ≥1 的整数")
    if set(p.capacity) != set(p.stages):
        errors.append("capacity(Cap_{j,t}) 键须覆盖全部阶段")
    else:
        for j, row in p.capacity.items():
            if set(row) != set(p.periods):
                errors.append(f"capacity[j={j}] 须覆盖全部周期")
            elif any(v < 0 for v in row.values()):
                errors.append(f"capacity[j={j}] 须非负")

    # ── 调度层参数 ──
    if set(p.proc_time) != set(p.products):
        errors.append("proc_time(pt^unit) 键须与产品一致")
    else:
        for prod, row in p.proc_time.items():
            if set(row) != set(p.stages):
                errors.append(f"proc_time[{prod}] 须覆盖全部阶段")
            elif any(v <= 0 for v in row.values()):
                errors.append(f"proc_time[{prod}] 须为正")
    if set(p.initial_setup) != set(p.products) or any(
        v < 0 for v in p.initial_setup.values()
    ):
        errors.append("initial_setup(S_0,i) 须覆盖全部产品且非负")
    if set(p.sdst) != set(p.products):
        errors.append("sdst 行键须与产品一致")
    else:
        for a, row in p.sdst.items():
            if set(row) != set(p.products):
                errors.append(f"sdst[{a}] 列键须与产品一致")
            else:
                if row[a] != 0:
                    errors.append(f"sdst[{a}][{a}] 同族设置时间须为 0")
                if any(v < 0 for v in row.values()):
                    errors.append(f"sdst[{a}] 须非负")
    if set(p.energy.power_proc) != set(p.speed_gears):
        errors.append("energy.power_proc(pe) 键须与速度档位一致")
    elif any(v < 0 for v in p.energy.power_proc.values()):
        errors.append("energy.power_proc(pe) 须非负")
    for name, v in [
        ("power_setup(se)", p.energy.power_setup),
        ("power_idle(ie)", p.energy.power_idle),
        ("energy_transport(te)", p.energy.energy_transport),
        ("power_aux(ae)", p.energy.power_aux),
    ]:
        if v < 0:
            errors.append(f"energy.{name} 须非负")

    # ── 订单流 ──
    order_ids = [o.order_id for o in p.orders]
    if len(set(order_ids)) != len(order_ids):
        errors.append("订单编号须唯一")
    known_products = set(p.products)
    for o in p.orders:
        if o.product not in known_products:
            errors.append(f"订单 {o.order_id} 产品 {o.product} 未定义")
        if o.quantity < 1:
            errors.append(f"订单 {o.order_id} 数量须 ≥1")
        if o.due_period not in p.periods:
            errors.append(f"订单 {o.order_id} 交付周期越界")
        if o.arrival_period not in p.periods:
            errors.append(f"订单 {o.order_id} 到达周期越界")

    # ── 滚动与反馈参数 ──
    if not (1 <= p.horizon_freeze <= p.horizon_window <= len(p.periods)):
        errors.append("须满足 1 ≤ H_f ≤ H_w ≤ T_max")
    if p.k_max < 1:
        errors.append("K_max 须 ≥1")
    if p.epsilon_converge <= 0:
        errors.append("ε_P 须为正")
    if (
        len(p.feedback_weights) != 3
        or any(w < 0 for w in p.feedback_weights)
        or abs(sum(p.feedback_weights) - 1.0) > 1e-9
    ):
        errors.append("代表解权重 (ω_C,ω_L,ω_E) 须非负且和为 1")
    if not (0 <= p.gamma <= 1):
        errors.append("γ 须在 [0,1] 内")
    if p.delta_max < 0:
        errors.append("δ^max 须非负")
    if p.n_restart < 1:
        errors.append("N_restart 须 ≥1")
    if not (0 < p.rho_min <= 1):
        errors.append("ρ_min 须在 (0,1] 内")
    for name, v in [
        ("κ_C", p.kappa_c),
        ("κ_L", p.kappa_l),
        ("κ_E", p.kappa_e),
        ("κ_S", p.kappa_s),
    ]:
        if v < 0:
            errors.append(f"{name} 须非负")
    if p.t_avail <= 0:
        errors.append("T^avail 须为正")
    if p.ot_max < 0:
        errors.append("OT^max 须非负")
    if p.transport_time < 0:
        errors.append("运输时间须非负")

    if errors:
        raise ValueError(
            "ProblemData 校验失败：\n" + "\n".join(f"- {e}" for e in errors)
        )
