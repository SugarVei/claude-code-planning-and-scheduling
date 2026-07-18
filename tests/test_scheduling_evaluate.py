"""论文口径评价器测试：手工构造调度，逐项锁定 Θ/LC/时间链/资源校验。"""
import pytest

from src.data.lot_sizing import build_jobs
from src.scheduling.evaluate import evaluate_schedule


def _buffer_schedule(problem):
    """金标 '5_预期行为轨迹' τ=1 缓冲序示例：M21 队列 [B,B,A,A,A,C]。

    全档位 s=1；配工 M11=α1、M21=α2、M31=α1（τ=1 可用 α1×2、α2×2 ✓）。
    """
    jobs = build_jobs(problem, {"A": 12, "B": 8, "C": 5})
    order = ["B1", "B2", "A1", "A2", "A3", "C1"]
    assignment = {}
    for j in jobs:
        assignment[(j.job_id, 1)] = ("M11", 1, 1)
        assignment[(j.job_id, 2)] = ("M21", 1, 2)
        assignment[(j.job_id, 3)] = ("M31", 1, 1)
    sequence = {(1, "M11"): order, (2, "M21"): order, (3, "M31"): order}
    return jobs, assignment, sequence


def test_buffer_sequence_theta_65(vtoy1_problem):
    """缓冲序 M21 设置合计 Θ_2 = 10+0+25+0+0+30 = 65（A05 条件分支的锚点）。"""
    jobs, assignment, sequence = _buffer_schedule(vtoy1_problem)
    sol = evaluate_schedule(vtoy1_problem, jobs, 1, assignment, sequence)
    assert sol.theta_stage[2] == pytest.approx(65)
    # Θ_j 与工序表逐段重算一致（式5-4 的甘特图口径）
    for j in vtoy1_problem.stages:
        recomputed = sum(op.setup_time for op in sol.operations if op.stage == j)
        assert sol.theta_stage[j] == pytest.approx(recomputed)


def test_labor_cost_and_ops(vtoy1_problem):
    """LC = 各被用机器配工工资和（式4-8）：200+280+200 = 680；工序表完整。"""
    jobs, assignment, sequence = _buffer_schedule(vtoy1_problem)
    sol = evaluate_schedule(vtoy1_problem, jobs, 1, assignment, sequence)
    assert sol.lc == pytest.approx(680)
    assert len(sol.operations) == len(jobs) * len(vtoy1_problem.stages)
    # OT/ρ 与 C_max 自洽（A04/A05 公式）
    assert sol.ot == pytest.approx(max(0.0, sol.cmax - 480))
    assert sol.rho == pytest.approx(1 - min(1.0, sol.ot / 120))


def test_timeline_setup_overlaps_transport(vtoy1_problem):
    """式(4-1)+(4-22)：加工开始 = max(机器就绪+设置, 工件到达)——
    M21 首工件 B1 的加工开始 = max(0+10, ST1完工+运输)。"""
    jobs, assignment, sequence = _buffer_schedule(vtoy1_problem)
    sol = evaluate_schedule(vtoy1_problem, jobs, 1, assignment, sequence)
    ops = {(op.job_id, op.stage): op for op in sol.operations}
    b1_s1 = ops[("B1", 1)]
    b1_s2 = ops[("B1", 2)]
    # 阶段1 首工件 B1？M11 队列首位是 B1：初始设置 10 → 加工 4×12=48
    assert b1_s1.setup_end == pytest.approx(max(10, 0))
    arrival = b1_s1.end + vtoy1_problem.transport_time
    assert b1_s2.setup_end == pytest.approx(max(10.0, arrival))


def test_skill_gear_violation_rejected(vtoy1_problem):
    """向下兼容（式4-6）：档位 > 技能 → 拒绝。"""
    jobs, assignment, sequence = _buffer_schedule(vtoy1_problem)
    bad = dict(assignment)
    bad[("C1", 2)] = ("M21", 3, 2)  # 档位3 > 技能2
    with pytest.raises(ValueError, match="向下兼容"):
        evaluate_schedule(vtoy1_problem, jobs, 1, bad, sequence)


def test_worker_availability_violation_rejected(vtoy1_problem):
    """工人可用性（式4-7）：τ=2 无 α=3 工人 → 任何 α3 配机被拒绝。"""
    jobs, assignment, sequence = _buffer_schedule(vtoy1_problem)
    bad = {
        key: (m, g, 3 if m == "M21" else s) if key[1] == 2 else (m, g, s)
        for key, (m, g, s) in assignment.items()
    }
    with pytest.raises(ValueError, match="工人可用性"):
        evaluate_schedule(vtoy1_problem, jobs, 2, bad, sequence)
