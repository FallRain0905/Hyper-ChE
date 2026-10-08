# Results and Discussion

## 7. Results

### 7.1 RQ1: Is chemical-domain prompting necessary?

We evaluate five retained systems on a frozen collection of 60 chemical documents and 1,328 chunks. The benchmark contains 58 retrieval queries and 4,196 judged query--chunk pairs, with all pairs assigned a final relevance grade. The main retrieval results use the shared \(\mathrm{IDCG}@5\) protocol and report grade-\(\geq 2\) relevance. The five systems are:

- **B0 (original hypergraph):** the original hypergraph cache and retrieval implementation;
- **B1 (chemical-prompt graph):** a chemistry-prompted binary graph;
- **B2 (chemical-prompt hypergraph):** a chemistry-prompted hypergraph without the final normalization and evidence-organization pipeline;
- **F0 (normalized hypergraph, no rerank):** the normalized final cache with reranking disabled;
- **F1 (normalized hypergraph):** the normalized final cache with the deterministic structural reranker enabled.

The same 150 accepted atomic facts are used for Composite Fact Recall (CFR). A fact is counted as supported only when its exact supporting chunk is retrieved within the top five. This criterion is intentionally stricter than ordinary chunk relevance: it measures whether a complete fact has a directly usable evidence unit in the retrieved set.

Relative to B0, the chemistry-prompted systems provide evidence that domain-specific prompting changes the retrieval representation in a useful way, but the effect is not uniformly positive across metrics or adapters. B1 improves grade-(\geq2) Hit@5 from 0.4828 to 0.6207, while B2 reaches 0.4483 on the same headline metric but raises CFR from 0.0933 to 0.1600. Because B1 and B2 use different upstream retrieval adapters, these comparisons answer whether the prompted system configurations are useful; they do not identify a prompt-only causal effect. The result motivates treating prompting as a necessary design factor to test, rather than assuming that a prompt alone guarantees a stronger hypergraph.

### 7.2 RQ2: Does normalization improve retrieval quality?

Table 1 reports grade-\(\geq 2\) retrieval performance. F1 obtains the best result on every primary ranking metric retained for the main comparison.

| System | P@1 | Hit@5 | MRR | gNDCG@5 |
|---|---:|---:|---:|---:|
| B0: original hypergraph | 0.1897 | 0.4828 | 0.2832 | 0.1779 |
| B1: chemical-prompt graph | 0.2759 | 0.6207 | 0.4091 | 0.3122 |
| B2: chemical-prompt hypergraph | 0.2241 | 0.4483 | 0.3194 | 0.2329 |
| F0: normalized hypergraph, no rerank | 0.3276 | 0.6552 | 0.4683 | 0.3842 |
| F1: normalized hypergraph | **0.3276** | **0.6724** | **0.4684** | **0.3873** |

The final normalized system improves substantially over B0. Hit@5 increases from 0.4828 to 0.6724 (+18.97 percentage points), MRR increases from 0.2832 to 0.4684 (+0.1852), and gNDCG@5 increases from 0.1779 to 0.3873 (+0.2094). F1 also exceeds B1, the strongest retained binary-graph comparison, by 5.17 percentage points in Hit@5, 0.0593 MRR points, and 0.0751 gNDCG points. At the stricter grade-\(\geq 3\) threshold, F1 reaches a Hit@5 of 0.5690, compared with 0.5345 for B1, 0.3793 for B2, and 0.3621 for B0. Thus, the advantage of F1 is not limited to lower-grade relevant chunks under the current judgment scale.

These results support the narrower claim that the normalized hypergraph pipeline is effective for the present chemical high-order-fact retrieval task. They do not imply that every hypergraph implementation is better than every binary graph. In particular, B2 is below B1, which makes the representation and retrieval pipeline jointly important.

### 7.3 RQ2 continued: Does normalization improve complete-fact recall?

CFR provides a complementary view of whether the retrieved evidence preserves a complete chemical fact rather than only a locally relevant fragment.

| System | Supported facts / 150 | CFR@5 | Macro query CFR |
|---|---:|---:|---:|
| B0: original hypergraph | 14 | 0.0933 | 0.1963 |
| B1: chemical-prompt graph | 50 | 0.3333 | 0.3213 |
| B2: chemical-prompt hypergraph | 24 | 0.1600 | 0.2011 |
| F0: normalized hypergraph, no rerank | 64 | 0.4267 | 0.4324 |
| F1: normalized hypergraph | **64** | **0.4267** | **0.4324** |

F1 supports 64 of the 150 accepted facts, compared with 14 for B0 and 50 for B1. Its CFR is therefore 0.4267, 0.3333 for B1, and 0.0933 for B0. This is the clearest evidence that the final pipeline improves coverage of complete, multi-role facts under the exact-chunk criterion. At the same time, 86 of the 150 facts are still not fully supported in the top five. The remaining gap indicates that cross-chunk evidence aggregation, candidate diversity, and retrieval of less lexically salient conditions remain unresolved.

CFR and Hit@5 should be interpreted together. Hit@5 can improve when one relevant fragment is retrieved, whereas CFR requires the exact supporting chunk for an accepted atomic fact. The higher CFR of F0/F1 therefore indicates a change in evidence coverage, not only a change in the ordering of individually relevant chunks.

### 7.4 RQ3: Where does the final-system advantage come from?

The final-system advantage is visible at three levels: the normalized fact representation, the hybrid candidate organization and recall pool, and the ordering applied after candidate generation. The results below separate these levels as far as the released experiments allow.

#### Why B2 is below B1

The B2 result should not be interpreted as evidence that hypergraph structure is intrinsically inferior to a binary graph. B1 and B2 are not a strict one-variable ablation. Their upstream retrieval adapters differ in several operational respects.

B1 uses a structured graph hybrid pipeline with entity dense retrieval, entity BM25, relationship dense retrieval, relationship BM25, weighted reciprocal-rank fusion, and incident-edge expansion. It does not impose a fixed quota between entity and relationship branches. B2 uses the upstream hyper_query interface, which returns separate entity and relation branches, takes ten results from each branch, interleaves them, and applies a top-20 cutoff while preserving the branch order. It therefore has a fixed 10+10 allocation and lacks a pipeline equivalent to B1's multi-channel fusion and expansion.

The candidate diagnostics are consistent with this explanation. Before the final branch quota and top-20 cutoff, the B2 candidate union has a higher gold recall than B1 (0.8889 versus 0.8222). After the B2 quota and truncation, its effective candidate recall falls to 0.5333, with 16 query-level quota or top-k losses. B1 has no corresponding quota loss in this diagnostic. Several B2 queries contain a gold entity or relation at a rank that is already outside the fixed branch budget, so the relevant candidate is discarded even though it appeared in a broader branch union.

The textual form of candidates may also contribute. B2 represents complete hyperedges with multiple entities, relation descriptions, and evidence text. Under the current BM25 and candidate-text construction, these longer descriptions can dilute query terms and place a relevant hyperedge lower in the branch ranking. This is an implementation-level explanation, not a theoretical property of hypergraphs. The current B2 top-20 diagnostic also reports no high-order candidate selected in the returned set, which means that this particular B2 adapter does not measure the full potential of high-order retrieval.

Accordingly, the paper treats B2 as an unreconstructed, chemistry-prompted hypergraph baseline and reports its limitations explicitly. A strict structural ablation would require B1 and B2 to share the same dense/BM25/RRF/expansion pipeline, candidate budget, textualization procedure, and reranking policy, with only the arity restriction changed. That controlled experiment is left for future work.

### 7.5 RQ4: What does reranking add after candidate generation?

F0 and F1 use the same hybrid RRF top-50 candidate pool. The only intended difference is whether the deterministic structural reranker is applied after candidate generation.

| Metric | F0 (no rerank) | F1 (rerank) | Difference |
|---|---:|---:|---:|
| P@1 | 0.3276 | 0.3276 | 0.0000 |
| Hit@5 | 0.6552 | 0.6724 | +0.0172 |
| MRR | 0.4683 | 0.4684 | +0.0001 |
| gNDCG@5 | 0.3842 | 0.3873 | +0.0031 |
| CFR@5 | 0.4267 | 0.4267 | 0.0000 |

Reranking produces a small improvement at the top-five boundary: Hit@5 increases by 1.72 percentage points and gNDCG@5 increases by 0.0031. MRR changes by only 0.0001, and CFR is unchanged. Because the candidate pool is frozen before reranking, the unchanged CFR is expected: F1 can reorder existing candidates but cannot introduce a fact that was absent from the top-50 pool.

This ablation separates two effects. The major improvement over B0/B1 is associated with the normalized representation and its hybrid candidate-generation pipeline. The current reranker supplies a limited ordering refinement rather than a new source of fact coverage. Future gains should therefore prioritize candidate recall, cross-chunk aggregation, and source diversity before adding more ranking complexity.

### 7.6 RQ3 continued: Evidence-source diversity and failure patterns

As a diagnostic derived from chunk-level qrels, F1 retrieves an average of 2.121 distinct source documents in its top five, with a duplicate ratio of 0.576. F0 has 2.103 distinct sources and a duplicate ratio of 0.579. B0, B1, and B2 have respectively 3.586/0.283, 2.897/0.421, and 3.621/0.276 for these two quantities.

The lower source diversity of F0/F1 indicates that higher chunk-level relevance is sometimes obtained by repeatedly retrieving evidence from the same source. This concentration is compatible with the unchanged F0/F1 CFR: reranking can promote a relevant chunk from an already retrieved source without increasing the number of independently supported facts. These source statistics are descriptive diagnostics computed from chunk qrels; they are not an independently annotated source-level gold standard.

The retained per-query inspection identifies three recurring failure patterns:

1. **Missing cross-chunk evidence:** one part of a fact is retrieved, but the condition or outcome required to establish the complete fact is absent from the top five;
2. **Condition binding errors:** a material or performance value is retrieved without the operational condition that scopes it;
3. **Incomplete comparison pairing:** evidence for one side of a comparison is retrieved, while the corresponding material, baseline, or measurement for the other side is missing.

These patterns explain why a system can obtain a relevant top-ranked chunk while still failing the stricter composite-fact criterion.

### 7.7 RQ4 continued: QA as a supplementary check and protocol boundary

The final QA run contains 40 questions: 35 answerable and 5 explicitly unanswerable. It uses top-\(k=5\) retrieved evidence with a 1,500-character evidence budget, temperature 1.0, top-\(p=0.95\), and seed 20260811. The generation and judging model is kimi-k2.6 served through Alibaba Cloud DashScope for F1. EFU repair is disabled.

| QA measure | F1 |
|---|---:|
| Good Rate | 0.2500 |
| Satisfactory-or-Better Rate | 0.5000 |
| Macro KPC | 0.4633 |
| Micro KPC | 0.4825 |
| Hallucination Rate | 0.2000 |
| False Abstention Rate | 0.1714 |
| False Answer Rate | 0.0000 |
| Unanswerable Abstention Accuracy | 1.0000 |
| Citation Reference Validity | 1.0000 |
| Citation Presence Rate | 0.7250 |
| Citation Support Score | 0.4649 |

Half of the questions reach satisfactory-or-better quality, and all cited references that are produced are valid under the QA audit. The false-answer rate is zero, while hallucination and false-abstention rates show that incomplete evidence still limits answer completeness and calibration. The QA results therefore provide a consistency check on the retrieval analysis rather than a replacement for it.

Historical QA runs for earlier groups used a Moonshot service, whereas F1 used Alibaba Cloud DashScope. The model name alone does not make these service conditions identical. We therefore do not use the QA records to claim a fully controlled five-group generation ranking. The service difference is reported as part of the experimental boundary.

## 8. Discussion

### 8.1 What the results say about chemical hypergraph retrieval

Chemical literature often states a result through a joint constraint over several roles: a material or component, a composition, an operating condition, a measurement or range, and a performance outcome. The retrieval objective is not merely to find any chunk mentioning one of these terms. It is to preserve the binding that makes the combination a usable fact.

The F1 results are consistent with this view. Relative to B0 and B1, F1 retrieves more complete atomic facts under the exact-supporting-chunk criterion and also improves conventional ranking metrics. The evidence supports the use of a hypergraph-oriented organization for this class of facts when the hypergraph is coupled with domain normalization and an appropriate retrieval adapter. It does not support the stronger statement that hypergraph structure alone guarantees an improvement.

### 8.2 Normalization is a retrieval mechanism, not only data cleaning

The final pipeline normalizes entity and relation variants, models measurement and condition instances, and keeps canonical and surface forms together. Canonical forms allow aliases, units, and relation variants to match during retrieval and aggregation. Surface forms preserve the wording and evidence pointers needed for citation and audit.

The difference between B2 and F1 is therefore best interpreted as a system-level transition from an unnormalized, quota-constrained hypergraph adapter to a normalized, evidence-oriented retrieval pipeline. The present results cannot isolate the contribution of each component because the comparison changes extraction, indexing, textualization, candidate fusion, and representation together. They do show that a high-order representation becomes more useful when its entities, relations, measurements, conditions, and evidence pointers are organized consistently.

### 8.3 Recall and ranking should be improved in that order

The F0/F1 comparison shows that reranking is not the main source of the observed gain. F0 already reaches CFR@5 = 0.4267, equal to F1, while F1 provides only a modest Hit@5 improvement. Once a complete fact is absent from the candidate pool, a downstream ranker cannot recover it. This places the highest priority on improving candidate generation, preserving cross-chunk links, and balancing source diversity.

The source-diversity diagnostic further suggests a trade-off. F1's top five are more concentrated within the same source than B1 or B2, which may help local relevance but reduce the chance of collecting complementary evidence from different sections or papers. A future aggregation stage could explicitly reward complementary fact roles and penalize redundant source selections, while retaining the exact evidence pointer needed for audit.

### 8.4 Interpreting the binary-graph comparison

B1 is a useful retained comparison because it is a strong chemistry-prompted binary graph, but it should not be treated as a perfectly controlled counterpart to B2. Its stronger result reflects both the binary representation and a different retrieval adapter. The B2 diagnosis shows that candidate quotas and ranking behavior can dominate the observed outcome before the representation is evaluated.

For this reason, the main conclusion is framed around the complete normalized pipeline: F1 is stronger than the retained baselines under the shared qrels protocol, while B2 exposes the need to co-design hypergraph representation and retrieval. A fair arity ablation is an important next experiment, but it is not required to state the bounded empirical result obtained here.

### 8.5 QA interpretation and practical meaning

The QA results show a useful but incomplete transfer from retrieval to generation. Valid citations and zero false answers indicate that the evidence interface is auditable. However, the Good Rate of 0.25 and Hallucination Rate of 0.20 show that evidence coverage and fact binding still constrain practical answer quality. This is especially relevant for high-order chemical questions, where a response may need a material, a condition, a measurement, and a comparative outcome at once.

Because F1 and earlier QA groups were served by different providers, QA should be reported as a supplementary end-to-end check. The primary scientific evidence remains the shared retrieval evaluation and the exact-supporting-chunk CFR.

### 8.6 Scope of the claim

The current evidence supports four bounded conclusions:

1. The normalized hypergraph pipeline improves retrieval quality over the retained original hypergraph and chemistry-prompted binary/hypergraph baselines on this frozen chemical benchmark.
2. It recovers more complete atomic facts at top five than those baselines under the accepted exact-chunk CFR protocol.
3. The deterministic reranker gives a small ordering benefit after candidate generation but does not increase complete-fact coverage.
4. Hypergraph structure alone is insufficient; normalization, fact-role organization, candidate fusion, and evidence textualization jointly determine performance.

These conclusions are limited to the 60-document benchmark, the frozen qrels, the Qwen/Qwen3-Embedding-4B 2560-dimensional embedding configuration, and the stated retrieval and QA protocols. No claim of statistical significance or broad cross-domain generalization is made in this draft.
