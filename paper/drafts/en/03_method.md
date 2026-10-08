# 5. Method

## 5.1 Task formulation and design goals

HyperChE is designed for retrieval over chemical literature in which a useful answer is often determined by a combination of entities, measurements, operating conditions, and outcomes. The retrieval target is therefore not only an isolated entity or a locally matching sentence. It is an evidence set that preserves the binding among the roles that jointly define a chemical fact.

Let $q$ be a query and let $R_k(q)$ be the ranked list of the top-$k$ source chunks returned by the system. The system is evaluated at two levels. At the chunk level, a returned chunk is relevant when it satisfies the shared query--chunk judgment protocol. At the fact level, a composite fact is supported only when its exact supporting chunk appears in $R_k(q)$. The second level prevents a system from receiving full credit merely for returning a related entity while missing the condition, measurement, or result that completes the fact.

The design has four goals:

1. preserve multi-role chemical facts as retrievable units;
2. make aliases, relation variants, and measurement expressions searchable under a common representation;
3. retain the original surface wording so that retrieved evidence can be traced back to the source text; and
4. separate candidate recall from candidate ordering so that the contribution of deterministic reranking can be measured.

## 5.2 Ordinary graphs and hypergraphs

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

## 5.3 Chemical fact extraction and evidence binding

The input corpus is divided into frozen source chunks. A domain-specific extraction pass produces, for each chunk, entity mentions, relation or fact descriptions, measurement instances, condition instances, and pointers to the source evidence. The extraction record is organized around a fact instance rather than around an unconstrained list of entity pairs. A useful abstract form is

\[
f_i=(s_i,r_i,A_i,M_i,C_i,P_i,E_i),
\]

where $A_i$ is the set of participating entities, $M_i$ is the set of measurements, $C_i$ is the set of conditions, $P_i$ contains the property or outcome roles, and $E_i$ identifies the source chunk and evidence span. The role sets may be partially populated when the source statement does not provide every role; the system does not fill missing roles by combining unrelated chunks.

Measurements are kept as typed local instances. A measurement may include a value or interval, a unit, a comparator, and the object to which the value applies. Conditions are kept as instances as well, so that temperature, composition, flow, loading, or other operating context remains attached to the fact in which it was observed. Values that are ambiguous in the chunk-local extraction are preserved rather than silently split or assigned to a different object. This prevents a value observed under one condition from becoming an unconditional property of the material.

The extraction record also stores the original surface wording and an evidence pointer. These two fields serve different purposes: the structured record supports matching and aggregation, while the surface evidence supports quotation, reconstruction, and manual audit.

## 5.4 Entity and relation normalization

Chemical literature uses aliases, abbreviations, spelling variants, unit variants, and relation phrases that refer to the same underlying concept. HyperChE maps such variants to a canonical representation before indexing. Normalization is applied to entity names, relation descriptions, and measurement or unit expressions when a canonical form is available. The source surface form is retained alongside the canonical form.

Let $x^{\mathrm{surf}}$ denote a mention as it appears in the source and $x^{\mathrm{can}}$ its normalized form. The dual record is

\[
\operatorname{Dual}(x)=
\bigl(x^{\mathrm{can}},x^{\mathrm{surf}},E_x\bigr),
\]

where $E_x$ is the evidence pointer. Canonical text makes equivalent mentions easier to aggregate across chunks and documents. Surface text preserves the wording needed to verify a result and to reconstruct the source chunk. The final cache uses the `dual_concat` index profile so that both views remain available to the retrieval representation; the exact surface string is never discarded from the evidence record.

Normalization is not treated as an independent semantic label. It is a representation and indexing operation whose value is tested through the end-to-end retrieval and composite-fact results. The final cache records the normalization version and an evidence rewrite audit, allowing the canonical record and its source form to be checked independently.

## 5.5 Hypergraph construction and indexed objects

Each normalized fact is represented by a hyperedge-like relationship object and a set of incident entity nodes. The relationship object contains the canonical relation text, surface description, typed role information, the measurement and condition instances, and the source pointer. Entity objects contain canonical and surface names plus their incident relationship identifiers. The resulting incidence structure supports two complementary retrieval views:

- **entity view:** retrieves entities whose canonical or surface descriptions match the query;
- **relationship view:** retrieves binary or higher-arity relationship objects whose fact descriptions match the query.

The same source chunk can therefore be reached from an entity match, a relationship match, or both. After graph expansion, the system reconstructs the complete source chunk rather than exposing only a truncated graph fragment to the generator. This keeps graph retrieval connected to verifiable textual evidence.

## 5.6 Hybrid candidate retrieval

For a query $q$, HyperChE independently computes dense and lexical scores for relationship objects and entity objects. The candidate lists are fused with weighted reciprocal rank fusion (RRF). For a candidate $d$, the fusion score has the form

\[
S_{\mathrm{RRF}}(d)=
\sum_{j\in\mathcal{L}(d)}
\frac{w_j}{k_{\mathrm{RRF}}+\operatorname{rank}_j(d)},
\]

where $\mathcal{L}(d)$ is the set of dense or BM25 lists containing $d$, $w_j$ is the channel weight, and $k_{\mathrm{RRF}}$ is the RRF offset. The final normalized retrieval configuration uses relationship dense and BM25 channels, entity dense and BM25 channels, one-hop incident-edge expansion, and a deterministic structural rerank over a frozen candidate pool. Relationship candidate depth is 50, entity candidate depth is 30, the RRF offset is 60, and the relationship and entity channel weights are fixed by the released protocol. These settings are held constant between the no-rerank and rerank variants.

One-hop expansion follows incident relationships from retrieved entities and adds their linked fact objects, subject to the released expansion limit. The resulting candidate pool is mapped back to source chunks. If multiple structured objects map to the same chunk, the chunk is retained once with its associated structured evidence. The final ranked output is a list of reconstructed source chunks, which is the unit used by the shared qrels and by the QA evidence interface.

## 5.7 F0/F1 reranking ablation

The F0/F1 comparison isolates the ordering stage. Both variants use the same hybrid RRF procedure and the same frozen top-50 candidate pool. F0 returns the pool after the common retrieval and expansion steps, with the existing structural rerank disabled. F1 applies the deterministic structural rerank to that identical pool and then reconstructs the source chunks. Reranking can change the order of candidates already present in the pool, but it cannot introduce a fact that was not retrieved into the pool.

This separation makes the interpretation explicit. A change in Hit@5, MRR, or graded NDCG between F0 and F1 is an ordering effect under a fixed recall pool. A change in Composite Fact Recall would indicate that the ordering brings an already retrieved exact-support chunk into the evaluated top-$k$; it would not indicate that reranking discovered a new candidate.

## 5.8 Evidence interface and generation boundary

For each query, the top five reconstructed source chunks are passed to the supplementary QA interface under the fixed evidence budget. EFU repair is disabled throughout the retrieval and QA runs. The QA generator therefore does not repair, invent, or retrieve missing evidence on behalf of the retrieval system. Citation validity and answer completeness are reported as supplementary outcomes, while the primary claims are based on the shared retrieval judgments and composite-fact coverage.
