"""
Point d'entrée principal de l'application ToitureAI.

FastAPI application avec:
- Endpoints pour tous les workflows migrés
- Middleware de logging et sécurité
- Gestion globale des erreurs
- Documentation OpenAPI
"""

from __future__ import annotations



import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.error_handler import global_exception_handler, ToitureAIError

# Configuration du logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gestionnaire de cycle de vie de l'application.

    Exécute du code au démarrage et à l'arrêt de l'application.
    """
    # Startup
    logger.info(f"Demarrage de {settings.app_name} en mode {settings.app_env}")
    logger.info(f"API disponible sur {settings.api_host}:{settings.api_port}")

    # Vérification des configurations critiques
    try:
        # Test de connexion Supabase (lazy)
        from app.core.database import supabase
        logger.info("Configuration Supabase OK")
    except Exception as e:
        logger.error(f"Erreur configuration Supabase: {e}")

    # Demarrage du scheduler (taches planifiees)
    try:
        from app.core.scheduler import scheduler_service
        scheduler_service.start()
        logger.info("Scheduler demarre")
    except Exception as e:
        logger.error(f"Erreur demarrage scheduler: {e}")

    yield

    # Shutdown
    logger.info(f"Arret de {settings.app_name}")

    # Arret du scheduler
    try:
        from app.core.scheduler import scheduler_service
        scheduler_service.stop()
        logger.info("Scheduler arrete")
    except Exception as e:
        logger.error(f"Erreur arret scheduler: {e}")


# Création de l'application FastAPI
app = FastAPI(
    title=settings.app_name,
    description="""
    ## ToitureAI - API de gestion de leads et devis

    Migration des workflows n8n vers Python/FastAPI.

    ### Workflows implementes:
    - **Workflow 1**: Lead Generation & Qualification AI
    - **Workflow 2**: Devis & Facturation Automatique
    - **Workflow 3**: Rapport Mensuel PDF (cron 1er du mois 8h)
    - **Workflow 4**: Lead Tracking
    - **Workflow 5**: DocuSeal Signature Completee
    - **Workflow 6**: Error Handler (integre)

    ### Authentification:
    Tous les endpoints webhook necessitent le header `X-Webhook-Secret`.
    """,
    version="1.0.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
    lifespan=lifespan
)

# Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://toitureai.fr",           # ton domaine principal
        "https://www.toitureai.fr",       # avec www
        "https://app.toitureai.fr",
        "http://localhost:3000",
        "http://localhost:4321",
        "http://localhost:5173",
        "http://localhost:8080",
    ] if settings.is_production else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Middleware de logging des requêtes
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log toutes les requêtes entrantes."""
    start_time = datetime.now(timezone.utc)

    # Log de la requête
    logger.info(
        f"📥 {request.method} {request.url.path} "
        f"from {request.client.host if request.client else 'unknown'}"
    )

    response = await call_next(request)

    # Calcul du temps de réponse
    process_time = (datetime.now(timezone.utc) - start_time).total_seconds()

    # Log de la réponse
    logger.info(
        f"📤 {request.method} {request.url.path} "
        f"- {response.status_code} ({process_time:.3f}s)"
    )

    # Ajout du header de temps de traitement
    response.headers["X-Process-Time"] = str(process_time)

    return response


# Handler d'exceptions global
@app.exception_handler(ToitureAIError)
async def toitureai_exception_handler(request: Request, exc: ToitureAIError):
    """Handler pour les exceptions ToitureAI."""
    return await global_exception_handler(request, exc)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Handler pour toutes les autres exceptions."""
    return await global_exception_handler(request, exc)


# === Routes de base ===

@app.get("/", tags=["health"])
async def root():
    """Page d'accueil de l'API."""
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "status": "running",
        "environment": settings.app_env,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/health", tags=["health"])
async def health_check():
    """
    Endpoint de health check.

    Utilisé par les load balancers et monitoring.
    """
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {}
    }

    # Check Supabase
    try:
        from app.core.database import supabase
        supabase.table("leads").select("id").limit(1).execute()
        health_status["services"]["supabase"] = "ok"
    except Exception as e:
        health_status["services"]["supabase"] = f"error: {str(e)[:50]}"
        health_status["status"] = "degraded"

    # Check OpenAI (on ne fait pas de vraie requête pour économiser)
    try:
        from openai import OpenAI
        OpenAI(api_key=settings.openai_api_key)
        health_status["services"]["openai"] = "configured"
    except Exception as e:
        health_status["services"]["openai"] = f"error: {str(e)[:50]}"

    # Check SendGrid (config only)
    try:
        from sendgrid import SendGridAPIClient
        SendGridAPIClient(settings.sendgrid_api_key)
        health_status["services"]["sendgrid"] = "configured"
    except Exception as e:
        health_status["services"]["sendgrid"] = f"error: {str(e)[:50]}"

    status_code = 200 if health_status["status"] == "healthy" else 503
    return JSONResponse(content=health_status, status_code=status_code)


@app.get("/ready", tags=["health"])
async def readiness_check():
    """
    Endpoint de readiness check.

    Vérifie que l'application est prête à recevoir du trafic.
    """
    return {"status": "ready", "timestamp": datetime.now(timezone.utc).isoformat()}


# === Import des routers ===

from app.api.lead_webhook import router as lead_router
from app.api.tracking import router as tracking_router
from app.api.devis_webhook import router as devis_router
from app.api.docuseal_webhook import router as docuseal_router
from app.api.rapport_webhook import router as rapport_router

# Enregistrement des routers
app.include_router(lead_router)
app.include_router(tracking_router)
app.include_router(devis_router)
app.include_router(docuseal_router)
app.include_router(rapport_router)


# === Point d'entrée pour uvicorn ===

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info"
    )
