# HyperChE Chemical Entity Normalization

本模块用于在化工文献抽取流程中进行轻量级实体归一化。当前版本不使用 embedding，不做复杂聚类，不做 agent。在线抽取流程默认会对中低置信 fuzzy candidates 调用 LLM 判别。

## 在线接入位置

归一化已经接入 JSON 领域抽取流程内部：

```text
chunk text
  -> Step 1 LLM entity extraction
  -> Step 1N string/alias/fuzzy normalization
  -> Step 2 LLM low/high relationship extraction
  -> relation entity validation
  -> hypergraph write
```

因此关系抽取提示词中的 `K_v_JSON` 会优先使用 canonical entity names。原始名称会保留在 `raw_name` 和 `mentions` 中。

## 归一化策略

当前主流程：

```text
entity mention
  -> normalize_text_for_match()
  -> alias registry exact match
  -> fuzzy top-5 candidates
  -> negative rules
  -> LLM judgement for medium/low-confidence candidates
  -> MERGE / NEED_REVIEW / CREATE_NEW
```

阈值：

- `score >= 95`: 自动 `MERGE`
- `85 <= score < 95`: 默认调用 LLM 判别
- `70 <= score < 85`: 默认调用 LLM 判别，通常仍保留更保守的 review
- `score < 70`: `CREATE_NEW`

如果命中 negative rule，即使 fuzzy 分数很高，也不会自动合并。

## LLM 判别

在线流程默认开启：

```json
{
  "enable_entity_normalization": true,
  "normalization_use_llm": true
}
```

如需关闭：

```json
{
  "normalization_use_llm": false
}
```

LLM 只处理需要判别的 fuzzy candidates，不会处理 exact alias match 和高分自动 fuzzy match。LLM 只能从 `top_candidates` 中选择已有 canonical_id，不能自由选择其他实体。

## 配置文件

主词表：

```text
configs/normalization/alias_registry.yaml
```

负例和高风险规则：

```text
configs/normalization/negative_pairs.yaml
configs/normalization/high_risk_rules.yaml
```

典型阻止合并规则包括：

- `PFOA` 和 `PFOS` 不合并
- `Nafion 117` 和 `Nafion 212` 不合并
- `V(IV)` 和 `V(V)` 不合并
- `BTO` 和 `Pt/BTO/BO` 不合并
- `degradation efficiency` 和 `defluorination efficiency` 不合并

## 在线字段

归一化后的实体会保留：

```json
{
  "raw_name": "N117",
  "mentions": ["N117"],
  "canonical_id": "membrane:nafion_117",
  "canonical_name": "Nafion 117",
  "normalization_method": "exact_alias_match",
  "normalization_confidence": 1.0,
  "need_review": false
}
```

## 日志

每个 chunk 会输出：

```text
Step 1N.1: Condition/unit normalization done
Step 1N.2: Registry loaded
Step 1N.3 entity[i]: initial_decision, candidates
Step 1N.4 LLM request/response
Step 1N.5 final entity[i]: final decision
Step 1N: Entity normalization complete
raw=..., normalized=..., merged=..., alias_matches=..., need_review=..., blocked=..., parsed_values=...
```

## 离线审计脚本

用于审计已有 `.hgdb` 或抽取 JSON：

```powershell
python scripts\normalize_hypergraph.py `
  --input web-ui\backend\hyperrag_cache\case1\hypergraph_chunk_entity_relation.hgdb `
  --output tmp\normalized_case1.json `
  --registry configs\normalization\alias_registry.yaml `
  --negative-pairs configs\normalization\negative_pairs.yaml `
  --negative-pairs configs\normalization\high_risk_rules.yaml `
  --use-llm false `
  --report tmp\normalization_report.json
```

也兼容旧用法：

```powershell
python scripts\normalize_hypergraph.py `
  --input web-ui\backend\hyperrag_cache\case1\hypergraph_chunk_entity_relation.hgdb `
  --output-dir tmp\normalization_case1
```

报告摘要：

```powershell
python scripts\report_normalization.py --report tmp\normalization_report.json
```
