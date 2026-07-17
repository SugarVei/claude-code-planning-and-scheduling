"""vendor NSGA-II-VNS-MOSA 适配器测试：问题翻译逐项核对 + 输出合法性自检。"""
import pytest

from src.data.lot_sizing import build_jobs
from src.scheduling.base import dominates
from src.scheduling.meta_vendor import VendorNsgaScheduler, build_vendor_problem


@pytest.fixture(scope="module")
def tau1_jobs(vtoy1_problem):
    return build_jobs(vtoy1_problem, {"A": 12, "B": 8, "C": 5})


@pytest.fixture(scope="module")
def tau1_front(vtoy1_problem, tau1_jobs):
    """τ=1 k=0 的 vendor 求解结果（module 级缓存，seed 固定）。"""
    return VendorNsgaScheduler().solve(vtoy1_problem, tau1_jobs, tau=1, seed=42)


class TestBuildVendorProblem:
    def test_dimensions_and_times(self, vtoy1_problem, tau1_jobs):
        vp = build_vendor_problem(vtoy1_problem, tau1_jobs, tau=1)
        assert vp.n_jobs == 6 and vp.n_stages == 3
        assert vp.machines_per_stage == [2, 1, 2]
        # PT = β×pt^unit×θ_s：C1(β=5) 阶段2(DIP, idx1) 档位1(idx0) = 5×25×1.0
        assert vp.processing_time[5, 1, 0, 0] == pytest.approx(125)
        assert vp.processing_time[5, 1, 0, 2] == pytest.approx(100)  # 档位3 ×0.8
        # SDST：B1(idx3)→C1(idx5) 深度换模 280；同族 A1→A2 = 0
        assert vp.setup_time[1, 0, 3, 5] == pytest.approx(280)
        assert vp.setup_time[0, 0, 0, 1] == pytest.approx(0)
        assert vp.shift_duration == 480

    def test_workers_by_tau(self, vtoy1_problem, tau1_jobs):
        vp1 = build_vendor_problem(vtoy1_problem, tau1_jobs, tau=1)
        vp2 = build_vendor_problem(vtoy1_problem, tau1_jobs, tau=2)
        assert list(vp1.workers_available) == [2, 2, 1]
        assert list(vp2.workers_available) == [2, 2, 0], "τ=2 α=3 缺勤机关"
        assert list(vp1.skill_wages) == [200, 280, 400]
        assert list(vp1.skill_compatibility) == [0, 1, 2], "向下兼容（0 起索引）"


class TestVendorFront:
    def test_nonempty_and_nondominated(self, tau1_front):
        assert len(tau1_front) >= 1
        for a in tau1_front:
            assert not any(
                dominates(b.objectives, a.objectives) for b in tau1_front
            ), "重评后解集须保持非支配（Stage 3 验收：非支配性自检）"

    def test_all_infeasible_at_tau1_k0(self, vtoy1_problem, tau1_front):
        """CP-SAT 已证明 C_max* = 509 > 504 → 元启发式所有解必然 Feas=0。"""
        for s in tau1_front:
            assert s.cmax >= 509 - 1e-6
            assert s.rho < vtoy1_problem.rho_min

    def test_stats_consistent_with_operations(self, vtoy1_problem, tau1_front):
        """Θ_j 与工序表逐段一致；C_max 与末阶段完工一致；LC 与配工一致。"""
        for s in tau1_front:
            for j in vtoy1_problem.stages:
                recomputed = sum(
                    op.setup_time for op in s.operations if op.stage == j
                )
                assert s.theta_stage[j] == pytest.approx(recomputed)
            last = max(op.end for op in s.operations)
            assert s.cmax == pytest.approx(last)
            used = {(op.stage, op.machine): op.skill for op in s.operations}
            assert s.lc == pytest.approx(
                sum(vtoy1_problem.worker_wage[a] for a in used.values())
            )
