# HyperChE project structure

| Directory | Purpose |
| --- | --- |
| `hyperrag/` | Core extraction, storage, embeddings and graph/hypergraph retrieval |
| `hyperche/normalization/` | Alias rules, post-hoc normalization, final evidence-bound cache |
| `hyperche/retrieval/` | Chemistry query normalization |
| `hyperche/prompts/` | Versioned domain prompt materialization |
| `configs/` | Experiment modes and normalization rules |
| `scripts/` | Cache construction, retrieval, annotation, QA and offline metric reproduction |
| `tests/` | Regression tests for normalization, evidence binding and retrieval |
| `web-ui/backend/` | FastAPI, authentication, providers and knowledge-base management |
| `web-ui/frontend/` | React/TypeScript interface |
| `experiments/final_v1/` | Public five-system experiment evidence |
| `paper/` | Chinese/English drafts, figure plan and LaTeX source |
| `deploy/` | Docker/Nginx deployment instructions |
| `examples/`, `evaluate/`, `reproduce/` | Upstream examples and legacy evaluation helpers |

Runtime settings, credentials, uploaded literature, vector databases and local
scratch results are not versioned. See the root README for current run commands.
