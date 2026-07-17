"""示例数据集测试：生成器可复现、模板读入器字段对齐、机制机关就位。"""
import pytest

from src.data.excel_adapter import load_y_style, load_y_template_structure
from src.data.sample_data import build_sample_workbook
from src.data.validators import validate_problem_data
from tests.conftest import REPO_ROOT

SAMPLE_PATH = REPO_ROOT / "data" / "sample_y_style.xlsx"


@pytest.fixture(scope="module")
def sample_problem():
    assert SAMPLE_PATH.exists(), "示例数据集缺失（由 src/data/sample_data.py 生成）"
    return load_y_style(SAMPLE_PATH)


def test_regenerated_workbook_loads_identically(tmp_path, sample_problem):
    """生成器确定性：重新生成的工作簿读入结果与入库文件一致。"""
    fresh = tmp_path / "sample.xlsx"
    build_sample_workbook(str(fresh))
    p2 = load_y_style(fresh)
    assert p2.products == sample_problem.products
    assert p2.proc_time == sample_problem.proc_time
    assert p2.sdst == sample_problem.sdst
    assert p2.worker_available == sample_problem.worker_available
    assert [
        (o.order_id, o.product, o.quantity, o.due_period, o.arrival_period)
        for o in p2.orders
    ] == [
        (o.order_id, o.product, o.quantity, o.due_period, o.arrival_period)
        for o in sample_problem.orders
    ]


def test_dimensions_and_scale(sample_problem):
    """规模符合 Stage 6 建议：产品族 5~8、阶段 3~4、周期 8~12。"""
    p = sample_problem
    assert 5 <= len(p.products) <= 8
    assert 3 <= len(p.stages) <= 4
    assert 8 <= len(p.periods) <= 12
    assert sum(len(m) for m in p.machines.values()) == 8
    assert len(p.orders) == 28
    validate_problem_data(p)


def test_loader_field_alignment(sample_problem):
    """模板字段 → ProblemData 对齐：θ 反推、产能、日历、能耗换算。"""
    p = sample_problem
    assert p.speed_factor == {1: 1.0, 2: 0.9, 3: 0.8}
    assert p.t_avail == 480 and p.ot_max == 120
    assert p.capacity[2][1] == 960, "DIP 2 台 × 480"
    assert p.initial_setup == {f: 10.0 for f in p.products}
    assert p.sdst["F3"]["F5"] == 240, "深度换模对"
    assert p.energy.energy_transport == pytest.approx(0.12), "0.01kWh/次 → kW·min/min"
    assert p.transport_time == 5


def test_mechanism_hooks(sample_problem):
    """机制机关：τ=6 高级技工缺勤（η=7/8）；τ=4 DIP 高负荷（加班型）。"""
    p = sample_problem
    assert p.worker_available[3][6] == 0
    assert sum(p.worker_available[l][6] for l in p.skill_levels) == 7
    d = p.demand_at(p.t_max)
    load_t4 = sum(d[f][4] * p.proc_time[f][2] for f in p.products)
    assert load_t4 == pytest.approx(848), "τ=4 DIP 高负荷（≤960 计划可行，调度紧张）"


def test_sample_marked_as_synthetic(sample_problem):
    """示例数据声明：文件名与各表元信息显式标注（硬性约束'不虚构'）。"""
    assert "sample" in SAMPLE_PATH.name
    structure = load_y_template_structure(SAMPLE_PATH)
    assert set(structure) >= {"一 订单与需求", "二 成本参数", "三 车间结构与工艺",
                             "四 能耗参数", "五 人力资源", "六 日历与产能"}
    import openpyxl

    wb = openpyxl.load_workbook(SAMPLE_PATH, read_only=True)
    for name in ["一 订单与需求", "二 成本参数", "三 车间结构与工艺",
                 "四 能耗参数", "五 人力资源", "六 日历与产能"]:
        first = next(wb[name].iter_rows(max_row=1, values_only=True))[0]
        assert "示例数据" in str(first), f"{name} 缺少示例数据标注"
