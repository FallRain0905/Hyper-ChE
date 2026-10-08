# 6. Experimental Setup

## 6.1 Corpus, queries, and frozen artifacts

The evaluation uses a fixed chemical literature collection from the flow-battery domain. The collection contains 60 documents and 1,328 frozen source chunks produced with a configured chunk length of 1,000. The retrieval test set contains 58 queries. The shared pooling and judgment process covers 4,196 query--chunk pairs, and every retained pair has a frozen relevance judgment. The composite-fact audit contains 150 user-accepted atomic facts.

The released final cache reports 11,950 entity records, 13,629 relationship records, and 14,676 audited evidence instances. These counts describe the construction and audit artifacts; they are not used as a proxy for retrieval quality. Raw experiment outputs remain preserved in the complete experiment directory, while the paper database contains the retained systems, the accepted qrels, the fact audit, and the derived summaries.

All retained systems use `Qwen/Qwen3-Embedding-4B` with 2,560 dimensions for embedding-based retrieval. EFU repair is disabled for every system. The original caches are treated as read-only inputs. The paper reports the released old-embedding experiment and does not mix it with a different embedding model or a repaired-generation run.

## 6.2 Main systems

The main table retains five systems. Their names and roles are fixed as follows.

| Group | System | Role in the paper |
|---|---|---|
| B0 | `original_hypergraph` | Original hypergraph baseline |
| B1 | `chem_prompt_graph` | Chemistry-prompt binary-graph comparison |
| B2 | `chem_prompt_hypergraph` | Chemistry-prompt, unnormalized hypergraph comparison |
| F0 | `normalized_final_no_rerank` | Normalized hypergraph with reranking disabled |
| F1 | `normalized_final` | Final normalized hypergraph with deterministic reranking |

B0--B2 are retained as system-level comparisons. They should not be read as a strict one-factor ablation: the historical systems differ in extraction, indexing, candidate adapters, and text realization. In particular, the B1 and B2 adapters use different candidate organization choices. The B2 result is therefore interpreted as a diagnosis of an unnormalized hypergraph implementation under its released retrieval protocol, rather than as evidence that hypergraphs are intrinsically inferior to binary graphs.

F0 and F1 form the controlled ablation. They share the same normalized cache, embedding model, hybrid RRF candidate process, and frozen top-50 candidate pool; only the deterministic structural rerank switch differs.

## 6.3 Retrieval protocol

The primary relevance threshold is grade ≥2, with grade ≥3 reported as a stricter sensitivity threshold. The shared qrels use four grades (0--3). For each query, all retained systems are evaluated against the same judged query--chunk set. The main metrics are:

- **P@1:** the proportion of queries whose first result reaches the selected relevance threshold;
- **Hit@5:** the proportion of queries with at least one threshold-reaching result in the top five;
- **MRR:** the mean reciprocal rank of the first threshold-reaching result;
- **shared gNDCG@5:** graded NDCG computed with a query-specific IDCG calculated from the shared candidate judgments; and
- **Composite Fact Recall@5 (CFR@5):** the fraction of the 150 accepted atomic facts whose exact supporting chunk appears in the top five.

The shared-IDCG construction uses the same per-query denominator for every retained system. Five queries have no usable IDCG under the frozen judgment set; they follow the released zero-denominator handling rule and are disclosed in the metric notes. We do not use significance language or claim statistical superiority because this paper version does not include confidence intervals or a formal hypothesis test.

CFR is intentionally stricter than ordinary chunk Hit@5. It requires an exact supporting chunk for an accepted atomic fact, so a related chunk or a matching entity without the fact's condition and result is not counted as complete support. `macro_query_CFR@5` is reported as a complementary query-level summary when needed. The source-level fields in the archive are derived from chunk qrels and are used only as diagnostics; they are not an independent source-level gold standard.

## 6.4 Supplementary QA protocol

QA is a supplementary check on how retrieved evidence is used. The fixed question set contains 40 questions: 35 answerable and 5 unanswerable. The generator receives the top five retrieved chunks, with a 1,500-character evidence budget. The generation configuration uses `kimi-k2.6`, temperature 1.0, top-(p) 0.95, and seed 20260811. EFU repair remains disabled.

The final normalized system uses an Aliyun DashScope service for generation and judging. Historical QA runs for the other retained groups used a Moonshot service. The model name is the same, but the serving providers and service conditions are different. Accordingly, QA numbers are reported as supplementary evidence and are not presented as a fully controlled five-group generation-quality ranking. The primary conclusions are based on retrieval metrics and CFR, which use the shared qrels and frozen fact audit.

This boundary is part of the interpretation of the results. The paper asks whether structured, normalized hypergraph evidence improves retrieval of high-order chemical facts within the frozen structured-evidence protocol. The conclusions remain specific to the retained systems, corpus, queries, and shared evidence judgments.

## 6.5 Reproducibility and audit controls

The reported configuration records the corpus version, cache identifiers, embedding model and dimension, retrieval candidate depths, RRF offset and channel weights, reranking switch, query file hash, qrels audit, composite-fact audit, QA generation settings, and random seed. API credentials are not part of the manuscript or the reproducibility package. The original caches and raw outputs are preserved, and all paper tables are derived from the retained experiment artifacts rather than from manually edited values.

The resulting protocol supports three distinct interpretations: B0--B2 compare released system variants; F0--F1 measure reranking under a shared candidate pool; and CFR tests whether retrieved evidence completes accepted high-order facts. Keeping these interpretations separate prevents a ranking difference caused by an adapter or a chunk-level scoring bias from being mistaken for a general theoretical claim about graph versus hypergraph representations.
