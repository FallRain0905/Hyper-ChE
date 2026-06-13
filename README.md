# HyperChE

HyperChE is a domain-adaptive hypergraph RAG platform for chemical engineering literature. It is built on top of the original [Hyper-RAG](https://github.com/iMoonLab/Hyper-RAG) project and extends it toward chemical knowledge modeling, Web deployment, domain prompts, public demos, and multi-provider API management.

The central idea is that chemical literature often contains facts that are not naturally pairwise: a conclusion may depend on a joint combination of system type, material, active species, condition, metric, and mechanistic evidence. HyperChE preserves these higher-order relations as hyperedges, so retrieval can return a more complete experimental context than plain vector RAG or pairwise graph RAG.

## Relationship To The Original Hyper-RAG

This repository is a derivative research and application project based on the original Hyper-RAG framework.

Original Hyper-RAG provides:

- Hypergraph-driven retrieval augmented generation.
- Low-order and high-order relation modeling.
- Hypergraph storage, entity/relation vector indexes, and RAG query logic.
- Baseline Hyper-RAG / Graph-RAG / naive RAG query modes.

HyperChE adds:

- Chemical-engineering-oriented domain adaptation.
- JSON-based structured extraction for entities, low-order relations, and high-order hyperedges.
- Domain prompt packs for flow batteries and PFAS piezocatalysis.
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
├── hyperrag/                         # Core Hyper-RAG library and chemical domain prompts
│   └── domains/
│       ├── default/
│       ├── flow_battery/
│       ├── flow_battery_streamline/
│       └── pfas_piezocatalysis/
├── web-ui/
│   ├── backend/                      # FastAPI backend
│   │   └── hyperrag_cache/
│   │       ├── case1/                # Curated flow-battery case database
│   │       └── case2/                # Curated PFAS case database
│   └── frontend/                     # React frontend
├── deploy/
│   └── nginx.hyperche.conf           # Container Nginx config
├── docker-compose.hyperche.yml       # Production-style Docker Compose stack
└── .env.hyperche.example             # Deployment environment example
```

## Main Features

- Literature upload and knowledge-base management.
- Domain selection for chemical subfields.
- LLM-based structured extraction of entities and hyperedges.
- Hypergraph construction and visualization.
- Hyper-RAG, Graph-RAG, and naive RAG query modes.
- Collapsible retrieval graph in answers to avoid heavy rendering.
- Public demo page with streaming Hyper-RAG answers.
- Admin-managed global API providers and user-managed personal API keys.
- PostgreSQL-backed login/register and quota management for public testing.

## Domain Adaptation

HyperChE currently includes two chemical domain prompt packs.

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

- Do not commit local upload folders, user databases, SQLite files, logs, or raw literature PDFs.
- Only the curated `case1` and `case2` HyperRAG databases are allowed under `web-ui/backend/hyperrag_cache/`.
- Large database files must remain under Git LFS.
- Local conversation examples are intentionally cleared from `web-ui/frontend/src/pages/Home/data.js`.

## License And Attribution

This project is based on the original Hyper-RAG project by iMoonLab. Please cite and acknowledge the original Hyper-RAG work when using HyperChE in academic or derivative projects.
