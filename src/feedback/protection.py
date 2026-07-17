"""保护处理（式3-9 口径的状态更新 + 算法5-1 第23~32行的移出次序）。

式(3-9) 口径（P3 问题的正确实现）：周期冻结执行后，状态按净量更新——
    net_p = Inv_{p,τ-1} − Back_{p,τ-1} + q_{p,τ} − D_{p,τ}
    Inv_p,τ = max{0, net_p}，Back_p,τ = max{0, −net_p}
即**欠交累计前必须先用正库存冲抵**（最优解性质 min{Inv,Back}=0，
论文 §3.4 (1) 段）；禁止"库存、欠交各自独立累加"的错误口径
（那会出现 Inv>0 且 Back>0 并双重计罚，见 tests/test_protection.py
中的对照复现）。

K_max 保护处理（算法5-1 第23~32行，金标变体 V2 口径）：反馈迭代达
K_max 仍不可接受时，按 b_p 升序选产品、同产品内按 β(i) 降序逐子批
将生产任务移出当前周期（每移一子批需重排产，由滚动控制器执行；
本模块只给出确定性的移出次序与状态重算）。
"""
from __future__ import annotations

from src.data.lot_sizing import split_lots
from src.data.problem_data import ProblemData


def update_state(
    problem: ProblemData,
    inv_prev: dict[str, float],
    back_prev: dict[str, float],
    q_frozen: dict[str, int],
    demand_tau: dict[str, int],
) -> tuple[dict[str, float], dict[str, float]]:
    """式(3-9) 状态更新：净量口径，正库存先冲抵欠交。"""
    inv: dict[str, float] = {}
    back: dict[str, float] = {}
    for p in problem.products:
        net = (
            inv_prev.get(p, 0.0)
            - back_prev.get(p, 0.0)
            + q_frozen.get(p, 0)
            - demand_tau.get(p, 0)
        )
        inv[p] = max(0.0, net)
        back[p] = max(0.0, -net)
    return inv, back


def kmax_removal_order(
    problem: ProblemData, q_tau: dict[str, int]
) -> list[tuple[str, int]]:
    """K_max 保护处理的子批移出次序（算法5-1 第23~32行 / 金标 V2）。

    产品按 b_p 升序（延期惩罚最小者先移出），同产品内子批按 β(i) 降序。
    返回 [(产品, 子批批量), ...]；控制器每移出一个子批即重排产。
    """
    active = [p for p in problem.products if q_tau.get(p, 0) > 0]
    order: list[tuple[str, int]] = []
    for p in sorted(active, key=lambda prod: problem.cost_back[prod]):
        sizes = split_lots(q_tau[p], problem.lot_size_max[p])
        for size in sorted(sizes, reverse=True):
            order.append((p, size))
    return order
