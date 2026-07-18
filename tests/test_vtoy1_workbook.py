"""金标算例 V-toy-1 工作簿完整性回归测试。

data/vtoy1.xlsx 是金标回归用例（只读，不可改动）。本文件按单元格坐标
锁定其全部关键参数与触发机关数值：任何对金标数据的意外改动都会使
本套件变红。这是 Stage 0 "冻结回归基线" 在数据侧的实现。

数值来源：工作簿各 sheet 实际单元格（坐标见各断言）；
设计依据：docs/SYSTEM_DESIGN.md §5 与工作簿 '0_说明'。
"""
import pytest

pytestmark = pytest.mark.regression

EXPECTED_SHEETS = [
    "0_说明",
    "1_系统与算法参数",
    "2_计划层数据",
    "3_调度层数据",
    "4_订单流",
    "5_预期行为轨迹",
    "6_断言清单",
    "7_变体设计",
    "8_P1判据歧义",
]


def test_sheet_structure(vtoy1_workbook):
    """工作簿包含全部 9 个 sheet，顺序与名称一致。"""
    assert vtoy1_workbook.sheetnames == EXPECTED_SHEETS


def test_rolling_mechanism_params(vtoy1_workbook):
    """规模与滚动机制参数（'1_系统与算法参数' 第一表）。"""
    ws = vtoy1_workbook["1_系统与算法参数"]
    assert ws["C9"].value == 4, "T_max 最大计划周期"
    assert ws["C10"].value == 3, "H_w 滚动窗口长度"
    assert ws["C11"].value == 1, "H_f 冻结长度"
    assert ws["C12"].value == 480, "T_t^avail 周期标准可用工时"
    assert ws["C13"].value == 120, "OT_t^max 最大加班时长"
    assert ws["C14"].value == 5, "运输时间（全部 5 min）"
    # 结构性文本参数
    assert ws["C3"].value == "A, B, C", "产品集合 P"
    assert "1.00" in ws["C7"].value and "0.90" in ws["C7"].value and "0.80" in ws["C7"].value, (
        "速度时间系数 θ_s 三档"
    )


def test_feedback_algorithm_params(vtoy1_workbook):
    """反馈与算法参数（'1_系统与算法参数' 第二表）。"""
    ws = vtoy1_workbook["1_系统与算法参数"]
    assert ws["C18"].value == "(0.50, 0.30, 0.20)", "代表解权重 (ω_C,ω_L,ω_E)"
    assert ws["C19"].value == 0.5, "γ 成本反馈阻尼"
    assert ws["C20"].value == 1, "δ^max 成本反馈上界系数"
    assert ws["C21"].value == 3, "N_restart 割生成重启次数"
    assert ws["C22"].value == 2, "κ_C 折算系数-加班"
    assert ws["C23"].value == 1, "κ_L 折算系数-人力增量"
    assert ws["C24"].value == 0.05, "κ_E 折算系数-能耗增量"
    assert ws["C25"].value == 0.5, "κ_S 折算系数-SDST"
    assert ws["C26"].value == 0.8, "ρ_min 调度可接受度阈值"
    assert ws["C27"].value == 0.01, "ε_P 目标改善阈值"
    assert ws["C28"].value == 3, "K_max 最大反馈迭代次数"


def test_planning_cost_params(vtoy1_workbook):
    """产品成本与批量参数（'2_计划层数据' 表一）。

    机关：b_B=8 为最小延期惩罚 → 变体 V2 保护处理按 b_p 升序应首先移出 B。
    """
    ws = vtoy1_workbook["2_计划层数据"]
    # 行序：A(3), B(4), C(5)；列序：c_p, h_p, b_p, g_p, U_p^lot
    expected = {
        "A": (50, 2, 10, 100, 4),
        "B": (60, 2, 8, 120, 4),
        "C": (70, 3, 12, 150, 5),
    }
    for row, product in [(3, "A"), (4, "B"), (5, "C")]:
        assert ws[f"A{row}"].value == product
        actual = tuple(ws[f"{col}{row}"].value for col in "BCDEF")
        assert actual == expected[product], f"产品 {product} 成本参数"
    # 机关核对：b_B 最小
    b_values = {p: expected[p][2] for p in expected}
    assert min(b_values, key=b_values.get) == "B"


def test_capacity_and_processing_time(vtoy1_workbook):
    """能力占用 a_{p,j} 与名义产能（'2_计划层数据'），并与调度层 pt^unit 一致。"""
    ws = vtoy1_workbook["2_计划层数据"]
    a_pj = {
        "A": (10, 15, 12),
        "B": (12, 20, 10),
        "C": (8, 25, 14),
    }
    for row, product in [(11, "A"), (12, "B"), (13, "C")]:
        actual = tuple(ws[f"{col}{row}"].value for col in "BCD")
        assert actual == a_pj[product], f"a_{{{product},j}}"
    # 名义产能：阶段1=960, 阶段2=480(瓶颈), 阶段3=960
    assert ws["C17"].value == 960
    assert ws["C18"].value == 480
    assert ws["C19"].value == 960
    assert ws["B18"].value == 1, "阶段2 单机 = 瓶颈"

    # 调度层 pt^unit（'3_调度层数据' 表一，s=1 基准）与计划层 a_{p,j} 同值
    ws3 = vtoy1_workbook["3_调度层数据"]
    for row, product in [(3, "A"), (4, "B"), (5, "C")]:
        actual = tuple(ws3[f"{col}{row}"].value for col in "BCD")
        assert actual == a_pj[product], f"pt^unit_{{{product},j}} 与 a_{{p,j}} 一致"


def test_sdst_matrix(vtoy1_workbook):
    """SDST 矩阵（'3_调度层数据' 表二）。

    机关：B↔C=280 深度换模 → τ=3 仅 B、C 同期时构成结构性组合冲突（通道3触发源）；
    τ=1 有 A 作缓冲可回避（最优序设置合计 = 10+25+30 = 65）。
    """
    ws = vtoy1_workbook["3_调度层数据"]
    # 行：0(初始)=11, A→=12, B→=13, C→=14；列：→A=B, →B=C, →C=D
    assert (ws["B11"].value, ws["C11"].value, ws["D11"].value) == (10, 10, 10), "虚拟工件初始设置 S_0,i=10"
    assert (ws["B12"].value, ws["C12"].value, ws["D12"].value) == (0, 20, 30), "A→ 行"
    assert (ws["B13"].value, ws["C13"].value, ws["D13"].value) == (25, 0, 280), "B→ 行"
    assert (ws["B14"].value, ws["C14"].value, ws["D14"].value) == (25, 280, 0), "C→ 行"
    # τ=1 缓冲序设置合计 = S_0 + B→A(或对称路径) = 10 + 25 + 30 = 65
    assert ws["B11"].value + ws["B13"].value + ws["D12"].value == 65


def test_energy_params(vtoy1_workbook):
    """能耗与功率参数（'3_调度层数据' 表三）。"""
    ws = vtoy1_workbook["3_调度层数据"]
    assert "s=1:3" in ws["B20"].value and "s=2:5" in ws["B20"].value and "s=3:8" in ws["B20"].value, (
        "加工功率 pe 三档"
    )
    assert ws["B21"].value == 2, "准备功率 se"
    assert ws["B22"].value == 1, "空闲功率 ie"
    assert ws["B23"].value == 0.1, "单位运输能耗 te"
    assert ws["B24"].value == 0.5, "单位时间辅助能耗 ae"


def test_worker_skill_availability(vtoy1_workbook):
    """工人技能与班次（'3_调度层数据' 表四）。

    机关：τ=2 时 α=3 工人缺勤（可用=0）→ 工人总数 4 < 机器数 5
    → η^skill = 4/5 = 0.8 进入 Cap^eff 更新，且全车间无人可开 s=3 档。
    """
    ws = vtoy1_workbook["3_调度层数据"]
    # 行：α=1(28), α=2(29), α=3(30)；列：工资=B, τ=1..4 可用数=C..F
    expected = {
        1: (200, 2, 2, 2, 2),
        2: (280, 2, 2, 2, 2),
        3: (400, 1, 0, 1, 1),
    }
    for row, alpha in [(28, 1), (29, 2), (30, 3)]:
        assert ws[f"A{row}"].value == alpha
        actual = tuple(ws[f"{col}{row}"].value for col in "BCDEF")
        assert actual == expected[alpha], f"技能等级 α={alpha} 工资与可用性"
    # 机关核对：τ=2 工人总数 4，机器数 5（M11,M12,M21,M31,M32）
    total_tau2 = sum(expected[a][2] for a in expected)
    assert total_tau2 == 4


def test_order_stream(vtoy1_workbook):
    """订单流 o1~o9（'4_订单流'）。

    机关：τ=1 聚合需求 A12/B8/C5 → 阶段2负荷 = 12×15+8×20+5×25 = 465 ≤ 480
    （聚合可行、调度不可行 —— 闭环存在意义的最小演示）；
    o6+o9 在 τ=3 构成 {B,C} 深度换模冲突（通道3触发）。
    """
    ws = vtoy1_workbook["4_订单流"]
    # (订单, 产品, 数量, 交付周期, 到达周期)
    expected_orders = [
        ("o1", "A", 12, 1, 1),
        ("o2", "B", 8, 1, 1),
        ("o3", "C", 5, 1, 1),
        ("o4", "A", 6, 2, 1),
        ("o5", "B", 6, 2, 1),
        ("o6", "C", 6, 3, 1),
        ("o7", "C", 4, 2, 2),
        ("o8", "A", 8, 4, 2),
        ("o9", "B", 14, 3, 3),
    ]
    for i, exp in enumerate(expected_orders):
        row = 3 + i
        actual = tuple(ws[f"{col}{row}"].value for col in "ABCDE")
        assert actual == exp, f"订单 {exp[0]}"
    # 机关核对：τ=1 (t=1) 阶段2负荷
    load_stage2 = 12 * 15 + 8 * 20 + 5 * 25
    assert load_stage2 == 465
    assert load_stage2 <= 480, "聚合可行"
    # 机关核对：τ=3 到期需求 B14(o9)+C6(o6)，阶段2负荷 430 ≤ 480 但 SDST 致不可行
    assert 14 * 20 + 6 * 25 == 430


def test_assertion_checklist_a01_a14(vtoy1_workbook):
    """断言清单（'6_断言清单'）：恰好 14 条，编号 A01~A14 连续，均有内容与论文位置。"""
    ws = vtoy1_workbook["6_断言清单"]
    entries = []
    for row in range(3, 17):  # A3:C16
        code = ws[f"A{row}"].value
        content = ws[f"B{row}"].value
        ref = ws[f"C{row}"].value
        entries.append((code, content, ref))
    assert len(entries) == 14
    for i, (code, content, ref) in enumerate(entries, start=1):
        assert code == f"A{i:02d}", f"断言编号连续: 第{i}条应为 A{i:02d}"
        assert content and str(content).strip(), f"{code} 断言内容非空"
        assert ref and str(ref).strip(), f"{code} 论文位置非空"
