"""集成生产计划与调度系统 —— 可视化界面（Streamlit 本地 Web 应用）。

启动（仓库根目录）：
    streamlit run app/webapp.py

流程：① 导入数据（上传 Excel 或选内置数据集，格式自动识别）→
② 配置方案/调度器 → ③ 运行闭环 → ④ 查看结果：指标卡片、各周期排程
总览、单周期钻取（机器甘特图、Pareto 解集分布、反馈迭代轨迹）、导出。

安全说明（对应总控问题清单的 Web 入口要求）：上传文件仅接受 .xlsx，
保存到本进程的临时目录后立即读入，不提供任何"按作业 ID 取文件"的
路径参数接口——不存在路径穿越面；内置数据集通过白名单下拉选择。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import streamlit as st

from app.plots import (
    cmax_overview_figure,
    gantt_figure,
    iteration_table_rows,
    pareto_figure,
    plan_overview_figure,
    state_overview_figure,
)
from src.cli import load_problem
from src.experiments.report import export_all
from src.experiments.runner import compute_metrics
from src.experiments.schemes import SCHEMES, run_scheme
from src.scheduling.exact_cpsat import CpSatScheduler
from src.scheduling.meta_vendor import VendorNsgaScheduler

BUILTIN_DATASETS = {  # 白名单：仓库内置数据集
    "示例数据集（Y企业风格，10 周期）": REPO_ROOT / "data" / "sample_y_style.xlsx",
    "V-toy-1 金标算例（4 周期）": REPO_ROOT / "data" / "vtoy1.xlsx",
}

st.set_page_config(page_title="计划-调度闭环系统", layout="wide")
st.title("集成生产计划与调度系统")
st.caption("滚动时域闭环：计划层 MILP → 子批化 → HFSP-SDST 调度 → 三通道反馈 → 滚动更新")

# ── ① 数据导入 ──────────────────────────────────────────────
with st.sidebar:
    st.header("① 导入数据")
    source = st.radio("数据来源", ["上传 Excel", "内置数据集"], horizontal=True)
    problem = None
    data_label = None
    if source == "上传 Excel":
        upload = st.file_uploader(
            "V-toy-1 格式或 Y企业模板格式工作簿", type=["xlsx"],
            help="格式按表名自动识别；参见 data/y_template.xlsx 采集模板",
        )
        if upload is not None:
            tmp = Path(tempfile.mkdtemp(prefix="ppsched_")) / "upload.xlsx"
            tmp.write_bytes(upload.getvalue())
            try:
                problem = load_problem(tmp)
                data_label = upload.name
            except (SystemExit, ValueError) as exc:
                st.error(f"数据读入失败：{exc}")
    else:
        choice = st.selectbox("选择数据集", list(BUILTIN_DATASETS))
        problem = load_problem(BUILTIN_DATASETS[choice])
        data_label = choice

    st.header("② 运行配置")
    scheme = st.selectbox(
        "实验方案", SCHEMES, index=2,
        format_func=lambda s: {
            "A": "A 传统两阶段（无反馈）", "B": "B 滚动无反馈",
            "C": "C 完整三通道（本文机制）", "D": "D 去成本修正（消融）",
        }[s],
    )
    scheduler_kind = st.radio(
        "调度求解器", ["cpsat", "vendor"], horizontal=True,
        format_func=lambda x: "CP-SAT（快，确定性）" if x == "cpsat"
        else "NSGA-II-VNS-MOSA（论文算法，慢）",
    )
    time_limit = st.slider("CP-SAT 单次时限（秒）", 1, 30, 3)
    seed = st.number_input("随机种子", value=0, step=1)
    run_clicked = st.button("③ 运行闭环", type="primary",
                            disabled=problem is None, use_container_width=True)

if problem is None:
    st.info("请先在左侧导入数据（上传 Excel 或选择内置数据集）。")
    st.stop()

# 数据概览
st.subheader(f"数据概览：{data_label}")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("产品族", len(problem.products))
c2.metric("加工阶段", len(problem.stages))
c3.metric("机器", sum(len(m) for m in problem.machines.values()))
c4.metric("计划周期", len(problem.periods))
c5.metric("订单", len(problem.orders))
with st.expander("订单明细 / 关键参数"):
    st.dataframe(
        [{"订单": o.order_id, "产品族": o.product, "数量": o.quantity,
          "到达周期": o.arrival_period, "交付周期": o.due_period}
         for o in problem.orders],
        use_container_width=True, height=240,
    )
    st.write(
        f"T^avail={problem.t_avail:.0f}min｜OT^max={problem.ot_max:.0f}min｜"
        f"H_w={problem.horizon_window}｜K_max={problem.k_max}｜"
        f"权重 (ω_C,ω_L,ω_E)={problem.feedback_weights}"
    )

# ── ③ 运行 ─────────────────────────────────────────────────
run_key = (data_label, scheme, scheduler_kind, time_limit, int(seed))
if run_clicked:
    scheduler = (
        CpSatScheduler(time_limit_s=float(time_limit), require_optimal=False)
        if scheduler_kind == "cpsat"
        else VendorNsgaScheduler()
    )
    with st.spinner(f"方案 {scheme} 滚动闭环运行中（{len(problem.periods)} 个周期）…"):
        result = run_scheme(problem, scheduler, scheme, base_seed=int(seed))
    st.session_state["run"] = (run_key, result)

if "run" not in st.session_state:
    st.stop()
stored_key, result = st.session_state["run"]
if stored_key != run_key:
    st.warning("配置已更改，当前展示的是上一次运行结果；点击「运行闭环」刷新。")
metrics = compute_metrics(problem, result, f"方案{scheme}")

# ── ④ 结果：指标卡片 ────────────────────────────────────────
st.subheader("运行结果")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("总成本(库存+延期+设置)", f"{metrics.total_cost:.0f} 元")
m2.metric("调度可行率", f"{metrics.feasible_rate:.0%}")
m3.metric("订单准时率", f"{metrics.on_time_rate:.0%}")
m4.metric("加班时长", f"{metrics.total_overtime:.0f} min")
m5.metric("期末欠交", f"{metrics.terminal_backlog:.0f} 件")

tab_overview, tab_period, tab_export = st.tabs(
    ["各周期排程总览", "单周期钻取（甘特/Pareto）", "结果导出"]
)

with tab_overview:
    st.plotly_chart(plan_overview_figure(problem, result), use_container_width=True)
    col_a, col_b = st.columns(2)
    col_a.plotly_chart(cmax_overview_figure(problem, result), use_container_width=True)
    col_b.plotly_chart(state_overview_figure(problem, result), use_container_width=True)
    st.dataframe(
        [{"τ": pr.tau, "k*": pr.k_star,
          **{f"q_{p}": pr.frozen_q.get(p, 0) for p in problem.products},
          "C_max": round(pr.schedule.cmax, 1), "OT": round(pr.schedule.ot, 1),
          "ρ": round(pr.schedule.rho, 3),
          "保护处理": "、".join(f"{p}−{s}" for p, s in pr.protection_events) or "-",
          "O^unfin": "、".join(sorted(pr.unfin_orders)) or "-"}
         for pr in result.periods],
        use_container_width=True,
    )

with tab_period:
    tau = st.select_slider("选择滚动周期 τ", [pr.tau for pr in result.periods])
    pr = result.period(tau)
    if not pr.schedule.operations:
        st.info(f"τ={tau} 无排产工件。")
    else:
        st.plotly_chart(
            gantt_figure(problem, pr.schedule,
                         f"τ={tau} 冻结调度甘特图（C_max={pr.schedule.cmax:.0f}min，"
                         f"ρ={pr.schedule.rho:.2f}）"),
            use_container_width=True,
        )
    final_it = pr.iterations[-1] if pr.iterations else None
    if final_it is not None and final_it.front:
        rep = final_it.representative.solution if final_it.representative else None
        st.plotly_chart(
            pareto_figure(problem, final_it.front, rep,
                          f"τ={tau} 非支配解集（{len(final_it.front)} 解）与代表解"),
            use_container_width=True,
        )
        if len(final_it.front) == 1:
            st.caption("CP-SAT 为单目标精确求解器（min C_max），仅一个解；"
                       "选择 NSGA-II-VNS-MOSA 可得到多解 Pareto 前沿。")
    if pr.iterations:
        st.markdown("**反馈迭代轨迹**")
        st.dataframe(iteration_table_rows(problem, pr), use_container_width=True)

with tab_export:
    out_dir = Path(tempfile.mkdtemp(prefix="ppsched_out_"))
    xlsx = export_all(problem, out_dir, {scheme: result}, {scheme: metrics})
    st.download_button(
        "下载汇总 xlsx（指标 + 逐周期明细）", xlsx.read_bytes(),
        file_name=f"运行结果_方案{scheme}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    detail = out_dir / "表5-4_逐周期明细.csv"
    st.download_button(
        "下载逐周期明细 CSV", detail.read_bytes(),
        file_name=f"逐周期明细_方案{scheme}.csv", mime="text/csv",
    )
