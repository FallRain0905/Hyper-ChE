# HyperChE paper figures

`make_paper_figures.py` writes the following paired PDF/PNG figures:

- `main_results_four_metrics.pdf` / `.png`: grouped bars for Hit@5, MRR,
  shared gNDCG@5, and Composite Fact Recall@5 for B0, B1, B2, F0, and F1.
- `f0_f1_rerank_ablation.pdf` / `.png`: controlled F0/F1 comparison. Both
  systems use the same hybrid RRF top-50 candidate pool; the only changed
  switch is deterministic structural reranking.

The values are the reported grade>=2 retrieval results from the shared qrels
protocol. PDF output is vector format for LaTeX inclusion; PNG output is a
300-dpi preview. The plotting script contains no API keys or endpoint data.

Regenerate with:

```text
python make_paper_figures.py
```
