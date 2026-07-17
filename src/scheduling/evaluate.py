"""论文口径调度评价器：给定"排队表 + 档位 + 技能"重演时间轴并统计全部反馈量。

这是调度层统计量的唯一事实源，CP-SAT 与 vendor 元启发式的输出都经由本模块
折算，保证 C_max/LC/E/Θ/OT/ρ 与论文第 4 章、金标断言完全一致：
  - 时间轴：同机相邻工件设置时间按产品族 SDST 查表（同族=0），
    首工件加初始设置 S_0,i（式4-1 的 I+ 口径）；跨阶段加运输时间（式4-22）；
  - LC（式4-8）：每台被使用机器配 1 名工人，工资按该机技能等级；
  - E（式4-11~4-16，kW·min）：PE=Σ PT·pe_s；SE=Σ S·se（含初始设置）；
    IE=Σ ie·(Span−P_total−S_total)，Span=MachEnd−MachStart（式4-14 口径，
    机器自身占用区间，非全程 makespan）；TE=Σ te·T_transport；AE=ae·C_max；
  - 资源校验：技能向下兼容 s ≤ α；各技能等级启用机器数 ≤ Available_{α,τ}
    （式4-6/4-7），违反即抛错（调度器输出必须合法）。

输入表示（与 vendor 四矩阵语义对齐，1 起编号）：
  assignment[(job_id, stage)] = (machine_name, gear, skill)
  sequence[(stage, machine_name)] = [job_id, ...]  # 该机加工顺序
"""
from __future__ import annotations

from src.data.lot_sizing import Job
from src.data.problem_data import ProblemData
from src.scheduling.base import Operation, ScheduleSolution, acceptability, overtime


def evaluate_schedule(
    problem: ProblemData,
    jobs: list[Job],
    tau: int,
    assignment: dict[tuple[str, int], tuple[str, int, int]],
    sequence: dict[tuple[int, str], list[str]],
) -> ScheduleSolution:
    """按论文口径重演调度并统计（见模块 docstring）。"""
    job_by_id = {j.job_id: j for j in jobs}
    stages = problem.stages

    # ── 结构校验 ──
    for (job_id, stage), (machine, gear, skill) in assignment.items():
        if machine not in problem.machines[stage]:
            raise ValueError(f"机器 {machine} 不属于阶段 {stage}")
        if gear not in problem.speed_gears:
            raise ValueError(f"非法速度档位 {gear}")
        if skill not in problem.skill_levels:
            raise ValueError(f"非法技能等级 {skill}")
        if gear > skill:
            raise ValueError(
                f"违反向下兼容（式4-6）：工件 {job_id} 阶段 {stage} 档位 {gear} > 技能 {skill}"
            )
    for j in jobs:
        for stage in stages:
            if (j.job_id, stage) not in assignment:
                raise ValueError(f"工件 {j.job_id} 阶段 {stage} 缺少分配")

    # 机器→技能等级（同机各工序技能必须一致；式4-4 每机至多一名工人）
    machine_skill: dict[tuple[int, str], int] = {}
    for (job_id, stage), (machine, gear, skill) in assignment.items():
        key = (stage, machine)
        if key in machine_skill and machine_skill[key] != skill:
            raise ValueError(f"机器 {machine} 阶段 {stage} 配工技能不一致")
        machine_skill[key] = skill

    # 工人可用性（式4-7）：各技能等级启用机器数 ≤ Available_{α,τ}
    used_count: dict[int, int] = {level: 0 for level in problem.skill_levels}
    for (stage, machine), skill in machine_skill.items():
        used_count[skill] += 1
    for level, cnt in used_count.items():
        avail = problem.worker_available[level][tau]
        if cnt > avail:
            raise ValueError(
                f"违反工人可用性（式4-7）：α={level} 启用 {cnt} 台机 > 可用 {avail} 人（τ={tau}）"
            )

    # ── 时间轴重演（同 vendor 解码次序：逐阶段、逐机器按给定序列）──
    completion: dict[tuple[str, int], float] = {}
    operations: list[Operation] = []
    pe = se_energy = te_energy = 0.0
    mach_stat: dict[tuple[int, str], dict[str, float]] = {}

    for si, stage in enumerate(stages):
        for machine in problem.machines[stage]:
            queue = sequence.get((stage, machine), [])
            mach_ready = 0.0
            prev_product: str | None = None
            for job_id in queue:
                job = job_by_id[job_id]
                _, gear, _skill = assignment[(job_id, stage)]
                proc = job.size * problem.proc_time[job.product][stage] * problem.speed_factor[gear]
                setup = problem.setup_time(prev_product, job.product)
                if si == 0:
                    ready = 0.0
                else:
                    ready = completion[(job_id, stages[si - 1])] + problem.transport_time
                    te_energy += problem.energy.energy_transport * problem.transport_time
                # 式(4-1)+(4-22)：加工开始 ≥ max(机器就绪+设置, 工件到达)
                # —— 设置可与工件运输/等待重叠；设置段紧贴加工前（式4-29 口径）
                setup_end = max(mach_ready + setup, ready)
                start = setup_end - setup
                end = setup_end + proc
                completion[(job_id, stage)] = end
                mach_ready = end
                prev_product = job.product

                stat = mach_stat.setdefault(
                    (stage, machine), {"start": start, "end": end, "proc": 0.0, "setup": 0.0}
                )
                stat["start"] = min(stat["start"], start)
                stat["end"] = max(stat["end"], end)
                stat["proc"] += proc
                stat["setup"] += setup

                pe += proc * problem.energy.power_proc[gear]
                se_energy += setup * problem.energy.power_setup
                operations.append(
                    Operation(
                        job_id=job_id,
                        product=job.product,
                        stage=stage,
                        machine=machine,
                        gear=gear,
                        skill=assignment[(job_id, stage)][2],
                        start=start,
                        setup_end=setup_end,
                        end=end,
                        setup_time=setup,
                    )
                )

    cmax = max((completion[(j.job_id, stages[-1])] for j in jobs), default=0.0)

    # Θ_{j}^{sdst}（式5-4，含初始设置）
    theta_stage = {j: 0.0 for j in stages}
    for op in operations:
        theta_stage[op.stage] += op.setup_time

    # LC（式4-8）
    lc = sum(problem.worker_wage[skill] for skill in machine_skill.values())

    # IE（式4-14）：Span = MachEnd − MachStart
    ie_energy = sum(
        problem.energy.power_idle * (s["end"] - s["start"] - s["proc"] - s["setup"])
        for s in mach_stat.values()
    )
    ae_energy = problem.energy.power_aux * cmax
    energy = pe + se_energy + ie_energy + te_energy + ae_energy

    return ScheduleSolution(
        cmax=cmax,
        lc=lc,
        energy=energy,
        theta_stage=theta_stage,
        ot=overtime(problem, cmax),
        rho=acceptability(problem, cmax),
        operations=operations,
        energy_breakdown={
            "processing": pe,
            "setup": se_energy,
            "idle": ie_energy,
            "transport": te_energy,
            "auxiliary": ae_energy,
        },
    )
