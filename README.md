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
src/planning/milp_model.py      # 泛化计划层 MILP（数据驱动；含三通道反馈接口）
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

## 当前状态（Stage 2 已完成）

本仓库从零构建（不存在历史 V-toy 实现），Stage 0 冻结的基线为
**金标算例数据 + A01~A14 断言规格**（tag: `stage0-foundation`）。

- Stage 1：L1 数据层 —— `ProblemData`、校验器、V-toy-1 金标读入器、
  子批化映射（4.8.1 节）、SDST 查表、式(3-3) 需求聚合、Y模板结构骨架；
- Stage 2：L2 计划层 MILP —— 完全由 `ProblemData` 驱动（产品/阶段/周期数
  任意）；变量 q/Y/U/Inv/Back/OT；含三通道反馈接口（Δc 风险惩罚项、
  Cap^eff 产能覆盖、式(5-9) 不可行组合割）与期末闭合约束；金标 τ=1/τ=3
  计划层场景精确复现（含"移C 72<112"与"二者接近"tie）；目标函数口径由
  金标轨迹反推（启动计费+窗口冷启动、无 c_p·q 项，见模块 docstring，
  待与论文式(3-x) 最终核对）；
- 回归进度：**A01、A02 已点亮**，A03~A14 为 skip 占位；
- 测试合计：43 通过 + 12 占位跳过。

下一阶段：Stage 3 —— 参数化调度适配器（见 docs/SYSTEM_DESIGN.md §6）。
