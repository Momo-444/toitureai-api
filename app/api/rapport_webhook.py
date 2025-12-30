"""
API endpoints pour les rapports mensuels.

Workflow 3: Rapport Mensuel PDF
- POST /api/v1/rapport/generate : Generer un rapport manuellement
- GET /api/v1/rapport/{rapport_id} : Recuperer un rapport
- GET /api/v1/rapport : Lister les rapports
- GET /api/v1/rapport/scheduler/status : Statut du scheduler
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Query

from app.core.config import settings
from app.models.rapport import (
    RapportGeneratePayload,
    RapportResponse,
)
from app.services.rapport_service import rapport_service
from app.core.scheduler import scheduler_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/rapport", tags=["Rapports"])


# === POST /api/v1/rapport/generate ===
@router.post(
    "/generate",
    response_model=RapportResponse,
    summary="Generer un rapport mensuel",
    description="""
    Declenche manuellement la generation d'un rapport mensuel.

    Par defaut, genere le rapport du mois precedent.

    Flux:
    1. Recupere les leads et devis de la periode
    2. Calcule les KPIs (leads, devis, CA)
    3. Genere le top 10 clients
    4. Cree le PDF avec WeasyPrint
    5. Upload vers Supabase Storage
    6. Envoie par email (optionnel)

    Necessite le header X-Webhook-Secret.
    """,
    responses={
        200: {"description": "Rapport genere avec succes"},
        401: {"description": "Secret webhook invalide"},
        500: {"description": "Erreur lors de la generation"},
    }
)
async def generate_rapport(
    payload: RapportGeneratePayload,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret")
):
    """
    Genere un rapport mensuel.

    Permet de declencher manuellement la generation d'un rapport
    pour une periode specifique.
    """
    # Verifie le secret
    if not x_webhook_secret or x_webhook_secret != settings.webhook_secret:
        raise HTTPException(
            status_code=401,
            detail="Secret webhook invalide"
        )

    try:
        result = await rapport_service.generate_rapport(
            mois=payload.mois,
            annee=payload.annee,
            envoyer_email=payload.envoyer_email,
            email_destinataire=payload.email_destinataire
        )

        return RapportResponse.success(
            rapport_id=result["rapport_id"],
            pdf_url=result["pdf_url"],
            periode=result["periode"],
            email_envoye=result["email_envoye"]
        )

    except Exception as e:
        logger.exception(f"Erreur generation rapport: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la generation: {str(e)}"
        )


# === GET /api/v1/rapport/{rapport_id} ===
@router.get(
    "/{rapport_id}",
    response_model=dict,
    summary="Recuperer un rapport",
    description="Recupere les details d'un rapport par son ID."
)
async def get_rapport(
    rapport_id: str,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret")
):
    """Recupere un rapport par son ID."""
    # Verifie le secret
    if not x_webhook_secret or x_webhook_secret != settings.webhook_secret:
        raise HTTPException(
            status_code=401,
            detail="Secret webhook invalide"
        )

    rapport = await rapport_service.get_rapport(rapport_id)

    if not rapport:
        raise HTTPException(
            status_code=404,
            detail="Rapport non trouve"
        )

    return {"status": "success", "rapport": rapport}


# === GET /api/v1/rapport ===
@router.get(
    "",
    response_model=dict,
    summary="Lister les rapports",
    description="Liste les rapports generes avec filtrage optionnel par annee."
)
async def list_rapports(
    annee: Optional[int] = Query(None, description="Filtrer par annee"),
    limit: int = Query(12, ge=1, le=100, description="Nombre max de resultats"),
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret")
):
    """Liste les rapports."""
    # Verifie le secret
    if not x_webhook_secret or x_webhook_secret != settings.webhook_secret:
        raise HTTPException(
            status_code=401,
            detail="Secret webhook invalide"
        )

    rapports = await rapport_service.list_rapports(annee=annee, limit=limit)

    return {
        "status": "success",
        "count": len(rapports),
        "rapports": rapports
    }


# === GET /api/v1/rapport/scheduler/status ===
@router.get(
    "/scheduler/status",
    response_model=dict,
    summary="Statut du scheduler",
    description="Retourne le statut du scheduler et la liste des jobs planifies."
)
async def scheduler_status(
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret")
):
    """Retourne le statut du scheduler."""
    # Verifie le secret
    if not x_webhook_secret or x_webhook_secret != settings.webhook_secret:
        raise HTTPException(
            status_code=401,
            detail="Secret webhook invalide"
        )

    jobs = scheduler_service.list_jobs()

    # Prochaine execution du rapport mensuel
    next_report = scheduler_service.get_next_run_time("monthly_report")

    return {
        "status": "success",
        "scheduler_running": scheduler_service._is_running,
        "jobs": jobs,
        "next_monthly_report": str(next_report) if next_report else None
    }


# === POST /api/v1/rapport/scheduler/trigger ===
@router.post(
    "/scheduler/trigger",
    response_model=RapportResponse,
    summary="Declencher le job rapport",
    description="Declenche manuellement le job de rapport mensuel du scheduler."
)
async def trigger_scheduler_job(
    mois: Optional[int] = Query(None, ge=1, le=12, description="Mois specifique"),
    annee: Optional[int] = Query(None, ge=2020, description="Annee specifique"),
    email: Optional[str] = Query(None, description="Email destinataire"),
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret")
):
    """Declenche manuellement le job de rapport."""
    # Verifie le secret
    if not x_webhook_secret or x_webhook_secret != settings.webhook_secret:
        raise HTTPException(
            status_code=401,
            detail="Secret webhook invalide"
        )

    try:
        result = await scheduler_service.trigger_monthly_report(
            mois=mois,
            annee=annee,
            email=email
        )

        return RapportResponse.success(
            rapport_id=result["rapport_id"],
            pdf_url=result["pdf_url"],
            periode=result["periode"],
            email_envoye=result["email_envoye"]
        )

    except Exception as e:
        logger.exception(f"Erreur trigger job: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur: {str(e)}"
        )


# === GET /api/v1/rapport/preview/{mois}/{annee} ===
@router.get(
    "/preview/{mois}/{annee}",
    response_model=dict,
    summary="Apercu des donnees du rapport",
    description="Retourne un apercu des donnees sans generer le PDF."
)
async def preview_rapport(
    mois: int,
    annee: int,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret")
):
    """Apercu des donnees du rapport."""
    # Verifie le secret
    if not x_webhook_secret or x_webhook_secret != settings.webhook_secret:
        raise HTTPException(
            status_code=401,
            detail="Secret webhook invalide"
        )

    # Validation
    if mois < 1 or mois > 12:
        raise HTTPException(status_code=400, detail="Mois invalide (1-12)")

    if annee < 2020:
        raise HTTPException(status_code=400, detail="Annee invalide (>= 2020)")

    try:
        # Recupere les donnees sans generer le PDF
        from app.services.rapport_service import RapportService
        from app.models.rapport import RapportPeriode
        from datetime import date
        from calendar import monthrange

        service = RapportService()

        # Calcule la periode
        _, last_day = monthrange(annee, mois)
        periode = RapportPeriode(
            mois=mois,
            annee=annee,
            date_debut=date(annee, mois, 1),
            date_fin=date(annee, mois, last_day)
        )

        # Recupere les donnees
        leads_data = await service._fetch_leads(periode)
        devis_data = await service._fetch_devis(periode)

        # Calcule les KPIs
        lead_kpis = service._calculate_lead_kpis(leads_data)
        devis_kpis = service._calculate_devis_kpis(devis_data)
        financial_kpis = service._calculate_financial_kpis(devis_data)
        top_clients = service._calculate_top_clients(devis_data, limit=5)

        return {
            "status": "success",
            "periode": {
                "titre": periode.titre,
                "mois": mois,
                "annee": annee,
                "debut": str(periode.date_debut),
                "fin": str(periode.date_fin)
            },
            "kpis": {
                "leads": {
                    "total": lead_kpis.total,
                    "gagnes": lead_kpis.gagnes,
                    "perdus": lead_kpis.perdus,
                    "en_cours": lead_kpis.en_cours,
                    "taux_conversion": lead_kpis.taux_conversion
                },
                "devis": {
                    "total": devis_kpis.total,
                    "signes": devis_kpis.signes,
                    "payes": devis_kpis.payes,
                    "en_attente": devis_kpis.en_attente,
                    "taux_signature": devis_kpis.taux_signature
                },
                "financier": {
                    "ca_mensuel": str(financial_kpis.ca_mensuel),
                    "ca_encaisse": str(financial_kpis.ca_encaisse),
                    "panier_moyen": str(financial_kpis.panier_moyen),
                    "ca_potentiel": str(financial_kpis.ca_potentiel)
                }
            },
            "top_clients": [
                {
                    "rang": c.rang,
                    "nom": c.nom,
                    "montant": str(c.montant_total)
                }
                for c in top_clients
            ]
        }

    except Exception as e:
        logger.exception(f"Erreur preview rapport: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur: {str(e)}"
        )
