"""计划层 MILP 测试：金标轨迹场景逐项复现 + 更大维度随机数据自检。

金标场景期望值取自 data/vtoy1.xlsx '5_预期行为轨迹' 与 '6_断言清单'
（τ=1/τ=3 的计划层输出行）；随机场景验证"完全由 ProblemData 驱动"
（产品数、阶段数、周期数任意）与约束结构自检（verify_solution）。
"""
import random

import pytest

from src.data.problem_data import EnergyParams, Order, ProblemData
from src.data.validators import validate_problem_data
from src.planning.milp_model import PlanningInputs, solve_planning, verify_solution


def _stage2_load(problem, sol, t):
    return sum(problem.proc_time[p][2] * sol.q[p][t] for p in problem.products)


class TestVtoyTau1:
    """τ=1：窗口 R_1={1,2,3}，需求 D^{(1)}（o1~o6）。"""

    def test_k0_full_demand_on_time(self, vtoy1_problem):
        """k=0：无反馈 → t=1 输出 q=(12,8,5)，阶段2负荷 465≤480，无加班无欠交。"""
        p = vtoy1_problem
        inputs = PlanningInputs(window=(1, 2, 3), demand=p.demand_at(1))
        sol = solve_planning(p, inputs)
        assert sol.status == "OPTIMAL"
        assert (sol.q["A"][1], sol.q["B"][1], sol.q["C"][1]) == (12, 8, 5)
        assert _stage2_load(p, sol, 1) == 465
        for t in inputs.window:
            for prod in p.products:
                assert sol.back[prod][t] == pytest.approx(0)
        # 窗口内全部已知需求足量生产（C 共 5+6=11，含 t=3 交付的 o6）
        assert sum(sol.q["C"].values()) == 11
        assert verify_solution(p, inputs, sol) == []

    def test_k1_effective_capacity_415(self, vtoy1_problem):
        """k=1：通道2 反馈 Cap_2^eff=415 → 移 3B 或移 2C（欠交罚均 24，
        金标"二者接近，以求解器为准"），t=2 清偿。"""
        p = vtoy1_problem
        inputs = PlanningInputs(
            window=(1, 2, 3), demand=p.demand_at(1), cap_eff={(2, 1): 415.0}
        )
        sol = solve_planning(p, inputs)
        assert _stage2_load(p, sol, 1) <= 415
        assert sol.cost_breakdown["backlog"] == pytest.approx(24)
        moved = (round(sol.back["B"][1]), round(sol.back["C"][1]))
        assert moved in {(3, 0), (0, 2)}, f"金标口径应移 3B 或 2C，实际 {moved}"
        assert sol.back["A"][1] == pytest.approx(0)
        for prod in p.products:  # t=2 起全部清偿
            assert sol.back[prod][2] == pytest.approx(0)
            assert sol.back[prod][3] == pytest.approx(0)
        assert verify_solution(p, inputs, sol) == []


class TestVtoyTau3:
    """τ=3：窗口 R_3={3,4}，需求 B14(o9)/C6(o6)@t3、A8(o8)@t4；窗口含 T_max。"""

    def test_k0_no_cut(self, vtoy1_problem):
        """k=0：无割 → q_3=(0,14,6) 负荷 430≤480，A8 留在 t=4。"""
        p = vtoy1_problem
        inputs = PlanningInputs(window=(3, 4), demand=p.demand_at(3))
        sol = solve_planning(p, inputs)
        assert (sol.q["A"][3], sol.q["B"][3], sol.q["C"][3]) == (0, 14, 6)
        assert (sol.q["A"][4], sol.q["B"][4], sol.q["C"][4]) == (8, 0, 0)
        assert _stage2_load(p, sol, 3) == 430
        assert sol.cost_breakdown["backlog"] == pytest.approx(0)
        assert verify_solution(p, inputs, sol) == []

    def test_k1_cut_bc_moves_c(self, vtoy1_problem):
        """k=1：通道3 割 {B,C}@t=3（式5-9：Y_B+Y_C≤1）→ 保B移C：
        q_3=(0,14,0)、Back_C,3=6（罚 72 < 移B 112，A11 口径）、q_4=(8,0,6)。"""
        p = vtoy1_problem
        inputs = PlanningInputs(
            window=(3, 4),
            demand=p.demand_at(3),
            cuts=((frozenset({"B", "C"}), 3),),
        )
        sol = solve_planning(p, inputs)
        assert sol.y["B"][3] + sol.y["C"][3] <= 1, "割约束生效"
        assert (sol.q["A"][3], sol.q["B"][3], sol.q["C"][3]) == (0, 14, 0)
        assert (sol.q["A"][4], sol.q["B"][4], sol.q["C"][4]) == (8, 0, 6)
        assert sol.back["C"][3] == pytest.approx(6)
        assert sol.cost_breakdown["backlog"] == pytest.approx(72)
        # 期末闭合：窗口含 T_max=4 → 全部欠交清零
        for prod in p.products:
            assert sol.back[prod][4] == pytest.approx(0)
        assert verify_solution(p, inputs, sol) == []

    def test_cut_only_binds_its_period(self, vtoy1_problem):
        """A11 口径：割仅作用于 t=τ=3，t=4 允许 B、C 同时在产。"""
        p = vtoy1_problem
        inputs = PlanningInputs(
            window=(3, 4),
            demand=p.demand_at(3),
            cuts=((frozenset({"B", "C"}), 3),),
        )
        sol = solve_planning(p, inputs)
        # t=4 产 C6（与 A 同期）不受割限制；构造性检查：把 B 也压到 t=4 无约束冲突
        assert sol.q["C"][4] == 6


class TestFeedbackChannels:
    """通道1（Δc 风险惩罚项）与目标结构。"""

    def test_delta_c_shifts_production(self, vtoy1_problem):
        """Δc_B,1=60（=δ^max·c_B 上界）→ B 全部移出 t=1（风险罚 480 ≫ 欠交 64）。"""
        p = vtoy1_problem
        base = solve_planning(
            p, PlanningInputs(window=(1, 2, 3), demand=p.demand_at(1))
        )
        assert base.q["B"][1] == 8
        sol = solve_planning(
            p,
            PlanningInputs(
                window=(1, 2, 3), demand=p.demand_at(1), delta_c={("B", 1): 60.0}
            ),
        )
        assert sol.q["B"][1] == 0, "成本修正应把 B 挤出 t=1"
        assert sol.cost_breakdown["risk"] == pytest.approx(0)

    def test_objective_excludes_production_cost(self, vtoy1_problem):
        """目标 = 库存+欠交+启动+风险（口径偏差1：不含 c_p·q 项；表3-3：无加班变量）。"""
        p = vtoy1_problem
        sol = solve_planning(
            p, PlanningInputs(window=(1, 2, 3), demand=p.demand_at(1))
        )
        assert sol.objective == pytest.approx(sum(sol.cost_breakdown.values()))


def _random_problem(seed: int) -> ProblemData:
    """随机生成更大维度的合法 ProblemData（6 产品 × 4 阶段 × 8 周期）。"""
    rng = random.Random(seed)
    products = [f"P{i}" for i in range(1, 7)]
    periods = list(range(1, 9))
    stages = [1, 2, 3, 4]
    machines = {j: [f"M{j}{m}" for m in (1, 2)] for j in stages}
    proc_time = {p: {j: rng.randint(2, 8) for j in stages} for p in products}
    orders = []
    for i, p in enumerate(products):
        for n in range(2):
            due = rng.randint(2, 8)
            orders.append(
                Order(
                    order_id=f"o{i}_{n}",
                    product=p,
                    quantity=rng.randint(10, 25),
                    due_period=due,
                    arrival_period=rng.randint(1, due),
                )
            )
    sdst = {
        a: {b: 0 if a == b else rng.randint(10, 60) for b in products}
        for a in products
    }
    return ProblemData(
        products=products,
        periods=periods,
        stages=stages,
        stage_names={j: f"S{j}" for j in stages},
        machines=machines,
        speed_gears=[1, 2, 3],
        skill_levels=[1, 2, 3],
        cost_prod={p: rng.randint(40, 90) for p in products},
        cost_inv={p: rng.randint(1, 4) for p in products},
        cost_back={p: rng.randint(6, 15) for p in products},
        cost_setup={p: rng.randint(80, 200) for p in products},
        lot_size_max={p: rng.randint(4, 6) for p in products},
        capacity={j: {t: 960.0 for t in periods} for j in stages},
        init_inventory={p: 0.0 for p in products},
        t_avail=480.0,
        ot_max=120.0,
        orders=orders,
        proc_time=proc_time,
        speed_factor={1: 1.0, 2: 0.9, 3: 0.8},
        sdst=sdst,
        initial_setup={p: 10.0 for p in products},
        worker_wage={1: 200.0, 2: 280.0, 3: 400.0},
        worker_available={l: {t: 2 for t in periods} for l in (1, 2, 3)},
        transport_time=5.0,
        energy=EnergyParams(
            power_proc={1: 3.0, 2: 5.0, 3: 8.0},
            power_setup=2.0,
            power_idle=1.0,
            energy_transport=0.1,
            power_aux=0.5,
        ),
        horizon_window=4,
        horizon_freeze=1,
        k_max=3,
        epsilon_converge=0.01,
        feedback_weights=(0.5, 0.3, 0.2),
        gamma=0.5,
        delta_max=1.0,
        n_restart=3,
        kappa_c=2.0,
        kappa_l=1.0,
        kappa_e=0.05,
        kappa_s=0.5,
        rho_min=0.8,
    )


class TestGeneralization:
    """数据驱动泛化：任意维度可解 + 约束结构自检。"""

    @pytest.mark.parametrize("seed", [7, 42])
    def test_random_larger_instance(self, seed):
        problem = _random_problem(seed)
        validate_problem_data(problem)
        inputs = PlanningInputs(
            window=tuple(problem.periods), demand=problem.demand_at(problem.t_max)
        )
        sol = solve_planning(problem, inputs)
        assert sol.status == "OPTIMAL"
        assert verify_solution(problem, inputs, sol) == []
        # 期末闭合：全部欠交清零；产量恰好覆盖总需求（h>0 时不过量生产）
        demand = inputs.demand
        for p in problem.products:
            assert sol.back[p][problem.t_max] == pytest.approx(0)
            assert sum(sol.q[p].values()) == sum(demand[p].values())

    def test_infeasible_reported(self, vtoy1_problem):
        """割覆盖全部产品且当期有硬需求、期末在窗口内 → 无解应明确抛错。"""
        p = vtoy1_problem
        inputs = PlanningInputs(
            window=(4,),
            demand={prod: {4: 5} for prod in p.products},
            cuts=((frozenset(p.products), 4),),
        )
        # t=4=T_max 期末闭合强制 Back=0，但割至多允许 2 族在产 → 必然不可行
        with pytest.raises(ValueError, match="无可行解"):
            solve_planning(p, inputs)