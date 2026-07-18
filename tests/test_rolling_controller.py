"""滚动控制器测试：金标闭环轨迹（CP-SAT 确定性）、通道开关日志、K_max 保护。"""
import logging

import pytest

from src.feedback.channels import FeedbackConfig
from src.rolling.controller import run_rolling
from src.scheduling.exact_cpsat import CpSatScheduler

pytestmark = pytest.mark.slow_solver


@pytest.fixture(scope="module")
def cpsat():
    return CpSatScheduler(time_limit_s=120)


@pytest.fixture(scope="module")
def full_loop(vtoy1_problem, cpsat):
    """全开配置闭环（与回归 A06~A09 同源）。"""
    return run_rolling(vtoy1_problem, cpsat, FeedbackConfig(), base_seed=0)


class TestGoldTrajectory:
    """金标 '5_预期行为轨迹' 的闭环复现（分支行为为硬性预期）。"""

    def test_tau1_feedback_then_freeze(self, vtoy1_problem, full_loop):
        pr = full_loop.period(1)
        k0 = pr.iterations[0]
        assert k0.feas == 0 and k0.q_tau == {"A": 12, "B": 8, "C": 5}
        assert k0.cut_decision is not None and k0.cut_decision.reason == "overtime_type", (
            "τ=1 加班型 → 不生成割（§2.2 守卫）"
        )
        # 反馈后移出 B（金标"移出B约3件或C约2件，以求解器为准"——本口径 Θ₂=55 → 移2B）
        assert pr.frozen_q == {"A": 12, "B": 6, "C": 5}
        assert pr.schedule.cmax <= vtoy1_problem.t_avail
        assert pr.back_after["B"] == pytest.approx(2)

    def test_tau2_k0_freeze_with_eta(self, full_loop):
        pr = full_loop.period(2)
        assert pr.k_star == 0, "τ=2 k=0 直接冻结分支"
        k0 = pr.iterations[0]
        assert k0.channels.eta == pytest.approx(0.8), "α=3 缺勤 → η=4/5"
        assert pr.frozen_q["B"] == 8, "需求6 + 清偿 Back_B=2"
        assert pr.back_after == {"A": 0, "B": 0, "C": 0}, "Back 跨周期清偿"

    def test_tau3_cut_then_keep_b(self, full_loop):
        pr = full_loop.period(3)
        k0 = pr.iterations[0]
        assert k0.feas == 0
        assert k0.cut_decision.generated and k0.cut_decision.combo == frozenset({"B", "C"})
        assert k0.new_cuts == frozenset({frozenset({"B", "C"})})
        assert pr.frozen_q == {"A": 0, "B": 14, "C": 0}, "割后保B移C"
        assert pr.back_after["C"] == pytest.approx(6)
        # 割后单族调度：Θ₂ 仅初始设置
        assert pr.schedule.theta_stage[2] == pytest.approx(10)

    def test_tau4_terminal_clearing(self, full_loop):
        pr = full_loop.period(4)
        assert pr.k_star == 0
        assert pr.frozen_q == {"A": 8, "B": 0, "C": 6}
        # A13 端到端：T_max 末全部 Back=0、库存≥0、O^unfin=∅
        assert full_loop.terminal_back == {"A": 0, "B": 0, "C": 0}
        for v in full_loop.terminal_inv.values():
            assert v >= 0
        assert all(not p.unfin_orders for p in full_loop.periods), "主线 V1 不触发保护"


class TestChannelSwitches:
    """任一单通道关闭：系统可运行不崩溃，日志明确记录禁用（Stage 5 验收）。"""

    def test_channel1_off(self, vtoy1_problem, cpsat, caplog):
        with caplog.at_level(logging.INFO, logger="rolling"):
            res = run_rolling(
                vtoy1_problem, cpsat,
                FeedbackConfig(cost_correction=False), base_seed=0,
            )
        assert len(res.periods) == 4
        assert "通道1(成本修正Δc)已禁用" in caplog.text
        # Δc 从未进入计划层
        for pr in res.periods:
            for it in pr.iterations:
                assert it.plan_inputs.delta_c == {}

    def test_channel2_off(self, vtoy1_problem, cpsat, caplog):
        with caplog.at_level(logging.INFO, logger="rolling"):
            res = run_rolling(
                vtoy1_problem, cpsat,
                FeedbackConfig(effective_capacity=False), base_seed=0,
            )
        assert len(res.periods) == 4
        assert "通道2(有效产能Cap^eff)已禁用" in caplog.text
        for pr in res.periods:
            for it in pr.iterations:
                assert it.plan_inputs.cap_eff == {}

    def test_channel3_off(self, vtoy1_problem, cpsat, caplog):
        with caplog.at_level(logging.INFO, logger="rolling"):
            res = run_rolling(
                vtoy1_problem, cpsat,
                FeedbackConfig(infeasible_cuts=False), base_seed=0,
            )
        assert len(res.periods) == 4
        assert "通道3(不可行组合割)已禁用" in caplog.text
        for pr in res.periods:
            for it in pr.iterations:
                assert it.plan_inputs.cuts == ()
        # 期末仍须清算归零（通道1/2 兜住可行性）
        assert res.terminal_back == {"A": 0, "B": 0, "C": 0}


class TestKmaxProtection:
    """算法5-1 第23~32行：K_max 仍不可接受 → 按 b_p 升序/β 降序移出并重排。"""

    def test_all_channels_off_triggers_protection(self, vtoy1_problem, cpsat, caplog):
        with caplog.at_level(logging.WARNING, logger="rolling"):
            res = run_rolling(
                vtoy1_problem, cpsat,
                FeedbackConfig(False, False, False), base_seed=0,
            )
        assert "触发保护处理" in caplog.text
        pr1 = res.period(1)
        assert pr1.protection_events, "τ=1 无反馈修正 → K_max 后必然走保护"
        assert pr1.protection_events[0][0] == "B", "b_B=8 最小 → 首先移出 B"
        sizes = [s for p, s in pr1.protection_events if p == "B"]
        assert sizes == sorted(sizes, reverse=True), "同产品内按 β(i) 降序"
        assert pr1.unfin_orders, "移出量登记未完成订单"
        assert pr1.schedule.rho >= vtoy1_problem.rho_min, "移出后方案可接受才冻结"
        # 保护处理不破坏期末清算（欠交经式3-9 进入后续周期并最终清偿）
        assert res.terminal_back == {"A": 0, "B": 0, "C": 0}
