from fastapi import FastAPI

from app.routes import health

app = FastAPI(title="Obsidian Workflow Worker", docs_url=None, redoc_url=None)
app.include_router(health.router)
