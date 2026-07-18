"""可视化图表构造测试（基于真实 V-toy 闭环运行结果的纯函数验证）。"""
import pytest

from app.plots import (
    cmax_overview_figure,
    family_colors,
    gantt_figure,
    iteration_table_rows,
    pareto_figure,
    plan_overview_figure,
    state_overview_figure,
)
from src.feedback.channels import FeedbackConfig
from src.rolling.controller import run_rolling
from src.scheduling.exact_cpsat import CpSatScheduler

pytestmark = pytest.mark.slow_solver


@pytest.fixture(scope="module")
def vtoy_run(vtoy1_problem):
    return run_rolling(
        vtoy1_problem, CpSatScheduler(time_limit_s=120), FeedbackConfig(), base_seed=0
    )


def test_family_colors_fixed_order(vtoy1_problem):
    colors = family_colors(vtoy1_problem)
    assert list(colors) == vtoy1_problem.products, "按 products 固定顺序分配"
    assert len(set(colors.values())) == len(colors), "不重复、不循环"


def test_gantt_figure(vtoy1_problem, vtoy_run):
    pr = vtoy_run.period(1)
    fig = gantt_figure(vtoy1_problem, pr.schedule, "τ=1")
    bars = [t for t in fig.data if t.type == "bar"]
    ops = pr.schedule.operations
    n_setup = sum(1 for op in ops if op.setup_time > 0)
    assert len(bars) == len(ops) + n_setup + 1, (
        "每道工序一条加工段 + 有设置的一条设置段 + 一条空闲机器占位"
    )
    legend_names = {t.name for t in bars if t.showlegend}
    assert legend_names >= {"A", "B", "C"}, "产品族图例齐全"


def test_pareto_figure_with_representative(vtoy1_problem, vtoy_run):
    it = vtoy_run.period(1).iterations[0]
    assert it.front, "前沿已随 IterationRecord 保存"
    fig = pareto_figure(vtoy1_problem, it.front, it.representative.solution, "τ=1 k=0")
    scatters = [t for t in fig.data if t.type == "scatter"]
    assert len(scatters) == 6, "3 个投影 ×（解集 + 代表解）"


def test_overview_figures(vtoy1_problem, vtoy_run):
    fig_q = plan_overview_figure(vtoy1_problem, vtoy_run)
    assert len(fig_q.data) == len(vtoy1_problem.products)
    fig_c = cmax_overview_figure(vtoy1_problem, vtoy_run)
    assert {t.name for t in fig_c.data} == {"加班 OT", "C_max"}
    fig_s = state_overview_figure(vtoy1_problem, vtoy_run)
    assert {t.name for t in fig_s.data} == {"库存", "欠交"}


def test_iteration_table(vtoy1_problem, vtoy_run):
    rows = iteration_table_rows(vtoy1_problem, vtoy_run.period(3))
    assert rows[0]["割判据"].startswith("structural→割{B,C}")
    assert rows[-1]["冻结"] == "✓"


def test_palette_capacity_guard(vtoy1_problem):
    import dataclasses

    too_many = dataclasses.replace(
        vtoy1_problem, products=[f"P{i}" for i in range(9)]
    )
    with pytest.raises(ValueError, match="色盘容量"):
        family_colors(too_many)
