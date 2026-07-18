# vendor_nsga —— 真实 NSGA-II-VNS-MOSA（论文配套算法，只读）

来源：https://github.com/SugarVei/NSGA-II-VNS-MOSA-1-19
（commit 0ab68e083fa347c905ae49fd6623865d36c33af1，目录 "NSGA-II-VNS-MOSA Algorithm"
下的 models/ 与 algorithms/，UI/实验/可视化部分未纳入）

- 论文主算法：`algorithms/nsga2_vns_mosa.py::NSGA2_VNS_MOSA`
  （两阶段：NSGA-II 全局搜索 + RP/AP 档案下的 VNS+MOSA 精炼；四矩阵编码
  M-Q-V-W；`paper_pseudocode_mapping.md` 与 `tests/test_paper_consistency.py`
  见源仓库）
- `hybrid_variants.py` 中同名类为消融对比变体，不是主算法。
- 本目录代码保持与源仓库逐字一致，不做任何修改（硬性约束"真算法唯一"）；
  与论文口径的度量差异（初始设置 S_0、能耗量纲 kWh、空闲能耗跨度口径）
  由 `src/scheduling/meta_vendor.py` 适配层以"真算法搜索 + 论文口径重评"
  方式处理，不触碰本目录。
