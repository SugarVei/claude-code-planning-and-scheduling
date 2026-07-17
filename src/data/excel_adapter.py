"""Excel 适配器：V-toy-1 金标工作簿读入器 + Y企业模板结构读入骨架。

V-toy-1（data/vtoy1.xlsx）为只读金标，版式已冻结（tests/test_vtoy1_workbook.py
按相同坐标锁定），故按单元格坐标解析；坐标常量与金标 sheet 一一对应。

Y企业模板（data/y_template.xlsx）本阶段只读结构（各 sheet 的"表x-y"标题与
表头），字段到 ProblemData 的映射留待 Stage 6 与示例数据一并对齐。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import openpyxl

from .problem_data import EnergyParams, Order, ProblemData
from .validators import validate_problem_data

# ── 通用解析助手 ──────────────────────────────────────────────


def _parse_gear_map(text: str) -> dict[int, float]:
    """解析 's=1:1.00; s=2:0.90; s=3:0.80' 形式的档位映射。"""
    pairs = re.findall(r"s\s*=\s*(\d+)\s*[:：]\s*([\d.]+)", str(text))
    return {int(s): float(v) for s, v in pairs}


def _parse_int_set(text: str) -> list[int]:
    """解析 '{1,2,3}' 形式的整数集合（取第一个花括号内容）。"""
    inner = re.search(r"\{([\d,\s]+)\}", str(text)).group(1)
    return [int(x) for x in inner.split(",")]


def _parse_machines(text: str) -> dict[int, list[str]]:
    """解析 'M1={M11,M12}; M2={M21}; M3={M31,M32}' 为 {阶段: [机器]}。"""
    result: dict[int, list[str]] = {}
    for stage, inner in re.findall(r"M(\d+)\s*=\s*\{([^}]*)\}", str(text)):
        result[int(stage)] = [m.strip() for m in inner.split(",") if m.strip()]
    return result


def _parse_stage_names(text: str) -> dict[int, str]:
    """解析 '1=SMT, 2=DIP, 3=组装' 为 {阶段: 名称}。"""
    pairs = re.findall(r"(\d+)\s*=\s*([^,，]+)", str(text))
    return {int(j): name.strip() for j, name in pairs}


def _parse_weights(text: str) -> tuple[float, float, float]:
    """解析 '(0.50, 0.30, 0.20)' 为三元组。"""
    nums = [float(x) for x in re.findall(r"[\d.]+", str(text))]
    return (nums[0], nums[1], nums[2])


# ── V-toy-1 金标读入器 ────────────────────────────────────────

SHEET_PARAMS = "1_系统与算法参数"
SHEET_PLANNING = "2_计划层数据"
SHEET_SCHEDULING = "3_调度层数据"
SHEET_ORDERS = "4_订单流"


def load_vtoy1(path: str | Path) -> ProblemData:
    """读入 V-toy-1 金标工作簿，构造并校验 ProblemData。"""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws1 = wb[SHEET_PARAMS]
    ws2 = wb[SHEET_PLANNING]
    ws3 = wb[SHEET_SCHEDULING]
    ws4 = wb[SHEET_ORDERS]

    # —— '1_系统与算法参数'：规模与滚动机制（C3..C14）——
    products = [x.strip() for x in str(ws1["C3"].value).split(",")]
    stage_names = _parse_stage_names(ws1["C4"].value)
    stages = sorted(stage_names)
    machines = _parse_machines(ws1["C5"].value)
    speed_gears = _parse_int_set(ws1["C6"].value)
    speed_factor = _parse_gear_map(ws1["C7"].value)
    skill_levels = _parse_int_set(ws1["C8"].value)
    t_max = int(ws1["C9"].value)
    periods = list(range(1, t_max + 1))
    horizon_window = int(ws1["C10"].value)
    horizon_freeze = int(ws1["C11"].value)
    t_avail = float(ws1["C12"].value)
    ot_max = float(ws1["C13"].value)
    transport_time = float(ws1["C14"].value)

    # —— '1_系统与算法参数'：反馈与算法参数（C18..C28）——
    feedback_weights = _parse_weights(ws1["C18"].value)
    gamma = float(ws1["C19"].value)
    delta_max = float(ws1["C20"].value)
    n_restart = int(ws1["C21"].value)
    kappa_c = float(ws1["C22"].value)
    kappa_l = float(ws1["C23"].value)
    kappa_e = float(ws1["C24"].value)
    kappa_s = float(ws1["C25"].value)
    rho_min = float(ws1["C26"].value)
    epsilon_converge = float(ws1["C27"].value)
    k_max = int(ws1["C28"].value)

    # —— '2_计划层数据'：成本与批量（行 3..5）、名义产能（行 17..19）——
    cost_prod: dict[str, float] = {}
    cost_inv: dict[str, float] = {}
    cost_back: dict[str, float] = {}
    cost_setup: dict[str, float] = {}
    lot_size_max: dict[str, int] = {}
    for row in range(3, 3 + len(products)):
        p = str(ws2[f"A{row}"].value)
        cost_prod[p] = float(ws2[f"B{row}"].value)
        cost_inv[p] = float(ws2[f"C{row}"].value)
        cost_back[p] = float(ws2[f"D{row}"].value)
        cost_setup[p] = float(ws2[f"E{row}"].value)
        lot_size_max[p] = int(ws2[f"F{row}"].value)
    capacity: dict[int, dict[int, float]] = {}
    for offset, j in enumerate(stages):
        cap = float(ws2[f"C{17 + offset}"].value)
        capacity[j] = {t: cap for t in periods}  # 全部周期 A_{j,f,t}=1

    # —— '3_调度层数据'：pt^unit（行 3..5）、SDST（行 11..14）、能耗、工人 ——
    proc_time: dict[str, dict[int, float]] = {}
    for row in range(3, 3 + len(products)):
        p = str(ws3[f"A{row}"].value)
        proc_time[p] = {
            j: float(ws3.cell(row=row, column=2 + offset).value)
            for offset, j in enumerate(stages)
        }
    initial_setup: dict[str, float] = {
        p: float(ws3.cell(row=11, column=2 + i).value) for i, p in enumerate(products)
    }
    sdst: dict[str, dict[str, float]] = {}
    for i, prev in enumerate(products):
        sdst[prev] = {
            nxt: float(ws3.cell(row=12 + i, column=2 + jj).value)
            for jj, nxt in enumerate(products)
        }
    energy = EnergyParams(
        power_proc=_parse_gear_map(ws3["B20"].value),
        power_setup=float(ws3["B21"].value),
        power_idle=float(ws3["B22"].value),
        energy_transport=float(ws3["B23"].value),
        power_aux=float(ws3["B24"].value),
    )
    worker_wage: dict[int, float] = {}
    worker_available: dict[int, dict[int, int]] = {}
    for i, level in enumerate(skill_levels):
        row = 28 + i
        worker_wage[level] = float(ws3[f"B{row}"].value)
        worker_available[level] = {
            tau: int(ws3.cell(row=row, column=3 + k).value)
            for k, tau in enumerate(periods)
        }

    # —— '4_订单流'：行 3 起，直到 A 列为空 ——
    orders: list[Order] = []
    row = 3
    while True:
        oid = ws4[f"A{row}"].value
        if oid is None or not str(oid).startswith("o"):
            break
        orders.append(
            Order(
                order_id=str(oid),
                product=str(ws4[f"B{row}"].value),
                quantity=int(ws4[f"C{row}"].value),
                due_period=int(ws4[f"D{row}"].value),
                arrival_period=int(ws4[f"E{row}"].value),
            )
        )
        row += 1

    problem = ProblemData(
        products=products,
        periods=periods,
        stages=stages,
        stage_names=stage_names,
        machines=machines,
        speed_gears=speed_gears,
        skill_levels=skill_levels,
        cost_prod=cost_prod,
        cost_inv=cost_inv,
        cost_back=cost_back,
        cost_setup=cost_setup,
        lot_size_max=lot_size_max,
        capacity=capacity,
        init_inventory={p: 0.0 for p in products},  # V-toy 从零启动
        t_avail=t_avail,
        ot_max=ot_max,
        orders=orders,
        proc_time=proc_time,
        speed_factor=speed_factor,
        sdst=sdst,
        initial_setup=initial_setup,
        worker_wage=worker_wage,
        worker_available=worker_available,
        transport_time=transport_time,
        energy=energy,
        horizon_window=horizon_window,
        horizon_freeze=horizon_freeze,
        k_max=k_max,
        epsilon_converge=epsilon_converge,
        feedback_weights=feedback_weights,
        gamma=gamma,
        delta_max=delta_max,
        n_restart=n_restart,
        kappa_c=kappa_c,
        kappa_l=kappa_l,
        kappa_e=kappa_e,
        kappa_s=kappa_s,
        rho_min=rho_min,
    )
    validate_problem_data(problem)
    return problem


# ── Y企业模板结构读入骨架（字段映射留待 Stage 6）─────────────────


@dataclass(frozen=True)
class TemplateTable:
    """模板中的一张数据表：'表x-y ...' 标题 + 其下一行表头。"""

    title: str
    headers: list[str]


def load_y_template_structure(path: str | Path) -> dict[str, list[TemplateTable]]:
    """扫描 Y企业模板各 sheet，返回 {sheet 名: [表结构]}（仅结构，不读数据）。"""
    wb = openpyxl.load_workbook(path, data_only=True)
    structure: dict[str, list[TemplateTable]] = {}
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        tables: list[TemplateTable] = []
        for i, row in enumerate(rows):
            first = row[0] if row else None
            if isinstance(first, str) and re.match(r"表\d+-\d+", first):
                headers = (
                    [str(c) for c in rows[i + 1] if c is not None]
                    if i + 1 < len(rows)
                    else []
                )
                tables.append(TemplateTable(title=first, headers=headers))
        structure[ws.title] = tables
    return structure


# ── Y企业模板正式读入器（Stage 6：字段 → ProblemData 对齐）─────────


def _table_rows(ws, title_prefix: str) -> list[tuple]:
    """取"表x-y"标题行之后的数据行（跳过表头行，读到空行/下一表为止）。"""
    rows = list(ws.iter_rows(values_only=True))
    out: list[tuple] = []
    in_table = header_skipped = False
    for row in rows:
        first = row[0] if row else None
        if isinstance(first, str) and first.startswith(title_prefix):
            in_table, header_skipped = True, False
            continue
        if in_table:
            if not header_skipped:
                header_skipped = True
                continue
            if first is None or (isinstance(first, str) and first.startswith("表")):
                break
            out.append(row)
    return out


def load_y_style(
    path: str | Path,
    *,
    horizon_window: int = 3,
    horizon_freeze: int = 1,
    k_max: int = 3,
    epsilon_converge: float = 0.01,
    feedback_weights: tuple[float, float, float] = (0.50, 0.30, 0.20),
    gamma: float = 0.5,
    delta_max: float = 1.0,
    n_restart: int = 3,
    kappa: tuple[float, float, float, float] = (2.0, 1.0, 0.05, 0.5),
    rho_min: float = 0.8,
) -> ProblemData:
    """读入 Y企业模板格式工作簿（含示例数据集）构造 ProblemData。

    滚动/反馈算法参数不属于企业采集范围（模板"填写说明"注明由研究方标定），
    经关键字参数传入，默认取论文既定值/V-toy 口径。
    型号级数据按 表1-2 对照聚合为产品族级（族内型号参数一致，取首个并校验）。
    """
    from datetime import date, timedelta  # noqa: F401

    wb = openpyxl.load_workbook(path, data_only=True)
    s1, s2, s3 = wb["一 订单与需求"], wb["二 成本参数"], wb["三 车间结构与工艺"]
    s4, s5, s6 = wb["四 能耗参数"], wb["五 人力资源"], wb["六 日历与产能"]

    # 表6-1：日历参数
    cal = {r[0]: r[1] for r in _table_rows(s6, "表6-1")}
    t_avail = float(cal["每班标准工时"]) * float(cal.get("每日班次数", 1))
    ot_max = float(cal["单日加班上限"])
    period_days = int(cal.get("计划周期长度", 1))
    start = date.fromisoformat(str(cal["排产起始日期"]))
    t_max = int(cal["计划周期数"])
    periods = list(range(1, t_max + 1))

    def to_period(d) -> int:
        dd = d.date() if hasattr(d, "date") else date.fromisoformat(str(d))
        return (dd - start).days // period_days + 1

    # 表1-2：型号 → 族
    fam_of = {str(r[0]): str(r[2]) for r in _table_rows(s1, "表1-2")}
    products = sorted(set(fam_of.values()))

    # 表1-1：订单（型号聚合为族；到达周期下限钳为 1）
    orders = [
        Order(
            order_id=str(r[0]),
            product=fam_of[str(r[1])],
            quantity=int(r[2]),
            due_period=to_period(r[4]),
            arrival_period=max(1, to_period(r[3])),
        )
        for r in _table_rows(s1, "表1-1")
    ]

    # 表1-3：期初库存（按族求和）
    init_inv = {p: 0.0 for p in products}
    for r in _table_rows(s1, "表1-3"):
        init_inv[fam_of[str(r[0])]] += float(r[1] or 0)

    # 表2-1：成本（族内取首个型号，校验一致）
    cost_prod, cost_inv, cost_back, cost_setup = {}, {}, {}, {}
    for r in _table_rows(s2, "表2-1"):
        fam = fam_of[str(r[0])]
        vals = (float(r[1]), float(r[2]), float(r[3]), float(r[4]))
        if fam in cost_prod:
            if (cost_prod[fam], cost_inv[fam], cost_back[fam], cost_setup[fam]) != vals:
                raise ValueError(f"族 {fam} 内型号成本不一致（族级模型要求一致）")
        cost_prod[fam], cost_inv[fam], cost_back[fam], cost_setup[fam] = vals

    # 表3-1：阶段与机器
    stage_names: dict[int, str] = {}
    machines: dict[int, list[str]] = {}
    n_gears = 0
    for r in _table_rows(s3, "表3-1"):
        j = int(r[0])
        stage_names[j] = str(r[1])
        machines.setdefault(j, []).append(str(r[2]))
        n_gears = max(n_gears, int(r[4]))
    stages = sorted(stage_names)
    speed_gears = list(range(1, n_gears + 1))

    # 表3-2：单件加工时间（档位1 为基准；θ_s 由比值推出并校验一致）
    proc_time: dict[str, dict[int, float]] = {p: {} for p in products}
    theta_samples: dict[int, list[float]] = {s: [] for s in speed_gears}
    base_time: dict[tuple[str, int], float] = {}
    rows32 = _table_rows(s3, "表3-2")
    for r in rows32:
        model, j, s, t = str(r[0]), int(r[1]), int(r[3]), float(r[4])
        if s == 1:
            base_time[(model, j)] = t
            fam = fam_of[model]
            if j in proc_time[fam] and abs(proc_time[fam][j] - t) > 1e-9:
                raise ValueError(f"族 {fam} 阶段 {j} 型号间基准工时不一致")
            proc_time[fam][j] = t
    for r in rows32:
        model, j, s, t = str(r[0]), int(r[1]), int(r[3]), float(r[4])
        theta_samples[s].append(t / base_time[(model, j)])
    speed_factor = {}
    for s in speed_gears:
        vals = theta_samples[s]
        speed_factor[s] = round(sum(vals) / len(vals), 6)
        if max(vals) - min(vals) > 1e-6:
            raise ValueError(f"档位 {s} 的速度系数在型号/阶段间不一致")

    # 表3-3：SDST（族级，"开机"行 → 初始设置）
    initial_setup: dict[str, float] = {}
    sdst = {a: {b: 0.0 for b in products} for a in products}
    for r in _table_rows(s3, "表3-3"):
        prev, nxt, t = str(r[2]), str(r[3]), float(r[4])
        if prev == "开机":
            initial_setup[nxt] = t
        else:
            sdst[prev][nxt] = t

    # 表3-4 / 表3-6
    trans_rows = _table_rows(s3, "表3-4")
    transport_time = sum(float(r[2]) for r in trans_rows) / len(trans_rows)
    lot_size_max: dict[str, int] = {}
    for r in _table_rows(s3, "表3-6"):
        lot_size_max[fam_of[str(r[0])]] = int(r[1])

    # 表4-1 / 表4-2：能耗
    power_proc: dict[int, float] = {}
    se = ie = None
    for r in _table_rows(s4, "表4-1"):
        power_proc[int(r[2])] = float(r[3])
        se = float(r[4]) if se is None else se
        ie = float(r[5]) if ie is None else ie
    misc = {str(r[0]): float(r[1]) for r in _table_rows(s4, "表4-2")}
    te = misc["单次运输能耗"] * 60.0 / transport_time  # kWh/次 → kW·min/min
    ae = misc["车间辅助功率"]

    # 表5-1 / 表5-2：技能与可用性
    skill_levels: list[int] = []
    worker_wage: dict[int, float] = {}
    for r in _table_rows(s5, "表5-1"):
        lv = int(r[0])
        skill_levels.append(lv)
        worker_wage[lv] = float(r[3])
        if int(r[2]) != lv:
            raise ValueError("向下兼容口径要求 可操作最高档位 = 技能等级")
    skill_levels.sort()
    default_avail: dict[int, int] | None = None
    overrides: dict[int, dict[int, int]] = {}
    for r in _table_rows(s5, "表5-2"):
        counts = {lv: int(r[i + 1]) for i, lv in enumerate(skill_levels)}
        if str(r[0]) == "常态配置":
            default_avail = counts
        else:
            overrides[to_period(r[0])] = counts
    worker_available = {
        lv: {
            t: overrides.get(t, default_avail)[lv] for t in periods
        }
        for lv in skill_levels
    }

    problem = ProblemData(
        products=products,
        periods=periods,
        stages=stages,
        stage_names=stage_names,
        machines=machines,
        speed_gears=speed_gears,
        skill_levels=skill_levels,
        cost_prod=cost_prod,
        cost_inv=cost_inv,
        cost_back=cost_back,
        cost_setup=cost_setup,
        lot_size_max=lot_size_max,
        capacity={j: {t: t_avail * len(machines[j]) for t in periods} for j in stages},
        init_inventory=init_inv,
        t_avail=t_avail,
        ot_max=ot_max,
        orders=orders,
        proc_time=proc_time,
        speed_factor=speed_factor,
        sdst=sdst,
        initial_setup=initial_setup,
        worker_wage=worker_wage,
        worker_available=worker_available,
        transport_time=transport_time,
        energy=EnergyParams(
            power_proc=power_proc,
            power_setup=se,
            power_idle=ie,
            energy_transport=te,
            power_aux=ae,
        ),
        horizon_window=horizon_window,
        horizon_freeze=horizon_freeze,
        k_max=k_max,
        epsilon_converge=epsilon_converge,
        feedback_weights=feedback_weights,
        gamma=gamma,
        delta_max=delta_max,
        n_restart=n_restart,
        kappa_c=kappa[0],
        kappa_l=kappa[1],
        kappa_e=kappa[2],
        kappa_s=kappa[3],
        rho_min=rho_min,
    )
    validate_problem_data(problem)
    return problem
