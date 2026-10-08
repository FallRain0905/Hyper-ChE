# HyperChE Web application

Use the root [README](../README.md) for the current installation and experiment
instructions and [deploy/README.md](../deploy/README.md) for Docker deployment.

- `backend/`: FastAPI, accounts, provider channels, prompt packs and databases.
- `frontend/`: React, source-evidence display and hypergraph visualization.
- The real API frontend command is `npm run start:production`; `npm run dev`
  runs the upstream mock mode.
- Caches, uploaded documents and provider credentials are local runtime data.

The root `docker-compose.hyperche.yml` is the supported deployment description.
The Compose file in this directory is retained for legacy SQLite deployments
with privately mounted settings and a cache seed.
