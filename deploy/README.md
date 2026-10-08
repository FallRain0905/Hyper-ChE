# HyperChE Docker deployment

Clone `https://github.com/FallRain0905/Hyper-ChE.git` and work from the repository root.

```bash
cp .env.hyperche.example .env
# Fill random database/application secrets and the administrator fields.
docker compose -f docker-compose.hyperche.yml --env-file .env up -d --build
docker compose -f docker-compose.hyperche.yml ps
```

The stack contains PostgreSQL, Redis, FastAPI, the Vite/React frontend and Nginx.
It listens on `HTTP_PORT` (default 80). Configure LLM/embedding channels in the
administrator interface. A database is created from uploaded literature; the
repository does not contain the original corpus or prebuilt vector caches.

Set `HYPERCHE_ADMIN_EMAIL` and `HYPERCHE_ADMIN_PASSWORD` before the first start.
No built-in administrator password is supplied. Both fields are required for
automatic administrator creation. Use strong `JWT_SECRET` and `APP_SECRET_KEY`
values and keep those values stable across restarts of an existing installation.

To supply a demo cache, privately populate the backend cache volume or mount a
seed directory at `/app/cache_seed/case1:ro` using a Compose override. The seed
is copied into writable runtime storage if the graph does not already exist.
Without a seed the application starts empty. `HYPERCHE_PUBLIC_DEMO_DATABASE`
selects the runtime database; it does not download or build one.

User accounts, provider secrets, uploaded files and generated caches live in
named volumes. `docker compose down` keeps them; deleting volumes deletes data.
The container build includes both `hyperrag` and `hyperche`, domain/normalization
configuration, and both Python requirement files.

This release checks the source and Compose configuration. A complete container
startup still requires Docker and a configured external model provider.
