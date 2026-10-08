# HyperChE backend

Install both Python requirement files from the repository root. From this
directory launch `python -m uvicorn main:app --host 127.0.0.1 --port 8000`.

Set HYPERCHE_ADMIN_EMAIL and HYPERCHE_ADMIN_PASSWORD to create the administrator.
Model credentials are configured through provider channels or private local
settings. No administrator account is automatically created without those fields.

See the root README and deploy/README.md for application keys, persistent storage
and Docker setup. Knowledge-base caches and settings.json are not published.
