"""在示例数据集上运行 Stage 6 全部实验并导出结果（论文表5-1~5-4、图5-2 数据）。

用法：python3 scripts/run_sample_experiments.py [输出目录]
运行配置（示例规模的工程折中，见 Stage 6 汇报）：CP-SAT 4s 时限
非严格模式（时限内最好解）、N_restart=2。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.excel_adapter import load_y_style
from src.experiments.report import export_all
from src.experiments.runner import (
    ABLATION_CONFIGS,
    compute_metrics,
    run_scheme_comparison,
    run_weight_sensitivity,
)
from src.rolling.controller import run_rolling
from src.scheduling.exact_cpsat import CpSatScheduler


def main() -> None:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "results/sample_y_style"
    problem = load_y_style("data/sample_y_style.xlsx", n_restart=2)
    scheduler = CpSatScheduler(time_limit_s=4, require_optimal=False)

    t0 = time.time()
    print("[1/3] 方案 A~D 对比 …", flush=True)
    results, metrics = run_scheme_comparison(problem, scheduler, base_seed=0)
    print(f"      完成（{time.time()-t0:.0f}s）", flush=True)

    print("[2/3] 单通道消融 …", flush=True)
    ablation = {"完整三通道(=方案C)": compute_metrics(problem, results["C"], "完整三通道(=方案C)")}
    for label, config in ABLATION_CONFIGS.items():
        if label == "完整三通道":
            continue
        ablation[label] = compute_metrics(
            problem, run_rolling(problem, scheduler, config, base_seed=0), label
        )
    print(f"      完成（{time.time()-t0:.0f}s）", flush=True)

    print("[3/3] 权重敏感性 …", flush=True)
    sensitivity = run_weight_sensitivity(
        problem, scheduler,
        [(0.50, 0.30, 0.20), (0.20, 0.30, 0.50), (0.34, 0.33, 0.33)],
        base_seed=0,
    )
    xlsx = export_all(problem, out_dir, results, metrics, ablation, sensitivity)
    print(f"全部完成（{time.time()-t0:.0f}s）→ {xlsx}", flush=True)
    for m in metrics.values():
        print(f"  {m.label}: 总成本={m.total_cost:.0f} 可行率={m.feasible_rate:.2f} "
              f"准时率={m.on_time_rate:.2f} OT={m.total_overtime:.0f}", flush=True)


if __name__ == "__main__":
    main()
