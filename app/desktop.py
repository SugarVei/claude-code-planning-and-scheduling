"""集成生产计划与调度系统 —— 桌面版界面（PyQt5）。

版式对齐论文配套算法程序（其 ui_screenshot.png / main_app 风格）：
顶部深色标题横幅 → 彩色渐变操作按钮 → 绿色数据概览卡片 → 蓝色参数
表单卡片 → 底部绿色"运行"/橙色"导出"按钮 → 全宽状态条；
运行完成后弹出独立结果窗口（总览 / 单周期甘特与 Pareto / 逐周期明细），
样式表复用其 ui/styles.py（app/qt_styles.py）。
启动：python -m app.desktop
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
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

EXTRA_QSS = f"""
QLabel#banner {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #263238, stop:1 #546E7A);
    color: white; font-size: 20px; font-weight: 700;
    border-radius: 12px; padding: 18px 24px;
}}
QPushButton#btnBlue {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #1E88E5, stop:1 #42A5F5);
    color: white; font-size: 14px; font-weight: 600;
    border: none; border-radius: 10px; padding: 12px 26px;
}}
QPushButton#btnPurple {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #8E24AA, stop:1 #AB47BC);
    color: white; font-size: 14px; font-weight: 600;
    border: none; border-radius: 10px; padding: 12px 26px;
}}
QPushButton#btnGreen {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #2E7D32, stop:1 #43A047);
    color: white; font-size: 15px; font-weight: 700;
    border: none; border-radius: 10px; padding: 14px 30px;
}}
QPushButton#btnOrange {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #EF6C00, stop:1 #FB8C00);
    color: white; font-size: 15px; font-weight: 700;
    border: none; border-radius: 10px; padding: 14px 30px;
}}
QPushButton#btnBlue:disabled, QPushButton#btnPurple:disabled,
QPushButton#btnGreen:disabled, QPushButton#btnOrange:disabled {{
    background: #B0BEC5;
}}
QFrame#cardGreen {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #E8F5E9, stop:1 #DCEDC8);
    border: 1px solid {COLORS['border']}; border-radius: 12px;
}}
QFrame#cardBlue {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #E3F2FD, stop:1 #E1F5FE);
    border: 1px solid {COLORS['border']}; border-radius: 12px;
}}
QLabel#cardTitle {{
    font-size: 15px; font-weight: 700; color: {COLORS['text_primary']};
    background: transparent; border: none;
}}
QLabel#statusBar {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #2E7D32, stop:1 #66BB6A);
    color: white; font-size: 14px; font-weight: 600;
    border-radius: 10px; padding: 12px 20px;
}}
QFrame#cardGreen QLabel, QFrame#cardBlue QLabel {{
    background: transparent; border: none;
}}
QComboBox, QDoubleSpinBox, QSpinBox {{ background: white; }}
"""


class RollingWorker(QThread):
    """后台运行滚动闭环（界面不冻结）。"""

    finished_ok = pyqtSignal(object, object)
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
        except Exception as exc:
            self.failed.emit(str(exc))


class ResultWindow(QMainWindow):
    """独立结果窗口（与配套算法程序的 ResultWindow 模式一致）。"""

    def __init__(self, problem, result, metrics, scheme: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"运行结果 —— 方案{scheme}")
        self.resize(1280, 860)
        self.problem, self.result = problem, result
        tabs = QTabWidget()

        # 总览页：指标卡片 + 三联图
        tab1 = QWidget()
        t1 = QVBoxLayout(tab1)
        cards = QHBoxLayout()
        for title, value in [
            ("总成本(库存+延期+设置)", f"{metrics.total_cost:.0f} 元"),
            ("调度可行率", f"{metrics.feasible_rate:.0%}"),
            ("订单准时率", f"{metrics.on_time_rate:.0%}"),
            ("加班时长", f"{metrics.total_overtime:.0f} min"),
            ("期末欠交", f"{metrics.terminal_backlog:.0f} 件"),
        ]:
            card = QFrame()
            card.setObjectName("cardBlue")
            cl = QVBoxLayout(card)
            lbl_t = QLabel(title)
            lbl_t.setAlignment(Qt.AlignCenter)
            lbl_v = QLabel(value)
            lbl_v.setAlignment(Qt.AlignCenter)
            lbl_v.setStyleSheet(
                f"font-size: 19px; font-weight: 700; color: {COLORS['primary']};"
            )
            cl.addWidget(lbl_t)
            cl.addWidget(lbl_v)
            cards.addWidget(card)
        t1.addLayout(cards)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(FigureCanvas(mpl_plots.overview_figure(problem, result)))
        t1.addWidget(area)
        tabs.addTab(tab1, "各周期排程总览")

        # 单周期钻取页
        tab2 = QWidget()
        t2 = QVBoxLayout(tab2)
        row = QHBoxLayout()
        row.addWidget(QLabel("选择滚动周期 τ："))
        self.combo_tau = QComboBox()
        self.combo_tau.addItems([f"τ={pr.tau}" for pr in result.periods])
        self.combo_tau.currentIndexChanged.connect(self._show_period)
        row.addWidget(self.combo_tau)
        row.addStretch(1)
        t2.addLayout(row)
        self.period_area = QScrollArea()
        self.period_area.setWidgetResizable(True)
        t2.addWidget(self.period_area)
        tabs.addTab(tab2, "单周期钻取（甘特/Pareto）")

        # 逐周期明细页
        table = QTableWidget()
        headers = (["τ", "k*"] + [f"q_{x}" for x in problem.products]
                   + ["C_max", "OT", "ρ", "保护处理", "O^unfin"])
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(result.periods))
        for r, pr in enumerate(result.periods):
            vals = ([pr.tau, pr.k_star]
                    + [pr.frozen_q.get(x, 0) for x in problem.products]
                    + [f"{pr.schedule.cmax:.1f}", f"{pr.schedule.ot:.1f}",
                       f"{pr.schedule.rho:.3f}",
                       "、".join(f"{a}−{b}" for a, b in pr.protection_events) or "-",
                       "、".join(sorted(pr.unfin_orders)) or "-"])
            for c, v in enumerate(vals):
                table.setItem(r, c, QTableWidgetItem(str(v)))
        table.resizeColumnsToContents()
        tabs.addTab(table, "逐周期明细")

        self.setCentralWidget(tabs)
        self._show_period(0)

    def _show_period(self, index: int):
        if index < 0:
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


class MainWindow(QMainWindow):
    """主窗口：方案确定页（垂直大卡片版式，对齐配套算法程序）。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("集成生产计划与调度系统")
        self.resize(1000, 780)
        self.problem = None
        self.result = None
        self.metrics = None
        self.scheme_used = "C"
        self.worker = None
        self.result_windows: list[ResultWindow] = []

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        banner = QLabel("集成生产计划与调度系统 —— 滚动时域闭环优化")
        banner.setObjectName("banner")
        banner.setAlignment(Qt.AlignCenter)
        lay.addWidget(banner)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_open = QPushButton("📂 浏览 Excel 数据…")
        self.btn_open.setObjectName("btnBlue")
        self.btn_open.clicked.connect(self._choose_file)
        btn_row.addWidget(self.btn_open)
        self.btn_builtin = QPushButton("📦 使用内置数据集")
        self.btn_builtin.setObjectName("btnPurple")
        self.btn_builtin.clicked.connect(self._builtin_menu)
        btn_row.addWidget(self.btn_builtin)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        card_data = QFrame()
        card_data.setObjectName("cardGreen")
        dl = QVBoxLayout(card_data)
        title1 = QLabel("① 数据概览")
        title1.setObjectName("cardTitle")
        dl.addWidget(title1)
        self.lbl_data = QLabel("尚未导入数据 —— 请点击上方按钮导入 Excel"
                               "（V-toy-1 / Y企业模板格式自动识别）")
        self.lbl_data.setWordWrap(True)
        dl.addWidget(self.lbl_data)
        lay.addWidget(card_data)

        card_cfg = QFrame()
        card_cfg.setObjectName("cardBlue")
        cl = QVBoxLayout(card_cfg)
        title2 = QLabel("② 方案与算法参数")
        title2.setObjectName("cardTitle")
        cl.addWidget(title2)
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        grid.addWidget(QLabel("实验方案："), 0, 0)
        self.combo_scheme = QComboBox()
        for code, label in SCHEME_LABELS.items():
            self.combo_scheme.addItem(label, code)
        self.combo_scheme.setCurrentIndex(2)
        grid.addWidget(self.combo_scheme, 0, 1)
        grid.addWidget(QLabel("调度求解器："), 1, 0)
        self.combo_solver = QComboBox()
        self.combo_solver.addItem("CP-SAT（快，确定性）", "cpsat")
        self.combo_solver.addItem("NSGA-II-VNS-MOSA（论文算法，慢）", "vendor")
        grid.addWidget(self.combo_solver, 1, 1)
        grid.addWidget(QLabel("CP-SAT 单次时限（秒）："), 2, 0)
        self.spin_limit = QDoubleSpinBox()
        self.spin_limit.setRange(1, 300)
        self.spin_limit.setValue(3)
        grid.addWidget(self.spin_limit, 2, 1)
        grid.addWidget(QLabel("随机种子："), 3, 0)
        self.spin_seed = QSpinBox()
        self.spin_seed.setRange(0, 9999)
        grid.addWidget(self.spin_seed, 3, 1)
        grid.setColumnStretch(2, 1)
        cl.addLayout(grid)
        lay.addWidget(card_cfg)
        lay.addStretch(1)

        run_row = QHBoxLayout()
        run_row.addStretch(1)
        self.btn_run = QPushButton("▶ 运行闭环，生成计划与调度方案")
        self.btn_run.setObjectName("btnGreen")
        self.btn_run.clicked.connect(self._run)
        self.btn_run.setEnabled(False)
        run_row.addWidget(self.btn_run)
        self.btn_export = QPushButton("⬇ 导出结果")
        self.btn_export.setObjectName("btnOrange")
        self.btn_export.clicked.connect(self._export)
        self.btn_export.setEnabled(False)
        run_row.addWidget(self.btn_export)
        run_row.addStretch(1)
        lay.addLayout(run_row)

        self.lbl_status = QLabel("就绪：请先导入数据")
        self.lbl_status.setObjectName("statusBar")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.lbl_status)
        self.setCentralWidget(central)

    # ── 数据导入 ──
    def _choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择数据工作簿", str(REPO_ROOT / "data"), "Excel (*.xlsx)")
        if path:
            self._load(path)

    def _builtin_menu(self):
        menu = QMenu(self)
        act1 = menu.addAction("示例数据集（Y企业风格，10 周期）")
        act2 = menu.addAction("V-toy-1 金标算例（4 周期，运行快）")
        chosen = menu.exec_(self.btn_builtin.mapToGlobal(
            self.btn_builtin.rect().bottomLeft()))
        if chosen is act1:
            self._load(REPO_ROOT / "data" / "sample_y_style.xlsx")
        elif chosen is act2:
            self._load(REPO_ROOT / "data" / "vtoy1.xlsx")

    def _load(self, path):
        try:
            self.problem = load_problem(path)
        except (SystemExit, ValueError) as exc:
            QMessageBox.critical(self, "数据读入失败", str(exc))
            return
        p = self.problem
        self.lbl_data.setText(
            f"✔ 已导入：{Path(path).name}\n"
            f"产品族 {len(p.products)}（{', '.join(p.products)}）｜"
            f"加工阶段 {len(p.stages)}｜机器 {sum(len(m) for m in p.machines.values())} 台｜"
            f"计划周期 {len(p.periods)}｜订单 {len(p.orders)} 张\n"
            f"T^avail={p.t_avail:.0f}min｜OT^max={p.ot_max:.0f}min｜"
            f"H_w={p.horizon_window}｜K_max={p.k_max}｜权重 {p.feedback_weights}"
        )
        self.btn_run.setEnabled(True)
        self.lbl_status.setText("数据就绪：可点击「运行闭环」生成方案")

    # ── 运行与结果 ──
    def _run(self):
        solver = (CpSatScheduler(self.spin_limit.value(), require_optimal=False)
                  if self.combo_solver.currentData() == "cpsat"
                  else VendorNsgaScheduler())
        self.scheme_used = self.combo_scheme.currentData()
        self.btn_run.setEnabled(False)
        self.lbl_status.setText(
            f"⏳ 方案 {self.scheme_used} 滚动闭环运行中"
            f"（{len(self.problem.periods)} 个周期），窗口可正常操作，请稍候…")
        self.worker = RollingWorker(self.problem, solver, self.scheme_used,
                                    self.spin_seed.value())
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_failed(self, message: str):
        self.btn_run.setEnabled(True)
        self.lbl_status.setText("运行失败，请检查数据或配置")
        QMessageBox.critical(self, "运行失败", message)

    def _on_done(self, result, metrics):
        self.result, self.metrics = result, metrics
        self.btn_run.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.lbl_status.setText(
            f"✔ 运行完成：总成本 {metrics.total_cost:.0f} 元｜"
            f"可行率 {metrics.feasible_rate:.0%}｜准时率 {metrics.on_time_rate:.0%}｜"
            f"加班 {metrics.total_overtime:.0f}min —— 结果窗口已打开")
        win = ResultWindow(self.problem, result, metrics, self.scheme_used, self)
        win.show()
        self.result_windows.append(win)

    def _export(self):
        out = QFileDialog.getExistingDirectory(self, "选择导出目录", str(REPO_ROOT))
        if not out:
            return
        xlsx = export_all(self.problem, out, {self.scheme_used: self.result},
                          {self.scheme_used: self.metrics})
        QMessageBox.information(self, "导出完成", f"已导出：\n{xlsx}")


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(MAIN_STYLESHEET + EXTRA_QSS)
    win = MainWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
