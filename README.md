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
tests/test_vtoy1_workbook.py    # 金标工作簿完整性回归（锁定关键参数与触发机关）
tests/test_regression_vtoy1.py  # A01~A14 断言（规格占位，随实现逐步点亮）
```

## 回归基线运行方式

```bash
pip install -r requirements.txt
pytest -m regression
```

`regression` 套件 = 金标工作簿完整性测试 + V-toy-1 断言 A01~A14。
**任何阶段结束时本套件必须全绿（无 FAILED）**；金标数据 `data/vtoy1.xlsx`
的任何意外改动都会使完整性测试变红。

## 当前状态（Stage 0 已完成）

本仓库从零构建（不存在历史 V-toy 实现），Stage 0 冻结的基线为：
**金标算例数据 + A01~A14 断言规格**（tag: `stage0-foundation`）。

- 金标完整性测试：**10 通过** —— 按单元格坐标锁定 SDST 矩阵（B↔C=280 深度换模
  机关）、成本参数（b_B=8 最小）、工人可用性（τ=2 缺勤机关）、订单流 o1~o9、
  滚动与反馈参数等全部关键数值；
- A01~A14：**14 条 skip 占位** —— 每条的 docstring 即断言规格与论文对应位置，
  对应机制在 Stage 1~5 实现后逐条替换为真实断言（点亮映射见文件头注释）。

下一阶段：Stage 1 —— ProblemData 与 Excel 适配器（见 docs/SYSTEM_DESIGN.md §6）。
