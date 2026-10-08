# 论文数据库数据字典

## 检索

- `P@1`：Top-1 结果达到指定相关性阈值的查询比例。
- `Hit@5`：Top-5 至少命中一个达到阈值的 chunk 的查询比例。
- `MRR`：首个相关 chunk 的倒数排名平均值。
- `gNDCG@5`：基于共享 IDCG 的 graded NDCG。

## 事实覆盖

- `supported_facts`：Top-5 含有精确支持 chunk 的 accepted atomic fact 数。
- `Composite Fact Recall@5`：`supported_facts / 150`。
- `macro_query_CFR@5`：先按 query 计算 CFR，再取宏平均。

## 评价限制

所有 qrels 以 `(query_id, chunk_id)` 为键；来源命中字段因此不构成独立来源级标注。
