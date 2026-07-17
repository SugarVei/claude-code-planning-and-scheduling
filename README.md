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

## 当前状态（Stage 3 已完成，公式已对照论文核实）

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
- 回归进度：**A01~A05、A14 已点亮**（6/14），A06~A13 待 Stage 4/5；
- 测试合计：65 通过 + 8 占位跳过。

下一阶段：Stage 4 —— 保护处理（式3-9 口径）+ 割判据加班型排除守卫。
