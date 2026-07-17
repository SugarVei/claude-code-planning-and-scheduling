"""V-toy-1 金标回归断言 A01~A14（随实现逐步点亮）。

断言原文取自金标工作簿 data/vtoy1.xlsx '6_断言清单'（每个测试的
docstring 即断言规格与论文对应位置）。本仓库从零构建（见
docs/SYSTEM_DESIGN.md Stage 1~5），断言随各阶段实现逐条点亮：

  已点亮：A01, A02（Stage 1：数据层 + 子批化映射 + SDST 查表）
         A03, A04, A05, A14（Stage 3：调度适配器 + 代表解选择）
         A10, A11, A12, A13（Stage 4：三步割判据+守卫、割池、式3-9 保护处理）
  Stage 5（滚动闭环）后可点亮：A06, A07, A08, A09

运行方式：pytest -m regression
"""
import pytest

from src.data.lot_sizing import build_jobs, processing_time, split_lots
from src.feedback.representative import select_representative
from src.scheduling.evaluate import evaluate_schedule
from src.scheduling.meta_vendor import VendorNsgaScheduler

pytestmark = pytest.mark.regression

NOT_IMPLEMENTED = "V-toy 闭环尚未实现（从零构建，Stage 1+ 逐步点亮）——本测试为断言规格占位"


@pytest.fixture(scope="module")
def tau1_k0_fronts(vtoy1_problem):
    """τ=1 k=0（q=12,8,5）三个不同随机种子的 vendor 求解结果（A03 判据①口径）。"""
    jobs = build_jobs(vtoy1_problem, {"A": 12, "B": 8, "C": 5})
    meta = VendorNsgaScheduler()
    return {
        seed: meta.solve(vtoy1_problem, jobs, tau=1, seed=seed) for seed in (1, 2, 3)
    }


def test_a01_lot_sizing(vtoy1_problem):
    """A01（4.8.1节）：子批化。

    n_A,1 = ⌈12/4⌉ = 3（批量 4,4,4）、n_B,1 = 2（4,4）、n_C,1 = 1（5）；
    工件加工时间 PT_i = β(i) × pt^unit × θ_s。
    """
    p = vtoy1_problem
    # τ=1, k=0 计划量 q = (A12, B8, C5)（金标 '5_预期行为轨迹'）
    jobs = build_jobs(p, {"A": 12, "B": 8, "C": 5})
    sizes = {}
    for job in jobs:
        sizes.setdefault(job.product, []).append(job.size)
    assert sizes["A"] == [4, 4, 4], "n_A,1 = ⌈12/4⌉ = 3，批量 4,4,4"
    assert sizes["B"] == [4, 4], "n_B,1 = 2，批量 4,4"
    assert sizes["C"] == [5], "n_C,1 = 1，批量 5"

    # PT_i = β(i) × pt^unit × θ_s（抽查各档位）
    a1 = next(j for j in jobs if j.job_id == "A1")
    c1 = next(j for j in jobs if j.job_id == "C1")
    assert processing_time(p, a1, 1, 1) == pytest.approx(4 * 10 * 1.00)
    assert processing_time(p, a1, 2, 2) == pytest.approx(4 * 15 * 0.90)
    assert processing_time(p, c1, 2, 1) == pytest.approx(5 * 25 * 1.00)
    assert processing_time(p, c1, 3, 3) == pytest.approx(5 * 14 * 0.80)

    # V2 变体口径：q_B=14 → 4 子批 (4,4,4,2)，β(i) 自然降序
    assert split_lots(14, p.lot_size_max["B"]) == [4, 4, 4, 2]


def test_a02_sdst_lookup(vtoy1_problem):
    """A02（4.8.1节/4.3节）：同族相邻 SDST=0；异族按矩阵查表；虚拟工件初始设置 S_0,i=10。"""
    p = vtoy1_problem
    # 虚拟工件初始设置 S_0,i = 10（对全部产品族）
    for prod in p.products:
        assert p.setup_time(None, prod) == 10
        assert p.setup_time(prod, prod) == 0, "同族相邻 SDST = 0"
    # 异族按矩阵查表
    assert p.setup_time("A", "B") == 20
    assert p.setup_time("A", "C") == 30
    assert p.setup_time("B", "A") == 25
    assert p.setup_time("C", "A") == 25
    assert p.setup_time("B", "C") == 280, "深度换模机关"
    assert p.setup_time("C", "B") == 280
    # 缓冲序 [B,B,A,A,A,C]（'5_预期行为轨迹' τ=1 示例）设置合计 Θ = 65
    seq = ["B", "B", "A", "A", "A", "C"]
    total = sum(
        p.setup_time(prev, nxt) for prev, nxt in zip([None] + seq[:-1], seq)
    )
    assert total == 65


def test_a03_restart_infeasible_tau1(vtoy1_problem, tau1_k0_fronts):
    """A03（5.2.1 判据①）：τ=1,k=0 时 3 次不同随机种子重启均 Feas=0。

    结构性根源：CP-SAT 已证明该工件集合精确最优 C_max*=509 > 504
    （tests/test_scheduling_cpsat.py），故任何重启都不可能 ρ ≥ 0.8。
    """
    for seed, front in tau1_k0_fronts.items():
        assert front, f"seed={seed} 解集非空"
        rep = select_representative(vtoy1_problem, front)
        assert rep.solution.rho < vtoy1_problem.rho_min, f"seed={seed} 应 Feas=0"
        assert rep.is_fallback, "Ω^acc=∅ → 兜底代表解"


def test_a04_rho_formula(vtoy1_problem, tau1_k0_fronts):
    """A04（式5-15，工作簿编号）：ρ 输出与手算一致：
    ρ = 1 − min{1, max{0, C_max−480}/120}。"""
    for front in tau1_k0_fronts.values():
        for s in front:
            expected = 1 - min(1.0, max(0.0, s.cmax - 480) / 120)
            assert s.rho == pytest.approx(expected)


def test_a05_ot_and_setup_sum(vtoy1_problem, tau1_k0_fronts):
    """A05（式5-4/4.8.2节）：OT = max{0, C_max−480}；
    Θ_2^sdst 等于代表解甘特图上 M21 各设置段之和（若为缓冲序则 =65）。
    """
    # OT 定义 + Θ_2 与甘特图逐段一致（对全部解）
    for front in tau1_k0_fronts.values():
        for s in front:
            assert s.ot == pytest.approx(max(0.0, s.cmax - 480))
            m21_setups = sum(
                op.setup_time
                for op in s.operations
                if op.stage == 2 and op.machine == "M21"
            )
            assert s.theta_stage[2] == pytest.approx(m21_setups)
    # 缓冲序锚点：M21 队列 [B,B,A,A,A,C] → Θ_2 = 10+25+30 = 65
    jobs = build_jobs(vtoy1_problem, {"A": 12, "B": 8, "C": 5})
    order = ["B1", "B2", "A1", "A2", "A3", "C1"]
    assignment = {}
    for j in jobs:
        assignment[(j.job_id, 1)] = ("M11", 1, 1)
        assignment[(j.job_id, 2)] = ("M21", 1, 2)
        assignment[(j.job_id, 3)] = ("M31", 1, 1)
    sol = evaluate_schedule(
        vtoy1_problem, jobs, 1, assignment,
        {(1, "M11"): order, (2, "M21"): order, (3, "M31"): order},
    )
    assert sol.theta_stage[2] == pytest.approx(65)


def test_a06_cost_correction_channel():
    """A06（式5-1~5-3 及增量/阻尼段）：Δc^(1) 量纲为元/件；Σ_p χ_p=1；
    k=0 基线下 κ_L、κ_E 增量项 =0；Δc^(1) = (1−γ)·0 + γ·Δĉ 且 ≤ δ^max·c_p。
    """
    pytest.skip(NOT_IMPLEMENTED)


def test_a07_effective_capacity_channel():
    """A07（式5-5 与 η 定义式）：Cap_2^eff,(1) = max{0, 480×η − Θ_2}；
    τ=1 时 η=1、τ=2 时 η=0.8。
    """
    pytest.skip(NOT_IMPLEMENTED)


def test_a08_plan_respects_feedback():
    """A08（3.2.1节下标约定/5.2.2节）：τ=1,k=1 计划层解满足阶段2负荷 ≤415；
    t>τ 各周期 Δc 与 Cap^eff 沿用上轮值。
    """
    pytest.skip(NOT_IMPLEMENTED)


def test_a09_freeze_four_conditions():
    """A09（3.5.4节/算法5-1第20行）：冻结判定同时核查四条件
    （Feas=1、C_max≤T^avail、Δℋ=∅、稳定性；k=0 时稳定性默认满足）。
    """
    pytest.skip(NOT_IMPLEMENTED)


@pytest.fixture(scope="module")
def cut_decisions(vtoy1_problem):
    """三步割判据在 τ=1 与 τ=3 的判定（CP-SAT 精确调度器为判据求解器）。"""
    from src.feedback.cuts import evaluate_cut_criterion
    from src.scheduling.exact_cpsat import CpSatScheduler

    cpsat = CpSatScheduler(time_limit_s=120)
    return {
        1: evaluate_cut_criterion(
            vtoy1_problem, 1, {"A": 12, "B": 8, "C": 5}, cpsat, seeds=[1, 2, 3]
        ),
        3: evaluate_cut_criterion(
            vtoy1_problem, 3, {"A": 0, "B": 14, "C": 6}, cpsat, seeds=[1, 2, 3]
        ),
    }


def test_a10_three_step_cut_criteria_tau3(vtoy1_problem, cut_decisions):
    """A10（5.2.1节/式5-6、5-9）：τ=3 三步判据逐步命中：
    ①通过 ②不排除 ③S={B,C}≠∅ → 生成割 Y_B+Y_C≤1（式5-9形式）。
    §2.2 加班型排除守卫：τ=1（OT≤OT^max）不得生成割。
    """
    # τ=1：①通过（全部重启 ρ<0.8）但 OT=29≤120 → 加班型排除，不生成割
    d1 = cut_decisions[1]
    assert all(r["fallback"] for r in d1.diagnostics["restarts"]), "① 3 次重启均 Feas=0"
    assert d1.diagnostics["stage_loads"][2] == pytest.approx(465)
    assert not d1.generated and d1.reason == "overtime_type"
    assert d1.diagnostics["best_ot"] <= vtoy1_problem.ot_max

    # τ=3：①通过 ②负荷 430≤480 不排除 ②′ OT=198>120 → ③ S={B,C} → 生成割
    d3 = cut_decisions[3]
    assert all(r["fallback"] for r in d3.diagnostics["restarts"]), "① 3 次重启均 Feas=0"
    assert d3.diagnostics["stage_loads"][2] == pytest.approx(430)
    assert d3.diagnostics["stage_loads"][2] <= 480, "② 负荷排除不触发"
    assert d3.diagnostics["best_ot"] > vtoy1_problem.ot_max, "②′ 加班上限内不可消化"
    assert d3.diagnostics["removal_tests"]["B"]["acceptable"], "③ 移B→仅C可行"
    assert d3.diagnostics["removal_tests"]["C"]["acceptable"], "③ 移C→仅B可行"
    assert d3.generated and d3.reason == "structural"
    assert d3.combo == frozenset({"B", "C"}), "割 C={B,C}（式5-9：Y_B+Y_C≤1）"


def test_a11_cut_scope_and_resolution(vtoy1_problem, cut_decisions):
    """A11（式3-12/5-9）：割仅作用于 t=τ=3；重解后 Y_B,3+Y_C,3≤1 成立；
    预计移 C（延期惩罚 6×12=72 < 14×8=112）。
    """
    from src.planning.milp_model import PlanningInputs, solve_planning

    combo = cut_decisions[3].combo
    sol = solve_planning(
        vtoy1_problem,
        PlanningInputs(
            window=(3, 4), demand=vtoy1_problem.demand_at(3), cuts=((combo, 3),)
        ),
    )
    assert sol.y["B"][3] + sol.y["C"][3] <= 1, "重解后割约束成立"
    assert (sol.q["A"][3], sol.q["B"][3], sol.q["C"][3]) == (0, 14, 0), "保B移C"
    assert sol.back["C"][3] == pytest.approx(6)
    assert sol.cost_breakdown["backlog"] == pytest.approx(72), "72 < 112"
    assert sol.q["C"][4] == 6, "割仅作用于 t=3，t=4 的 C 不受限"


def test_a12_cut_set_lifecycle(cut_decisions):
    """A12（式5-10 与清零机制）：ℋ_3^inf 在 τ=3 冻结后清空，ℋ_4^inf,(0)=∅；
    周期内 Δℋ 按式(5-10)累积。
    """
    from src.feedback.cuts import InfeasibleCutPool

    pool = InfeasibleCutPool()
    # τ=3 反馈迭代内：Δℋ 并入（式5-10），重复并入不重复计数
    pool.accumulate({cut_decisions[3].combo})
    pool.accumulate({cut_decisions[3].combo})
    assert len(pool) == 1
    assert pool.cuts_for(3) == ((frozenset({"B", "C"}), 3),)
    # τ=3 冻结后清空 → ℋ_4^inf,(0) = ∅
    pool.clear_after_freeze()
    assert len(pool) == 0
    assert pool.cuts_for(4) == ()


def test_a13_state_chain_and_terminal(vtoy1_problem):
    """A13（式3-9/3-27~3-30）：状态链：Back_B,1 经式(3-9)进入 τ=2 平衡并清偿；
    Back_C,3 在 τ=4 清偿；T_max 末全部 Back=0、库存≥0、O^unfin=∅。
    保护处理口径：欠交累计前必须先用正库存冲抵（式3-9），禁止直接累加。

    按金标 '5_预期行为轨迹' 冻结的逐周期 q 走状态链（闭环端到端复验在
    Stage 5 滚动控制器中进行）；主线 V1 保护处理不触发 → O^unfin 恒为 ∅。
    """
    from src.feedback.protection import update_state

    p = vtoy1_problem
    frozen_q = {1: {"A": 12, "B": 5, "C": 5}, 2: {"A": 6, "B": 9, "C": 4},
                3: {"A": 0, "B": 14, "C": 0}, 4: {"A": 8, "B": 0, "C": 6}}
    inv = dict(p.init_inventory)
    back = {prod: 0.0 for prod in p.products}
    trace = {}
    for tau in p.periods:
        demand_tau = {prod: p.demand_at(tau)[prod][tau] for prod in p.products}
        inv, back = update_state(p, inv, back, frozen_q[tau], demand_tau)
        trace[tau] = (dict(inv), dict(back))
        for prod in p.products:
            assert min(inv[prod], back[prod]) == 0, "式(3-9) 冲抵性质"

    assert trace[1][1]["B"] == pytest.approx(3), "Back_B,1 = 3"
    assert trace[2][1]["B"] == pytest.approx(0), "Back_B 经 τ=2 平衡清偿"
    assert trace[3][1]["C"] == pytest.approx(6), "Back_C,3 = 6"
    assert trace[4][1]["C"] == pytest.approx(0), "Back_C 在 τ=4 清偿"
    for prod in p.products:  # T_max 末全链路清算
        assert trace[4][1][prod] == pytest.approx(0), "全部 Back=0"
        assert trace[4][0][prod] >= 0, "库存 ≥ 0"


def test_a14_representative_selection(vtoy1_problem):
    """A14（式5-16~5-18，工作簿编号）：代表解选择：Ω^acc 非空时取 s(π) 最小；
    τ=3,k=0 时 Ω^acc=∅ → 走违约字典序兜底，兜底解仅用于反馈折算不被冻结。
    """
    # τ=3, k=0：q=(0,14,6) → {B,C} 深度换模冲突，全部解 C_max ≥ 634 > 480
    jobs = build_jobs(vtoy1_problem, {"A": 0, "B": 14, "C": 6})
    front = VendorNsgaScheduler().solve(vtoy1_problem, jobs, tau=3, seed=7)
    assert front
    for s in front:
        assert s.cmax > vtoy1_problem.t_avail, "结构冲突下无可接受解"
    rep = select_representative(vtoy1_problem, front)
    assert rep.is_fallback, "Ω^acc=∅ → 违约字典序兜底（仅用于反馈折算，不冻结）"
    # 兜底字典序首键 = ρ 违约量最小 ⇔ ρ 最大
    assert rep.solution.rho == pytest.approx(max(s.rho for s in front))

    # Ω^acc 非空分支：τ=3 割后 q=(0,14,0) 单族 → 存在可接受解 → 取 s(π) 最小（非兜底）
    jobs_cut = build_jobs(vtoy1_problem, {"A": 0, "B": 14, "C": 0})
    front_cut = VendorNsgaScheduler().solve(vtoy1_problem, jobs_cut, tau=3, seed=7)
    rep_cut = select_representative(vtoy1_problem, front_cut)
    assert not rep_cut.is_fallback
    assert rep_cut.solution.rho >= vtoy1_problem.rho_min
    assert rep_cut.solution.cmax <= vtoy1_problem.t_avail
