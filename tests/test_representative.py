"""代表解选择测试（式5-11~5-17）：合成集验证选择规则，真实集验证兜底分支。"""
import pytest

from src.scheduling.base import ScheduleSolution
from src.feedback.representative import select_representative


def _sol(cmax, lc, energy, rho=None, ot=None):
    """构造只带目标量的解（代表解选择不需要工序表）。"""
    ot = max(0.0, cmax - 480) if ot is None else ot
    rho = 1 - min(1.0, ot / 120) if rho is None else rho
    return ScheduleSolution(
        cmax=cmax, lc=lc, energy=energy, theta_stage={}, ot=ot, rho=rho
    )


def test_acceptable_min_score_selected(vtoy1_problem):
    """Ω^acc 非空 → 取 s(π) 最小（式5-16）；并列按 C̃max 字典序。权重 (0.5,0.3,0.2)。"""
    sols = [
        _sol(430, 1000, 4000),  # C̃=0.5, L̃C≈0.4706, Ẽ=0.5 → s≈0.4912 ← 最小
        _sol(400, 1360, 5000),  # C̃=0, L̃C=1, Ẽ=1 → s=0.5
        _sol(460, 680, 3000),   # C̃=1, L̃C=0, Ẽ=0 → s=0.5
    ]
    rep = select_representative(vtoy1_problem, sols)
    assert not rep.is_fallback
    assert rep.index == 0, "s(π) 最小者当选"
    # 评分严格并列时按 C̃max 字典序优先（式5-16 并列规则）
    tie = [_sol(400, 1360, 5000), _sol(460, 680, 3000)]  # s 均为 0.5
    rep_tie = select_representative(vtoy1_problem, tie)
    assert rep_tie.index == 0, "并列取 C̃max 更小者"


def test_unacceptable_filtered_out(vtoy1_problem):
    """可接受性过滤（式5-15）：C_max>480 或 ρ<ρ_min 的解不入 Ω^acc。"""
    sols = [
        _sol(520, 400, 1000),   # C_max 超 T^avail → 排除（即便其余目标最优）
        _sol(470, 1360, 6000),  # 可接受
    ]
    rep = select_representative(vtoy1_problem, sols)
    assert rep.index == 1 and not rep.is_fallback


def test_fallback_lex_order(vtoy1_problem):
    """Ω^acc=∅ → 式(5-17)：先比 ρ 违约量，再比工期违约量，再比 s(π)。"""
    sols = [
        _sol(530, 680, 3000),   # ρ=1-50/120≈0.583 违约 0.217
        _sol(510, 1360, 6000),  # ρ=0.75 违约 0.05 ← 最小
        _sol(510, 680, 3000),   # 同 ρ 违约 0.05、同工期违约 30、s 更小 ← 胜出
    ]
    rep = select_representative(vtoy1_problem, sols)
    assert rep.is_fallback
    assert rep.index == 2


def test_empty_set_raises(vtoy1_problem):
    with pytest.raises(ValueError, match="解集为空"):
        select_representative(vtoy1_problem, [])
