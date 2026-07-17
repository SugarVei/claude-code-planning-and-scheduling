# 集成生产计划与调度系统

《Y企业混合流水车间生产计划与调度反馈集成优化研究》的实验平台与决策支持原型。
实现滚动时域闭环集成优化机制：**计划层（滚动时域 MILP）→ 子批化映射 → 调度层
（HFSP-SDST 多目标元启发式）→ 反馈层（三通道结构化反馈）→ 滚动更新**。

系统设计与分阶段开发计划见 [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md)。

## 仓库结构

```
CLAUDE.md                       # 开发行为规则（先思考、简单优先、外科手术式修改、目标驱动）
docs/SYSTEM_DESIGN.md           # 系统框架设计 + 分阶段开发总控
data/vtoy1.xlsx                 # V-toy-1 金标回归算例（只读，勿改动）
data/y_template.xlsx            # Y企业数据采集模板（只读）
src/data/problem_data.py        # ProblemData 数据类（字段注释 = 论文符号）
src/data/lot_sizing.py          # 子批化映射 q^plan → I^sch（4.8.1 节）
src/data/validators.py          # 数据完整性校验
src/data/excel_adapter.py       # V-toy-1 读入器 + Y模板结构读入骨架
src/planning/milp_model.py      # 泛化计划层 MILP（式3-4~3-14；含三通道反馈接口）
src/scheduling/base.py          # SchedulerAdapter 接口 + OT/ρ/非支配工具
src/scheduling/evaluate.py      # 论文口径评价器（式4-1~4-16/5-4 唯一事实源）
src/scheduling/exact_cpsat.py   # CP-SAT 精确调度器（min C_max 判定性验证）
src/scheduling/meta_vendor.py   # 真实 NSGA-II-VNS-MOSA 适配器（搜索+论文口径重评）
src/feedback/representative.py  # Pareto 代表解选择（式5-11~5-17）
src/feedback/cuts.py            # 三步割判据+加班型守卫（式5-6/5-9/5-10）
src/feedback/protection.py      # 保护处理（式3-9 冲抵口径 + K_max 移出次序）
src/feedback/channels.py        # 三通道折算（式5-1~5-5）+ FeedbackConfig 开关
src/rolling/controller.py       # 滚动主循环（算法5-1：冻结四条件/K_max 保护/状态更新）
vendor_nsga/                    # 论文配套算法源码（只读，见其 README 溯源）
tests/test_vtoy1_workbook.py    # 金标工作簿完整性回归（锁定关键参数与触发机关）
tests/test_regression_vtoy1.py  # A01~A14 断言（随实现逐步点亮）
```

## 回归基线运行方式

```bash
pip install -r requirements.txt
pytest -m regression
```

`regression` 套件 = 金标工作簿完整性测试 + V-toy-1 断言 A01~A14。
**任何阶段结束时本套件必须全绿（无 FAILED）**；金标数据 `data/vtoy1.xlsx`
的任何意外改动都会使完整性测试变红。

## 当前状态（Stage 5 已完成：闭环打通，A01~A14 全部点亮）

本仓库从零构建（不存在历史 V-toy 实现），Stage 0 冻结的基线为
**金标算例数据 + A01~A14 断言规格**（tag: `stage0-foundation`）。

- Stage 1：L1 数据层 —— `ProblemData`、校验器、V-toy-1 金标读入器、
  子批化映射（4.8.1 节）、SDST 查表、式(3-3) 需求聚合、Y模板结构骨架；
- Stage 2：L2 计划层 MILP —— 式(3-4)~(3-14)，已对照论文正文核实
  （表3-3 无加班变量、式3-11 硬约束）；与正文的三处刻意偏差
  （无 c_p·q 项、g_p 按启动计费+窗口冷启动、T_max 期末闭合）由金标
  硬断言强制，反证与回写建议见 `src/planning/milp_model.py` docstring；
- Stage 3：L3 调度层 —— `SchedulerAdapter` 接口；论文口径评价器
  （式4-1~4-16/5-4，含初始设置 S_0、kW·min、机器占用区间空闲能耗）；
  CP-SAT 精确调度器（判定性验证：τ=1 k0 C*=509>504 ⇒ 必然 Feas=0、
  τ=3 k0 C*=678≥634 且 OT>OT^max ⇒ ρ=0、割后单族 Θ₂=10）；
  `vendor_nsga/` 真实 NSGA-II-VNS-MOSA 原样接入（真算法搜索+论文口径
  重评）；代表解选择（式5-11~5-17，含兜底分支）；
- Stage 4：反馈层判据与保护处理 —— 三步割生成判据 + §2.2 加班型排除
  守卫（τ=1 判加班型不生成割 / τ=3 结构型生成割 {B,C}，中间量见
  `docs/stage4_cut_guard_report.md`）；割池生命周期（式5-10 周期内累积、
  冻结后清零）；式(3-9) 保护处理（正库存先冲抵欠交，含 P3 错误口径的
  对照复现测试）；K_max 移出次序（b_p 升序、β 降序，V2 口径）；
- Stage 5：滚动闭环 —— `run_rolling` 数据驱动主循环（H_w/H_f/K_max/ε_P/
  N_restart 全部来自 ProblemData）；三通道折算（式5-1~5-5，κ_L/κ_E 增量
  口径、Δc 阻尼封顶、η=工人/机器）；反馈仅在不可接受时返回计划层
  （§3.5.3），通道按诊断类型分派（加班/负荷型→通道1+2、结构型→通道3）；
  冻结四条件（式3-19~3-22）；K_max 保护处理（算法5-1 第23~32行，含
  O^unfin 登记）；`FeedbackConfig` 三通道独立开关（禁用走日志）；
  金标闭环轨迹逐周期复现（CP-SAT 确定性调度器）；
- 回归进度：**A01~A14 全部点亮（14/14）**；
- 测试合计：96 通过，0 跳过。

下一阶段：Stage 6 —— 示例数据 + 实验框架（方案 A~D、消融、敏感性、导出）。
