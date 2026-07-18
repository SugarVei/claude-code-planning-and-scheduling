"""集成生产计划与调度系统 —— 桌面版界面（PyQt5，与论文配套算法程序同风格）。

启动（仓库根目录）：python -m app.desktop
布局沿用配套算法程序的设计语言（app/qt_styles.py 即其 ui/styles.py）：
左侧参数面板（数据导入/方案配置/运行）+ 右侧结果标签页
（总览图表 / 单周期甘特与 Pareto / 逐周期明细 / 导出），
求解在 QThread 后台执行，界面不冻结。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from app import mpl_plots
from app.qt_styles import COLORS, MAIN_STYLESHEET
from src.cli import load_problem
from src.experiments.report import export_all
from src.experiments.runner import compute_metrics
from src.experiments.schemes import run_scheme
from src.scheduling.exact_cpsat import CpSatScheduler
from src.scheduling.meta_vendor import VendorNsgaScheduler

SCHEME_LABELS = {
    "A": "A 传统两阶段（无反馈）", "B": "B 滚动无反馈",
    "C": "C 完整三通道（本文机制）", "D": "D 去成本修正（消融）",
}


class RollingWorker(QThread):
    """后台运行滚动闭环（界面不冻结）。"""

    finished_ok = pyqtSignal(object, object)  # result, metrics
    failed = pyqtSignal(str)

    def __init__(self, problem, scheduler, scheme, seed):
        super().__init__()
        self.problem, self.scheduler = problem, scheduler
        self.scheme, self.seed = scheme, seed

    def run(self):
        try:
            result = run_scheme(self.problem, self.scheduler, self.scheme, self.seed)
            metrics = compute_metrics(self.problem, result, f"方案{self.scheme}")
            self.finished_ok.emit(result, metrics)
        except Exception as exc:  # 界面必须收到失败信号而非静默崩溃
            self.failed.emit(str(exc))


def _metric_card(title: str) -> tuple[QGroupBox, QLabel]:
    box = QGroupBox(title)
    lay = QVBoxLayout(box)
    value = QLabel("—")
    value.setStyleSheet(
        f"font-size: 20px; font-weight: 700; color: {COLORS['primary']}; border: none;"
    )
    value.setAlignment(Qt.AlignCenter)
    lay.addWidget(value)
    return box, value


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("集成生产计划与调度系统（滚动时域闭环）")
        self.resize(1480, 920)
        self.problem = None
        self.result = None
        self.metrics = None
        self.worker = None

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_input_panel())
        splitter.addWidget(self._build_result_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([360, 1120])
        self.setCentralWidget(splitter)

    # ── 左侧：参数面板 ──
    def _build_input_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)

        box_data = QGroupBox("① 导入数据")
        dl = QVBoxLayout(box_data)
        self.btn_open = QPushButton("浏览 Excel 文件…")
        self.btn_open.clicked.connect(self._choose_file)
        dl.addWidget(self.btn_open)
        dl.addWidget(QLabel("或选择内置数据集："))
        self.combo_builtin = QComboBox()
        self.combo_builtin.addItems([
            "（不使用内置数据）",
            "示例数据集（Y企业风格，10 周期）",
            "V-toy-1 金标算例（4 周期）",
        ])
        self.combo_builtin.currentIndexChanged.connect(self._choose_builtin)
        dl.addWidget(self.combo_builtin)
        self.lbl_data = QLabel("尚未导入数据")
        self.lbl_data.setWordWrap(True)
        dl.addWidget(self.lbl_data)
        lay.addWidget(box_data)

        box_cfg = QGroupBox("② 运行配置")
        cl = QVBoxLayout(box_cfg)
        cl.addWidget(QLabel("实验方案："))
        self.combo_scheme = QComboBox()
        for code, label in SCHEME_LABELS.items():
            self.combo_scheme.addItem(label, code)
        self.combo_scheme.setCurrentIndex(2)
        cl.addWidget(self.combo_scheme)
        cl.addWidget(QLabel("调度求解器："))
        self.combo_solver = QComboBox()
        self.combo_solver.addItem("CP-SAT（快，确定性）", "cpsat")
        self.combo_solver.addItem("NSGA-II-VNS-MOSA（论文算法，慢）", "vendor")
        cl.addWidget(self.combo_solver)
        row = QHBoxLayout()
        row.addWidget(QLabel("CP-SAT 时限(s)："))
        self.spin_limit = QDoubleSpinBox()
        self.spin_limit.setRange(1, 300)
        self.spin_limit.setValue(3)
        row.addWidget(self.spin_limit)
        row.addWidget(QLabel("种子："))
        self.spin_seed = QSpinBox()
        self.spin_seed.setRange(0, 9999)
        row.addWidget(self.spin_seed)
        cl.addLayout(row)
        lay.addWidget(box_cfg)

        self.btn_run = QPushButton("③ 运行闭环")
        self.btn_run.setObjectName("primaryButton")
        self.btn_run.setMinimumHeight(40)
        self.btn_run.clicked.connect(self._run)
        self.btn_run.setEnabled(False)
        lay.addWidget(self.btn_run)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)
        lay.addStretch(1)
        return panel

    # ── 右侧：结果标签页 ──
    def _build_result_panel(self) -> QWidget:
        self.tabs = QTabWidget()

        cards = QHBoxLayout()
        self.card_values = {}
        for key, title in [("cost", "总成本(库存+延期+设置)"), ("feas", "调度可行率"),
                           ("ontime", "订单准时率"), ("ot", "加班时长"),
                           ("back", "期末欠交")]:
            box, value = _metric_card(title)
            self.card_values[key] = value
            cards.addWidget(box)

        self.overview_area = QScrollArea()
        self.overview_area.setWidgetResizable(True)
        tab1 = QWidget()
        t1 = QVBoxLayout(tab1)
        t1.addLayout(cards)
        t1.addWidget(self.overview_area)
        self.tabs.addTab(tab1, "各周期排程总览")

        tab2 = QWidget()
        t2 = QVBoxLayout(tab2)
        row = QHBoxLayout()
        row.addWidget(QLabel("选择滚动周期 τ："))
        self.combo_tau = QComboBox()
        self.combo_tau.currentIndexChanged.connect(self._show_period)
        row.addWidget(self.combo_tau)
        row.addStretch(1)
        t2.addLayout(row)
        self.period_area = QScrollArea()
        self.period_area.setWidgetResizable(True)
        t2.addWidget(self.period_area)
        self.tabs.addTab(tab2, "单周期钻取（甘特/Pareto）")

        self.table_detail = QTableWidget()
        self.tabs.addTab(self.table_detail, "逐周期明细")

        tab4 = QWidget()
        t4 = QVBoxLayout(tab4)
        self.btn_export = QPushButton("导出结果（xlsx + CSV）…")
        self.btn_export.clicked.connect(self._export)
        self.btn_export.setEnabled(False)
        t4.addWidget(self.btn_export)
        t4.addStretch(1)
        self.tabs.addTab(tab4, "结果导出")
        return self.tabs

    # ── 事件 ──
    def _choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择数据工作簿", str(REPO_ROOT / "data"), "Excel (*.xlsx)")
        if path:
            self.combo_builtin.setCurrentIndex(0)
            self._load(path)

    def _choose_builtin(self, index: int):
        paths = {1: REPO_ROOT / "data" / "sample_y_style.xlsx",
                 2: REPO_ROOT / "data" / "vtoy1.xlsx"}
        if index in paths:
            self._load(paths[index])

    def _load(self, path):
        try:
            self.problem = load_problem(path)
        except (SystemExit, ValueError) as exc:
            QMessageBox.critical(self, "数据读入失败", str(exc))
            return
        p = self.problem
        self.lbl_data.setText(
            f"✔ {Path(path).name}\n产品族 {len(p.products)}｜阶段 {len(p.stages)}｜"
            f"机器 {sum(len(m) for m in p.machines.values())}｜"
            f"周期 {len(p.periods)}｜订单 {len(p.orders)}"
        )
        self.btn_run.setEnabled(True)

    def _run(self):
        solver = (CpSatScheduler(self.spin_limit.value(), require_optimal=False)
                  if self.combo_solver.currentData() == "cpsat"
                  else VendorNsgaScheduler())
        scheme = self.combo_scheme.currentData()
        self.btn_run.setEnabled(False)
        self.lbl_status.setText(f"方案 {scheme} 运行中，请稍候…（周期数 "
                                f"{len(self.problem.periods)}）")
        self.worker = RollingWorker(self.problem, solver, scheme,
                                    self.spin_seed.value())
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_failed(self, message: str):
        self.btn_run.setEnabled(True)
        self.lbl_status.setText("")
        QMessageBox.critical(self, "运行失败", message)

    def _on_done(self, result, metrics):
        self.result, self.metrics = result, metrics
        self.btn_run.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.lbl_status.setText("✔ 运行完成")
        m = metrics
        self.card_values["cost"].setText(f"{m.total_cost:.0f} 元")
        self.card_values["feas"].setText(f"{m.feasible_rate:.0%}")
        self.card_values["ontime"].setText(f"{m.on_time_rate:.0%}")
        self.card_values["ot"].setText(f"{m.total_overtime:.0f} min")
        self.card_values["back"].setText(f"{m.terminal_backlog:.0f} 件")

        self.overview_area.setWidget(
            FigureCanvas(mpl_plots.overview_figure(self.problem, result)))
        self.combo_tau.blockSignals(True)
        self.combo_tau.clear()
        self.combo_tau.addItems([f"τ={pr.tau}" for pr in result.periods])
        self.combo_tau.blockSignals(False)
        self._show_period(0)
        self._fill_detail_table()

    def _show_period(self, index: int):
        if self.result is None or index < 0:
            return
        pr = self.result.periods[index]
        container = QWidget()
        lay = QVBoxLayout(container)
        if pr.schedule.operations:
            lay.addWidget(FigureCanvas(mpl_plots.gantt_figure(
                self.problem, pr.schedule,
                f"τ={pr.tau} 冻结调度甘特图（C_max={pr.schedule.cmax:.0f}min，"
                f"ρ={pr.schedule.rho:.2f}）")))
        else:
            lay.addWidget(QLabel(f"τ={pr.tau} 无排产工件"))
        final_it = pr.iterations[-1] if pr.iterations else None
        if final_it is not None and final_it.front:
            rep = (final_it.representative.solution
                   if final_it.representative else None)
            lay.addWidget(FigureCanvas(mpl_plots.pareto_figure(
                self.problem, final_it.front, rep,
                f"τ={pr.tau} 非支配解集（{len(final_it.front)} 解）与代表解")))
            if len(final_it.front) == 1:
                tip = QLabel("提示：CP-SAT 为单目标精确求解（min C_max），仅 1 个解；"
                             "选 NSGA-II-VNS-MOSA 可得多解 Pareto 前沿。")
                tip.setWordWrap(True)
                lay.addWidget(tip)
        lay.addStretch(1)
        self.period_area.setWidget(container)

    def _fill_detail_table(self):
        p, result = self.problem, self.result
        headers = (["τ", "k*"] + [f"q_{x}" for x in p.products]
                   + ["C_max", "OT", "ρ", "保护处理", "O^unfin"])
        self.table_detail.setColumnCount(len(headers))
        self.table_detail.setHorizontalHeaderLabels(headers)
        self.table_detail.setRowCount(len(result.periods))
        for r, pr in enumerate(result.periods):
            vals = ([pr.tau, pr.k_star] + [pr.frozen_q.get(x, 0) for x in p.products]
                    + [f"{pr.schedule.cmax:.1f}", f"{pr.schedule.ot:.1f}",
                       f"{pr.schedule.rho:.3f}",
                       "、".join(f"{a}−{b}" for a, b in pr.protection_events) or "-",
                       "、".join(sorted(pr.unfin_orders)) or "-"])
            for c, v in enumerate(vals):
                self.table_detail.setItem(r, c, QTableWidgetItem(str(v)))
        self.table_detail.resizeColumnsToContents()

    def _export(self):
        out = QFileDialog.getExistingDirectory(self, "选择导出目录", str(REPO_ROOT))
        if not out:
            return
        scheme = self.combo_scheme.currentData()
        xlsx = export_all(self.problem, out, {scheme: self.result},
                          {scheme: self.metrics})
        QMessageBox.information(self, "导出完成", f"已导出：\n{xlsx}")


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(MAIN_STYLESHEET)
    win = MainWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
