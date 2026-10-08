# HyperChE 最终实验组计划实施报告

## 一、报告目的

本报告记录当前已经确认的实验决策，并明确后续实施阶段。本报告只记录现有项目的实验规划，不包含新的代码改动。

## 二、当前已经确定的决策

### 1. 放弃 EFU repair

当前 EFU repair 采用局部规则补全超边节点，不能重新理解原文，无法可靠解决复杂条件、比较实验和多事实绑定问题。最终方案中取消：

```text
enable_efu_repair = false
```

不再设置 `final_no_repair`，也不引入新的 LLM-based EFU repair。

### 2. 最终组的组成

最终组定义为：

```text
化学领域 prompt
+ one-pass 抽取
+ 实体/关系归一化
+ measurement instances
+ canonical/surface dual_concat
+ hybrid retrieval/rerank
+ EFU repair 关闭
```

处理流程为：

```text
化学领域抽取
→ 实体和关系归一化
→ 数值、单位和条件结构化
→ 生成 canonical/surface 双文本
→ 建立实体和关系向量
→ 混合检索与重排
```

### 3. 不重新构建已有基线

以下缓存和结果继续保留：

```text
hyper_base
hyper_chem_prompt
```

它们不因最终组改变而重建。

### 4. 当前最终缓存不能直接使用

当前 `hyper_final` 只有少量文档和 chunk，不能作为完整 60 文档最终组。完整最终组需要从现有的 `hyper_chem_prompt` 出发，通过后处理归一化生成新的目标缓存，不覆盖原缓存。

## 三、实验组规划

### 3.1 正式检索实验：7 组

#### 主比较组：5 组

| 编号 | 组名 | 实际方法 | 作用 |
|---|---|---|---|
| B0 | Original Hypergraph | `hyper_base` + 原始 hyper-query | 原始 Hyper-RAG 基线 |
| B1 | Chem-Prompt Binary Graph | 化学 prompt + 二元图结构检索 | 观察化学 prompt 和二元图效果 |
| B2 | Chem-Prompt Hypergraph | 化学 prompt + 超图检索 | 当前化学超图基线 |
| B3 | Hybrid Text | BM25 + dense + RRF | 强文本基线 |
| F1 | Normalized Final | 归一化 + measurement + dual_concat + rerank，EFU 关闭 | 最终方法 |

#### 机制解释组：2 组

| 编号 | 组名 | 实际方法 | 作用 |
|---|---|---|---|
| R1 | C-HG + Chunk Dense Rerank | 化学超图候选 + frozen chunk cosine 重排 | 观察 chunk 重排收益 |
| F0 | Normalized Final without Rerank | 归一化 + measurement + dual_concat，关闭 rerank，EFU 关闭 | 区分结构化知识收益和 rerank 收益 |

因此正式检索实验共 7 组，其中 `F0 → F1` 用于判断最终组中的 rerank 是否带来额外收益。

### 3.2 正式 QA 实验：建议 5 组

当前正式 QA 的四组继续保留：

```text
B0 Original HG
B1 Chem-Prompt Graph
B2 Chem-Prompt Hypergraph
B3 Hybrid Text
```

增加 `F1 Normalized Final`，正式 QA 主实验共 5 组。F0 和 R1 首先作为检索层消融；只有需要研究 rerank 对最终回答质量的影响时，再将 F0 加入 QA。

## 四、是否需要重新建库

### 4.1 不需要重建的部分

以下内容可以直接复用：

- `hyper_base`
- `hyper_chem_prompt`
- 60 篇文献
- 1328 个 frozen chunks
- 现有 chunk 切分
- 现有 chunk embedding
- 已完成的 B0–B3 结果
- 已完成的 R1 检索方案

### 4.2 需要重新生成的部分

最终组需要生成新的 normalized cache，因为以下内容会变化：

- canonical entity
- canonical relation
- measurement nodes
- condition nodes
- canonical/surface embedding text
- entity vector store
- relationship vector store
- 最终检索配置

因此需要重新生成归一化后的图结构、measurement/condition 结构、实体向量、关系向量和 dual_concat 索引。

### 4.3 是否需要重新跑全部 LLM 抽取

不一定。当前 `hyper_chem_prompt` 已经完成化学 prompt、one-pass 抽取和 60 篇文献的原始实体、关系和超边。因此优先采用后处理路线：

```text
hyper_chem_prompt
→ 归一化候选生成
→ LLM 判断模糊实体
→ 重写图结构
→ 重新生成实体/关系向量
→ 验证
→ 发布新 cache
```

当前 `hyper_norm_posthoc_v1.work` 就是这条路线的中间结果。这里的 LLM 只用于归一化候选判断，不用于 EFU repair。

### 4.4 向量重建范围

需要重新生成：

- 规范化后的实体向量
- 规范化后的关系/超边向量
- `dual_concat` 对应的新 embedding

在文档集合、chunk 切分、embedding 模型和维度不变时，原始文本 chunk 及其 frozen embedding 可以复用。

## 五、下一步实施阶段

### 阶段 0：冻结实验决策

确认并记录：

```text
enable_efu_repair = false
enable_entity_normalization = true
enable_measurement_instances = true
index_profile = dual_concat
enable_hybrid_rerank = true
```

同时固定 60 篇文献、1328 个 chunk、embedding 模型和维度、query 文件、top-k、QA 生成模型、评审模型和 evidence budget。

### 阶段 1：验收源缓存

检查 `hyper_chem_prompt`：

- 文档数为 60
- chunk 数为 1328
- chunk ID 稳定
- chunk embedding 完整
- 实体和关系原始字段存在
- source cache 只读

### 阶段 2：完成归一化后处理

继续使用 `hyper_norm_posthoc_v1.work`，完成候选生成、模糊候选 LLM 判断、canonical entity map 构建、图结构重写、measurement/condition 保留、EFU repair 关闭、新建实体和关系向量以及发布新 target cache。

### 阶段 3：最终缓存验收

最终缓存必须满足：

- 60 篇文档
- 1328 个 chunk
- corpus manifest 完整
- run_config 与最终方案一致
- `enable_efu_repair=false`
- normalization 字段完整
- measurement/condition 字段完整
- canonical 和 surface 字段存在
- entity/relation vector 数量与图结构一致
- embedding 模型和维度一致

验收未通过时，不进入正式评估。

### 阶段 4：运行正式检索实验

运行：

```text
B0、B1、B2、B3、R1、F0、F1
```

所有组使用同一 query 文件、同一 frozen chunk 集、同一 shared qrels、同一 IDCG 和同一 top-k。

主要指标：

- P@1
- Hit@5
- MRR
- shared gNDCG@5
- Source-level Hit@5
- Composite Fact Recall

### 阶段 5：运行正式 QA 实验

运行：

```text
B0、B1、B2、B3、F1
```

固定同一 40QA 文件、同一生成模型、同一 judge、同一 evidence budget、同一 top-k 和同一回答评价标准。

主要指标：

- Good
- Key Point Coverage
- Groundedness
- Hallucination
- Answerable Empty
- Unanswerable Abstention

### 阶段 6：结果归因与报告

重点比较：

1. `B2 vs F0`：归一化和 measurement 是否带来收益；
2. `F0 vs F1`：rerank 是否带来额外收益；
3. `B2 vs R1`：chunk dense rerank 的独立收益；
4. `F1 vs B3`：最终结构化方法是否超过强文本基线。

最终结论必须区分化学 prompt、超图结构、归一化和 measurement、rerank 各自的影响，不能把所有变化统一归因于“最终组”。

## 六、当前执行边界

1. 不修改或覆盖 `hyper_base`、`hyper_chem_prompt`。
2. 不把当前不完整的 `hyper_final` 当作最终结果。
3. 不把旧版五组 QA 结果与新正式 QA 直接合并。
4. 不再启用 EFU repair。
5. 不新增 LLM-based EFU repair。
6. 不在最终缓存验收前运行正式结论实验。
7. 不把 R1 的 chunk rerank 结果误称为 normalized final 结果。

## 七、当前状态总结

已经完成：

- 基线缓存
- 化学 prompt 缓存
- 现有四组正式检索/QA 对照
- chunk dense rerank 方案
- 归一化模块和后处理工具

尚未完成：

- 去掉 EFU repair 后的完整 normalized final cache
- F0/F1 正式检索结果
- F1 正式 QA 结果
- 最终组的完整归因分析

下一步核心任务：

> 从完整的 `hyper_chem_prompt` 出发，生成一个 60 文档、EFU repair 关闭、归一化和 measurement 开启、dual_concat 完整的最终缓存，然后运行 F0/F1。

## 八、旧模型执行路线更新（2026-10-01）

### 1. 模型与费用决策

用户最终选择继续使用硅基流动 `Qwen/Qwen3-Embedding-4B`，2560 维。新增五个 key 已分别验证 embedding 返回 HTTP 200、2560 维。此次只重建最终组的实体与关系向量，复用基线与 frozen chunk 向量；不执行统一阿里模型的全量向量重建。

### 2. 已发布中间库的边界

`hyper_norm_posthoc_v1` 已完成归一化、校验和发布。其实体/关系为阿里 `qwen3.7-text-embedding`，chunk 为旧模型，且 measurement 与 dual_concat 未开启，因此它仅作为 canonical map 和判定记录来源，不能直接参加正式最终组检索。

32,582 个候选都有判定记录，其中 260 个 API 失败候选按 UNCERTAIN 保留，不合并。不得将“判定记录齐全”表述为所有 LLM judge 调用成功。

### 3. 完整 final 的离线准备

新目标为 `hyper_final_posthoc_v1`，工作目录为同名 `.work`。已从原始缓存恢复 1,322 个 chunk 的实体数组，六个未匹配 chunk 在源图中没有结构抽取，不补跑全文 LLM。

实现入口：

- `scripts/build_final_cache_posthoc.py`
- `hyperche/normalization/final_cache.py`

流程为 prepare → embed → validate → publish，可断点恢复。prepare 复用既有 canonical 判定，并从逐 chunk 的原始数值字段创建 measurement/condition。对多值、部分区间或语义不明确的字段保留原结构，记录原因，不猜测数值归属。每条原始 evidence instance 都有重写审计；只替换该关系原有节点，不添加缺失节点，EFU repair 关闭。

当前准备结果：11,950 个实体、13,629 条关系，其中 415 个 measurement 节点、514 个 condition 节点，2,155 条局部实例记录。canonical/surface 两段使用既有双文本构造函数。修正了 energy density 被误判为 energy efficiency 的规则；历史 canonical ID 与实例 ID 相撞时区分身份，不覆盖节点。

### 4. embedding 执行与验收

五个 key 分别使用持久客户端，5 路并发，每批 16 条，单次硬超时 120 秒。约 25,579 条向量、1,599 批请求。使用批次二进制断点避免每批重写整个大型 JSON；最终才导出完整向量文件。断点验证模型、维度和文本签名，禁止复用中间库的阿里向量。

发布前检查文档/chunk 数量、原缓存校验和、图与向量一一对应、模型与维度一致、实例数值为标量或明确区间、关系来源局部绑定、双文本存在、EFU 关闭。F0/F1 检索和 F1 QA 仍须在发布验收后运行；增加最终组候选后，补齐共享 qrels，并为七组共用同一 IDCG 重算指标。

已恢复每 30 分钟检查与推进。进度无实质变化时保持安静；完成、失败或需要人工处理时通知。

### 5. F0/F1 的可执行检索定义

`scripts/final_graph_retrieval.py` 复用现有 StructuredGraphIndex 的实体/关系 dense、BM25、weighted RRF 和 incident expansion。两组先冻结同一 RRF top-50 关系候选池，再重构相同 chunk 候选集合；F0 按 RRF 顺序输出，F1 使用现有词项覆盖与多实体共同支持的确定性结构重排（0.004 × lexical coverage + 最多 0.003 的 structure bonus）。不新增付费 reranker、不根据 gold 调整候选或权重。

入口 `scripts/run_final_retrieval.py` 固定原 58-query 文件校验和、top-k=20，保存 F0/F1 的共同候选审计与逐 chunk 来源描述。最终指标另用共享 qrels 计算。F0/F1 仅改变重排开关；B2 与 F0 的检索核不同，因此其差值反映整套 final 索引与混合检索的效果，不能单独归因为实体归一化或 measurement。若需要纯归一化归因，须另做同检索核对照，不能从现有七组直接得出。

历史 B0 与 chemistry 的 chunk ID 一致，但有 259 个 chunk 文本不同。本次保持历史基线协议并披露该限制，不宣称所有组文本逐字节一致。

### 6. 后续自动推进入口

`scripts/continue_final_experiment.py` 等待最终库验收并发布，随后断点推进：F0/F1 检索 → 保留原五组结果、合并七组 Top-20 候选 → 复用旧 qrels、仅标注新增候选 → 七组共用 IDCG 重算 → F1 40QA。进度记录在缓存根目录 `hyper_final_experiment_v1_state.json`，产物位于 `outputs/final_experiment_v1_old_embedding`。不得在已有推进进程存活时重复启动。

新增 qrels 保持原 `Qwen/Qwen3.5-35B-A3B` 标注模型，新硅基接口已实测成功；QA 阿里接口的 `kimi-k2.6` 也已实测成功。QA 冻结题目、模型名、生成/评审规则及参数，但服务商由历史 Moonshot 改为阿里；此差异是可比性限制，不能表述为服务条件完全一致。未覆盖历史四组 QA 产物。

主评估结束后仍需补齐 Source-level Hit@5、Composite Fact Recall、共享 qrels 审计、五组 QA 比较和归因报告。总进度中的 `reporting_pending=true` 表示这些阶段尚未完成，不能把数值计算完成当作全部实验结论完成。

### 7. 本轮建库实测结果

最终库已通过校验并发布为 `hyper_final_posthoc_v1`：60 文档、1,328 chunks、11,950 个实体向量、13,629 条关系向量；14,676 个原始 evidence instances 均保留重写审计。实体/关系及复用的 chunk 向量统一为旧模型 2560 维，原缓存校验和不变。

embedding 主阶段实测耗时 742.9 秒（约 12.4 分钟），共 1,600 次请求；其中 1 次请求失败后切换 key 成功恢复。五个 key 的成功请求数分别为 319、321、320、320、319，确认全部实际参与。未读取服务商账单，不把请求数换算成未经核实的费用。

F0/F1 均已完成 58-query 检索，共同候选池校验通过。目前进入共享 qrels 增量标注，正式结论仍待完整指标、QA 和审计完成。
