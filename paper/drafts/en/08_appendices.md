# Appendix

The appendices follow the reproducibility-oriented organization used by HyperGraphRAG: prompt interfaces, construction and retrieval algorithms, data and judgments, evaluation protocol, configuration, detailed audit outputs, cost accounting, and the reproducibility manifest.

## Appendix A. Chemical fact extraction and query interfaces

### A.1 Extraction interface

The offline extraction prompt asks the model to segment each frozen source chunk into self-contained chemical fact records. The output schema preserves:

- a fact or relationship description;
- entity mentions with role, surface form, and canonical form when available;
- measurement instances with value or interval, unit, comparator, and measured object;
- condition instances such as composition, temperature, flow, loading, or operating mode;
- property or outcome roles;
- source chunk identifier and evidence span; and
- an extraction completeness or uncertainty field when the source statement is incomplete.

The prompt keeps roles that belong to the same experimental statement together and leaves unavailable roles empty. It must not fill a missing condition or result by combining unrelated chunks. Service credentials are never part of the prompt or paper package.

### A.2 Query parsing interface

The online query parser returns structured search cues rather than an answer: entity and material mentions, relation or outcome terms, measurement and unit cues, condition terms, normalized aliases when available, and the original query text for evidence tracing. The parser keeps the input language and does not invent a chemical fact.

### A.3 Evidence-grounded QA interface

The QA interface receives the query and the reconstructed top-five source chunks. The prompt requires an answer supported by the supplied evidence, citations or source pointers when available, and explicit abstention when evidence is insufficient. It does not perform EFU repair or retrieve extra evidence.

## Appendix B. HyperChE construction and online retrieval

### B.1 Offline construction

    Input: frozen documents D
    For each source chunk:
        extract chemical fact records and evidence spans
        normalize entities, relations, measurements, and units
        retain canonical and surface forms
        create a hyperedge-like fact object with typed roles
        link the fact object to incident entities and source chunks
    store incidence structure and evidence pointers
    build entity and fact-object dense and lexical indexes
    audit normalization rewrites and cache integrity
    Output: normalized HyperChE cache

A bipartite incidence structure is used as a storage representation. The semantic object remains the fact object together with its member set, typed roles, and evidence pointer.

### B.2 Online retrieval and generation

    Input: query q
    parse q into entity, relation, measurement, and condition cues
    retrieve entity and fact-object candidates from dense and lexical indexes
    fuse lists with weighted RRF
    expand retrieved entities through incident fact objects
    map structured candidates back to source chunks
    construct the common hybrid RRF top-50 candidate pool
    apply the deterministic reranker only for F1
    return the top-five reconstructed chunks to the QA interface
    Output: ranked evidence and optional grounded answer

F0 and F1 use the same candidate pool. The only switch between them is the deterministic structural reranking stage after candidate generation.

### B.3 Construction and retrieval complexity

Let D be the number of documents, r the maximum number of extracted facts per document, and n the maximum number of entities or typed roles per fact. Under a constant prompt cost per document, extraction requires model calls proportional to D. Fact-object insertion is O(D r), incidence writes are bounded by O(D r n), and embedding the final entity and fact-object sets requires O(|V| + |E_H|) encoder calls. These are structural upper bounds; actual wall-clock cost depends on token length, batching, retries, and the index implementation.

For a query, dense or lexical lookup has a linear-scan upper bound of O(|V| + |E_H|). One-hop expansion is bounded by O(k d), where k is the retrieved candidate count and d is the average incident degree. Source reconstruction and deterministic reranking add costs proportional to candidate-pool size and evidence length. Approximate nearest-neighbor indexes can reduce practical lookup cost.


## Appendix C. Dataset, qrels, and Composite Fact Recall

The frozen evaluation contains 60 chemical documents, 1,328 source chunks, 58 queries, 4,196 judged query--chunk pairs, and 150 user-accepted atomic facts. The source chunks and query files are frozen before the retained-system comparison.

The shared qrels use grades 0--3. The primary threshold is grade >= 2, with grade >= 3 reported as a stricter sensitivity view. Every retained system is evaluated against the same judged query--chunk pairs and the same per-query IDCG denominator. Five queries have no usable IDCG under the frozen judgment set and follow the released zero-denominator handling rule.

Composite Fact Recall at k is defined over the 150 accepted atomic facts. An atomic fact is counted as supported only when its exact supporting source chunk appears in the top-k result list. A related chunk, matching entity, or partial condition does not count as complete support. Source-level hit and diversity fields are derived from chunk qrels and are diagnostic rather than independently annotated source-level gold.

The audit package contains the accepted fact file, the qrels audit, and the derived CFR summaries. The full 4,196-row qrels table is kept as a supplementary artifact rather than embedded in the paper body.

## Appendix D. Evaluation and QA protocol

All retained systems use Qwen/Qwen3-Embedding-4B with 2,560 embedding dimensions. The original caches are read-only inputs and EFU repair is disabled throughout retrieval and QA.

The retained system views are:

| System | Configuration |
|---|---|
| B0 | original hypergraph |
| B1 | chemistry-prompt binary graph |
| B2 | chemistry-prompt unnormalized hypergraph |
| F0 | normalized hypergraph with reranking disabled |
| F1 | normalized hypergraph with deterministic reranking |

The normalized retrieval configuration uses entity and relationship dense and BM25 channels, one-hop incident-fact expansion, relationship candidate depth 50, entity candidate depth 30, and RRF offset 60. F0 and F1 share the hybrid RRF top-50 candidate pool; F1 applies the deterministic structural reranker after candidate generation.

The released configuration uses relationship dense and BM25 weights of 1.0 and entity dense and BM25 weights of 0.8. The expansion weight is 0.9, expansion depth is one hop, the maximum expanded fact-object count is 100, and the chunk candidate depth is 30. The final QA run uses three parallel workers with 120-second model and embedding timeouts.

Retrieval metrics are P@1, Hit@5, MRR, shared gNDCG@5, and Composite Fact Recall@5. QA is supplementary and uses 40 questions, 35 answerable and 5 unanswerable, top-k=5, a 1,500-character evidence budget, temperature 1.0, top-p 0.95, and seed 20260811. F1 uses an Alibaba Cloud DashScope service, while historical QA records use a Moonshot service. The provider difference is disclosed and the QA values are not treated as a fully controlled generation ranking.

## Appendix E. Detailed results and audit slices

The main tables report retained-system aggregate metrics. The supplementary package provides the following auditable views without duplicating all rows in the paper:

1. per-query ranked outputs and threshold hits;
2. shared-IDCG inputs and zero-denominator cases;
3. Composite Fact Recall support mappings from accepted facts to exact chunks;
4. slices by fact arity, support mode, question type, and difficulty;
5. F0/F1 candidate-boundary changes under the shared top-50 pool; and
6. representative failure categories.

The recurring failure categories are missing cross-chunk evidence, incorrect condition binding, and incomplete comparison pairing. These cases explain why a relevant top-ranked chunk does not always constitute complete fact support. The supplementary files are shared_retrieval_per_query_retained.csv, shared_retrieval_ranked_topk_retained.csv, shared_qrels_final_audit.json, composite_fact_gold_user_accepted.json, composite_fact_recall_retained.csv, and the QA summary files in the paper database.

### E.1 Representative evidence-assembly case

The audit package contains a cross-section question, QA_RFB_001, asking whether post-cycling capacity loss in a methyl-viologen flow cell is better explained by intrinsic 3-TMA PROXYL degradation or by self-discharge. The accepted evidence comes from source document RFB_002 and two exact chunks, RFB_002_CHK_001 and RFB_002_CHK_009. The case has fact arity 4 and support mode cross_section. The accepted interpretation combines the post-cycling diagnostic results, the absence of strong irreversible-degradation evidence, and the evidence for self-discharge or crossover. This case illustrates why retrieving one related sentence is insufficient: the answer requires evidence from more than one section while keeping the material, condition, diagnostic measurement, and mechanism bound to the same question.

## Appendix F. Hypergraph construction cost and maintenance

The construction cost has four components: LLM extraction and retry tokens, normalization and evidence-rewrite work, embedding calls for entities and fact objects, and storage/index construction. A document update can require re-extraction of affected chunks, re-normalization of aliases and units, regeneration of incident links, and refresh of the corresponding dense and lexical index entries. This makes incremental maintenance more expensive than appending an unstructured text record.

The current experiment records structural counts and protocol settings, but it does not claim a complete monetary cost or wall-clock benchmark. A future cost table should report extraction tokens, embedding calls, build time, index size, update time, and query latency separately. Reporting these components will make the accuracy--cost trade-off explicit.

## Appendix G. Reproducibility manifest

The paper database contains protocol records, frozen query and qrels artifacts, accepted fact audit, retrieval summaries, QA summaries, and source-level diagnostic files. Principal artifact names are:

- hyper_final_experiment_v1_state.json;
- hyper_final_posthoc_v1_run_config.json;
- shared_qrels_final_audit.json;
- composite_fact_gold_user_accepted.json;
- composite_fact_recall_retained.csv;
- shared_retrieval_summary_retained.json; and
- qa_final_protocol.json and qa_final_summary_normalized_final.json.

A final arXiv package should include code version, cache version, query-file hash, qrels audit hash, embedding model and dimension, retrieval settings, QA settings, and appendix tables. API keys and other secrets must remain outside the manuscript, source archive, and reproducibility package.
