"""Excel 适配器测试：V-toy-1 读入结果逐项对照金标数值；Y 模板结构骨架。

金标期望值与 tests/test_vtoy1_workbook.py 锁定的单元格数值一一对应——
适配器读入的 ProblemData 必须与工作簿完全一致。
"""
import pytest

from src.data.excel_adapter import load_y_template_structure
from tests.conftest import Y_TEMPLATE_PATH


class TestLoadVtoy1:
    """load_vtoy1 逐字段对照金标。"""

    def test_dimensions(self, vtoy1_problem):
        p = vtoy1_problem
        assert p.products == ["A", "B", "C"]
        assert p.periods == [1, 2, 3, 4]
        assert p.t_max == 4
        assert p.stages == [1, 2, 3]
        assert p.stage_names == {1: "SMT", 2: "DIP", 3: "组装"}
        assert p.machines == {1: ["M11", "M12"], 2: ["M21"], 3: ["M31", "M32"]}
        assert sum(len(ms) for ms in p.machines.values()) == 5, "机器总数 5（τ=2 机关分母）"
        assert p.speed_gears == [1, 2, 3]
        assert p.skill_levels == [1, 2, 3]

    def test_rolling_and_feedback_params(self, vtoy1_problem):
        p = vtoy1_problem
        assert p.horizon_window == 3 and p.horizon_freeze == 1
        assert p.t_avail == 480 and p.ot_max == 120 and p.transport_time == 5
        assert p.feedback_weights == (0.50, 0.30, 0.20)
        assert p.gamma == 0.5 and p.delta_max == 1 and p.n_restart == 3
        assert (p.kappa_c, p.kappa_l, p.kappa_e, p.kappa_s) == (2, 1, 0.05, 0.5)
        assert p.rho_min == 0.8 and p.epsilon_converge == 0.01 and p.k_max == 3

    def test_planning_params(self, vtoy1_problem):
        p = vtoy1_problem
        assert p.cost_prod == {"A": 50, "B": 60, "C": 70}
        assert p.cost_inv == {"A": 2, "B": 2, "C": 3}
        assert p.cost_back == {"A": 10, "B": 8, "C": 12}
        assert p.cost_setup == {"A": 100, "B": 120, "C": 150}
        assert p.lot_size_max == {"A": 4, "B": 4, "C": 5}
        assert p.init_inventory == {"A": 0, "B": 0, "C": 0}
        for t in p.periods:
            assert p.capacity[1][t] == 960
            assert p.capacity[2][t] == 480, "阶段2 瓶颈"
            assert p.capacity[3][t] == 960

    def test_scheduling_params(self, vtoy1_problem):
        p = vtoy1_problem
        assert p.proc_time == {
            "A": {1: 10, 2: 15, 3: 12},
            "B": {1: 12, 2: 20, 3: 10},
            "C": {1: 8, 2: 25, 3: 14},
        }
        assert p.speed_factor == {1: 1.00, 2: 0.90, 3: 0.80}
        assert p.initial_setup == {"A": 10, "B": 10, "C": 10}
        assert p.sdst == {
            "A": {"A": 0, "B": 20, "C": 30},
            "B": {"A": 25, "B": 0, "C": 280},
            "C": {"A": 25, "B": 280, "C": 0},
        }
        assert p.worker_wage == {1: 200, 2: 280, 3: 400}
        assert p.worker_available == {
            1: {1: 2, 2: 2, 3: 2, 4: 2},
            2: {1: 2, 2: 2, 3: 2, 4: 2},
            3: {1: 1, 2: 0, 3: 1, 4: 1},  # τ=2 α=3 缺勤机关
        }
        assert p.energy.power_proc == {1: 3, 2: 5, 3: 8}
        assert p.energy.power_setup == 2 and p.energy.power_idle == 1
        assert p.energy.energy_transport == 0.1 and p.energy.power_aux == 0.5

    def test_orders(self, vtoy1_problem):
        p = vtoy1_problem
        assert len(p.orders) == 9
        # (订单, 产品, 数量, 交付, 到达)
        expected = [
            ("o1", "A", 12, 1, 1),
            ("o2", "B", 8, 1, 1),
            ("o3", "C", 5, 1, 1),
            ("o4", "A", 6, 2, 1),
            ("o5", "B", 6, 2, 1),
            ("o6", "C", 6, 3, 1),
            ("o7", "C", 4, 2, 2),
            ("o8", "A", 8, 4, 2),
            ("o9", "B", 14, 3, 3),
        ]
        actual = [
            (o.order_id, o.product, o.quantity, o.due_period, o.arrival_period)
            for o in p.orders
        ]
        assert actual == expected


class TestDemandAggregation:
    """demand_at：式(3-3) 按到达周期聚合 D_{p,t}^{(τ)}。"""

    def test_tau1(self, vtoy1_problem):
        d = vtoy1_problem.demand_at(1)
        assert d["A"] == {1: 12, 2: 6, 3: 0, 4: 0}
        assert d["B"] == {1: 8, 2: 6, 3: 0, 4: 0}
        assert d["C"] == {1: 5, 2: 0, 3: 6, 4: 0}
        # 工作簿 '4_订单流' 注记：τ=1 (t=1) 阶段2负荷 = 465 ≤ 480
        load = sum(
            d[p][1] * vtoy1_problem.proc_time[p][2] for p in vtoy1_problem.products
        )
        assert load == 465

    def test_dynamic_arrivals(self, vtoy1_problem):
        d2 = vtoy1_problem.demand_at(2)  # o7(C,4,t2)、o8(A,8,t4) 到达
        assert d2["C"][2] == 4 and d2["A"][4] == 8
        assert d2["B"][3] == 0, "o9 尚未到达"
        d3 = vtoy1_problem.demand_at(3)  # o9(B,14,t3) 到达 → {B,C} 冲突源
        assert d3["B"][3] == 14 and d3["C"][3] == 6
        assert vtoy1_problem.demand_at(4) == d3, "τ=4 无新到达"


@pytest.fixture(scope="module")
def structure():
    return load_y_template_structure(Y_TEMPLATE_PATH)


class TestYTemplateStructure:
    """Y企业模板结构读入骨架（字段映射留待 Stage 6）。"""

    def test_tables_detected(self, structure):
        titles = {
            sheet: [t.title.split()[0] for t in tables]
            for sheet, tables in structure.items()
        }
        assert titles["一 订单与需求"] == ["表1-1", "表1-2", "表1-3"]
        assert titles["二 成本参数"] == ["表2-1"]
        assert titles["三 车间结构与工艺"] == [
            "表3-1", "表3-2", "表3-3", "表3-4", "表3-5", "表3-6",
        ]
        assert titles["四 能耗参数"] == ["表4-1", "表4-2"]
        assert titles["五 人力资源"] == ["表5-1", "表5-2"]
        assert titles["六 日历与产能"] == ["表6-1", "表6-2"]

    def test_key_headers(self, structure):
        t11 = structure["一 订单与需求"][0]
        assert "订单号" in t11.headers and "要求交付日期" in t11.headers
        t32 = structure["三 车间结构与工艺"][1]
        assert "速度档位" in t32.headers and "单件加工时间（min/件）" in t32.headers
        t51 = structure["五 人力资源"][0]
        assert "技能等级" in t51.headers and "可操作的最高速度档位" in t51.headers
