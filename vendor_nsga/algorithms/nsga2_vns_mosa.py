# -*- coding: utf-8 -*-
"""algorithms/nsga2_vns_mosa.py

NSGA-II + VNS + MOSA (paper-aligned two-phase hybrid)

设计目标：
- 第一阶段：使用 NSGA-II 获得初始 Pareto 近似集。
- 第二阶段：以该近似集构建外部档案 AP 与代表集 RP，在降温过程中对 RP 执行 VNS 生成候选集，
  并用 MOSA 的 Metropolis 准则进行接受/拒绝与档案更新。

该实现刻意与 repo 其余“对比算法”隔离，供 comparison_worker 直接调用。
"""

from __future__ import annotations

import math
import os
import csv
from datetime import datetime
import random
from copy import deepcopy
from typing import List, Tuple, Optional, Dict

import numpy as np

from models.problem import SchedulingProblem
from models.solution import Solution
from models.decoder import Decoder
from algorithms.nsga2 import NSGAII
from algorithms.operators import (
    four_matrix_sx_crossover,
    mutation_single,
    mutation_multi,
    mutation_inversion,
)


class NSGA2_VNS_MOSA:
    """NSGA-II-VNS-MOSA 2-phase hybrid (核心算法)."""

    def __init__(
        self,
        problem: SchedulingProblem,
        pop_size: int = 200,
        n_generations: int = 100,
        crossover_prob: float = 0.95,
        mutation_prob: float = 0.15,
        initial_temp: float = 1000.0,
        cooling_rate: float = 0.95,
        final_temp: float = 1e-3,
        mosa_layers: int = 50,
        rp_size: int = 40,
        ap_size: int = 200,
        epsilon_greedy: float = 0.1,
        vns_max_iters: int = 5,     # 保留参数以兼容 UI；在此实现中表示“每个代表解每层生成候选的轮数”
        elite_ratio: float = 0.1,   # 兼容参数：此实现不使用（两阶段设计）
        weight_mode: str = "random",  # "random" | "fixed"
        fixed_weights: Tuple[float, float, float] = (1/3, 1/3, 1/3),
        audit_enabled: bool = False,
        audit_dir: str = "audit",
        audit_sample_k: int = 20,
        seed: Optional[int] = None,
    ):
        self.problem = problem
        self.decoder = Decoder(problem)

        self.pop_size = pop_size
        self.n_generations = n_generations
        self.crossover_prob = crossover_prob
        self.mutation_prob = mutation_prob

        self.initial_temp = float(initial_temp)
        self.cooling_rate = float(cooling_rate)
        self.final_temp = float(final_temp)
        self.mosa_layers = int(mosa_layers)
        self.rp_size = int(rp_size)
        self.ap_size = int(ap_size)
        self.epsilon_greedy = float(epsilon_greedy)
        self.vns_max_iters = int(vns_max_iters)

        self.weight_mode = weight_mode
        self.fixed_weights = fixed_weights

        self.audit_enabled = bool(audit_enabled)
        self.audit_dir = str(audit_dir)
        self.audit_sample_k = int(audit_sample_k)
        self._audit_rows: List[dict] = []
        self._constraint_rows: List[dict] = []
        if self.audit_enabled:
            os.makedirs(self.audit_dir, exist_ok=True)

        self.seed = seed
        self.rng = np.random.default_rng(seed)
        if seed is not None:
            random.seed(seed)

        # NSGA-II 第一阶段（复用实现，覆写其 crossover 以匹配 SX）
        self.nsga2 = NSGAII(
            problem,
            pop_size=pop_size,
            n_generations=n_generations,
            crossover_prob=crossover_prob,
            mutation_prob=mutation_prob,
            seed=seed,
        )
        self._patch_nsga2_operators()

        self.progress_callback = None

        # 收敛历史（供 UI/实验使用）
        self.convergence_history = {
            "phase": [],
            "iteration": [],
            "temperature": [],
            "n_ap": [],
            "best_makespan": [],
            "best_labor_cost": [],
            "best_energy": [],
        }

    def set_progress_callback(self, callback):
        self.progress_callback = callback
        self.nsga2.set_progress_callback(callback)

    # ---------------------------------------------------------------------
    # Phase 1: NSGA-II
    # ---------------------------------------------------------------------
    def _patch_nsga2_operators(self):
        """将 NSGA-II 的交叉替换为 SX，并将 mutate 改为 (single/multi/inversion) 随机族。"""
        nsga2 = self.nsga2
        problem = self.problem
        decoder = nsga2.decoder

        def crossover(p1: Solution, p2: Solution) -> Tuple[Solution, Solution]:
            if self.rng.random() > self.nsga2.crossover_prob:
                c1, c2 = p1.copy(), p2.copy()
                if c1.objectives is None:
                    decoder.decode(c1)
                if c2.objectives is None:
                    decoder.decode(c2)
                return c1, c2
            # four_matrix_sx_crossover 返回一个子代，因此需要调用两次
            c1 = four_matrix_sx_crossover(p1, p2, self.rng, problem, decoder)
            c2 = four_matrix_sx_crossover(p2, p1, self.rng, problem, decoder) # 交换父代以增加多样性
            return c1, c2

        def mutate(sol: Solution) -> Solution:
            if random.random() > nsga2.mutation_prob:
                return sol
            mode = self.rng.choice(["single", "multi", "inversion"], p=[0.5, 0.3, 0.2])
            if mode == "single":
                return mutation_single(sol, self.rng, problem)
            if mode == "multi":
                return mutation_multi(sol, self.rng, problem, k=3)
            return mutation_inversion(sol, self.rng, problem)

        # monkey patch
        nsga2.crossover = crossover  # type: ignore
        nsga2.mutate = mutate        # type: ignore

    # ---------------------------------------------------------------------
    # Phase 2: MOSA + VNS
    # ---------------------------------------------------------------------
    @staticmethod
    def _dominates(a: Solution, b: Solution) -> bool:
        return a.dominates(b)

    @staticmethod
    def _crowding_distance(solutions: List[Solution]) -> List[float]:
        n = len(solutions)
        if n == 0:
            return []
        if n <= 2:
            return [float("inf")] * n

        objs = np.array([s.objectives for s in solutions], dtype=float)
        cd = np.zeros(n, dtype=float)
        for m in range(objs.shape[1]):
            order = np.argsort(objs[:, m])
            cd[order[0]] = np.inf
            cd[order[-1]] = np.inf
            fmin, fmax = objs[order[0], m], objs[order[-1], m]
            if fmax - fmin == 0:
                continue
            for k in range(1, n - 1):
                if np.isinf(cd[order[k]]):
                    continue
                cd[order[k]] += (objs[order[k + 1], m] - objs[order[k - 1], m]) / (fmax - fmin)
        return cd.tolist()

    def _phi(self, sol: Solution, ref: List[Solution], weights: Tuple[float, float, float]) -> float:
        """论文中的标量化 Φ：基于参考集的 min-max 归一化 + 加权和。"""
        objs = np.array([s.objectives for s in ref], dtype=float)
        mn = objs.min(axis=0)
        mx = objs.max(axis=0)
        denom = np.where(mx - mn == 0, 1.0, mx - mn)
        z = (np.array(sol.objectives, dtype=float) - mn) / denom
        w = np.array(weights, dtype=float)
        w = w / max(1e-12, w.sum())
        return float(np.dot(w, z))

    def _sample_weights(self) -> Tuple[float, float, float]:
        if self.weight_mode == "fixed":
            w = np.array(self.fixed_weights, dtype=float)
            w = w / max(1e-12, w.sum())
            return float(w[0]), float(w[1]), float(w[2])
        # random: Dirichlet(1,1,1)
        w = self.rng.dirichlet(np.ones(3))
        return float(w[0]), float(w[1]), float(w[2])

    def _epsilon_greedy_select(self, candidates: List[Solution], ref: List[Solution], weights) -> Solution:
        if not candidates:
            raise ValueError("empty candidate set")
        if self.rng.random() < self.epsilon_greedy:
            return candidates[int(self.rng.integers(0, len(candidates)))]
        return min(candidates, key=lambda s: self._phi(s, ref, weights))

    def _update_archive(self, ap: List[Solution], s_new: Solution) -> List[Solution]:
        """外部档案 AP：加入新解，删除被支配解，并按拥挤度裁剪至容量。"""
        # 先删除被新解支配的
        ap2 = [s for s in ap if not s_new.dominates(s)]
        # 若新解被支配，则不加入
        for s in ap2:
            if s.dominates(s_new):
                return ap2
        ap2.append(s_new)

        # 裁剪
        if len(ap2) > self.ap_size:
            cd = self._crowding_distance(ap2)
            # 删除拥挤度最小的直到满足容量（保留 inf 边界点）
            while len(ap2) > self.ap_size:
                finite = [(i, cd[i]) for i in range(len(ap2)) if not math.isinf(cd[i])]
                if not finite:
                    ap2 = ap2[: self.ap_size]
                    break
                i_min = min(finite, key=lambda x: x[1])[0]
                ap2.pop(i_min)
                cd.pop(i_min)
        return ap2

    def _build_rp_from_ap(self, ap: List[Solution]) -> List[Solution]:
        if not ap:
            return []
        if len(ap) <= self.rp_size:
            return [s.copy() for s in ap]
        cd = self._crowding_distance(ap)
        idx = np.argsort([-cd_i if not math.isinf(cd_i) else float("inf") for cd_i in cd])
        chosen = [ap[int(i)].copy() for i in idx[: self.rp_size]]
        return chosen

    # ---------------- VNS neighborhood operators ----------------
    def _n1_machine(self, sol: Solution) -> Solution:
        s = sol.copy()
        i = int(self.rng.integers(0, self.problem.n_jobs))
        j = int(self.rng.integers(0, self.problem.n_stages))
        m_j = int(self.problem.machines_per_stage[j])
        if m_j > 1:
            cur = int(s.machine_assign[i, j])
            cand = int(self.rng.integers(0, m_j))
            if cand == cur:
                cand = (cand + 1) % m_j
            s.machine_assign[i, j] = cand
            s.sequence_priority[i, j] = int(self.rng.integers(0, 1000))
        s.objectives = None
        if s.repair(self.problem) is None:
            return None
        return s

    def _n1_speed(self, sol: Solution) -> Solution:
        s = sol.copy()
        i = int(self.rng.integers(0, self.problem.n_jobs))
        j = int(self.rng.integers(0, self.problem.n_stages))
        cur = int(s.speed_level[i, j])
        cand = int(self.rng.integers(0, self.problem.n_speed_levels))
        if cand == cur:
            cand = max(0, cur - 1)
        s.speed_level[i, j] = cand
        # 技能下兼容：先同步到 speed，repair 会再统一到 ω[j,f]
        s.worker_skill[i, j] = max(int(s.worker_skill[i, j]), cand)
        s.objectives = None
        if s.repair(self.problem) is None:
            return None
        return s

    def _n1_worker(self, sol: Solution) -> Solution:
        s = sol.copy()
        i = int(self.rng.integers(0, self.problem.n_jobs))
        j = int(self.rng.integers(0, self.problem.n_stages))
        # 先随机选择新技能，再通过 repair 统一 ω 并兼容 V
        cand = int(self.rng.integers(0, self.problem.n_skill_levels))
        s.worker_skill[i, j] = cand
        s.speed_level[i, j] = min(int(s.speed_level[i, j]), cand)
        s.objectives = None
        if s.repair(self.problem) is None:
            return None
        return s

    def _n1_queue_swap(self, sol: Solution) -> Solution:
        s = sol.copy()
        j = int(self.rng.integers(0, self.problem.n_stages))
        if self.problem.n_jobs < 2:
            return s
        i1, i2 = self.rng.choice(self.problem.n_jobs, size=2, replace=False)
        s.sequence_priority[i1, j], s.sequence_priority[i2, j] = s.sequence_priority[i2, j], s.sequence_priority[i1, j]
        s.objectives = None
        if s.repair(self.problem) is None:
            return None
        return s

    def _n2_path(self, sol: Solution) -> Solution:
        s = sol.copy()
        i = int(self.rng.integers(0, self.problem.n_jobs))
        for j in range(self.problem.n_stages):
            m_j = int(self.problem.machines_per_stage[j])
            if m_j > 0:
                s.machine_assign[i, j] = int(self.rng.integers(0, m_j))
            s.sequence_priority[i, j] = int(self.rng.integers(0, 1000))
        s.objectives = None
        if s.repair(self.problem) is None:
            return None
        return s

    def _n2_mode(self, sol: Solution) -> Solution:
        s = sol.copy()
        i = int(self.rng.integers(0, self.problem.n_jobs))
        # 以同一个速度/技能模式覆盖该 job 的所有阶段（趋向节能）
        target_speed = int(self.rng.integers(0, self.problem.n_speed_levels))
        target_skill = max(target_speed, int(self.rng.integers(target_speed, self.problem.n_skill_levels)))
        for j in range(self.problem.n_stages):
            s.speed_level[i, j] = target_speed
            s.worker_skill[i, j] = target_skill
        s.objectives = None
        if s.repair(self.problem) is None:
            return None
        return s

    def _n3_swap_rows(self, sol: Solution) -> Solution:
        s = sol.copy()
        if self.problem.n_jobs < 2:
            return s
        a, b = self.rng.choice(self.problem.n_jobs, size=2, replace=False)
        s.machine_assign[[a, b], :] = s.machine_assign[[b, a], :]
        s.sequence_priority[[a, b], :] = s.sequence_priority[[b, a], :]
        s.speed_level[[a, b], :] = s.speed_level[[b, a], :]
        s.worker_skill[[a, b], :] = s.worker_skill[[b, a], :]
        s.objectives = None
        if s.repair(self.problem) is None:
            return None
        return s

    def _n3_block_insert(self, sol: Solution) -> Solution:
        s = sol.copy()
        j = int(self.rng.integers(0, self.problem.n_stages))
        n = self.problem.n_jobs
        if n < 4:
            return s
        # 在某阶段上做“块移动”，只作用于 priority（机器/速度/技能保持）
        order = list(np.argsort(s.sequence_priority[:, j]))
        a = int(self.rng.integers(0, n - 2))
        b = int(self.rng.integers(a + 1, min(n - 1, a + 3)))  # 块长度 2~3
        block = order[a:b+1]
        rest = [x for x in order if x not in block]
        ins = int(self.rng.integers(0, len(rest) + 1))
        new_order = rest[:ins] + block + rest[ins:]
        for rank, job in enumerate(new_order):
            s.sequence_priority[job, j] = rank
        s.objectives = None
        if s.repair(self.problem) is None:
            return None
        return s

    def _generate_candidate_set(self, s_cur: Solution) -> Tuple[List[Solution], Dict]:
        """按论文生成候选集合 C：仅保留“可行/修复成功”的候选（h≤8）。"""
        ops = [
            self._n1_machine,
            self._n1_speed,
            self._n1_worker,
            self._n1_queue_swap,
            self._n2_path,
            self._n2_mode,
            self._n3_swap_rows,
            self._n3_block_insert,
        ]

        candidates: List[Solution] = []
        stats = {"n_ops": len(ops), "n_repair_failed": 0, "n_valid": 0}
        ops_idx = list(range(len(ops)))
        self.rng.shuffle(ops_idx)

        for k in ops_idx:
            cand = ops[k](s_cur)  # 可能为 None（修复失败）
            if cand is None:
                stats["n_repair_failed"] += 1
                continue
            self.decoder.decode(cand)
            candidates.append(cand)
            stats["n_valid"] += 1

        return candidates, stats

    def _mosa_accept(self, s_cur: Solution, s_new: Solution, T: float, ref: List[Solution], weights) -> bool:
        if s_new.dominates(s_cur):
            return True
        if s_cur.dominates(s_new):
            # 允许劣解以概率接受
            pass
        delta = self._phi(s_new, ref, weights) - self._phi(s_cur, ref, weights)
        if delta <= 0:
            return True
        if T <= 1e-12:
            return False
        p = math.exp(-delta / T)
        return self.rng.random() < p

    # ---------------------------------------------------------------------
    def run(self) -> List[Solution]:
        """运行两阶段 NSGA-II-VNS-MOSA，返回 AP (Pareto archive)."""
        # ---------- Phase 1: NSGA-II ----------
        if self.progress_callback:
            self.progress_callback(0, self.n_generations + self.mosa_layers, "Phase 1: NSGA-II")

        pop = self.nsga2.run()
        # 用最后一代 population 的非支配前沿作为初始 AP
        fronts = self.nsga2.non_dominated_sort(pop)
        ap = [pop[i].copy() for i in fronts[0]] if fronts else [s.copy() for s in pop]
        # 容量裁剪
        if len(ap) > self.ap_size:
            cd = self._crowding_distance(ap)
            idx = np.argsort([-c if not math.isinf(c) else float("inf") for c in cd])
            ap = [ap[int(i)] for i in idx[: self.ap_size]]

        rp = self._build_rp_from_ap(ap)

        # 记录一次
        self._log_progress("phase1_end", 0, self.initial_temp, ap)

        # ---------- Phase 2: MOSA + VNS ----------
        T = self.initial_temp
        for layer in range(self.mosa_layers):
            if T < self.final_temp:
                break

            if self.progress_callback:
                self.progress_callback(self.n_generations + layer + 1, self.n_generations + self.mosa_layers,
                                       f"Phase 2: MOSA layer {layer+1}/{self.mosa_layers} (T={T:.3g})")

            weights = self._sample_weights()

            # 对 RP 中每个解执行若干轮 VNS + MOSA
            new_rp = []
            for r_idx, r in enumerate(rp):
                s_cur = r.copy()
                for vns_iter in range(self.vns_max_iters):
                    C, c_stats = self._generate_candidate_set(s_cur)

                    if self.audit_enabled:
                        self._audit_rows.append({
                            "phase": "mosa",
                            "layer": int(layer + 1),
                            "temperature": float(T),
                            "rp_index": int(r_idx),
                            "vns_iter": int(vns_iter + 1),
                            "c_ops": int(c_stats.get("n_ops", 0)),
                            "c_valid": int(c_stats.get("n_valid", 0)),
                            "c_repair_failed": int(c_stats.get("n_repair_failed", 0)),
                            "c_empty": int(1 if len(C) == 0 else 0),
                            "accepted": None,
                        })

                    if not C:
                        # 论文：若本次 VNS 无有效候选，则令 S_new = S_cur（等价于不发生状态转移）
                        break
                    ref = ap + rp + C
                    s_new = self._epsilon_greedy_select(C, ref, weights)
                    accepted = self._mosa_accept(s_cur, s_new, T, ref, weights)
                    if self.audit_enabled:
                        try:
                            self._audit_rows[-1]["accepted"] = int(1 if accepted else 0)
                        except Exception:
                            pass
                    if accepted:
                        s_cur = s_new
                    ap = self._update_archive(ap, s_new)
                new_rp.append(s_cur)

            rp = self._build_rp_from_ap(ap) if ap else new_rp
            if self.audit_enabled:
                self._audit_constraints(layer + 1, T, ap)
            self._log_progress("mosa", layer + 1, T, ap)

            T *= self.cooling_rate

        if self.audit_enabled:
            self._flush_audit_files()
        return ap

    # ---------------------------------------------------------------------
    # 审计：一致性验证与日志输出（用于论文附录/复现实验）
    def _audit_constraints(self, layer: int, T: float, ap: List[Solution]) -> None:
        if not ap:
            return
        k = min(self.audit_sample_k, len(ap))
        idx = list(range(len(ap)))
        self.rng.shuffle(idx)
        idx = idx[:k]
        for s_idx, i in enumerate(idx):
            sol = ap[int(i)]
            ok, details = sol.check_paper_constraints(self.problem)
            row = {
                "layer": int(layer),
                "temperature": float(T),
                "ap_index": int(i),
                "sample_index": int(s_idx),
                "ok": int(1 if ok else 0),
            }
            row.update(details)
            self._constraint_rows.append(row)

    def _flush_audit_files(self) -> None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        vns_csv = os.path.join(self.audit_dir, f"audit_vns_moves_{ts}.csv")
        cons_csv = os.path.join(self.audit_dir, f"audit_constraints_{ts}.csv")
        appendix_md = os.path.join(self.audit_dir, f"consistency_appendix_table_{ts}.md")

        # CSV: VNS moves
        if self._audit_rows:
            with open(vns_csv, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(self._audit_rows[0].keys()))
                w.writeheader()
                w.writerows(self._audit_rows)

        # CSV: constraint checks
        if self._constraint_rows:
            with open(cons_csv, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(self._constraint_rows[0].keys()))
                w.writeheader()
                w.writerows(self._constraint_rows)

        # Markdown appendix table: 汇总通过率与关键计数
        total_moves = len([r for r in self._audit_rows if r.get("c_empty", 0) == 0])
        empty_moves = len([r for r in self._audit_rows if r.get("c_empty", 0) == 1])
        accepted_moves = len([r for r in self._audit_rows if r.get("accepted") == 1])

        n_checks = len(self._constraint_rows)
        n_ok = len([r for r in self._constraint_rows if r.get("ok", 0) == 1])
        pass_rate = (n_ok / n_checks) if n_checks > 0 else 0.0

        def sum_field(field: str) -> int:
            return int(sum(int(r.get(field, 0)) for r in self._constraint_rows)) if self._constraint_rows else 0

        binding_v = sum_field("binding_violations")
        comp_v = sum_field("compatibility_violations")
        avail_v = sum_field("availability_violations")
        minskill_v = sum_field("min_skill_violations")

        md = []
        md.append("# 论文一致性验证表（自动生成）\n")
        md.append("该表用于支撑论文中‘实现严格遵循伪代码/约束定义’的可复核证据。\n")
        md.append("## MOSA/VNS 过程统计\n")
        md.append("| 指标 | 数值 |\n|---|---:|\n")
        md.append(f"| VNS 迭代次数（非空候选） | {total_moves} |\n")
        md.append(f"| VNS 空候选次数（C=∅） | {empty_moves} |\n")
        md.append(f"| MOSA 接受次数 | {accepted_moves} |\n")

        md.append("\n## 约束一致性抽样检查（AP 中随机抽样）\n")
        md.append("| 指标 | 数值 |\n|---|---:|\n")
        md.append(f"| 抽样检查次数 | {n_checks} |\n")
        md.append(f"| 全部约束通过次数 | {n_ok} |\n")
        md.append(f"| 通过率 | {pass_rate:.4f} |\n")
        md.append(f"| 人机绑定违约计数（累计） | {binding_v} |\n")
        md.append(f"| 速度-技能兼容违约计数（累计） | {comp_v} |\n")
        md.append(f"| 可用性违约计数（累计） | {avail_v} |\n")
        md.append(f"| 最低可行技能违约计数（累计） | {minskill_v} |\n")

        with open(appendix_md, "w", encoding="utf-8") as f:
            f.write("".join(md))

    def _log_progress(self, phase: str, it: int, T: float, ap: List[Solution]):
        if not ap:
            return
        objs = np.array([s.objectives for s in ap], dtype=float)
        best = objs.min(axis=0)
        self.convergence_history["phase"].append(phase)
        self.convergence_history["iteration"].append(int(it))
        self.convergence_history["temperature"].append(float(T))
        self.convergence_history["n_ap"].append(int(len(ap)))
        self.convergence_history["best_makespan"].append(float(best[0]))
        self.convergence_history["best_labor_cost"].append(float(best[1]))
        self.convergence_history["best_energy"].append(float(best[2]))

    def get_convergence_data(self) -> Dict:
        return self.convergence_history