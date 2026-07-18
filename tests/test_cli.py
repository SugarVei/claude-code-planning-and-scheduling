"""CLI 端到端测试（真实子进程调用，Stage 7 验收）。"""
import subprocess
import sys

import openpyxl
import pytest

from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.slow_solver


def _run_cli(args, timeout=300):
    return subprocess.run(
        [sys.executable, "-m", "src.cli", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout,
    )


def test_run_sample_scheme_a(tmp_path):
    """示例数据端到端：方案 A + CP-SAT 非严格 → 指标与导出文件齐全。"""
    out = tmp_path / "cli_a"
    r = _run_cli([
        "run", "--input", "data/sample_y_style.xlsx", "--scheme", "A",
        "--output", str(out), "--time-limit", "2",
    ])
    assert r.returncode == 0, r.stderr
    assert "6 产品族 / 3 阶段 / 10 周期 / 28 订单" in r.stdout
    assert "总成本" in r.stdout and "结果已导出" in r.stdout
    assert (out / "实验结果汇总.xlsx").exists()
    assert (out / "表5-1_四方案对比.csv").exists()
    assert (out / "表5-4_逐周期明细.csv").exists()


def test_run_vtoy_scheme_c(tmp_path):
    """V-toy 金标格式自动识别 + 方案 C 完整闭环。"""
    out = tmp_path / "cli_c"
    r = _run_cli([
        "run", "--input", "data/vtoy1.xlsx", "--scheme", "C",
        "--output", str(out), "--strict", "--time-limit", "120",
    ])
    assert r.returncode == 0, r.stderr
    assert "3 产品族 / 3 阶段 / 4 周期 / 9 订单" in r.stdout
    assert "调度可行率=1.00" in r.stdout
    assert "期末欠交=0件" in r.stdout
    assert (out / "实验结果汇总.xlsx").exists()


def test_bad_inputs_rejected(tmp_path):
    """错误输入明确报错：不存在的文件 / 非法方案。"""
    r = _run_cli(["run", "--input", "no_such.xlsx", "--scheme", "C"])
    assert r.returncode != 0
    assert "不存在" in (r.stdout + r.stderr)
    r2 = _run_cli(["run", "--input", "data/vtoy1.xlsx", "--scheme", "X"])
    assert r2.returncode != 0


def test_unrecognized_workbook_format_rejected(tmp_path):
    """既非 V-toy-1 亦非 Y企业模板格式的工作簿：明确报错。"""
    bad_wb = tmp_path / "unrecognized.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "not_a_known_sheet"
    wb.save(bad_wb)
    r = _run_cli(["run", "--input", str(bad_wb), "--scheme", "C"])
    assert r.returncode != 0
    assert "无法识别的工作簿格式" in (r.stdout + r.stderr)
