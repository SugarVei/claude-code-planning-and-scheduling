"""Plotly 图表构造（纯函数，供 Streamlit 界面与测试使用）。

配色遵循 dataviz 校验通过的分类色盘（固定顺序、不循环；≤8 系列）；
设置段用中性灰 + 斜纹纹理（次级编码）；单轴原则（C_max 与 OT 同为
分钟量纲，共轴合法）；文本一律用文字色，不用系列色。
"""
from __future__ import annotations

import plotly.graph_objects as go

from src.data.problem_data import ProblemData
from src.rolling.controller import PeriodResult, RollingResult
from src.scheduling.base import ScheduleSolution

# dataviz 参考色盘（已通过六项校验的固定顺序分类色，light 模式）
CATEGORICAL = ["#2a78d6", "#008300", "#e87ba4", "#eda100", "#1baf7a", "#eb6834",
               "#4a3aa7", "#e34948"]
SETUP_GRAY = "#9a9890"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e8e7e3"
STATUS_SERIOUS = "#e34948"

_LAYOUT = dict(
    plot_bgcolor="#fcfcfb",
    paper_bgcolor="#fcfcfb",
    font=dict(color=TEXT_PRIMARY, size=13),
    margin=dict(l=60, r=30, t=48, b=48),
)


def family_colors(problem: ProblemData) -> dict[str, str]:
    """产品族 → 分类色（按 products 固定顺序分配，不循环）。"""
    if len(problem.products) > len(CATEGORICAL):
        raise ValueError("产品族数超过色盘容量（>8），请折叠或分面")
    return {p: CATEGORICAL[i] for i, p in enumerate(problem.products)}


def gantt_figure(
    problem: ProblemData, schedule: ScheduleSolution, title: str
) -> go.Figure:
    """单周期机器甘特图：设置段（灰、斜纹）+ 加工段（族色）；T^avail 参考线。"""
    colors = family_colors(problem)
    machines = [
        f"{problem.stage_names[j]}·{m}"
        for j in problem.stages
        for m in problem.machines[j]
    ]
    fig = go.Figure()
    # 零宽占位：让空闲机器也显示行（用户可见哪台机器未被使用）
    fig.add_trace(go.Bar(
        y=machines, x=[0] * len(machines), orientation="h",
        marker=dict(color="rgba(0,0,0,0)"), showlegend=False, hoverinfo="skip",
    ))
    family_rank = {p: i for i, p in enumerate(problem.products)}
    seen_families: set[str] = set()
    setup_in_legend = False
    for op in schedule.operations:
        y = f"{problem.stage_names[op.stage]}·{op.machine}"
        if op.setup_time > 0:
            fig.add_trace(go.Bar(
                y=[y], x=[op.setup_time], base=[op.start], orientation="h",
                marker=dict(color=SETUP_GRAY, opacity=0.55,
                            pattern=dict(shape="/", fgcolor="#fcfcfb", size=5)),
                width=0.55, name="设置/换模", legendgroup="setup",
                legendrank=1100, showlegend=not setup_in_legend,
                hovertemplate=(f"{op.job_id} 设置 %{{x:.0f}}min"
                               f"<br>{y}<extra></extra>"),
            ))
            setup_in_legend = True
        fig.add_trace(go.Bar(
            y=[y], x=[op.end - op.setup_end], base=[op.setup_end], orientation="h",
            marker=dict(color=colors[op.product],
                        line=dict(color="#fcfcfb", width=1)),
            width=0.55, name=op.product, legendgroup=op.product,
            legendrank=1000 + family_rank[op.product],
            showlegend=op.product not in seen_families,
            hovertemplate=(
                f"{op.job_id}（{op.product}）加工 %{{x:.0f}}min"
                f"<br>{y}｜档位 s={op.gear}｜工人 α={op.skill}"
                f"<br>开工 {op.setup_end:.0f} → 完工 {op.end:.0f}<extra></extra>"
            ),
        ))
        seen_families.add(op.product)
    fig.add_vline(x=problem.t_avail, line_dash="dash", line_color=TEXT_SECONDARY,
                  annotation_text=f"T^avail={problem.t_avail:.0f}",
                  annotation_font_color=TEXT_SECONDARY)
    if schedule.cmax > problem.t_avail:
        fig.add_vline(x=problem.t_avail + problem.ot_max, line_dash="dot",
                      line_color=STATUS_SERIOUS,
                      annotation_text="加班上限",
                      annotation_font_color=STATUS_SERIOUS)
    fig.update_layout(
        **_LAYOUT, title=title, barmode="overlay",
        xaxis=dict(title="时间（min）", gridcolor=GRID, zeroline=False),
        yaxis=dict(categoryorder="array", categoryarray=machines[::-1], title=""),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        height=max(320, 60 * len(machines)),
    )
    return fig


def pareto_figure(
    problem: ProblemData,
    front: list[ScheduleSolution],
    representative: ScheduleSolution | None,
    title: str,
) -> go.Figure:
    """Pareto 解集三目标两两投影（C_max–LC、C_max–E、LC–E），代表解高亮。"""
    from plotly.subplots import make_subplots

    pairs = [("cmax", "lc", "C_max（min）", "LC（元）"),
             ("cmax", "energy", "C_max（min）", "E（kW·min）"),
             ("lc", "energy", "LC（元）", "E（kW·min）")]
    fig = make_subplots(rows=1, cols=3, horizontal_spacing=0.09)
    for i, (ax, ay, lx, ly) in enumerate(pairs, start=1):
        fig.add_trace(go.Scatter(
            x=[getattr(s, ax) for s in front],
            y=[getattr(s, ay) for s in front],
            mode="markers", name="非支配解",
            marker=dict(size=9, color=CATEGORICAL[0], opacity=0.75,
                        line=dict(color="#fcfcfb", width=1)),
            showlegend=(i == 1),
            hovertemplate=f"{lx}=%{{x:.1f}}<br>{ly}=%{{y:.1f}}<extra></extra>",
        ), row=1, col=i)
        if representative is not None:
            fig.add_trace(go.Scatter(
                x=[getattr(representative, ax)], y=[getattr(representative, ay)],
                mode="markers", name="代表解 π*",
                marker=dict(size=15, symbol="star", color=CATEGORICAL[3],
                            line=dict(color=TEXT_PRIMARY, width=1)),
                showlegend=(i == 1),
                hovertemplate=f"π*：{lx}=%{{x:.1f}}<br>{ly}=%{{y:.1f}}<extra></extra>",
            ), row=1, col=i)
        fig.update_xaxes(title_text=lx, gridcolor=GRID, row=1, col=i)
        fig.update_yaxes(title_text=ly, gridcolor=GRID, row=1, col=i)
    fig.update_layout(**_LAYOUT, title=title, height=360,
                      legend=dict(orientation="h", yanchor="bottom", y=1.06))
    return fig


def plan_overview_figure(problem: ProblemData, result: RollingResult) -> go.Figure:
    """各周期排程总览：冻结产量 q_{p,τ} 堆叠柱（族色，2px 表面间隔）。"""
    colors = family_colors(problem)
    taus = [pr.tau for pr in result.periods]
    fig = go.Figure()
    for p in problem.products:
        fig.add_trace(go.Bar(
            x=taus, y=[pr.frozen_q.get(p, 0) for pr in result.periods],
            name=p, marker=dict(color=colors[p],
                                line=dict(color="#fcfcfb", width=2)),
            hovertemplate=f"τ=%{{x}}｜{p}：%{{y}} 件<extra></extra>",
        ))
    fig.update_layout(
        **_LAYOUT, barmode="stack", title="各周期冻结产量计划 q<sub>p,τ</sub>",
        xaxis=dict(title="滚动周期 τ", dtick=1, gridcolor=GRID),
        yaxis=dict(title="产量（件）", gridcolor=GRID),
        legend=dict(orientation="h", yanchor="bottom", y=1.02), height=380,
    )
    return fig


def cmax_overview_figure(problem: ProblemData, result: RollingResult) -> go.Figure:
    """各周期 C_max 与加班（同为分钟量纲，共轴）+ T^avail/加班上限参考线。"""
    taus = [pr.tau for pr in result.periods]
    cmax = [pr.schedule.cmax for pr in result.periods]
    ot = [pr.schedule.ot for pr in result.periods]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=taus, y=ot, name="加班 OT", width=0.45,
        marker=dict(color=CATEGORICAL[5], line=dict(color="#fcfcfb", width=1)),
        hovertemplate="τ=%{x}｜OT=%{y:.0f}min<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=taus, y=cmax, name="C_max", mode="lines+markers",
        line=dict(color=CATEGORICAL[0], width=2), marker=dict(size=8),
        hovertemplate="τ=%{x}｜C_max=%{y:.0f}min<extra></extra>",
    ))
    fig.add_hline(y=problem.t_avail, line_dash="dash", line_color=TEXT_SECONDARY,
                  annotation_text="T^avail", annotation_font_color=TEXT_SECONDARY)
    fig.add_hline(y=problem.t_avail + problem.ot_max, line_dash="dot",
                  line_color=STATUS_SERIOUS, annotation_text="可接受上限",
                  annotation_font_color=STATUS_SERIOUS)
    fig.update_layout(
        **_LAYOUT, title="各周期完工时间与加班（min）",
        xaxis=dict(title="滚动周期 τ", dtick=1, gridcolor=GRID),
        yaxis=dict(title="分钟", gridcolor=GRID),
        legend=dict(orientation="h", yanchor="bottom", y=1.02), height=380,
    )
    return fig


def state_overview_figure(problem: ProblemData, result: RollingResult) -> go.Figure:
    """各周期期末库存/欠交总量（欠交取负向，双向柱）。"""
    taus = [pr.tau for pr in result.periods]
    inv = [sum(pr.inv_after.values()) for pr in result.periods]
    back = [-sum(pr.back_after.values()) for pr in result.periods]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=taus, y=inv, name="库存", width=0.45,
        marker=dict(color=CATEGORICAL[4], line=dict(color="#fcfcfb", width=1)),
        hovertemplate="τ=%{x}｜库存 %{y:.0f} 件<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=taus, y=back, name="欠交", width=0.45,
        marker=dict(color=CATEGORICAL[7], line=dict(color="#fcfcfb", width=1)),
        hovertemplate="τ=%{x}｜欠交 %{customdata:.0f} 件<extra></extra>",
        customdata=[-b for b in back],
    ))
    fig.add_hline(y=0, line_color=TEXT_SECONDARY, line_width=1)
    fig.update_layout(
        **_LAYOUT, barmode="relative", title="各周期期末状态（库存↑ / 欠交↓）",
        xaxis=dict(title="滚动周期 τ", dtick=1, gridcolor=GRID),
        yaxis=dict(title="件", gridcolor=GRID),
        legend=dict(orientation="h", yanchor="bottom", y=1.02), height=340,
    )
    return fig


def iteration_table_rows(problem: ProblemData, pr: PeriodResult) -> list[dict]:
    """单周期反馈迭代轨迹（表格数据）。"""
    rows = []
    for it in pr.iterations:
        cut = "-"
        if it.cut_decision is not None:
            cut = it.cut_decision.reason
            if it.cut_decision.generated:
                cut += "→割" + "{" + ",".join(sorted(it.cut_decision.combo)) + "}"
        rows.append({
            "k": it.k,
            "计划 q_τ": ", ".join(f"{p}:{q}" for p, q in it.q_tau.items() if q),
            "C_max": round(it.schedule.cmax, 1),
            "OT": round(it.schedule.ot, 1),
            "ρ": round(it.schedule.rho, 3),
            "Feas": it.feas,
            "割判据": cut,
            "冻结": "✓" if it.freeze.frozen else "",
        })
    return rows
