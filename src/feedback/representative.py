"""Pareto 代表解选择（论文 §5.3.1：式5-11~5-17）。

流程：可接受性过滤（式5-15）→ 归一化加权排序（式5-11~5-14、式5-16 及其
字典序并列规则）→ 空集兜底（式5-17 违约字典序）。

编号说明：金标工作簿把可接受度算式记为"式(5-15)"、兜底式记为"式(5-18)"，
与论文正文编号（5-15=可接受子集、5-17=兜底、5-18=默认权重）存在错位；
本实现按论文正文结构组织、以金标算式为数值口径（ρ 公式见
src/scheduling/base.py::acceptability）。

兜底代表解仅用于反馈折算，不得冻结为执行方案（"仅用于反馈折算与保守
修补依据"），由 is_fallback 标志向滚动控制器传达（A14 口径）。
"""
from __future__ import annotations

from dataclasses import dataclass

from src.data.problem_data import ProblemData
from src.scheduling.base import ScheduleSolution

_EPS = 1e-9


@dataclass(frozen=True)
class RepresentativeResult:
    """代表解选择结果。"""

    solution: ScheduleSolution   # π_τ^{*,(k)}
    index: int                   # 在输入解集中的下标
    is_fallback: bool            # True = 式(5-17) 兜底（Ω^acc=∅），仅供反馈折算
    score: float                 # s(π)（式5-14；兜底解同样报告其加权评分）


def _normalize(values: list[float]) -> list[float]:
    """最小—最大归一化（式5-11~5-13）；ε 仅在极差为零时防零分母。"""
    lo, hi = min(values), max(values)
    span = hi - lo if hi > lo else _EPS
    return [(x - lo) / span for x in values]


def select_representative(
    problem: ProblemData, solutions: list[ScheduleSolution]
) -> RepresentativeResult:
    """从非支配解集 Ω^ND 中选取代表解 π*（式5-15~5-17）。"""
    if not solutions:
        raise ValueError("解集为空，无法选择代表解")

    c_norm = _normalize([s.cmax for s in solutions])
    l_norm = _normalize([s.lc for s in solutions])
    e_norm = _normalize([s.energy for s in solutions])
    w_c, w_l, w_e = problem.feedback_weights
    scores = [
        w_c * c + w_l * l + w_e * e for c, l, e in zip(c_norm, l_norm, e_norm)
    ]

    # 式(5-15)：Ω^acc = {π : ρ(π) ≥ ρ_min 且 C_max(π) ≤ T^avail}
    acceptable = [
        i
        for i, s in enumerate(solutions)
        if s.rho >= problem.rho_min and s.cmax <= problem.t_avail
    ]

    if acceptable:
        # 式(5-16)：评分最小；并列时按字典序 C̃ → L̃C → Ẽ
        best = min(
            acceptable, key=lambda i: (scores[i], c_norm[i], l_norm[i], e_norm[i])
        )
        return RepresentativeResult(
            solution=solutions[best], index=best, is_fallback=False, score=scores[best]
        )

    # 式(5-17)：违约字典序 lexmin (ρ 违约量, 工期违约量, s(π))
    best = min(
        range(len(solutions)),
        key=lambda i: (
            max(0.0, problem.rho_min - solutions[i].rho),
            max(0.0, solutions[i].cmax - problem.t_avail),
            scores[i],
        ),
    )
    return RepresentativeResult(
        solution=solutions[best], index=best, is_fallback=True, score=scores[best]
    )
