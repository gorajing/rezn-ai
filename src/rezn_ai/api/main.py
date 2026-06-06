"""FastAPI entrypoint for the rezn-ai orchestration service."""

from __future__ import annotations

from fastapi import FastAPI

from rezn_ai.tracing.weave_client import default_project_name


app = FastAPI(
    title="rezn-ai orchestration API",
    description="Multi-agent music candidate orchestration with Weave, Redis, and CopilotKit.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "weave_project": default_project_name(),
    }
