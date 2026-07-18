"""薄壳 CLI（Stage 7）：一条命令运行方案并导出结果。

用法（仓库根目录）：
    python3 -m src.cli run --input data/sample_y_style.xlsx --scheme C \
        --output results/my_run [--scheduler cpsat|vendor] [--time-limit 3] \
        [--strict] [--seed 0]

输入工作簿格式自动识别：
    V-toy-1 金标工作簿（含 '1_系统与算法参数' 表）→ load_vtoy1
    Y企业模板格式（含 '一 订单与需求' 表）→ load_y_style
输出：指标表 + 逐周期明细 CSV 与汇总 xlsx（见 src/experiments/report.py）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import openpyxl

from src.data.excel_adapter import load_vtoy1, load_y_style
from src.data.problem_data import ProblemData
from src.experiments.report import export_all
from src.experiments.runner import compute_metrics
from src.experiments.schemes import SCHEMES, run_scheme
from src.scheduling.exact_cpsat import CpSatScheduler
from src.scheduling.meta_vendor import VendorNsgaScheduler


def load_problem(path: str | Path) -> ProblemData:
    """按工作簿表名自动识别格式并读入。"""
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"输入文件不存在：{path}")
    names = openpyxl.load_workbook(path, read_only=True).sheetnames
    if "1_系统与算法参数" in names:
        return load_vtoy1(path)
    if "一 订单与需求" in names:
        return load_y_style(path)
    raise SystemExit(f"无法识别的工作簿格式：{path}（既非 V-toy-1 亦非 Y企业模板格式）")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m src.cli",
        description="集成生产计划与调度系统：滚动闭环运行入口（薄壳）",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="运行一个实验方案并导出指标/明细")
    run_p.add_argument("--input", required=True, help="输入工作簿（V-toy-1 或 Y模板格式）")
    run_p.add_argument("--scheme", choices=SCHEMES, default="C", help="方案（默认 C 完整三通道）")
    run_p.add_argument("--output", default="results/run", help="输出目录")
    run_p.add_argument(
        "--scheduler", choices=("cpsat", "vendor"), default="cpsat",
        help="调度器：cpsat=CP-SAT（默认）；vendor=真实 NSGA-II-VNS-MOSA",
    )
    run_p.add_argument("--time-limit", type=float, default=3.0, help="CP-SAT 单次时限（秒）")
    run_p.add_argument("--strict", action="store_true", help="CP-SAT 需证明最优（小规模验证用）")
    run_p.add_argument("--seed", type=int, default=0, help="随机种子基数")
    args = parser.parse_args(argv)

    problem = load_problem(args.input)
    if args.scheduler == "cpsat":
        scheduler = CpSatScheduler(
            time_limit_s=args.time_limit, require_optimal=args.strict
        )
    else:
        scheduler = VendorNsgaScheduler()

    print(
        f"输入 {args.input}：{len(problem.products)} 产品族 / "
        f"{len(problem.stages)} 阶段 / {len(problem.periods)} 周期 / "
        f"{len(problem.orders)} 订单；方案 {args.scheme}，调度器 {args.scheduler}"
    )
    result = run_scheme(problem, scheduler, args.scheme, base_seed=args.seed)
    metrics = compute_metrics(problem, result, f"方案{args.scheme}")
    xlsx = export_all(
        problem, args.output, {args.scheme: result}, {args.scheme: metrics}
    )
    print(
        f"总成本(库存+延期+设置)={metrics.total_cost:.0f} "
        f"(库存 {metrics.holding_cost:.0f} / 延期 {metrics.backlog_cost:.0f} / "
        f"设置 {metrics.setup_cost:.0f})\n"
        f"调度可行率={metrics.feasible_rate:.2f}  平均反馈迭代={metrics.avg_iterations:.2f}  "
        f"订单准时率={metrics.on_time_rate:.2f}  加班={metrics.total_overtime:.0f}min  "
        f"期末欠交={metrics.terminal_backlog:.0f}件"
    )
    print(f"结果已导出 → {xlsx}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
