"""结果导出（Stage 6 (e)）：论文表 5-1~5-4 与图 5-2 的数据文件。

CSV 采用 utf-8-sig（Excel 直接打开不乱码）；同时汇总为一个 xlsx。
"""
from __future__ import annotations

import csv
from pathlib import Path

import openpyxl

from src.data.problem_data import ProblemData
from src.experiments.runner import SchemeMetrics
from src.rolling.controller import RollingResult

METRIC_HEADER = [
    "方案", "库存成本", "延期成本", "设置成本", "总成本(库存+延期+设置)",
    "调度可行率", "平均反馈迭代次数", "订单准时率", "加班时长(min)", "期末欠交(件)",
]


def _metric_row(m: SchemeMetrics) -> list:
    return [
        m.label, round(m.holding_cost, 2), round(m.backlog_cost, 2),
        round(m.setup_cost, 2), round(m.total_cost, 2),
        round(m.feasible_rate, 4), round(m.avg_iterations, 3),
        round(m.on_time_rate, 4), round(m.total_overtime, 1),
        round(m.terminal_backlog, 1),
    ]


def _write_csv(path: Path, header: list, rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def export_metric_table(
    metrics: dict[str, SchemeMetrics], path: Path
) -> list[list]:
    rows = [_metric_row(m) for m in metrics.values()]
    _write_csv(path, METRIC_HEADER, rows)
    return rows


def export_period_detail(
    problem: ProblemData, results: dict[str, RollingResult], path: Path
) -> list[list]:
    """逐周期明细（表5-4 与图5-2 曲线数据：成本/加班/迭代随 τ 的轨迹）。"""
    header = (
        ["方案", "周期τ", "反馈迭代k*"]
        + [f"q_{p}" for p in problem.products]
        + ["C_max", "OT", "ρ", "可接受", "当期库存成本", "当期延期成本"]
    )
    rows = []
    for label, result in results.items():
        for pr in result.periods:
            holding = sum(
                problem.cost_inv[p] * pr.inv_after[p] for p in problem.products
            )
            backlog = sum(
                problem.cost_back[p] * pr.back_after[p] for p in problem.products
            )
            acceptable = int(
                pr.schedule.rho >= problem.rho_min
                and pr.schedule.cmax <= problem.t_avail + 1e-9
            )
            rows.append(
                [label, pr.tau, pr.k_star]
                + [pr.frozen_q.get(p, 0) for p in problem.products]
                + [
                    round(pr.schedule.cmax, 1), round(pr.schedule.ot, 1),
                    round(pr.schedule.rho, 3), acceptable,
                    round(holding, 1), round(backlog, 1),
                ]
            )
    _write_csv(path, header, rows)
    return rows


def export_all(
    problem: ProblemData,
    out_dir: str | Path,
    scheme_results: dict[str, RollingResult],
    scheme_metrics: dict[str, SchemeMetrics],
    ablation_metrics: dict[str, SchemeMetrics] | None = None,
    sensitivity_metrics: dict[str, SchemeMetrics] | None = None,
) -> Path:
    """导出全部表格：CSV（表5-1~5-4）+ 汇总 xlsx。返回 xlsx 路径。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tables: dict[str, tuple[list, list[list]]] = {}

    rows = export_metric_table(scheme_metrics, out / "表5-1_四方案对比.csv")
    tables["表5-1 四方案对比"] = (METRIC_HEADER, rows)
    if ablation_metrics:
        rows = export_metric_table(ablation_metrics, out / "表5-2_通道消融.csv")
        tables["表5-2 通道消融"] = (METRIC_HEADER, rows)
    if sensitivity_metrics:
        rows = export_metric_table(sensitivity_metrics, out / "表5-3_权重敏感性.csv")
        tables["表5-3 权重敏感性"] = (METRIC_HEADER, rows)
    detail_header = None
    detail_rows = export_period_detail(
        problem, scheme_results, out / "表5-4_逐周期明细.csv"
    )
    detail_header = (
        ["方案", "周期τ", "反馈迭代k*"]
        + [f"q_{p}" for p in problem.products]
        + ["C_max", "OT", "ρ", "可接受", "当期库存成本", "当期延期成本"]
    )
    tables["表5-4 逐周期明细(图5-2)"] = (detail_header, detail_rows)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, (header, rows) in tables.items():
        ws = wb.create_sheet(name[:31])
        ws.append(header)
        for r in rows:
            ws.append(r)
    xlsx = out / "实验结果汇总.xlsx"
    wb.save(xlsx)
    return xlsx
