"""三通道折算单元测试（式5-1~5-5 手算锁定，合成代表解）。"""
import pytest

from src.feedback.channels import compute_channels
from src.scheduling.base import Operation, ScheduleSolution


def _rep(problem, ops, cmax, lc, energy, theta_stage):
    return ScheduleSolution(
        cmax=cmax, lc=lc, energy=energy, theta_stage=theta_stage,
        ot=max(0.0, cmax - problem.t_avail),
        rho=1 - min(1.0, max(0.0, cmax - problem.t_avail) / problem.ot_max),
        operations=ops,
    )


def _op(product, stage, setup_end, end):
    return Operation(
        job_id=f"{product}x", product=product, stage=stage, machine="M21",
        gear=1, skill=1, start=setup_end, setup_end=setup_end, end=end,
        setup_time=0.0,
    )


def test_chi_load_share_and_pooled(vtoy1_problem):
    """式(5-1)/(5-2)：χ 按代表解加工时长占比；式(5-3)：k=0 基线下仅 κ_C/κ_S 项。"""
    p = vtoy1_problem
    ops = [_op("A", 2, 0, 300), _op("B", 2, 300, 400)]  # L_A=300, L_B=100
    rep = _rep(p, ops, cmax=540, lc=1000, energy=4000, theta_stage={2: 65.0})
    ch = compute_channels(
        p, 1, {"A": 12, "B": 8, "C": 0}, rep,
        prev_delta_c={x: 0.0 for x in p.products}, lc_base=1000, e_base=4000,
    )
    assert ch.chi["A"] == pytest.approx(0.75)
    assert ch.chi["B"] == pytest.approx(0.25)
    assert sum(ch.chi.values()) == pytest.approx(1.0), "Σχ_p = 1（A06）"
    # k=0 基线：lc_inc=e_inc=0 → pooled = κ_C·OT + κ_S·Θ = 2×60 + 0.5×65
    assert ch.lc_inc == 0 and ch.e_inc == 0
    assert ch.pooled_cost == pytest.approx(2 * 60 + 0.5 * 65)
    # Δĉ_A = χ_A/q_A × pooled；Δc^(1) = γ·Δĉ（prev=0）
    assert ch.delta_c_hat["A"] == pytest.approx(0.75 / 12 * 152.5)
    assert ch.delta_c_next["A"] == pytest.approx(0.5 * 0.75 / 12 * 152.5)


def test_increment_terms_active_when_above_base(vtoy1_problem):
    """κ_L/κ_E 作用于相对基线的增量 max{0, ·−base}。"""
    p = vtoy1_problem
    ops = [_op("A", 2, 0, 100)]
    rep = _rep(p, ops, cmax=480, lc=1360, energy=5000, theta_stage={2: 0.0})
    ch = compute_channels(
        p, 1, {"A": 12}, rep,
        prev_delta_c={x: 0.0 for x in p.products}, lc_base=1000, e_base=4400,
    )
    assert ch.lc_inc == pytest.approx(360)
    assert ch.e_inc == pytest.approx(600)
    assert ch.pooled_cost == pytest.approx(1 * 360 + 0.05 * 600)  # OT=0, Θ=0


def test_damping_and_cap(vtoy1_problem):
    """阻尼 (1−γ)prev+γΔĉ 与封顶 δ^max·c_p（A06）。"""
    p = vtoy1_problem
    ops = [_op("A", 2, 0, 100)]
    rep = _rep(p, ops, cmax=600, lc=0, energy=0, theta_stage={2: 500.0})
    ch = compute_channels(
        p, 1, {"A": 1}, rep,
        prev_delta_c={"A": 40.0, "B": 0.0, "C": 0.0}, lc_base=0, e_base=0,
    )
    # pooled = 2×120 + 0.5×500 = 490；Δĉ_A = 1/1×490 = 490 → 未封顶为 0.5×40+0.5×490=265
    assert ch.delta_c_hat["A"] == pytest.approx(490, rel=1e-6)
    assert ch.delta_c_next["A"] == pytest.approx(p.delta_max * p.cost_prod["A"]), "封顶 δ^max·c_A=50"


def test_eta_and_cap_eff(vtoy1_problem):
    """式(5-5)：η=min{1, 工人/机器}（τ=1→1.0，τ=2→0.8）；Cap^eff=max{0,Cap·η−Θ_j}。"""
    p = vtoy1_problem
    ops = [_op("A", 2, 0, 100)]
    rep = _rep(p, ops, 400, 680, 3000, {1: 20.0, 2: 65.0, 3: 10.0})
    ch1 = compute_channels(p, 1, {"A": 12}, rep, {x: 0.0 for x in p.products}, 680, 3000)
    ch2 = compute_channels(p, 2, {"A": 12}, rep, {x: 0.0 for x in p.products}, 680, 3000)
    assert ch1.eta == pytest.approx(1.0) and ch2.eta == pytest.approx(0.8)
    assert ch1.cap_eff_next[2] == pytest.approx(480 * 1.0 - 65)
    assert ch2.cap_eff_next[2] == pytest.approx(480 * 0.8 - 65)  # ≈319（金标 A07 口径）
    assert ch2.cap_eff_next[1] == pytest.approx(960 * 0.8 - 20)
