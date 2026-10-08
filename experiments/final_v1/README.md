# Frozen final experiment evidence

This directory is the public evidence snapshot for B0/B1/B2/F0/F1.

- `retrieval/`: summary, per-query, slice, top-k and source diagnostics.
- `cfr/`: accepted fact annotations, qrels, audit acceptance and CFR outputs.
- `qa/`: F1's 40-question answers, protocol, summaries and diagnostic slices.
- `protocol/`: frozen run settings and experiment state.
- `benchmark/`: the 58 queries and a compact export of frozen candidate ranks.
- `reports/`: system attribution and the B1/B2 retrieval diagnosis.

There are 60 documents, 1,328 chunks, 58 retrieval queries, 4,196 pooled judgments
and 150 accepted facts. The exported rank pool retains every pair, including
pairs without a ranking for a retained system, to keep the frozen shared IDCG.
It contains only IDs and ranks, not the full literature passages or vectors.

Run `python scripts/reproduce_paper_metrics.py` from the repository root to
recompute retrieval and CFR from the frozen rankings and accepted judgments,
and verify them against the archived summaries. No API calls are needed.

B1/B2 differ in retrieval adapters; the comparison does not isolate arity or
prompting. F0/F1 share a hybrid RRF top-50 candidate pool. EFU repair is disabled.
QA is supplementary: F1 used Alibaba Cloud DashScope and historical runs used
Moonshot. The nominal `kimi-k2.6` name does not make those services identical.
No complete historical multi-system QA comparison is claimed here.

Audit acceptance: the user confirmed the review after spot-checking. Existing
judgments retained after provider failures are recorded in the audit files.
Original local paths in frozen metadata are provenance, not clone setup paths.
The source corpus and vector caches must be supplied separately for fresh runs.
