"""三步割判据分支测试（stub 调度器，不依赖真实求解）+ 割池生命周期。"""
import pytest

from src.feedback.cuts import InfeasibleCutPool, evaluate_cut_criterion
from src.scheduling.base import ScheduleSolution


def _sol(problem, cmax, lc=1000.0, energy=4000.0):
    ot = max(0.0, cmax - problem.t_avail)
    rho = 1 - min(1.0, ot / problem.ot_max)
    return ScheduleSolution(
        cmax=cmax, lc=lc, energy=energy, theta_stage={}, ot=ot, rho=rho
    )


class StubScheduler:
    """按工件集合的产品构成返回预设 C_max 的假调度器。

    cmax_by_families: {frozenset(产品族): cmax}
    """

    def __init__(self, problem, cmax_by_families):
        self.problem = problem
        self.cmax_by_families = cmax_by_families
        self.calls = []

    def solve(self, problem, jobs, tau, seed=None):
        families = frozenset(j.product for j in jobs)
        self.calls.append((families, seed))
        return [_sol(self.problem, self.cmax_by_families[families])]


def test_acceptable_short_circuits(vtoy1_problem):
    """① 存在可接受重启 → 不生成割（reason=acceptable）。"""
    stub = StubScheduler(vtoy1_problem, {frozenset({"B", "C"}): 450.0})
    d = evaluate_cut_criterion(
        vtoy1_problem, 3, {"B": 14, "C": 6}, stub, seeds=[1, 2, 3]
    )
    assert not d.generated and d.reason == "acceptable"
    assert len(stub.calls) == 3, "N_restart=3 次重启"


def test_load_type_excluded(vtoy1_problem):
    """② 阶段负荷超过当前 Cap^eff → 负荷型，不生成割。"""
    stub = StubScheduler(vtoy1_problem, {frozenset({"B", "C"}): 700.0})
    d = evaluate_cut_criterion(
        vtoy1_problem, 3, {"B": 14, "C": 6}, stub,
        cap_eff_row={2: 400.0},  # 负荷 430 > 400 → 负荷型
        seeds=[1],
    )
    assert not d.generated and d.reason == "load_type"


def test_overtime_type_guard(vtoy1_problem):
    """②′ §2.2 守卫：OT ≤ OT^max（ρ>0）→ 加班型，不进入移除测试。"""
    stub = StubScheduler(vtoy1_problem, {frozenset({"A", "B", "C"}): 540.0})
    d = evaluate_cut_criterion(
        vtoy1_problem, 1, {"A": 12, "B": 8, "C": 5}, stub, seeds=[1, 2, 3]
    )
    assert not d.generated and d.reason == "overtime_type"
    assert d.diagnostics["best_ot"] == pytest.approx(60)
    assert len(stub.calls) == 3, "守卫生效则不做移除测试（无第 4 次调用）"


def test_structural_cut_generated(vtoy1_problem):
    """③ 单产品移除均可行 → S={B,C} → 割生成。"""
    stub = StubScheduler(
        vtoy1_problem,
        {
            frozenset({"B", "C"}): 680.0,  # 全集：OT=200>120 → ρ=0
            frozenset({"C"}): 200.0,       # 移B → 可接受
            frozenset({"B"}): 300.0,       # 移C → 可接受
        },
    )
    d = evaluate_cut_criterion(
        vtoy1_problem, 3, {"B": 14, "C": 6}, stub, seeds=[1, 2, 3]
    )
    assert d.generated and d.combo == frozenset({"B", "C"})
    assert d.reason == "structural"
    assert d.diagnostics["removal_tests"]["B"]["acceptable"]
    assert d.diagnostics["removal_tests"]["C"]["acceptable"]


def test_no_single_removal_no_cut(vtoy1_problem):
    """③ 无任何单产品移除可恢复 → S=∅ → 不生成割（保持稀疏性）。"""
    stub = StubScheduler(
        vtoy1_problem,
        {
            frozenset({"B", "C"}): 680.0,
            frozenset({"C"}): 640.0,  # 移B 仍不可接受
            frozenset({"B"}): 650.0,  # 移C 仍不可接受
        },
    )
    d = evaluate_cut_criterion(
        vtoy1_problem, 3, {"B": 14, "C": 6}, stub, seeds=[1]
    )
    assert not d.generated and d.reason == "no_single_removal"


class TestCutPool:
    def test_accumulate_union_and_clear(self):
        """式(5-10) 并集累积（去重）；冻结后清空 → ℋ_{τ+1}^{(0)}=∅（A12 口径）。"""
        pool = InfeasibleCutPool()
        pool.accumulate({frozenset({"B", "C"})})
        pool.accumulate({frozenset({"B", "C"})})  # 重复并入不增长
        assert len(pool) == 1
        pool.accumulate({frozenset({"A", "C"})})
        assert len(pool) == 2
        cuts = pool.cuts_for(tau=3)
        assert all(t == 3 for _, t in cuts), "割仅作用于当前周期 τ"
        pool.clear_after_freeze()
        assert len(pool) == 0 and pool.cuts_for(4) == ()
