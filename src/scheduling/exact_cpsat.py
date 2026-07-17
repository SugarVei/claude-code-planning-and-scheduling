"""CP-SAT 精确调度器（论文式(4-1)~(4-34) 的约束编程实现，小规模验证用）。

结构映射：
  机器选择 x_{i,j,f} / 速度选择 v_{i,j,s}（式4-19/4-20）；
  同机排序 y_{i,i',j,f} → 每机一个 AddCircuit（虚拟节点 0 即论文虚拟工件，
  0→i 弧带初始设置 S_0,i，i→i' 弧带 SDST，式4-1/4-24 口径，
  设置时间与设置能耗天然计入——对应已知问题清单"精确求解器必须含设置项"）；
  人机耦合 u_{j,f,α}（式4-4/4-5）、向下兼容（式4-6）、工人可用性（式4-7）；
  工艺顺序+运输（式4-22）、完工定义（式4-25）、C_max（式4-26）。

目标：min C_max 精确解（金标 V-toy 的判定性用途：τ=1 k=0 证明
C_max* > 480+24 → 任何调度器都 Feas=0；τ=3 证明 OT* > OT^max）。
LC/E 等统计由 evaluate.py 对解重演给出（与元启发式同一口径）。
时间刻度 ×SCALE 取整（θ_s 两位小数 → SCALE=10 精确）。
"""
from __future__ import annotations

from ortools.sat.python import cp_model

from src.data.lot_sizing import Job
from src.data.problem_data import ProblemData
from src.scheduling.base import ScheduleSolution
from src.scheduling.evaluate import evaluate_schedule

SCALE = 10


class CpSatScheduler:
    """SchedulerAdapter 实现：min C_max 精确求解（返回单元素解列表）。"""

    def __init__(self, time_limit_s: float = 60.0):
        self.time_limit_s = time_limit_s

    def solve(
        self, problem: ProblemData, jobs: list[Job], tau: int, seed: int | None = None
    ) -> list[ScheduleSolution]:
        if not jobs:
            return []
        sol = self._solve_min_cmax(problem, jobs, tau, seed)
        return [sol]

    def min_cmax(
        self, problem: ProblemData, jobs: list[Job], tau: int, seed: int | None = None
    ) -> float:
        """精确最小 C_max（判定性验证入口）。"""
        return self._solve_min_cmax(problem, jobs, tau, seed).cmax

    def _solve_min_cmax(
        self, problem: ProblemData, jobs: list[Job], tau: int, seed: int | None
    ) -> ScheduleSolution:
        m = cp_model.CpModel()
        stages = problem.stages
        n = len(jobs)
        gears = problem.speed_gears
        levels = problem.skill_levels

        pt = {  # 缩放后的 PT_{i,j,s}
            (i, j, s): round(
                SCALE * jobs[i].size * problem.proc_time[jobs[i].product][j]
                * problem.speed_factor[s]
            )
            for i in range(n)
            for j in stages
            for s in gears
        }
        horizon = sum(
            max(pt[i, j, s] for s in gears) for i in range(n) for j in stages
        ) + round(
            SCALE
            * (
                n * len(stages) * (max(problem.initial_setup.values())
                + max(v for row in problem.sdst.values() for v in row.values()))
                + n * (len(stages) - 1) * problem.transport_time
            )
        )

        x = {}   # x[i,j,f] 机器选择
        v = {}   # v[i,j,s] 速度选择
        st = {}  # ST_{i,j} 加工开始
        ct = {}  # CT_{i,j} 完工
        for i in range(n):
            for j in stages:
                for f in problem.machines[j]:
                    x[i, j, f] = m.NewBoolVar(f"x_{i}_{j}_{f}")
                m.AddExactlyOne(x[i, j, f] for f in problem.machines[j])  # 式4-19
                for s in gears:
                    v[i, j, s] = m.NewBoolVar(f"v_{i}_{j}_{s}")
                m.AddExactlyOne(v[i, j, s] for s in gears)  # 式4-19
                st[i, j] = m.NewIntVar(0, horizon, f"ST_{i}_{j}")
                ct[i, j] = m.NewIntVar(0, horizon, f"CT_{i}_{j}")
                m.Add(  # 式4-25：CT = ST + Σ PT·v
                    ct[i, j]
                    == st[i, j] + sum(pt[i, j, s] * v[i, j, s] for s in gears)
                )

        # 人机耦合（式4-4/4-5/4-6/4-7）
        u = {}
        for j in stages:
            for f in problem.machines[j]:
                for a in levels:
                    u[j, f, a] = m.NewBoolVar(f"u_{j}_{f}_{a}")
                used = m.NewBoolVar(f"used_{j}_{f}")
                m.AddMaxEquality(used, [x[i, j, f] for i in range(n)])
                m.Add(sum(u[j, f, a] for a in levels) == 1).OnlyEnforceIf(used)
                m.Add(sum(u[j, f, a] for a in levels) == 0).OnlyEnforceIf(used.Not())
                machine_level = sum(a * u[j, f, a] for a in levels)
                for i in range(n):
                    gear_of_i = sum(s * v[i, j, s] for s in gears)
                    m.Add(gear_of_i <= machine_level).OnlyEnforceIf(x[i, j, f])  # 式4-6
        for a in levels:
            m.Add(  # 式4-7
                sum(u[j, f, a] for j in stages for f in problem.machines[j])
                <= problem.worker_available[a][tau]
            )

        # 工艺顺序 + 运输（式4-22）
        transport = round(SCALE * problem.transport_time)
        for i in range(n):
            for prev_j, j in zip(stages, stages[1:]):
                m.Add(st[i, j] >= ct[i, prev_j] + transport)

        # 同机排序：每机 AddCircuit，虚拟节点 0 = 论文虚拟工件（式4-1/4-23/4-24）
        for j in stages:
            for f in problem.machines[j]:
                arcs = []
                # 虚拟节点 0 的自环：机器无工件时圈退化为 0→0（否则每机被迫用工）
                arcs.append((0, 0, m.NewBoolVar(f"empty_{j}_{f}")))
                for i in range(n):
                    lit_start = m.NewBoolVar(f"arc0_{i}_{j}_{f}")
                    arcs.append((0, i + 1, lit_start))
                    s0 = round(SCALE * problem.initial_setup[jobs[i].product])
                    m.Add(st[i, j] >= s0).OnlyEnforceIf(lit_start)
                    arcs.append((i + 1, 0, m.NewBoolVar(f"arcE_{i}_{j}_{f}")))
                    arcs.append((i + 1, i + 1, x[i, j, f].Not()))  # 不在此机 → 自环
                    for i2 in range(n):
                        if i2 == i:
                            continue
                        lit = m.NewBoolVar(f"arc_{i}_{i2}_{j}_{f}")
                        arcs.append((i + 1, i2 + 1, lit))
                        sdst = round(
                            SCALE
                            * problem.setup_time(jobs[i].product, jobs[i2].product)
                        )
                        m.Add(st[i2, j] >= ct[i, j] + sdst).OnlyEnforceIf(lit)  # 式4-1
                m.AddCircuit(arcs)

        cmax = m.NewIntVar(0, horizon, "cmax")
        for i in range(n):
            m.Add(cmax >= ct[i, stages[-1]])  # 式4-26
        m.Minimize(cmax)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.time_limit_s
        # 单线程：多 worker 下返回的最优解不确定（目标值同、解不同），
        # 会使闭环反馈链（代表解 Θ_j → Cap^eff → 计划）不可复现
        solver.parameters.num_search_workers = 1
        if seed is not None:
            solver.parameters.random_seed = seed
        status = solver.Solve(m)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise ValueError(f"CP-SAT 无可行调度（status={solver.StatusName(status)}）")
        if status != cp_model.OPTIMAL:
            raise ValueError(
                f"CP-SAT 未在 {self.time_limit_s}s 内证明最优（判定性用途需最优解）"
            )

        # 提取解 → 论文口径重评（LC/E/Θ/OT/ρ 与元启发式同一事实源）
        assignment: dict[tuple[str, int], tuple[str, int, int]] = {}
        sequence: dict[tuple[int, str], list[str]] = {}
        for j in stages:
            for f in problem.machines[j]:
                level = next(
                    (a for a in levels if solver.Value(u[j, f, a])), None
                )
                on_machine = [
                    i for i in range(n) if solver.Value(x[i, j, f])
                ]
                if not on_machine:
                    continue
                on_machine.sort(key=lambda i: solver.Value(st[i, j]))
                sequence[(j, f)] = [jobs[i].job_id for i in on_machine]
                for i in on_machine:
                    gear = next(s for s in gears if solver.Value(v[i, j, s]))
                    assignment[(jobs[i].job_id, j)] = (f, gear, level)

        sol = evaluate_schedule(problem, jobs, tau, assignment, sequence)
        exact_cmax = solver.Value(cmax) / SCALE
        if abs(sol.cmax - exact_cmax) > 1e-6:
            raise AssertionError(
                f"评价器与 CP-SAT 时间轴不一致：{sol.cmax} vs {exact_cmax}"
            )
        return sol
