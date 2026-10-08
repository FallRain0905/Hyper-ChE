# Public release verification

Snapshot prepared on 2026-10-08 for B0/B1/B2/F0/F1.

## Verified

- `python scripts/reproduce_paper_metrics.py`: all five systems match archived
  retrieval metrics at grades 1/2/3 and CFR, including every per-fact support flag.
- Dataset dimensions: 58 retrieval queries, 4,196 qrels, 150 accepted facts.
- `python -m pytest tests -q`: 83 passed, 20 subtests passed; 3 existing warnings.
- `npm run build`: frontend production build passed; 6,339 modules transformed.
  Existing lint/import/bundle-size warnings remain.
- Docker Compose YAML parses and contains PostgreSQL, Redis, backend, frontend,
  Nginx. Docker image execution was not available in the verification environment.
- Markdown links resolve; manuscript body, bibliography and real PDF figures
  exist; all project Python source parses.
- Public code/data paths were scanned for common API/token/private-key formats.
  Runtime settings, cache databases, full literature and generated bundles are
  excluded from the published snapshot.

## Source changes for deployment

- Include `hyperche`, `configs`, and both requirement files in the backend image.
- Start without a demo seed; copy a privately mounted seed when provided.
- Pass prompt-domain and demo-database environment settings to the backend.
- Create an administrator only when both email and password are supplied;
  remove workstation-specific default credentials from the public source.

## Pending paper and experiment work

- Author and affiliation information, plus three method/example figures.
- Final manuscript layout and arXiv server compilation.
- Complete comparable historical QA summaries; no such claim is made.
- Controlled B1/B2 retrieval ablation and quantified build/service cost.

`examples/` and `reproduce/` contain inherited utilities. Some require the
user's private `my_config.py`; they are not the offline paper-results entrypoint.
The original caches and manuscript/editor copies remain local and are unchanged.
