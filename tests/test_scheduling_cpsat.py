"""CP-SAT 精确调度器测试：金标判定量的精确验证（式4-1~4-34）。

各断言值为 CP-SAT 证明的最优目标值（与求解器版本无关），
分别锚定金标 '5_预期行为轨迹' 各分支的结构性前提。
"""
import pytest

from src.data.lot_sizing import build_jobs
from src.scheduling.exact_cpsat import CpSatScheduler

pytestmark = pytest.mark.slow_solver  # 单测约 0.1~2s，标记便于选择性运行


@pytest.fixture(scope="module")
def cpsat():
    return CpSatScheduler(time_limit_s=120)


def test_tau1_k0_no_acceptable_schedule_exists(vtoy1_problem, cpsat):
    """τ=1 k=0 (12,8,5)：精确最优 C_max*=509 > 504 ⇒ 任何调度器 ρ<0.8。

    这是 A03"3次重启均 Feas=0"的结构性证明：可接受需 C_max ≤ 480+0.2×120=504。
    """
    jobs = build_jobs(vtoy1_problem, {"A": 12, "B": 8, "C": 5})
    sol = cpsat.solve(vtoy1_problem, jobs, tau=1)[0]
    assert sol.cmax == pytest.approx(509.0)
    assert sol.cmax > 504, "可接受阈值 ρ_min=0.8 对应 C_max ≤ 504"
    assert sol.rho < vtoy1_problem.rho_min
    assert 0 < sol.ot <= vtoy1_problem.ot_max, "加班型不可行（上限内）→ 不生成割（§2.2 守卫）"


def test_tau1_k1_acceptable_after_feedback(vtoy1_problem, cpsat):
    """τ=1 k=1 (12,5,5)：C_max*=445 ∈ 金标带 [440,480] → Feas=1 可冻结。"""
    jobs = build_jobs(vtoy1_problem, {"A": 12, "B": 5, "C": 5})
    sol = cpsat.solve(vtoy1_problem, jobs, tau=1)[0]
    assert sol.cmax == pytest.approx(445.0)
    assert sol.cmax <= vtoy1_problem.t_avail
    assert sol.rho == pytest.approx(1.0)


def test_tau3_k0_structural_conflict(vtoy1_problem, cpsat):
    """τ=3 k=0 (B14,C6)：C_max*=678 ≥ 金标下界 634；OT=198 > OT^max → ρ=0。

    加班上限内不可消化 → 三步判据进入③单产品移除 → 割 {B,C}（A10 前提）。
    """
    jobs = build_jobs(vtoy1_problem, {"A": 0, "B": 14, "C": 6})
    sol = cpsat.solve(vtoy1_problem, jobs, tau=3)[0]
    assert sol.cmax == pytest.approx(678.0)
    assert sol.cmax >= 634, "金标下界：430×0.8 + (10+280) = 634"
    assert sol.ot > vtoy1_problem.ot_max
    assert sol.rho == 0.0
    assert sol.theta_stage[2] == pytest.approx(290), "10 初始 + 280 深度换模"


def test_tau3_k1_single_family_after_cut(vtoy1_problem, cpsat):
    """τ=3 k=1 割后 (B14)：单族 Θ_2=10（仅初始设置），C_max ≪ 480 → 冻结。"""
    jobs = build_jobs(vtoy1_problem, {"A": 0, "B": 14, "C": 0})
    sol = cpsat.solve(vtoy1_problem, jobs, tau=3)[0]
    assert sol.theta_stage[2] == pytest.approx(10)
    assert sol.cmax <= vtoy1_problem.t_avail
    assert sol.rho == pytest.approx(1.0)
