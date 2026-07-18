"""实验框架测试：方案 A~D、指标、消融/敏感性、导出（V-toy 快速通道）。"""
import csv

import pytest

from src.experiments.report import export_all
from src.experiments.runner import (
    compute_metrics,
    run_ablation,
    run_scheme_comparison,
    run_weight_sensitivity,
)
from src.scheduling.exact_cpsat import CpSatScheduler

pytestmark = pytest.mark.slow_solver


@pytest.fixture(scope="module")
def cpsat():
    return CpSatScheduler(time_limit_s=120)


@pytest.fixture(scope="module")
def comparison(vtoy1_problem, cpsat):
    """V-toy 上的四方案对比（金标机制已验证，此处验证实验框架）。"""
    return run_scheme_comparison(vtoy1_problem, cpsat, base_seed=0)


class TestSchemeComparison:
    def test_all_schemes_complete(self, vtoy1_problem, comparison):
        results, metrics = comparison
        assert set(results) == {"A", "B", "C", "D"}
        for r in results.values():
            assert len(r.periods) == len(vtoy1_problem.periods)

    def test_scheme_a_misses_dynamic_orders(self, comparison):
        """方案 A 静态计划看不到动态到达订单（o7~o9）→ 期末欠交>0。"""
        _, metrics = comparison
        assert metrics["A"].terminal_backlog > 0
        assert metrics["A"].on_time_rate < 1.0

    def test_scheme_b_freezes_infeasible(self, comparison):
        """方案 B 无反馈：τ=1/τ=3 的不可接受方案被直接冻结 → 可行率<1、k*=0。"""
        _, metrics = comparison
        assert metrics["B"].feasible_rate < 1.0
        assert metrics["B"].avg_iterations == 0
        assert metrics["B"].total_overtime > 0

    def test_scheme_c_full_feedback(self, comparison):
        """方案 C 三通道闭环：全部周期可接受、期末清算归零。"""
        _, metrics = comparison
        assert metrics["C"].feasible_rate == 1.0
        assert metrics["C"].terminal_backlog == 0
        assert metrics["C"].avg_iterations > 0
        assert metrics["C"].total_overtime == 0

    def test_tradeoff_story(self, comparison):
        """机制故事：B 按期硬排但排不出可行调度；C 以少量欠交换全程可行。"""
        _, metrics = comparison
        assert metrics["C"].feasible_rate > metrics["B"].feasible_rate
        assert metrics["B"].total_overtime > metrics["C"].total_overtime


def test_ablation_one_click(vtoy1_problem, cpsat):
    """消融实验通过 FeedbackConfig 一键配置（Stage 6 验收）。"""
    out = run_ablation(vtoy1_problem, cpsat, base_seed=0)
    assert set(out) == {"完整三通道", "去成本修正", "去有效产能", "去不可行割"}
    assert out["完整三通道"].feasible_rate == 1.0


def test_weight_sensitivity(vtoy1_problem, cpsat):
    out = run_weight_sensitivity(
        vtoy1_problem, cpsat, [(0.50, 0.30, 0.20), (0.20, 0.30, 0.50)], base_seed=0
    )
    assert len(out) == 2
    for m in out.values():
        assert m.total_cost >= 0


def test_export_files(vtoy1_problem, comparison, tmp_path):
    """导出：表5-1/5-4 CSV + 汇总 xlsx 可读（表5-2/5-3 结构同 5-1）。"""
    results, metrics = comparison
    xlsx = export_all(vtoy1_problem, tmp_path, results, metrics)
    assert xlsx.exists()
    csv_51 = tmp_path / "表5-1_四方案对比.csv"
    with open(csv_51, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[0][0] == "方案" and len(rows) == 5
    csv_54 = tmp_path / "表5-4_逐周期明细.csv"
    with open(csv_54, encoding="utf-8-sig") as f:
        detail = list(csv.reader(f))
    assert len(detail) == 1 + 4 * len(vtoy1_problem.periods)
