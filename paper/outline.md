# HyperChE arXiv 论文大纲 v2

## 0. 版本定位

这一版按照 HyperGraphRAG 的论证顺序重新组织：**完整化工事实例子 → 普通图与超图定义 → HyperChE 构建 → 检索与证据组装 → 研究问题驱动的实验分析**。

论文的中心结论限定为：

> 化工知识中的材料、条件、测量值和性能结果经常组成跨文本块的高阶组合事实。实体/关系归一化、measurement/condition instances、canonical/surface 双表示和混合检索使超图能够更完整地覆盖这些事实。

本文不把结论写成“所有超图实现都优于所有二元图实现”。B1/B2 的检索入口和候选配额不同，B2 的结果作为原始化学超图实现的诊断证据；主要证据来自 B0→F1、B2→F1、CFR 以及 F0→F1 的对照。

## 1. 题目与摘要

### 1.1 暂定题目

**HyperChE: Normalized Hypergraph Retrieval for High-Order Chemical Knowledge**

可选副标题：*Evidence Binding through Entity and Measurement Normalization*。

### 1.2 摘要必须包含

1. 化工事实包含多个实体、条件、测量和结果，二元拆分和文本块检索容易削弱绑定关系；
2. HyperChE 使用化工领域抽取、超图表示、实体/关系归一化、measurement/condition instances、canonical/surface 双表示和混合检索；
3. 数据规模：60 篇文献、1,328 个 chunks、58 个查询、4,196 个 judged query/chunk pairs、150 个 accepted atomic facts；
4. 主结果：F1 grade≥2 Hit@5=0.6724、MRR=0.4684、gNDCG@5=0.3873、CFR@5=0.4267；
5. 对照：B0 Hit@5=0.4828、CFR@5=0.0933；B1/B2 用于解释化学图和原始化学超图的差异；
6. 限制：B1/B2 不是严格单变量实验；历史 QA 与最终 QA 服务条件不同。

## 2. 引言：先用事实说明问题

### 2.1 化工高阶事实的动机例子

先给出一个材料—电解液或膜—操作条件—测量值—性能结果的完整句子，并标出五类角色。说明这些角色共同决定结论，单独保留某个实体或二元关系会削弱对象、条件和结果之间的绑定。

### 2.2 三种知识表示对照

用一张图并列说明：

- 标准 RAG：整段文本块；
- 二元图：拆成多条 pairwise edges；
- HyperChE：一条 hyperedge 连接同一高阶事实中的多个实体、measurement 和 condition。

该图应采用“事实—表示—可检索证据”的叙述方式，避免只画抽象节点。

### 2.3 研究问题

- 如何让超图保留化工高阶事实中的实体、条件、测量和结果绑定？
- 归一化与 measurement 建模是否改善高阶事实覆盖？
- 超图检索的收益来自表示、候选组织还是 rerank？
- 检索证据覆盖能否传递到 QA 的完整性和引用有效性？

### 2.4 贡献

1. 面向化工文献的高阶超图表示和 evidence binding 流程；
2. 实体/关系归一化、measurement/condition instances 与 canonical/surface 双表示；
3. 固定 qrels、共享 IDCG、CFR 和 QA 的可审计评估数据库；
4. 对原始超图、化学 prompt 图、化学 prompt 超图和最终归一化超图的系统分析；
5. 对 B1/B2 协议差异、B2 较低结果和 chunk-level 评价边界的明确诊断。

## 3. 背景与相关工作

### 3.1 化学信息抽取与领域知识图谱

介绍实体、反应、材料、测量和条件抽取，指出化工事实通常具有多实体和多条件结构。

### 3.2 GraphRAG 与 HypergraphRAG

简述普通图 RAG 的二元关系限制，再引用 HyperGraphRAG 的定义—例子—构建—检索—生成结构。

### 3.3 RAG 中的证据绑定与评价

说明 chunk 命中、来源命中和组合事实覆盖分别衡量什么，解释为什么本文采用 CFR 补充 Hit@5。

## 4. 问题定义与表示

### 4.1 普通图和超图

普通图：(G=(V,E))，二元边连接两个实体。

超图：

\[
G_H=(V,E_H),\qquad V_{e_H}=(v_1,\ldots,v_n),\ n\ge2.
\]

高阶事实：

\[
F_n=(e_H,V_{e_H}).
\]

强调普通图是 (n=2) 的特殊情形，超图的重点是保留事实内部的联合绑定。

### 4.2 HyperChE 化工事实单元

定义一个化工事实由实体、关系、measurement、condition、performance 和证据 chunk 组成。给出从原文 surface form 到 canonical form 的映射。

### 4.3 归一化目标

定义实体别名、单位、关系变体和测量表达的规范化，并说明归一化后的表示如何支持跨 chunk 对齐。

### 4.4 检索目标与 CFR

定义给定查询 (q) 的候选 chunk 排序，说明 Hit@5 衡量单个相关证据命中，CFR 衡量一个 composite fact 所需 atomic facts 的覆盖比例。

## 5. HyperChE 方法

### 5.1 文档分块与化工领域抽取

说明文档、chunk、实体、关系和高阶事实的抽取流程，保持原始证据可回溯。

### 5.2 超图构建与证据链接

说明 hyperedge、entity、measurement/condition instances 的存储方式，以及实体—超边—chunk 的关联。

### 5.3 实体和关系归一化

说明 canonical key、别名映射、单位归一化和关系规范化；强调规范化用于对齐，不覆盖原始 surface evidence。

### 5.4 Canonical/surface 双表示

说明 canonical representation 用于匹配和聚合，surface representation 用于证据展示、引用和审计。

### 5.5 混合检索

说明 dense entity、dense relation/hyperedge、BM25 和 RRF 的候选融合。明确 F0/F1 使用同一 hybrid RRF top-50 候选池，唯一开关是最终 rerank。

### 5.6 候选重构与生成

说明从命中的实体和超边恢复相关 chunk，组合跨 chunk 证据，并将证据交给 QA 生成器。记录 EFU repair 始终关闭。

## 6. 实验设置与可审计协议

### 6.1 数据集和固定缓存

- 60 篇文献；
- 1,328 个 chunks；
- 58 个查询；
- 4,196 个 query/chunk qrels；
- 150 个用户接受的 atomic facts；
- Qwen/Qwen3-Embedding-4B，2,560 维；
- EFU repair 关闭。

### 6.2 五组主分析系统

| 系统 | 含义 | 论文用途 |
|---|---|---|
| B0 | original_hypergraph | 原始超图基线 |
| B1 | chem_prompt_graph | 化学 prompt 二元图对照 |
| B2 | chem_prompt_hypergraph | 未归一化化学超图对照 |
| F0 | normalized_final_no_rerank | 归一化最终超图，无 rerank |
| F1 | normalized_final | 归一化最终超图，启用 rerank |


### 6.3 评价指标

- grade≥2 Hit@5：相关证据是否进入前五；
- MRR：首个相关证据的排序质量；
- shared gNDCG@5：在共享 IDCG 下比较排序质量；
- CFR@5：组合事实的 atomic fact 覆盖；
- QA：Good、KPC、Hallucination、Citation validity 等固定字段。

### 6.4 QA 协议与服务披露

40 个 QA，35 个 answerable、5 个 unanswerable，top-k=5，答案最多 1,500 字符，temperature=1.0，top-p=0.95，seed=20260811。最终 QA 使用 kimi-k2.6 和阿里云 DashScope；历史 QA 使用 Moonshot，服务条件不宣称完全一致。

### 6.5 评价边界

说明 source-level 指标由 chunk qrels 推导，不是独立 source-level gold；B1/B2 的检索入口、分支排序和固定 quota 不完全同构。

## 7. 结果分析：按研究问题组织

### RQ1：归一化超图是否改善主要检索指标？

主表报告五组 grade≥2 指标：

| 系统 | Hit@5 | MRR | gNDCG@5 | CFR@5 |
|---|---:|---:|---:|---:|
| B0 | 0.4828 | 0.2832 | 0.1779 | 0.0933 |
| B1 | 0.6207 | 0.4091 | 0.3122 | 0.3333 |
| B2 | 0.4483 | 0.3194 | 0.2329 | 0.1600 |
| F0 | 0.6552 | 0.4683 | 0.3842 | 0.4267 |
| F1 | **0.6724** | **0.4684** | **0.3873** | **0.4267** |

结果叙述采用“数值—现象—机制”：F1 在固定评价协议下取得最高主组结果；相对 B0，CFR 从 0.0933 提升到 0.4267，说明改进集中体现在组合事实覆盖。

### RQ2：哪些表示机制改善高阶事实覆盖？

比较 B0/B2 与 F0/F1，按 fact arity、support mode、question type 和 difficulty 分层。重点分析归一化、measurement instances 和 dual representation 如何减少别名不一致、条件错配和跨 chunk 证据遗漏。

### RQ3：F0→F1 的 rerank 改善了什么？

报告 Hit@5 增加 1.72 个百分点，MRR 变化很小，CFR 保持 0.4267。结论写成：rerank 主要优化候选顺序，组合事实覆盖主要由表示和候选组织决定。

### RQ4：为什么 B2 低于 B1？

将 B2 作为协议诊断案例，引用独立诊断报告：B2 的上游关键词抽取、实体/关系分支顺序和固定 10+10 quota 会截断候选；超边文本更长也可能带来词项稀释和候选分散。由于两组入口不完全同构，不能把差异单独归因于“超图结构”。

### RQ5：检索覆盖是否传递到 QA？

报告 F1 QA 的 Good、KPC、Hallucination 和 Citation validity，并按 answerable、difficulty、fact arity、question type 和 support mode 分层。把 QA 结果与 CFR 联系起来，同时披露最终 QA 和历史 QA 的服务商差异。

## 8. 诊断与案例分析

### 8.1 化工高阶事实案例

展示同一事实在文本块、二元图和归一化超图中的表示，标出 canonical entity、surface evidence、measurement 和 condition。

### 8.2 B1/B2 候选损失案例

展示 gold chunk 已进入候选并集但在 quota/top-k 阶段被截断的查询，解释 B2 结果的协议因素。

### 8.3 失败模式

- 跨 chunk 证据没有同时进入候选；
- measurement 与对象或条件绑定错误；
- 同义实体未归一化；
- 候选过长导致排序信号稀释；
- QA 证据覆盖不足导致答案不完整。

## 9. 讨论

### 9.1 中心结论

超图的价值在于表达高阶组合事实；归一化和证据组织决定这种表示能否被检索利用。F1 的结果支持“超图结构更适合描述化工高阶知识”这一论文主张，具体收益通过 CFR 体现。

### 9.2 方法含义

化工 RAG 应同时维护 canonical matching 和 surface evidence；应把 measurement 和 condition 作为事实内部角色，而不是普通关键词；检索评价应同时报告命中、排序和组合事实覆盖。

### 9.3 对 B1/B2 的解释边界

B1 较高说明当前二元图路径具有更集中的局部匹配信号；B2 较低说明原始超图实现仍受候选组织限制。两者共同说明“结构表达能力”和“检索适配器”需要联合设计。

## 10. 局限与未来工作

1. B1/B2 尚未使用完全统一的检索管线，未来运行公平单变量消融；
2. 259 个同 ID chunks 存在历史 base/chem 文本差异；
3. source-level 指标来自 chunk qrels 推导；
4. 当前没有预注册显著性检验和置信区间；
5. source-level 指标由 chunk qrels 推导，不是独立 source-level gold；
6. QA 服务商差异限制历史 QA 与最终 QA 的严格比较；
7. 后续增加独立 source-level gold、组合证据评价和统一候选池实验。

## 11. 结论

结论只保留三点：

1. 化工知识中的条件、测量和性能经常构成高阶组合事实，超图能以一个事实单元保留其绑定关系；
2. 实体/关系归一化、measurement/condition 建模和 dual representation 使超图检索更能覆盖这些组合事实；
3. rerank 提供有限的排序收益，而主要的事实覆盖收益来自表示和证据组织。

## 12. 图表清单

- Figure 1：化工事实的文本块、二元图和超图对照；
- Figure 2：HyperChE 构建—归一化—检索—证据组装—QA 流程；
- Figure 3：canonical/surface 与 measurement/condition 表示；
- Figure 4：五组 Hit@5、MRR、gNDCG 和 CFR；
- Figure 5：B1/B2 候选损失和 B2 失败案例；
- Table 1：数据集、查询和 qrels 审计；
- Table 2：五组系统配置；
- Table 3：主检索结果；
- Table 4：CFR 分层结果；
- Table 5：F0/F1 rerank 消融；
- Table 6：F1 QA 结果；
- Appendix Table A1：逐查询检索结果与阈值命中；
- Appendix Table A2：shared IDCG、qrels 和 CFR 审计字段；
- Appendix Table A3：F0/F1 候选边界与失败类型；
- Appendix Table A4：实验配置、QA 协议和构建成本记录；
- Appendix Table A5：复现文件、版本和哈希清单。

## 13. 五天执行顺序

- **第 1 天**：确认题目、摘要、化工事实示例、Problem Definition 和主结果表；
- **第 2 天**：完成 Method、实验协议和图 1/图 2；
- **第 3 天**：完成 RQ1--RQ5、CFR、B1/B2 诊断和 QA；
- **第 4 天**：完成 Related Work、Discussion、Limitations、Conclusion 和附录；
- **第 5 天**：统一编译、核对所有数字、检查引用与图表、生成 arXiv 自包含压缩包。

正式分章节起草应在本大纲确认后开始。
