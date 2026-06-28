# HyperChE

HyperChE is a domain-adaptive hypergraph RAG platform for chemical engineering literature. It is built on top of the original [Hyper-RAG](https://github.com/iMoonLab/Hyper-RAG) project and extends it toward chemical knowledge modeling, domain-specific extraction, Web deployment, public demos, multi-provider API management, conservative entity normalization, and benchmark evaluation.

The central idea is that chemical literature often contains facts that are not naturally pairwise. A conclusion may depend on a joint combination of system type, material, active species, operating condition, performance metric, and mechanistic evidence. HyperChE preserves these higher-order experimental facts as hyperedges, so retrieval can return a more complete context than plain vector RAG or pairwise Graph-RAG.

## Relationship To The Original Hyper-RAG

This repository is a derivative research and application project based on the original Hyper-RAG framework.

Original Hyper-RAG provides:

- Hypergraph-driven retrieval augmented generation.
- Low-order and high-order relation modeling.
- Hypergraph storage, entity/relation vector indexes, and RAG query logic.
- Baseline Hyper-RAG, Graph-RAG, and naive RAG query modes.

HyperChE adds:

- Chemical-engineering-oriented domain adaptation.
- JSON-based structured extraction for entities, low-order relations, and high-order hyperedges.
- Domain prompt packs for flow batteries and PFAS piezocatalysis.
- A conservative chemical entity normalization module.
- Measurement and condition instance nodes for numeric experimental facts.
- Experiment modes for main experiments and ablation studies.
- Fact Coverage@k and QA evaluation CLIs.
- A React + FastAPI Web application branded as HyperChE.
- Login/register, admin settings, user API key management, trial quotas, and public demo pages.
- Multi-provider LLM and embedding API key pooling.
- Public demo streaming responses through SSE.
- Two curated case databases for paper experiments and platform demonstration.

## Current Case Databases

Only two curated case databases are kept in this formal repository:

| Case | Path | Domain | Description |
| --- | --- | --- | --- |
| Case 1 | `web-ui/backend/hyperrag_cache/case1` | `flow_battery_streamline` | Flow battery literature, including VRFB, ICRFB, membrane materials, electrode modification, additives, conditions, metrics, and degradation mechanisms. |
| Case 2 | `web-ui/backend/hyperrag_cache/case2` | `pfas_piezocatalysis` | PFAS/PFOA/PFOS/GenX removal, enrichment, degradation, defluorination, mineralization, piezocatalysis, contact-electro-catalysis, and mechanism evidence. |

The case databases contain large vector files. They are tracked with Git LFS. Before cloning or pushing this repository, install Git LFS:

```bash
git lfs install
```

## Project Structure

```text
Hyper-RAG/
|-- hyperrag/                         # Core Hyper-RAG library and domain prompt loader
|   |-- domains/
|   |   |-- default/
|   |   |-- flow_battery/
|   |   |-- flow_battery_streamline/
|   |   |-- pfas_piezocatalysis/
|   |   `-- generic_json/              # Generic JSON profile for prompt ablation
|   `-- experiment.py                  # Experiment mode resolver
|-- hyperche/
|   `-- normalization/                 # Conservative chemical entity normalization
|-- configs/
|   |-- experiments/                   # Mode, cache-map, and QA-map examples
|   `-- normalization/                 # Alias registry, negative rules, equivalence maps
|-- scripts/
|   |-- build_experiment_cache.py      # Build benchmark caches by experiment mode
|   |-- evaluate_fact_coverage.py      # Fact Coverage@k evaluator
|   |-- evaluate_qa_answers.py         # Seven-dimension QA answer evaluator
|   |-- normalize_hypergraph.py        # Offline normalization audit tool
|   `-- report_normalization.py        # Normalization report helper
|-- web-ui/
|   |-- backend/                       # FastAPI backend
|   |   `-- hyperrag_cache/
|   |       |-- case1/                  # Curated flow-battery case database
|   |       `-- case2/                  # Curated PFAS case database
|   `-- frontend/                      # React frontend
|-- deploy/
|   `-- nginx.hyperche.conf            # Container Nginx config
|-- docker-compose.hyperche.yml        # Production-style Docker Compose stack
`-- .env.hyperche.example             # Deployment environment example
```

## Main Features

- Literature upload and knowledge-base management.
- Domain selection for chemical subfields.
- LLM-based structured extraction of entities and hyperedges.
- Hypergraph construction and visualization.
- Hyper-RAG, Graph-RAG, and naive RAG query modes.
- Conservative entity normalization with exact aliases, fuzzy candidates, negative rules, and optional LLM judgment.
- Numeric measurement/condition instance nodes, such as `measurement:ee_80_9_percent` and `condition:current_density_100_ma_cm2`.
- Collapsible retrieval graph in answers to avoid heavy rendering.
- Public demo page with streaming Hyper-RAG answers.
- Admin-managed global API providers and user-managed personal API keys.
- PostgreSQL-backed login/register and quota management for public testing.

## Domain Adaptation

HyperChE currently includes two chemical domain prompt packs and one generic JSON prompt profile.

### Flow Battery

Representative entity types include:

- `ACTIVE_SPECIES`
- `MEMBRANE`
- `ELECTRODE`
- `CONDITION`
- `METRIC`
- `DEGRADATION`
- `SYSTEM`

Representative relation / hyperedge types include:

- `COMPOSITION`
- `OPERATION`
- `DEGRADATION`
- `COMPARISON`

### PFAS Piezocatalysis

Representative entity types include:

- `PFAS_TARGET`
- `CATALYST_MATERIAL`
- `MATERIAL_FEATURE`
- `PIEZO_PROPERTY`
- `PROCESS_STRATEGY`
- `CONDITION`
- `METRIC`
- `ACTIVE_SPECIES`
- `MECHANISM_EVIDENCE`
- `WATER_MATRIX`

Representative relation / hyperedge types include:

- `MATERIAL_DESIGN`
- `OPERATION_PERFORMANCE`
- `MECHANISM_PATHWAY`
- `ADSORPTION_ORIENTATION`
- `CHARGE_TRANSFER`
- `COUPLING_STRATEGY`
- `MATRIX_APPLICATION`
- `COMPARISON`

### Generic JSON

`hyperrag/domains/generic_json/` keeps the same JSON output schema as the chemical prompts but uses generic entity and relation labels. It is intended for prompt-profile ablation, especially the `hyper_base` experiment mode.

## Experiment Modes

Experiment modes are configured in `configs/experiments/modes.yaml`.

| Mode | Query View | Prompt Profile | Normalization | Measurement Instances | EFU Repair | Hybrid Rerank |
| --- | --- | --- | --- | --- | --- | --- |
| `graph_final` | graph | chemistry | on | on | on | on |
| `hyper_base` | hyper | generic_json | off | off | off | off |
| `hyper_chem_prompt` | hyper | chemistry | off | off | off | off |
| `hyper_norm` | hyper | chemistry | on | off | off | off |
| `hyper_final` | hyper | chemistry | on | on | on | on |
| `final_no_measurement` | hyper | chemistry | on | off | on | on |
| `final_no_repair` | hyper | chemistry | on | on | off | on |
| `final_no_rerank` | hyper | chemistry | on | on | on | off |
| `final_full` | hyper | chemistry | on | on | on | on |

Each built cache writes a `run_config.json` file into the cache directory. The evaluator reads this metadata to decide graph/hyper view and reranking behavior.

## CLI Usage

### 1. Build An Experiment Cache

Set OpenAI-compatible LLM and embedding providers through environment variables:

```powershell
$env:LLM_API_KEY="sk-..."
$env:LLM_BASE_URL="https://api.deepseek.com"
$env:LLM_MODEL="deepseek-v4-flash"
$env:EMB_API_KEY="sk-..."
$env:EMB_BASE_URL="https://api.siliconflow.cn/v1"
$env:EMB_MODEL="Qwen/Qwen3-Embedding-4B"
$env:EMB_DIM="2560"
```

Build a cache for one mode:

```powershell
python scripts\build_experiment_cache.py `
  --input C:\Users\surface\Downloads\flow_battery_embedding_corpus.md `
  --cache-dir web-ui\backend\hyperrag_cache\flow_benchmark_hyper_final `
  --mode hyper_final `
  --domain flow_battery
```

Useful options:

```powershell
--chunk-size 1200
--chunk-overlap 100
--llm-timeout 600
--embedding-timeout 120
--llm-max-async 4
--embedding-max-async 4
--embedding-batch-num 8
```

### 2. Configure A Multi-Mode Cache Map

Copy the example:

```powershell
Copy-Item configs\experiments\cache_map.example.yaml configs\experiments\cache_map.yaml
```

Then edit `configs/experiments/cache_map.yaml` so each mode points to its own cache directory.

### 3. Run Fact Coverage@k Evaluation

Single-cache legacy style:

```powershell
python scripts\evaluate_fact_coverage.py `
  --gold C:\Users\surface\Downloads\flow_battery_longdoc_gold_efu_facts_v03.json `
  --cache-dir web-ui\backend\hyperrag_cache\flow_benchmark_hyper_final `
  --k 1,3,5,10 `
  --judge-mode heuristic `
  --output web-ui\backend\hyperrag_cache\flow_benchmark_hyper_final\fact_coverage_report.json
```

Multi-mode, multi-judge style:

```powershell
$env:DEEPSEEK_API_KEY="sk-..."
$env:KIMI_API_KEY="sk-..."
$env:QWEN_API_KEY="sk-..."

python scripts\evaluate_fact_coverage.py `
  --gold C:\Users\surface\Downloads\flow_battery_longdoc_gold_efu_facts_v03.json `
  --modes graph_final hyper_base hyper_chem_prompt hyper_norm hyper_final `
  --cache-map configs\experiments\cache_map.yaml `
  --k-values 1 3 5 10 `
  --judge-mode llm `
  --judge-models kimi deepseek qwen `
  --output-dir outputs\fact_coverage\flow_v03_main
```

Fact Coverage outputs:

```text
outputs/fact_coverage/{run_id}/
|-- run_config.json
|-- fact_coverage_summary.csv
|-- fact_coverage_summary.json
|-- fact_coverage_full_judgments.json
|-- fact_coverage_llm_judgments.jsonl
|-- fact_coverage_heuristic_diagnostics.json
|-- evidence_contexts.jsonl
|-- model_raw_outputs.jsonl
|-- errors.jsonl
`-- run.log
```

### 4. Run QA Answer Evaluation

Create a QA answer map from the example:

```powershell
Copy-Item configs\experiments\qa_answer_map.example.yaml configs\experiments\qa_answer_map.yaml
```

Then run:

```powershell
python scripts\evaluate_qa_answers.py `
  --answer-map configs\experiments\qa_answer_map.yaml `
  --modes graph_final hyper_base hyper_chem_prompt hyper_norm hyper_final `
  --judge-models kimi deepseek qwen `
  --output-dir outputs\qa_eval\flow_v03_main
```

The QA evaluator scores each answer on seven dimensions:

- factual correctness
- condition completeness
- numerical accuracy
- mechanistic support
- comparative clarity
- source grounding
- readability

QA outputs:

```text
outputs/qa_eval/{run_id}/
|-- run_config.json
|-- qa_score_summary.csv
|-- qa_score_summary.json
|-- qa_full_judgments.json
|-- qa_llm_judgments.jsonl
|-- model_raw_outputs.jsonl
|-- errors.jsonl
`-- run.log
```

## Local Development

### Backend

```bash
cd web-ui/backend
python -m venv .venv
.venv/Scripts/activate  # Windows
pip install -r requirements.txt
python main.py
```

### Frontend

```bash
cd web-ui/frontend
npm install
npm run dev
```

The frontend uses `VITE_SERVER_URL` to locate the backend. In local development, the default backend URL is usually `http://localhost:8000`.

## Docker Deployment

Copy the environment example and edit secrets:

```bash
cp .env.hyperche.example .env
```

Start the stack:

```bash
docker compose -f docker-compose.hyperche.yml --env-file .env up -d --build
```

The stack includes:

- PostgreSQL
- Redis
- FastAPI backend
- React frontend
- Nginx reverse proxy

For public demo queries, set:

```env
HYPERCHE_PUBLIC_DEMO_DATABASE=case1
```

or:

```env
HYPERCHE_PUBLIC_DEMO_DATABASE=case2
```

## API Configuration

Global platform API providers are configured by the admin user in the Web settings page. Personal user API keys can also be added in the settings page and will take priority for that user's requests.

The backend supports OpenAI-compatible providers for both LLM and embedding calls. Multiple keys and multiple providers can be configured to improve throughput and failover.

## Notes For Repository Maintenance

- Do not commit local upload folders, user databases, SQLite files, logs, raw literature PDFs, or temporary files.
- Only the curated `case1` and `case2` HyperRAG databases are allowed under `web-ui/backend/hyperrag_cache/`.
- Large database files must remain under Git LFS.
- Local conversation examples are intentionally cleared from the public demo data.
- Keep experiment outputs under `outputs/`; commit only selected summaries when they are intended as paper artifacts.

## License And Attribution

This project is based on the original Hyper-RAG project by iMoonLab. Please cite and acknowledge the original Hyper-RAG work when using HyperChE in academic or derivative projects.
