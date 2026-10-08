# Abstract

Chemical literature often expresses a useful result as a high-order fact: a material or formulation is evaluated under particular composition and operating conditions, produces one or more measurements, and is associated with a performance outcome. These roles may be distributed across chunks or repeated with different names and units. Chunk retrieval preserves the text but provides a coarse retrieval unit, while pairwise graph representations can weaken the binding between conditions, measurements, and outcomes. We present **HyperChE**, a chemical-domain retrieval-augmented generation pipeline that organizes such evidence with a normalized hypergraph. HyperChE combines entity and relation normalization, explicit measurement and condition instances, canonical/surface dual representations, and hybrid entity–hyperedge retrieval with deterministic candidate reranking. We evaluate five retained systems on a frozen collection of 60 documents and 1,328 chunks using 58 queries, 4,196 judged query–chunk pairs, and 150 accepted atomic facts. Under the grade-$\geq2$ protocol, the final system obtains Hit@5 = 0.6724, MRR = 0.4684, and shared gNDCG@5 = 0.3873, with Composite Fact Recall@5 = 0.4267. These results are higher than the original hypergraph and the chemical-prompt pairwise-graph comparison in the same evaluation view. The F0-to-F1 reranker changes Hit@5 by 1.72 percentage points but does not change Composite Fact Recall, indicating that most of the gain comes from representation and candidate recall. The results support normalized hypergraph organization for chemical high-order facts within this dataset and protocol; they do not imply that an unnormalized hypergraph or every hypergraph implementation will outperform a pairwise graph.

**Keywords:** chemical information retrieval; retrieval-augmented generation; hypergraph; knowledge representation; entity normalization; high-order facts
# 1. Introduction

Chemical literature often reports a result by jointly specifying a material or formulation, its composition and operating conditions, one or more measurements, and a resulting property or performance value. These roles may be spread across chunks or repeated with different names and units. A text chunk can preserve the wording, while independently indexed pairwise edges can preserve local relations, yet neither representation guarantees that all conditions, measurements, and outcomes remain bound to the same experimental instance. We call this multi-role evidence a **high-order chemical fact**. A hyperedge provides a direct retrieval unit for such a fact: it can connect the material, components, condition instances, measurements, outcome, and source locations in one record.

At query time, HyperChE answers a question in three steps. (1) It encodes the question and searches the entity and hyperedge indexes using dense and lexical matching; canonical forms support alias and relation-variant matching, while surface forms are retained for evidence tracing. (2) It fuses these lists with weighted RRF, expands matched entities to incident fact hyperedges, maps the structured candidates back to source chunks, and optionally applies deterministic structural reranking to the shared candidate pool. (3) It passes the top reconstructed evidence chunks, together with their fact roles and source pointers, to the QA generator, which produces a grounded answer and citations. The extraction, normalization, and index construction that make these operations possible are offline preparation steps described in the method section; the experiment groups and evaluation protocol are described separately. They are not stages of the online answer workflow.

We study three design questions and one evaluation-boundary question:

- **RQ1 — Chemical prompting:** What does a chemical-domain extraction prompt add to graph and hypergraph construction and retrieval, and does its effect differ between pairwise and hypergraph representations?
- **RQ2 — Normalization and coverage:** Does entity/relation normalization improve retrieval quality and recovery of complete facts, as measured by both ranking metrics and Composite Fact Recall (CFR)?
- **RQ3 — Final-system advantage:** Where does the advantage of the final normalized hypergraph configuration come from? With the same candidate pool, does structural reranking improve ordering, and does it add new complete facts?
- **RQ4 — Generation and boundaries:** How is retrieval coverage reflected in supplementary QA, and which protocol factors limit the strength of the conclusions?

The study uses 60 documents, 1,328 frozen chunks, 58 queries, 4,196 judged query–chunk pairs, and 150 accepted atomic facts. The primary comparison comprises B0 (original hypergraph), B1 (chemical-prompt graph), B2 (chemical-prompt hypergraph), F0 (normalized hypergraph without reranking), and F1 (normalized hypergraph with reranking), all evaluated with shared qrels and a shared IDCG denominator.

Our contributions are threefold. First, we provide a chemical high-order fact representation that binds entities, relations, measurements, conditions, outcomes, and evidence locations. Second, we combine normalization with canonical/surface dual forms and instance-level evidence traceability. Third, we analyze prompting, normalization, candidate recall, and reranking under one shared evaluation protocol instead of treating “hypergraph” as a single undifferentiated factor.

Under the grade-$\geq2$ protocol, F1 obtains Hit@5 = 0.6724, MRR = 0.4684, shared gNDCG@5 = 0.3873, and CFR@5 = 0.4267, supporting 64 of 150 accepted atomic facts in the top five (B0: 14; B1: 50). Relative to F0, reranking raises Hit@5 from 0.6552 to 0.6724 but leaves CFR unchanged, indicating that the main gain is associated with chemical prompting plus normalized evidence organization and candidate recall, while reranking mainly changes boundary ordering. The remainder of the paper describes the representation and pipeline, evaluates these questions, and discusses the protocol limits and implications for chemical RAG.

# 2. Related Work and Problem Positioning

## 2.1 Chemical information extraction and knowledge graphs

Chemical information extraction must represent more than named entities. A useful record may include material identity, composition, synthesis or operating conditions, a measurement with a unit and interval, a comparison target, and a reported property or performance outcome. The same concept may appear under abbreviations, spelling variants, trade names, alternate unit conventions, or context-dependent relation phrases. A knowledge representation that only stores an entity string and a generic relation can therefore merge mentions that should remain distinct or detach a measurement from the condition under which it was obtained.

Knowledge graphs provide a practical abstraction for indexing entities and relations, and chemical knowledge graph systems have enabled search, prediction, and synthesis-oriented applications. Their common representation is a collection of typed entities and pairwise edges. This representation is valuable for many tasks, particularly when a fact is naturally binary or when graph traversal is the main operation. For the retrieval problem considered here, however, a chemical observation may be jointly constrained by more than two participants and by attached measurements and conditions. The challenge is to preserve that scope while still supporting efficient matching and source-level inspection.

HyperChE treats normalization as part of the representation rather than as a post-processing cosmetic step. Canonical forms support aggregation and retrieval across aliases, relation variants, units, and numerical forms. Surface forms and evidence pointers remain available for citation, audit, and reconstruction of the original claim. Measurement and condition instances are represented as roles within a fact record so that values from separate experimental settings are not silently converted into unconditional properties.

## 2.2 Retrieval-augmented generation and graph-augmented retrieval

Standard retrieval-augmented generation (RAG) usually indexes document chunks and supplies the top-ranked passages to a language model. This design is simple and preserves local prose, but the chunk is a coarse retrieval unit: it may contain several facts, omit a condition located in a neighboring chunk, or return a phrase without exposing the relations that connect the phrase to the question. Chunk retrieval can also be highly competitive under a query/chunk relevance protocol because a directly returned chunk already contains the answer text.

Graph-augmented RAG introduces entities, relations, communities, or paths as additional retrieval and reasoning structures. GraphRAG and subsequent systems use graph construction, entity retrieval, graph expansion, or path-based ranking to improve organization of large corpora. Other systems specialize the graph interface for particular domains or combine graph evidence with chunk retrieval. These methods demonstrate that structured retrieval can complement the local context of conventional RAG.

The relevant distinction for HyperChE is the retrieval unit and the evidence assembly operation. A pairwise graph exposes local edges and neighborhoods. A hypergraph exposes a set of entities and roles that belong to one n-ary fact, allowing an entity match to expand to its complete fact or a fact match to expose all of its members. HyperChE therefore uses hybrid retrieval to produce candidates but evaluates whether the returned evidence supports complete accepted facts, not only whether one local phrase is relevant.

## 2.3 Hypergraph knowledge representation

A standard graph is commonly written as

\[
G=(V,E),
\]

where $V$ is a set of entities and each edge in $E$ connects two endpoints. A pairwise fact can be written with an endpoint tuple $V_e=(v_h,v_t)$. A hypergraph generalizes this structure as

\[
G_H=(V,E_H),
\]

where each hyperedge $e_H\in E_H$ connects two or more entities,

\[
V_{e_H}=(v_1,v_2,\ldots,v_n),\qquad n\geq 2.
\]

The corresponding n-ary fact is

\[
F_n=(e_H,V_{e_H})\in G_H.
\]

The $n=2$ case contains an ordinary edge as a special case. The point of the generalization is not merely to increase the number of edges. It changes the unit that can be stored, retrieved, expanded, and inspected: a hyperedge can represent the joint membership of several entities in one fact. The HyperGraphRAG paper uses this definition after first showing a concrete fact in three forms—chunk text, binary graph edges, and one hyperedge—to make the loss of binding under pairwise decomposition intuitive. It then constructs a knowledge hypergraph, retrieves entities and hyperedges, expands the retrieved structure in both directions, and combines the recovered facts with chunk evidence.

This explanatory sequence is useful for chemical applications. A reader should first see a material–component–condition–measurement–outcome record and how it is fragmented by pairwise edges. The formal definition then clarifies what the proposed hyperedge preserves. The implementation may use a bipartite incidence graph or another database structure for storage; that storage choice does not by itself reduce the semantic representation to binary facts when the hyperedge membership is preserved losslessly.

Prior hypergraph representation and hyper-relational embedding work has often focused on link prediction, node classification, or representation learning. HyperChE addresses a different operational goal: retrieving source-grounded evidence for questions about chemical experiments. Consequently, the central measurements are retrieval ranking and complete fact coverage, with QA treated as a supplementary check on whether retrieved evidence can support a generated answer.

## 2.4 Evaluation of chemical RAG systems

Evaluation choices influence what a system appears to retrieve well. Chunk-level qrels are useful for auditing relevance at a frozen retrieval unit, but they reward systems that return the chunk containing the target wording. They do not necessarily measure whether a system recovers all components of a multi-part chemical fact or combines evidence across chunks. A source-level count derived from chunk labels can diagnose concentration and diversity, but it is not an independent source-level gold standard. Generated-answer metrics can assess correctness, completeness, abstention, and citation behavior, yet they also depend on the generation model and service conditions.

HyperChE reports several views to separate these effects. Hit@5, MRR, and shared gNDCG@5 measure ranking against common query/chunk judgments. Composite Fact Recall requires the exact supporting chunk for an accepted atomic fact to appear in the top five, so it tests a stricter form of evidence coverage. Source-diversity statistics are reported as diagnostics derived from the same retrieval outputs. QA metrics are supplementary: the historical groups and F1 use different service providers even though they use the same nominal model name, so those results are not presented as a fully controlled five-group generation ranking.

## 2.5 Problem positioning and scope of this study

HyperChE is positioned at the intersection of chemical information extraction, graph-augmented RAG, and hypergraph knowledge representation. We separate three design questions that are often conflated: whether a chemical-domain prompt is needed to construct useful structure, whether normalization improves retrieval and complete-fact recall, and where the advantage of the final configuration comes from. The study therefore asks whether a jointly designed pipeline—domain prompting, normalization, measurement/condition modeling, canonical/surface traceability, and entity–hyperedge retrieval—improves recovery of high-order evidence under a shared protocol.

The retained experiments provide five system views: the original hypergraph (B0), a chemical-prompt pairwise graph (B1), an unnormalized chemical-prompt hypergraph (B2), a normalized hypergraph without reranking (F0), and the normalized hypergraph with deterministic reranking (F1). Because the B1 and B2 retrieval entrances, budgets, candidate ordering, and hyperedge textualization are not strictly identical, their difference is interpreted as a system-level diagnostic rather than a single-module causal ablation. The F0/F1 comparison is narrower: both systems use the same hybrid RRF top-50 candidate pool and differ only in the reranking switch used after candidate generation.

This scope leads to three practical conclusions. First, the value of a chemical prompt must be assessed against the original extraction pipeline rather than assumed. Second, normalized structure and candidate recall should be evaluated against prompt-only systems using both ranking metrics and Composite Fact Recall. Third, the final group's advantage should be decomposed into fact representation, candidate organization/recall, and post-retrieval ordering; the graph structure alone is not a guarantee of quality. The rest of the paper follows this separation in the problem definition, method, experiments, and limitations.

> **Citation integration note.** The final LaTeX manuscript should map the descriptive references in this draft to the project bibliography, including the HyperGraphRAG arXiv paper, GraphRAG, LightRAG, and relevant chemical information-extraction and hypergraph representation work. No new numerical claim is introduced here beyond the frozen experiment records summarized in the paper database.

# 3. Problem Definition

## 3.1 Task formulation and design goals

HyperChE is designed for retrieval over chemical literature in which a useful answer is often determined by a combination of entities, measurements, operating conditions, and outcomes. The retrieval target is therefore not only an isolated entity or a locally matching sentence. It is an evidence set that preserves the binding among the roles that jointly define a chemical fact.

Let $q$ be a query and let $R_k(q)$ be the ranked list of the top-$k$ source chunks returned by the system. The system is evaluated at two levels. At the chunk level, a returned chunk is relevant when it satisfies the shared query--chunk judgment protocol. At the fact level, a composite fact is supported only when its exact supporting chunk appears in $R_k(q)$. The second level prevents a system from receiving full credit merely for returning a related entity while missing the condition, measurement, or result that completes the fact.

The design has four goals:

1. preserve multi-role chemical facts as retrievable units;
2. make aliases, relation variants, and measurement expressions searchable under a common representation;
3. retain the original surface wording so that retrieved evidence can be traced back to the source text; and
4. separate candidate recall from candidate ordering so that the contribution of deterministic reranking can be measured.

## 3.2 Ordinary graphs and hypergraphs

An ordinary graph is written as

\[
G=(V,E),
\]

where $V$ is a set of nodes and each edge $e\in E$ connects two endpoints, for example $e=(v_h,v_t)$. This representation is appropriate for a binary relation, but a chemical statement can require more than two jointly constrained roles. For example, the statement that a material under a specified operating condition has a measured value and a corresponding performance result cannot be fully characterized by one isolated pairwise edge without distributing the condition and measurement over additional edges.

HyperChE uses a hypergraph

\[
G_H=(V,E_H),
\]

where a hyperedge $e_H\in E_H$ is incident to a set of two or more nodes,

\[
V_{e_H}=(v_1,v_2,\ldots,v_n),\qquad n\geq 2.
\]

The associated high-order fact is represented as

\[
F_n=(e_H,V_{e_H}).
\]

An ordinary edge is therefore the $n=2$ case, whereas a hyperedge can keep the material, component, condition, measurement, property, and outcome of one fact in a common incidence scope. The implementation may store the incidence relation as a bipartite edge--entity structure for indexing. This storage choice does not reduce the semantic unit to an independent collection of binary facts: the hyperedge identity, its member set, its typed roles, and its evidence pointer are retained together.



# 4. HyperChE Method

## 4.1 Chemical fact extraction and evidence binding

The input corpus is divided into frozen source chunks. A domain-specific extraction pass produces, for each chunk, entity mentions, relation or fact descriptions, measurement instances, condition instances, and pointers to the source evidence. The extraction record is organized around a fact instance rather than around an unconstrained list of entity pairs. A useful abstract form is

\[
f_i=(s_i,r_i,A_i,M_i,C_i,P_i,E_i),
\]

where $A_i$ is the set of participating entities, $M_i$ is the set of measurements, $C_i$ is the set of conditions, $P_i$ contains the property or outcome roles, and $E_i$ identifies the source chunk and evidence span. The role sets may be partially populated when the source statement does not provide every role; the system does not fill missing roles by combining unrelated chunks.

Measurements are kept as typed local instances. A measurement may include a value or interval, a unit, a comparator, and the object to which the value applies. Conditions are kept as instances as well, so that temperature, composition, flow, loading, or other operating context remains attached to the fact in which it was observed. Values that are ambiguous in the chunk-local extraction are preserved rather than silently split or assigned to a different object. This prevents a value observed under one condition from becoming an unconditional property of the material.

The extraction record also stores the original surface wording and an evidence pointer. These two fields serve different purposes: the structured record supports matching and aggregation, while the surface evidence supports quotation, reconstruction, and manual audit.

## 4.2 Entity and relation normalization

Chemical literature uses aliases, abbreviations, spelling variants, unit variants, and relation phrases that refer to the same underlying concept. HyperChE maps such variants to a canonical representation before indexing. Normalization is applied to entity names, relation descriptions, and measurement or unit expressions when a canonical form is available. The source surface form is retained alongside the canonical form.

Let $x^{\mathrm{surf}}$ denote a mention as it appears in the source and $x^{\mathrm{can}}$ its normalized form. The dual record is

\[
\operatorname{Dual}(x)=
\bigl(x^{\mathrm{can}},x^{\mathrm{surf}},E_x\bigr),
\]

where $E_x$ is the evidence pointer. Canonical text makes equivalent mentions easier to aggregate across chunks and documents. Surface text preserves the wording needed to verify a result and to reconstruct the source chunk. The final cache uses the `dual_concat` index profile so that both views remain available to the retrieval representation; the exact surface string is never discarded from the evidence record.

Normalization is not treated as an independent semantic label. It is a representation and indexing operation whose value is tested through the end-to-end retrieval and composite-fact results. The final cache records the normalization version and an evidence rewrite audit, allowing the canonical record and its source form to be checked independently.

## 4.3 Hypergraph construction and indexed objects

Each normalized fact is represented by a hyperedge-like relationship object and a set of incident entity nodes. The relationship object contains the canonical relation text, surface description, typed role information, the measurement and condition instances, and the source pointer. Entity objects contain canonical and surface names plus their incident relationship identifiers. The resulting incidence structure supports two complementary retrieval views:

- **entity view:** retrieves entities whose canonical or surface descriptions match the query;
- **relationship view:** retrieves binary or higher-arity relationship objects whose fact descriptions match the query.

The same source chunk can therefore be reached from an entity match, a relationship match, or both. After graph expansion, the system reconstructs the complete source chunk rather than exposing only a truncated graph fragment to the generator. This keeps graph retrieval connected to verifiable textual evidence.

## 4.4 Hybrid candidate retrieval

For a query $q$, HyperChE independently computes dense and lexical scores for relationship objects and entity objects. The candidate lists are fused with weighted reciprocal rank fusion (RRF). For a candidate $d$, the fusion score has the form

\[
S_{\mathrm{RRF}}(d)=
\sum_{j\in\mathcal{L}(d)}
\frac{w_j}{k_{\mathrm{RRF}}+\operatorname{rank}_j(d)},
\]

where $\mathcal{L}(d)$ is the set of dense or BM25 lists containing $d$, $w_j$ is the channel weight, and $k_{\mathrm{RRF}}$ is the RRF offset. The final normalized retrieval configuration uses relationship dense and BM25 channels, entity dense and BM25 channels, one-hop incident-edge expansion, and a deterministic structural rerank over a frozen candidate pool. Relationship candidate depth is 50, entity candidate depth is 30, the RRF offset is 60, and the relationship and entity channel weights are fixed by the released protocol. These settings are held constant between the no-rerank and rerank variants.

One-hop expansion follows incident relationships from retrieved entities and adds their linked fact objects, subject to the released expansion limit. The resulting candidate pool is mapped back to source chunks. If multiple structured objects map to the same chunk, the chunk is retained once with its associated structured evidence. The final ranked output is a list of reconstructed source chunks, which is the unit used by the shared qrels and by the QA evidence interface.

## 4.5 F0/F1 reranking ablation

The F0/F1 comparison isolates the ordering stage. Both variants use the same hybrid RRF procedure and the same frozen top-50 candidate pool. F0 returns the pool after the common retrieval and expansion steps, with the existing structural rerank disabled. F1 applies the deterministic structural rerank to that identical pool and then reconstructs the source chunks. Reranking can change the order of candidates already present in the pool, but it cannot introduce a fact that was not retrieved into the pool.

This separation makes the interpretation explicit. A change in Hit@5, MRR, or graded NDCG between F0 and F1 is an ordering effect under a fixed recall pool. A change in Composite Fact Recall would indicate that the ordering brings an already retrieved exact-support chunk into the evaluated top-$k$; it would not indicate that reranking discovered a new candidate.

## 4.6 Evidence interface and generation boundary

For each query, the top five reconstructed source chunks are passed to the supplementary QA interface under the fixed evidence budget. EFU repair is disabled throughout the retrieval and QA runs. The QA generator therefore does not repair, invent, or retrieve missing evidence on behalf of the retrieval system. Citation validity and answer completeness are reported as supplementary outcomes, while the primary claims are based on the shared retrieval judgments and composite-fact coverage.

# 5. Experimental Setup

## 5.1 Corpus, queries, and frozen artifacts

The evaluation uses a fixed chemical literature collection from the flow-battery domain. The collection contains 60 documents and 1,328 frozen source chunks produced with a configured chunk length of 1,000. The retrieval test set contains 58 queries. The shared pooling and judgment process covers 4,196 query--chunk pairs, and every retained pair has a frozen relevance judgment. The composite-fact audit contains 150 user-accepted atomic facts.

The released final cache reports 11,950 entity records, 13,629 relationship records, and 14,676 audited evidence instances. These counts describe the construction and audit artifacts; they are not used as a proxy for retrieval quality. Raw experiment outputs remain preserved in the complete experiment directory, while the paper database contains the retained systems, the accepted qrels, the fact audit, and the derived summaries.

All retained systems use `Qwen/Qwen3-Embedding-4B` with 2,560 dimensions for embedding-based retrieval. EFU repair is disabled for every system. The original caches are treated as read-only inputs. The paper reports the released old-embedding experiment and does not mix it with a different embedding model or a repaired-generation run.

## 5.2 Main systems

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

## 5.3 Retrieval protocol

The primary relevance threshold is grade ≥2, with grade ≥3 reported as a stricter sensitivity threshold. The shared qrels use four grades (0--3). For each query, all retained systems are evaluated against the same judged query--chunk set. The main metrics are:

- **P@1:** the proportion of queries whose first result reaches the selected relevance threshold;
- **Hit@5:** the proportion of queries with at least one threshold-reaching result in the top five;
- **MRR:** the mean reciprocal rank of the first threshold-reaching result;
- **shared gNDCG@5:** graded NDCG computed with a query-specific IDCG calculated from the shared candidate judgments; and
- **Composite Fact Recall@5 (CFR@5):** the fraction of the 150 accepted atomic facts whose exact supporting chunk appears in the top five.

The shared-IDCG construction uses the same per-query denominator for every retained system. Five queries have no usable IDCG under the frozen judgment set; they follow the released zero-denominator handling rule and are disclosed in the metric notes. We do not use significance language or claim statistical superiority because this paper version does not include confidence intervals or a formal hypothesis test.

CFR is intentionally stricter than ordinary chunk Hit@5. It requires an exact supporting chunk for an accepted atomic fact, so a related chunk or a matching entity without the fact's condition and result is not counted as complete support. `macro_query_CFR@5` is reported as a complementary query-level summary when needed. The source-level fields in the archive are derived from chunk qrels and are used only as diagnostics; they are not an independent source-level gold standard.

## 5.4 Supplementary QA protocol

QA is a supplementary check on how retrieved evidence is used. The fixed question set contains 40 questions: 35 answerable and 5 unanswerable. The generator receives the top five retrieved chunks, with a 1,500-character evidence budget. The generation configuration uses `kimi-k2.6`, temperature 1.0, top-(p) 0.95, and seed 20260811. EFU repair remains disabled.

The final normalized system uses an Aliyun DashScope service for generation and judging. Historical QA runs for the other retained groups used a Moonshot service. The model name is the same, but the serving providers and service conditions are different. Accordingly, QA numbers are reported as supplementary evidence and are not presented as a fully controlled five-group generation-quality ranking. The primary conclusions are based on retrieval metrics and CFR, which use the shared qrels and frozen fact audit.

This boundary is part of the interpretation of the results. The paper asks whether structured, normalized hypergraph evidence improves retrieval of high-order chemical facts within the frozen structured-evidence protocol. The conclusions remain specific to the retained systems, corpus, queries, and shared evidence judgments.

## 6.1 Results

### 6.1.1 RQ1: Is chemical-domain prompting necessary?

We evaluate five retained systems on a frozen collection of 60 chemical documents and 1,328 chunks. The benchmark contains 58 retrieval queries and 4,196 judged query--chunk pairs, with all pairs assigned a final relevance grade. The main retrieval results use the shared \(\mathrm{IDCG}@5\) protocol and report grade-\(\geq 2\) relevance. The five systems are:

- **B0 (original hypergraph):** the original hypergraph cache and retrieval implementation;
- **B1 (chemical-prompt graph):** a chemistry-prompted binary graph;
- **B2 (chemical-prompt hypergraph):** a chemistry-prompted hypergraph without the final normalization and evidence-organization pipeline;
- **F0 (normalized hypergraph, no rerank):** the normalized final cache with reranking disabled;
- **F1 (normalized hypergraph):** the normalized final cache with the deterministic structural reranker enabled.

The same 150 accepted atomic facts are used for Composite Fact Recall (CFR). A fact is counted as supported only when its exact supporting chunk is retrieved within the top five. This criterion is intentionally stricter than ordinary chunk relevance: it measures whether a complete fact has a directly usable evidence unit in the retrieved set.

Relative to B0, the chemistry-prompted systems provide evidence that domain-specific prompting changes the retrieval representation in a useful way, but the effect is not uniformly positive across metrics or adapters. B1 improves grade-(\geq2) Hit@5 from 0.4828 to 0.6207, while B2 reaches 0.4483 on the same headline metric but raises CFR from 0.0933 to 0.1600. Because B1 and B2 use different upstream retrieval adapters, these comparisons answer whether the prompted system configurations are useful; they do not identify a prompt-only causal effect. The result motivates treating prompting as a necessary design factor to test, rather than assuming that a prompt alone guarantees a stronger hypergraph.

### 6.1.2 RQ2: Does normalization improve retrieval quality?

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

### 6.1.3 RQ2 continued: Does normalization improve complete-fact recall?

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

### 6.1.4 RQ3: Where does the final-system advantage come from?

The final-system advantage is visible at three levels: the normalized fact representation, the hybrid candidate organization and recall pool, and the ordering applied after candidate generation. The results below separate these levels as far as the released experiments allow.

#### Why B2 is below B1

The B2 result should not be interpreted as evidence that hypergraph structure is intrinsically inferior to a binary graph. B1 and B2 are not a strict one-variable ablation. Their upstream retrieval adapters differ in several operational respects.

B1 uses a structured graph hybrid pipeline with entity dense retrieval, entity BM25, relationship dense retrieval, relationship BM25, weighted reciprocal-rank fusion, and incident-edge expansion. It does not impose a fixed quota between entity and relationship branches. B2 uses the upstream hyper_query interface, which returns separate entity and relation branches, takes ten results from each branch, interleaves them, and applies a top-20 cutoff while preserving the branch order. It therefore has a fixed 10+10 allocation and lacks a pipeline equivalent to B1's multi-channel fusion and expansion.

The candidate diagnostics are consistent with this explanation. Before the final branch quota and top-20 cutoff, the B2 candidate union has a higher gold recall than B1 (0.8889 versus 0.8222). After the B2 quota and truncation, its effective candidate recall falls to 0.5333, with 16 query-level quota or top-k losses. B1 has no corresponding quota loss in this diagnostic. Several B2 queries contain a gold entity or relation at a rank that is already outside the fixed branch budget, so the relevant candidate is discarded even though it appeared in a broader branch union.

The textual form of candidates may also contribute. B2 represents complete hyperedges with multiple entities, relation descriptions, and evidence text. Under the current BM25 and candidate-text construction, these longer descriptions can dilute query terms and place a relevant hyperedge lower in the branch ranking. This is an implementation-level explanation, not a theoretical property of hypergraphs. The current B2 top-20 diagnostic also reports no high-order candidate selected in the returned set, which means that this particular B2 adapter does not measure the full potential of high-order retrieval.

Accordingly, the paper treats B2 as an unreconstructed, chemistry-prompted hypergraph baseline and reports its limitations explicitly. A strict structural ablation would require B1 and B2 to share the same dense/BM25/RRF/expansion pipeline, candidate budget, textualization procedure, and reranking policy, with only the arity restriction changed. That controlled experiment is left for future work.

### 6.1.5 RQ4: What does reranking add after candidate generation?

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

### 6.1.6 RQ3 continued: Evidence-source diversity and failure patterns

As a diagnostic derived from chunk-level qrels, F1 retrieves an average of 2.121 distinct source documents in its top five, with a duplicate ratio of 0.576. F0 has 2.103 distinct sources and a duplicate ratio of 0.579. B0, B1, and B2 have respectively 3.586/0.283, 2.897/0.421, and 3.621/0.276 for these two quantities.

The lower source diversity of F0/F1 indicates that higher chunk-level relevance is sometimes obtained by repeatedly retrieving evidence from the same source. This concentration is compatible with the unchanged F0/F1 CFR: reranking can promote a relevant chunk from an already retrieved source without increasing the number of independently supported facts. These source statistics are descriptive diagnostics computed from chunk qrels; they are not an independently annotated source-level gold standard.

The retained per-query inspection identifies three recurring failure patterns:

1. **Missing cross-chunk evidence:** one part of a fact is retrieved, but the condition or outcome required to establish the complete fact is absent from the top five;
2. **Condition binding errors:** a material or performance value is retrieved without the operational condition that scopes it;
3. **Incomplete comparison pairing:** evidence for one side of a comparison is retrieved, while the corresponding material, baseline, or measurement for the other side is missing.

These patterns explain why a system can obtain a relevant top-ranked chunk while still failing the stricter composite-fact criterion.

### 6.1.7 RQ4 continued: QA as a supplementary check and protocol boundary

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

## 6.2 Discussion

### 6.2.1 What the results say about chemical hypergraph retrieval

Chemical literature often states a result through a joint constraint over several roles: a material or component, a composition, an operating condition, a measurement or range, and a performance outcome. The retrieval objective is not merely to find any chunk mentioning one of these terms. It is to preserve the binding that makes the combination a usable fact.

The F1 results are consistent with this view. Relative to B0 and B1, F1 retrieves more complete atomic facts under the exact-supporting-chunk criterion and also improves conventional ranking metrics. The evidence supports the use of a hypergraph-oriented organization for this class of facts when the hypergraph is coupled with domain normalization and an appropriate retrieval adapter. It does not support the stronger statement that hypergraph structure alone guarantees an improvement.

### 6.2.2 Normalization is a retrieval mechanism, not only data cleaning

The final pipeline normalizes entity and relation variants, models measurement and condition instances, and keeps canonical and surface forms together. Canonical forms allow aliases, units, and relation variants to match during retrieval and aggregation. Surface forms preserve the wording and evidence pointers needed for citation and audit.

The difference between B2 and F1 is therefore best interpreted as a system-level transition from an unnormalized, quota-constrained hypergraph adapter to a normalized, evidence-oriented retrieval pipeline. The present results cannot isolate the contribution of each component because the comparison changes extraction, indexing, textualization, candidate fusion, and representation together. They do show that a high-order representation becomes more useful when its entities, relations, measurements, conditions, and evidence pointers are organized consistently.

### 6.2.3 Recall and ranking should be improved in that order

The F0/F1 comparison shows that reranking is not the main source of the observed gain. F0 already reaches CFR@5 = 0.4267, equal to F1, while F1 provides only a modest Hit@5 improvement. Once a complete fact is absent from the candidate pool, a downstream ranker cannot recover it. This places the highest priority on improving candidate generation, preserving cross-chunk links, and balancing source diversity.

The source-diversity diagnostic further suggests a trade-off. F1's top five are more concentrated within the same source than B1 or B2, which may help local relevance but reduce the chance of collecting complementary evidence from different sections or papers. A future aggregation stage could explicitly reward complementary fact roles and penalize redundant source selections, while retaining the exact evidence pointer needed for audit.

### 6.2.4 Interpreting the binary-graph comparison

B1 is a useful retained comparison because it is a strong chemistry-prompted binary graph, but it should not be treated as a perfectly controlled counterpart to B2. Its stronger result reflects both the binary representation and a different retrieval adapter. The B2 diagnosis shows that candidate quotas and ranking behavior can dominate the observed outcome before the representation is evaluated.

For this reason, the main conclusion is framed around the complete normalized pipeline: F1 is stronger than the retained baselines under the shared qrels protocol, while B2 exposes the need to co-design hypergraph representation and retrieval. A fair arity ablation is an important next experiment, but it is not required to state the bounded empirical result obtained here.

### 6.2.5 QA interpretation and practical meaning

The QA results show a useful but incomplete transfer from retrieval to generation. Valid citations and zero false answers indicate that the evidence interface is auditable. However, the Good Rate of 0.25 and Hallucination Rate of 0.20 show that evidence coverage and fact binding still constrain practical answer quality. This is especially relevant for high-order chemical questions, where a response may need a material, a condition, a measurement, and a comparative outcome at once.

Because F1 and earlier QA groups were served by different providers, QA should be reported as a supplementary end-to-end check. The primary scientific evidence remains the shared retrieval evaluation and the exact-supporting-chunk CFR.

### 6.2.6 Scope of the claim

The current evidence supports four bounded conclusions:

1. The normalized hypergraph pipeline improves retrieval quality over the retained original hypergraph and chemistry-prompted binary/hypergraph baselines on this frozen chemical benchmark.
2. It recovers more complete atomic facts at top five than those baselines under the accepted exact-chunk CFR protocol.
3. The deterministic reranker gives a small ordering benefit after candidate generation but does not increase complete-fact coverage.
4. Hypergraph structure alone is insufficient; normalization, fact-role organization, candidate fusion, and evidence textualization jointly determine performance.

These conclusions are limited to the 60-document benchmark, the frozen qrels, the Qwen/Qwen3-Embedding-4B 2560-dimensional embedding configuration, and the stated retrieval and QA protocols. No claim of statistical significance or broad cross-domain generalization is made in this draft.

# 7. Limitations and Reproducibility

## 7.1 Scope and reproducibility boundaries

This study should be interpreted within the scope of its frozen corpus, query set, and evaluation protocol. The collection contains 60 documents, 1,328 text chunks, 58 queries, 4,196 judged query/chunk pairs, and 150 accepted atomic facts. The results therefore provide evidence for high-order chemical knowledge retrieval under this setting; they do not establish domain-independent superiority over every graph or text retrieval system.

First, the B1 and B2 systems do not use fully isomorphic retrieval adapters. Their upstream query paths differ in candidate extraction, branch ordering, quota handling, and the textual form used for graph or hypergraph candidates. The lower B2 score should consequently be read as a diagnostic of an unnormalized hypergraph implementation and its retrieval interface, rather than as an isolated causal estimate of hypergraph structure. A future controlled ablation should use the same candidate entry points, candidate budget, text serialization, fusion rule, and reranking stage for both representations.

Second, the comparison between the earlier systems and F0/F1 includes system-level changes in extraction, indexing, normalization, measurement modeling, evidence linking, and candidate organization. The B2-to-F1 improvement therefore cannot be assigned to one component without a factorial ablation. The F0-to-F1 comparison is narrower: both systems share the same hybrid RRF top-50 candidate pool, and the difference is the deterministic reranking switch. Under this controlled comparison, reranking changes ranking quality only slightly and does not increase Composite Fact Recall.

Third, the current source-level results are derived from chunk-level qrels. A source is counted as relevant when a top-five chunk from that source has a relevant chunk judgment. These values are useful diagnostics for source diversity and duplication, but they are not independent source-level gold evaluations. Future work should annotate source-level relevance directly and evaluate evidence sets rather than individual chunks alone.

Fourth, the QA results are supplementary. The final normalized system uses kimi-k2.6 through an Aliyun DashScope-compatible service, whereas historical QA records use a Moonshot service. The two service conditions are therefore not fully controlled or directly interchangeable. We report the final QA metrics as evidence about the end-to-end behavior of the final system, not as a strict five-group generation ranking.

Fifth, the study does not claim preregistered significance tests or confidence intervals. The reported differences are descriptive and should be verified on larger query sets and with resampling or paired statistical tests. EFU repair was disabled throughout the final retrieval and QA protocol, so the results do not measure any contribution from LLM-based evidence repair.

## 8. Conclusion

Chemical literature frequently expresses knowledge as a combination of materials, compositions, operating conditions, measurements, and performance outcomes. These roles jointly constrain the meaning of a fact, and their association can be weakened when the fact is represented only as independent pairwise relations or retrieved as an undifferentiated text block. HyperChE addresses this problem with a normalized hypergraph representation that preserves high-order fact membership, measurement and condition instances, and a dual view of canonical matching forms and surface evidence.

Across the frozen evaluation set, the final normalized system reaches a grade≥2 Hit@5 of 0.6724, MRR of 0.4684, shared gNDCG@5 of 0.3873, and Composite Fact Recall@5 of 0.4267. The corresponding original hypergraph values are 0.4828, 0.2832, 0.1779, and 0.0933. The CFR increase is especially relevant: it indicates that the final system retrieves a larger number of complete atomic-fact supports, rather than only improving isolated chunk matches. F0 and F1 have the same CFR, while F1 improves Hit@5 by 1.72 percentage points, showing that the reranker mainly changes the order of already retrieved candidates.

These results support a bounded conclusion. Hypergraph structure is a useful representation for high-order chemical knowledge when it is paired with entity and relation normalization, explicit measurement and condition modeling, and an evidence-aware retrieval organization. The representation alone does not guarantee better retrieval: the B1/B2 comparison shows that candidate extraction, quota allocation, serialization, and ranking interfaces materially affect the observed result. Future work should unify these interfaces, construct independent source-level and composite-evidence gold annotations, improve cross-chunk evidence aggregation, and evaluate the same QA service conditions across all systems.


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
