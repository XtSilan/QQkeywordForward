"""Layered self-update service: HTTP API + background loops + git/docker glue.

Modules::

    config      env-driven configuration (read once at import)
    git         git subprocess helpers (local/remote SHA, dirty check)
    docker_api  Docker Engine API over the unix socket
    state       shared run state + persisted last-run record
    versioning  build-version parsing / staleness decision (pure)
    signatures  webhook HMAC + ref filter (pure)
    service     helper lifecycle, poll/watch loops, check-and-start
    api         FastAPI routes

``deploy/app.py`` is only the uvicorn entrypoint; the throwaway update
helper is ``deploy/update_run.py`` (spawned as a sibling container).
"""
