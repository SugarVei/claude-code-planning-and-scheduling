"""子批化映射单元测试（4.8.1 节口径；金标场景由回归 A01 覆盖）。"""
import pytest

from src.data.lot_sizing import build_jobs, processing_time, split_lots


def test_split_lots_rules():
    assert split_lots(12, 4) == [4, 4, 4]
    assert split_lots(8, 4) == [4, 4]
    assert split_lots(5, 5) == [5]
    assert split_lots(14, 4) == [4, 4, 4, 2], "末批余量（V2 变体 β 降序口径）"
    assert split_lots(3, 4) == [3]
    assert split_lots(0, 4) == []


def test_build_jobs_skips_zero_quantity(vtoy1_problem):
    # τ=3 割后重解口径：q=(0, 14, 0) → 仅 B 生成子批
    jobs = build_jobs(vtoy1_problem, {"A": 0, "B": 14, "C": 0})
    assert [(j.job_id, j.product, j.size) for j in jobs] == [
        ("B1", "B", 4), ("B2", "B", 4), ("B3", "B", 4), ("B4", "B", 2),
    ]


def test_processing_time_gear_coupling(vtoy1_problem):
    jobs = build_jobs(vtoy1_problem, {"B": 4})
    (b1,) = jobs
    # PT = β × pt^unit × θ_s；B 在阶段2基准 20 min/件
    assert processing_time(vtoy1_problem, b1, 2, 1) == pytest.approx(80.0)
    assert processing_time(vtoy1_problem, b1, 2, 2) == pytest.approx(72.0)
    assert processing_time(vtoy1_problem, b1, 2, 3) == pytest.approx(64.0)
