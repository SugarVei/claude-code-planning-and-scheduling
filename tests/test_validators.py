"""校验器测试：金标数据通过；各类结构性坏数据被拒并给出可读信息。"""
import copy
import dataclasses

import pytest

from src.data.problem_data import Order
from src.data.validators import validate_problem_data


def _tampered(problem, **replacements):
    """深拷贝后替换字段，避免污染 session 级金标 fixture。"""
    return dataclasses.replace(copy.deepcopy(problem), **replacements)


def test_gold_data_passes(vtoy1_problem):
    validate_problem_data(vtoy1_problem)  # 不抛异常即通过


def test_negative_cost_rejected(vtoy1_problem):
    bad = copy.deepcopy(vtoy1_problem)
    bad.cost_prod["A"] = -1
    with pytest.raises(ValueError, match="cost_prod"):
        validate_problem_data(bad)


def test_missing_proc_time_stage_rejected(vtoy1_problem):
    bad = copy.deepcopy(vtoy1_problem)
    del bad.proc_time["A"][2]
    with pytest.raises(ValueError, match="proc_time\\[A\\]"):
        validate_problem_data(bad)


def test_sdst_diagonal_nonzero_rejected(vtoy1_problem):
    bad = copy.deepcopy(vtoy1_problem)
    bad.sdst["A"]["A"] = 7
    with pytest.raises(ValueError, match="同族"):
        validate_problem_data(bad)


def test_weights_not_normalized_rejected(vtoy1_problem):
    bad = _tampered(vtoy1_problem, feedback_weights=(0.5, 0.5, 0.5))
    with pytest.raises(ValueError, match="权重"):
        validate_problem_data(bad)


def test_freeze_exceeds_window_rejected(vtoy1_problem):
    bad = _tampered(vtoy1_problem, horizon_freeze=5)
    with pytest.raises(ValueError, match="H_f"):
        validate_problem_data(bad)


def test_unknown_order_product_rejected(vtoy1_problem):
    bad = copy.deepcopy(vtoy1_problem)
    bad.orders.append(Order("ox", "Z", 1, 1, 1))
    with pytest.raises(ValueError, match="产品 Z 未定义"):
        validate_problem_data(bad)


def test_availability_missing_period_rejected(vtoy1_problem):
    bad = copy.deepcopy(vtoy1_problem)
    del bad.worker_available[3][2]
    with pytest.raises(ValueError, match="worker_available\\[α=3\\]"):
        validate_problem_data(bad)


def test_lot_size_zero_rejected(vtoy1_problem):
    bad = copy.deepcopy(vtoy1_problem)
    bad.lot_size_max["A"] = 0
    with pytest.raises(ValueError, match="U_p"):
        validate_problem_data(bad)
