"""matplotlib 图表构造（桌面版界面用；配色与 app/plots.py 同一色盘）。"""
from __future__ import annotations

import matplotlib
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from app.plots import CATEGORICAL, GRID, SETUP_GRAY, STATUS_SERIOUS, TEXT_SECONDARY, family_colors
from src.data.problem_data import ProblemData
from src.rolling.controller import RollingResult
from src.scheduling.base import ScheduleSolution

matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "WenQuanYi Zen Hei", "sans-serif",
]
matplotlib.rcParams["axes.unicode_minus"] = False


def _style_axes(ax):
    ax.grid(True, color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def gantt_figure(problem: ProblemData, schedule: ScheduleSolution, title: str) -> Figure:
    """单周期机器甘特图：设置段（灰斜纹）+ 加工段（族色）+ 参考线。"""
    colors = family_colors(problem)
    machines = [
        f"{problem.stage_names[j]}·{m}"
        for j in problem.stages
        for m in problem.machines[j]
    ][::-1]
    y_of = {name: i for i, name in enumerate(machines)}
    fig = Figure(figsize=(9, max(3.2, 0.55 * len(machines) + 1.2)), dpi=100)
    ax = fig.add_subplot(111)
    for op in schedule.operations:
        y = y_of[f"{problem.stage_names[op.stage]}·{op.machine}"]
        if op.setup_time > 0:
            ax.barh(y, op.setup_time, left=op.start, height=0.55,
                    color=SETUP_GRAY, alpha=0.55, hatch="///",
                    edgecolor="white", linewidth=0.8, zorder=2)
        ax.barh(y, op.end - op.setup_end, left=op.setup_end, height=0.55,
                color=colors[op.product], edgecolor="white", linewidth=0.8, zorder=3)
        width = op.end - op.setup_end
        if width >= 25:  # 选择性直接标注（避免小段文字挤压）
            ax.text(op.setup_end + width / 2, y, op.job_id, ha="center",
                    va="center", fontsize=8, color="white", zorder=4)
    ax.axvline(problem.t_avail, linestyle="--", color=TEXT_SECONDARY, linewidth=1.2)
    ax.text(problem.t_avail, len(machines) - 0.3, f" T^avail={problem.t_avail:.0f}",
            color=TEXT_SECONDARY, fontsize=9, va="bottom")
    if schedule.cmax > problem.t_avail:
        ax.axvline(problem.t_avail + problem.ot_max, linestyle=":",
                   color=STATUS_SERIOUS, linewidth=1.2)
    ax.set_yticks(range(len(machines)))
    ax.set_yticklabels(machines)
    ax.set_xlabel("时间（min）")
    ax.set_title(title, fontsize=11)
    _style_axes(ax)
    handles = [Patch(facecolor=colors[p], label=p) for p in problem.products
               if any(op.product == p for op in schedule.operations)]
    handles.append(Patch(facecolor=SETUP_GRAY, alpha=0.55, hatch="///", label="设置/换模"))
    ax.legend(handles=handles, loc="lower right", fontsize=8, ncol=len(handles))
    fig.tight_layout()
    return fig


def pareto_figure(problem: ProblemData, front: list[ScheduleSolution],
                  representative: ScheduleSolution | None, title: str) -> Figure:
    """Pareto 解集三目标两两投影，代表解 π* 星标。"""
    pairs = [("cmax", "lc", "C_max（min）", "LC（元）"),
             ("cmax", "energy", "C_max（min）", "E（kW·min）"),
             ("lc", "energy", "LC（元）", "E（kW·min）")]
    fig = Figure(figsize=(10, 3.4), dpi=100)
    for i, (ax_attr, ay_attr, lx, ly) in enumerate(pairs, start=1):
        ax = fig.add_subplot(1, 3, i)
        ax.scatter([getattr(s, ax_attr) for s in front],
                   [getattr(s, ay_attr) for s in front],
                   s=42, color=CATEGORICAL[0], alpha=0.75,
                   edgecolors="white", linewidths=0.8, zorder=3, label="非支配解")
        if representative is not None:
            ax.scatter([getattr(representative, ax_attr)],
                       [getattr(representative, ay_attr)],
                       s=170, marker="*", color=CATEGORICAL[3],
                       edgecolors="black", linewidths=0.6, zorder=4, label="代表解 π*")
        ax.set_xlabel(lx, fontsize=9)
        ax.set_ylabel(ly, fontsize=9)
        ax.tick_params(labelsize=8)
        _style_axes(ax)
        if i == 1:
            ax.legend(fontsize=8, loc="best")
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    return fig


def overview_figure(problem: ProblemData, result: RollingResult) -> Figure:
    """总览三联图：冻结产量堆叠柱 / C_max与OT / 期末库存欠交。"""
    colors = family_colors(problem)
    taus = [pr.tau for pr in result.periods]
    fig = Figure(figsize=(10, 8.6), dpi=100)

    ax1 = fig.add_subplot(311)
    bottom = [0.0] * len(taus)
    for p in problem.products:
        vals = [pr.frozen_q.get(p, 0) for pr in result.periods]
        ax1.bar(taus, vals, bottom=bottom, label=p, color=colors[p],
                edgecolor="white", linewidth=1.5, zorder=3)
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax1.set_title("各周期冻结产量计划 q_{p,τ}", fontsize=11)
    ax1.set_ylabel("产量（件）")
    ax1.legend(fontsize=8, ncol=min(6, len(problem.products)))
    _style_axes(ax1)

    ax2 = fig.add_subplot(312)
    ax2.bar(taus, [pr.schedule.ot for pr in result.periods], width=0.45,
            color=CATEGORICAL[5], edgecolor="white", label="加班 OT", zorder=3)
    ax2.plot(taus, [pr.schedule.cmax for pr in result.periods], "-o",
             color=CATEGORICAL[0], linewidth=2, markersize=6, label="C_max", zorder=4)
    ax2.axhline(problem.t_avail, linestyle="--", color=TEXT_SECONDARY, linewidth=1.2)
    ax2.axhline(problem.t_avail + problem.ot_max, linestyle=":",
                color=STATUS_SERIOUS, linewidth=1.2)
    ax2.set_title("各周期完工时间与加班（min；虚线 T^avail，点线可接受上限）", fontsize=11)
    ax2.set_ylabel("分钟")
    ax2.legend(fontsize=8)
    _style_axes(ax2)

    ax3 = fig.add_subplot(313)
    ax3.bar(taus, [sum(pr.inv_after.values()) for pr in result.periods], width=0.45,
            color=CATEGORICAL[4], edgecolor="white", label="库存", zorder=3)
    ax3.bar(taus, [-sum(pr.back_after.values()) for pr in result.periods], width=0.45,
            color=CATEGORICAL[7], edgecolor="white", label="欠交", zorder=3)
    ax3.axhline(0, color=TEXT_SECONDARY, linewidth=1)
    ax3.set_title("各周期期末状态（库存↑ / 欠交↓）", fontsize=11)
    ax3.set_xlabel("滚动周期 τ")
    ax3.set_ylabel("件")
    ax3.legend(fontsize=8)
    _style_axes(ax3)
    for ax in (ax1, ax2, ax3):
        ax.set_xticks(taus)
    fig.tight_layout()
    return fig
