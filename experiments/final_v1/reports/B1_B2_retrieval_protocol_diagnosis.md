# B1/B2 检索协议诊断记录

日期：2026-10-03
实验范围：HyperChE Retrieval v5 / shared qrels

## 1. 记录目的

本文件记录 `chem_prompt_graph`（B1）高于 `chem_prompt_hypergraph`（B2）的原因，避免将该差异误写成“超图结构天然不如二元图”。该诊断不改变论文主线：归一化、measurement、dual_concat 和最终检索组织使超图系统的检索能力明显增强。

## 2. 观测结果

在最终用户接受版 shared qrels、grade≥2 下：

| 系统 | Hit@5 | MRR | gNDCG@5 | CFR@5 |
|---|---:|---:|---:|---:|
| B1 `chem_prompt_graph` | 0.620690 | 0.409134 | 0.312238 | 0.333333 |
| B2 `chem_prompt_hypergraph` | 0.448276 | 0.319448 | 0.232940 | 0.160000 |

逐查询比较：B1 胜出 11 个查询，B2 胜出 1 个查询，46 个查询持平。差异主要出现在高阶、组合和相邻 chunk 任务：

- high-order：B1 0.7143，B2 0.4286；
- compositional：B1 0.5556，B2 0.3889；
- adjacent_chunks：B1 0.875，B2 0.500。

## 3. 已确认的协议差异

### B1

B1 使用 `structured_graph_hybrid_v1`：

- entity dense；
- entity BM25；
- relationship dense；
- relationship BM25；
- weighted RRF；
- incident-edge expansion；
- 无固定 entity/relation 分支配额。

### B2

B2 使用上游 `hyper_query`：

- entity branch 和 relation branch 分开返回；
- entity/relation 各取 10 条；
- 按分支顺序交错合并成 Top-20；
- 保留上游分支排序；
- 没有与 B1 等价的多通道 RRF 和 expansion。

因此 B1/B2 不是只改变“二元边/高阶边”的严格结构消融。

## 4. 候选诊断

B2 的候选池并集 gold recall 实际高于 B1：

- B1 candidate-union gold recall：0.8222；
- B2 candidate-union gold recall：0.8889。

但 B2 在固定分支配额和 Top-20 截断后降至 0.5333，并发生 16 次 quota/top-k loss；B1 没有 quota loss，候选并集和最终 Top-20 均为 0.8222。

典型案例包括：

- `RQ_RFB_011_01`：gold entity rank=17；
- `RQ_RFB_014_01`：gold ranks=77/38；
- `RQ_RFB_023_01`：gold relation rank=27；
- `RQ_RFB_034_01`：gold entity rank=73。

这些候选已经进入 B2 的分支并集，但在固定 10+10 配额或 Top-20 截断中被丢弃。另有少数查询的 gold chunk 未进入分支并集，属于关键词抽取或候选映射失败。

## 5. 可能的工程机制

B1 只保留二元边，候选文本较短，实体和关系词较集中。B2 的完整超边候选包含多个实体、关系描述和证据文本；在当前 BM25/候选文本化方式下，较长文本可能导致查询词稀释和长度归一化影响，使相关超边排序靠后。该机制与 B2 来源更分散但相关命中更少的现象一致：

- B1 平均 Top-5 不同来源数：2.897；
- B2 平均 Top-5 不同来源数：3.621。

这是基于当前实现的工程解释，不应写成超图结构的理论结论。

此外，B2 的正式检索诊断中 `high_order_candidate_count=0`。这意味着本轮 Top-20 结果没有真正利用高阶超边证据，当前 B2 不能代表高阶超图检索的理论上限。

## 6. 对论文核心结论的影响

该问题不削弱论文的核心结论，反而说明：**超图表示需要配合实体归一化、measurement 组织、双文本表示和适合的候选融合，才能发挥作用。**

最终 F1 在完整处理后达到：

- Hit@5：0.672414；
- MRR：0.468397；
- gNDCG@5：0.387291；
- CFR@5：0.426667。

相对原始超图 B0，F1 的 CFR 从 0.093333 提升到 0.426667；相对 B2，Hit@5 提升 22.41 个百分点，CFR 提升 26.67 个百分点。

建议论文表述为：

> 原始化学超图组在当前上游分支配额和候选排序协议下低于二元图组。该差异主要反映原始超图检索适配器、候选合并和超边文本化的限制，不能单独归因于超图结构本身。加入实体/关系归一化、measurement instances 和 dual representation 后，最终超图系统显著增强了化工高阶组合事实的检索覆盖。

## 7. 后续公平实验建议

时间允许时，后续只需做一个小型补充消融：让 B1 和 B2 共用同一套 dense/BM25/RRF/expansion 和候选合并策略，仅改变 arity=2 过滤开关。这样才能独立估计高阶边的结构收益。

本轮论文不重新运行该实验，主文将其作为协议限制和未来工作记录。
