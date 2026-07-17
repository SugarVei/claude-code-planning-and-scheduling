"""保护处理测试：式(3-9) 冲抵口径（含 P3 错误口径对照复现）+ V2 移出次序。"""
import pytest

from src.feedback.protection import kmax_removal_order, update_state


def _naive_update_p3_bug(inv_prev, back_prev, q, demand, products):
    """P3 错误口径复现：库存与欠交各自独立累加、不互相冲抵。

    这是被审计判为错误的行为（欠交累计前未用正库存冲抵），
    仅用于对照测试，证明其违反式(3-9) 的 min{Inv,Back}=0 性质。
    """
    inv, back = {}, {}
    for p in products:
        inv[p] = inv_prev.get(p, 0.0) + max(0, q.get(p, 0) - demand.get(p, 0))
        back[p] = back_prev.get(p, 0.0) + max(0, demand.get(p, 0) - q.get(p, 0))
    return inv, back


def test_positive_inventory_offsets_backlog(vtoy1_problem):
    """式(3-9)：期初正库存 5、本期缺产 3 → Inv=2, Back=0（先冲抵）。"""
    inv, back = update_state(
        vtoy1_problem,
        inv_prev={"A": 5.0, "B": 0.0, "C": 0.0},
        back_prev={"A": 0.0, "B": 0.0, "C": 0.0},
        q_frozen={"A": 0},
        demand_tau={"A": 3},
    )
    assert inv["A"] == 2 and back["A"] == 0


def test_p3_bug_reproduced_then_fixed(vtoy1_problem):
    """先复现错误行为：独立累加口径产生 Inv>0 且 Back>0（双重计罚）；
    修复后的 update_state 满足 min{Inv,Back}=0 且数值正确。"""
    inv_prev = {"A": 5.0, "B": 0.0, "C": 0.0}
    back_prev = {"A": 0.0, "B": 0.0, "C": 0.0}
    q = {"A": 0}
    d = {"A": 3}
    # 错误口径：A 同时挂着库存 5 与欠交 3
    bad_inv, bad_back = _naive_update_p3_bug(
        inv_prev, back_prev, q, d, vtoy1_problem.products
    )
    assert bad_inv["A"] == 5 and bad_back["A"] == 3, "P3 病理行为复现"
    assert min(bad_inv["A"], bad_back["A"]) > 0, "违反 min{Inv,Back}=0"
    # 正确口径
    inv, back = update_state(vtoy1_problem, inv_prev, back_prev, q, d)
    for p in vtoy1_problem.products:
        assert min(inv[p], back[p]) == 0, "式(3-9) 最优解性质"
    assert inv["A"] == 2 and back["A"] == 0


def test_backlog_cleared_by_later_production(vtoy1_problem):
    """欠交跨周期清偿：Back=3 + 本期多产 3 → 归零（金标 τ=1→τ=2 的 B 链）。"""
    inv, back = update_state(
        vtoy1_problem,
        inv_prev={"B": 0.0},
        back_prev={"B": 3.0},
        q_frozen={"B": 9},
        demand_tau={"B": 6},
    )
    assert inv["B"] == 0 and back["B"] == 0


def test_kmax_removal_order_v2(vtoy1_problem):
    """V2 口径：b_p 升序（B=8 最先）、同产品内 β(i) 降序（14→4,4,4,2）。"""
    order = kmax_removal_order(vtoy1_problem, {"A": 0, "B": 14, "C": 6})
    assert order == [("B", 4), ("B", 4), ("B", 4), ("B", 2), ("C", 5), ("C", 1)]


def test_kmax_removal_order_all_products(vtoy1_problem):
    """三族同期时：B(b=8) → A(b=10) → C(b=12)。"""
    order = kmax_removal_order(vtoy1_problem, {"A": 12, "B": 8, "C": 5})
    products_in_order = [p for p, _ in order]
    assert products_in_order == ["B", "B", "A", "A", "A", "C"]
    assert order[0] == ("B", 4) and order[-1] == ("C", 5)
