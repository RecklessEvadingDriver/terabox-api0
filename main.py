import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.proxy_pool import proxy_pool
from app.routers import terabox_router, proxy_router
from app.utils.rate_limiter import rate_limit_middleware
from app.utils.logger import log


# ─── App Start/Stop ───────────────────────────────────────────────────────────

START_TIME = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup aur shutdown events"""
    log.info(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} starting...")
    # Vercel serverless pe background tasks nahi chalte
    # Proxy pool lazy-load hoga pehli request pe
    try:
        await proxy_pool.start()
    except Exception as e:
        log.error(f"Proxy pool startup error: {e}, continuing with empty pool")
    log.info("✅ Startup done!")
    yield
    log.info("🛑 Shutting down...")
    try:
        await proxy_pool.stop()
    except Exception as e:
        log.warning(f"Proxy pool shutdown error: {e}")


# ─── App Init ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
## 🚀 Terabox Direct Link Generator API

Terabox share URLs se **direct download links** generate karo — with:
- ⚡ Auto proxy rotation
- 🔄 Retry logic
- 💾 Response caching
- 🛡️ Rate limiting
- 📊 Live proxy stats

### Quick Start
```
GET /api/get-link?url=https://terabox.com/s/XXXXX
```
    """,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ─── Middleware ───────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(rate_limit_middleware)


# ─── Exception Handlers ───────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )


# ─── Routers ─────────────────────────────────────────────────────────────────

app.include_router(terabox_router.router)
app.include_router(proxy_router.router)


# ─── Root Endpoints ───────────────────────────────────────────────────────────

@app.get("/", tags=["Info"])
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "docs": "/docs",
        "endpoints": {
            "get_link": "GET /api/get-link?url=TERABOX_URL",
            "batch":    "POST /api/batch",
            "proxy_stats": "GET /proxy/stats",
            "proxy_refresh": "POST /proxy/refresh",
            "cache_stats": "GET /api/cache/stats",
        },
    }


@app.get("/health", tags=["Info"])
async def health():
    stats = proxy_pool.stats()
    uptime = round(time.time() - START_TIME, 2)

    status = "healthy"
    if stats["active_proxies"] == 0:
        status = "degraded (no proxies)"

    return {
        "status": status,
        "version": settings.APP_VERSION,
        "uptime_seconds": uptime,
        "proxy_pool_size": stats["active_proxies"],
        "tor_enabled": stats["tor_enabled"],
    }


@app.post("/init", tags=["Info"])
async def initialize():
    """Manual proxy pool initialization (for Vercel cold starts)"""
    log.info("Manual initialization requested")
    try:
        await proxy_pool.start()
        stats = proxy_pool.stats()
        return {
            "status": "initialized",
            "active_proxies": stats["active_proxies"],
            "message": f"Proxy pool initialized with {stats['active_proxies']} alive proxies"
        }
    except Exception as e:
        log.error(f"Initialization failed: {e}")
        return {
            "status": "partial",
            "error": str(e),
            "message": "Proxy pool will work with direct connection fallback"
        }


# ─── WSGI Export for Vercel ─────────────────────────────────────────────────────
# Vercel needs the app object directly
__all__ = ['app']
