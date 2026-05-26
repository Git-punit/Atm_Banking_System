# main.py — app factory and startup
# wires up routers, middleware, and exception handlers
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import get_settings
from app.core.exceptions import ATMBaseException
from app.core.logging_config import configure_logging, get_logger
from app.database import create_all_tables
from app.middleware.rate_limiter import limiter
from app.routers.admin import router as admin_router
from app.routers.atm import router as atm_router
from app.routers.auth import admin_auth_router, router as auth_router
from app.routers.account import router as account_router
from app.routers.transaction import router as transaction_router

settings = get_settings()
configure_logging()
logger = get_logger(__name__)


# startup / shutdown

@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    logger.info("startup", app=settings.app_name, env=settings.app_env)
    # Create tables in development/testing; use Alembic migrations in production
    if not settings.is_production:
        create_all_tables()
        logger.info("database_tables_created")
    yield
    logger.info("shutdown", app=settings.app_name)




def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description=(
            "Production-grade ATM Banking System API.\n\n"
            "Supports card authentication, withdrawals, deposits, transfers, "
            "mini-statements, ATM terminal management, and admin operations."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # cors
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_production else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # map domain errors to structured JSON responses
    @app.exception_handler(ATMBaseException)
    async def atm_exception_handler(request: Request, exc: ATMBaseException):
        return JSONResponse(
            status_code=exc.http_status,
            content=exc.to_dict(),
        )

    # catch-all — never leak stack traces to the client
    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.error("unhandled_exception", error=str(exc), path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error_code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred. Please try again.",
            },
        )

    # routers
    app.include_router(auth_router)
    app.include_router(admin_auth_router)
    app.include_router(account_router)
    app.include_router(transaction_router)
    app.include_router(atm_router)
    app.include_router(admin_router)


    @app.get("/health", tags=["Health"], summary="Health check")
    def health():
        return {
            "status": "healthy",
            "app": settings.app_name,
            "env": settings.app_env,
            "version": "1.0.0",
        }

    return app


app = create_app()
