import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config.settings import settings
from app.core.middleware import GlobalErrorHandlerMiddleware, LoggingMiddleware
from app.utils.logging import configure_logging
from app.routes import auth, health, users
configure_logging()


security = HTTPBasic()

def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
    # Deny outright when docs credentials are not configured, so an unset
    # DOCS_PASSWORD can never be satisfied by an empty password.
    if not (settings.DOCS_USERNAME and settings.DOCS_PASSWORD):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Docs are not available.",
            headers={"WWW-Authenticate": "Basic"},
        )
    correct_username = secrets.compare_digest(credentials.username, settings.DOCS_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, settings.DOCS_PASSWORD)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    from app.config.filebase import filebase_proxy
    from app.config.firebase import firebase_proxy
    from app.config.redis import redis_proxy
    from app.config.supabase import supabase_proxy
    from app.config.temporal import temporal_proxy

    await redis_proxy.init_client()
    await temporal_proxy.init_client()
    supabase_proxy.init_client()
    firebase_proxy.init_client()
    filebase_proxy.init_client()

    import asyncio
    from app.services.health_service import HealthService

    async def _health_loop():
        while True:
            await asyncio.sleep(30)
            try:
                await HealthService.check_readiness()
            except Exception as e:
                import structlog
                structlog.get_logger(__name__).error("health_loop_failed", error=str(e))

    app.state.health_task = asyncio.create_task(_health_loop())

    yield  # Application runs here

    # Shutdown
    health_task = getattr(app.state, "health_task", None)
    if health_task:
        health_task.cancel()

    from app.config.observability import observability_proxy

    await redis_proxy.close_client()
    await observability_proxy.close_clients()


def create_app() -> FastAPI:
    env = settings.APP_ENV.lower()

    if env in ["production", "prod", "staging", "testing"]:
        docs_url = None
        redoc_url = None
        openapi_url = None
    else:
        docs_url = "/docs"
        redoc_url = "/redoc"
        openapi_url = "/openapi.json"

    app = FastAPI(
        title="Obsidian API",
        description="Autonomous Earth Intelligence Platform — public API.",
        version="1.0.0",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        lifespan=lifespan,
    )

    if env in ["staging", "testing"]:
        @app.get("/docs", include_in_schema=False)
        async def get_swagger_documentation(username: str = Depends(get_current_username)):
            return get_swagger_ui_html(openapi_url="/openapi.json", title="docs")

        @app.get("/redoc", include_in_schema=False)
        async def get_redoc_documentation(username: str = Depends(get_current_username)):
            return get_redoc_html(openapi_url="/openapi.json", title="redoc")

        @app.get("/openapi.json", include_in_schema=False)
        async def openapi(username: str = Depends(get_current_username)):
            return get_openapi(title=app.title, version=app.version, routes=app.routes)

    _register_middleware(app)
    _setup_observability(app)
    _register_routes(app)

    return app


def _setup_observability(app: FastAPI) -> None:
    from app.config.observability import observability_proxy

    observability_proxy.init_clients()
    observability_proxy.instrument_fastapi(app)


def _register_middleware(app: FastAPI) -> None:
    app.add_middleware(GlobalErrorHandlerMiddleware)
    app.add_middleware(LoggingMiddleware)
    # Wildcard origins and credentialed requests are mutually exclusive per the
    # CORS spec; only allow credentials when an explicit origin allowlist is set.
    allow_all_origins = settings.CORS_ORIGINS == ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=not allow_all_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _register_routes(app: FastAPI) -> None:
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)


app = None
if __name__ != "__main__":
    app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.APP_ENV == "development",
        workers=1 if settings.APP_ENV == "development" else 4,
        log_config=None,
    )
