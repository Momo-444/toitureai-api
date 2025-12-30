"""
API endpoints pour la gestion des devis.

Workflow 2: Devis & Facturation Automatique
- POST /api/v1/devis/webhook : Creation d'un devis (depuis le dashboard)
- GET /api/v1/devis/{devis_id} : Recuperer un devis
- GET /api/v1/devis/lead/{lead_id} : Recuperer tous les devis d'un lead
- PATCH /api/v1/devis/{devis_id} : Mettre a jour un devis
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Request, BackgroundTasks, Depends
from pydantic import ValidationError

from app.core.config import settings
from app.core.database import LeadRepository, DevisRepository
from app.models.devis import (
    DevisCreatePayload,
    DevisResponse,
    DevisUpdate,
    DevisInDB,
)
from app.services.hmac_service import WebhookSecretValidator
from app.services.devis_service import devis_service
from app.core.error_handler import (
    ToitureAIError,
    ValidationError as AppValidationError,
    AuthenticationError,
    DatabaseError,
    ErrorHandler,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/devis", tags=["Devis"])

# Repositories
lead_repo = LeadRepository()
devis_repo = DevisRepository()


# === Dependency pour validation du secret ===
async def verify_webhook_secret(
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret")
) -> None:
    """
    Verifie le secret du webhook dans les headers.

    Raises:
        HTTPException 401 si le secret est invalide ou absent.
    """
    if not x_webhook_secret:
        logger.warning("Webhook sans X-Webhook-Secret header")
        raise HTTPException(
            status_code=401,
            detail="Header X-Webhook-Secret manquant"
        )

    validator = WebhookSecretValidator()
    if not validator.validate(x_webhook_secret):
        logger.warning("Webhook avec secret invalide")
        raise HTTPException(
            status_code=401,
            detail="Secret webhook invalide"
        )


# === POST /api/v1/devis/webhook ===
@router.post(
    "/webhook",
    response_model=DevisResponse,
    summary="Creer un devis",
    description="""
    Cree un devis pour un lead existant.

    Modes de generation des lignes:
    1. **Custom**: Fournir `lignes_devis_custom` avec les lignes manuelles
    2. **Budget**: Fournir `budget_negocie` pour generation automatique
    3. **IA**: Sans lignes ni budget, utilise OpenAI pour estimer

    Le PDF est genere, uploade vers Supabase Storage, et envoye par email.
    """,
    responses={
        200: {"description": "Devis cree avec succes"},
        401: {"description": "Secret webhook invalide"},
        404: {"description": "Lead non trouve"},
        422: {"description": "Donnees invalides"},
        500: {"description": "Erreur serveur"},
    }
)
async def create_devis(
    payload: DevisCreatePayload,
    request: Request,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_webhook_secret)
):
    """
    Cree un nouveau devis pour un lead.

    Flux:
    1. Valide le payload
    2. Recupere le lead depuis Supabase
    3. Genere les lignes (custom, budget ou IA)
    4. Calcule les totaux
    5. Genere le PDF avec WeasyPrint
    6. Upload vers Supabase Storage
    7. Insere le devis en BDD
    8. Envoie l'email avec PDF attache
    9. Retourne les infos du devis
    """
    try:
        # 1. Recupere le lead
        lead = await lead_repo.get_by_id(payload.lead_id)

        if not lead:
            logger.warning(f"Lead non trouve: {payload.lead_id}")
            raise HTTPException(
                status_code=404,
                detail=f"Lead {payload.lead_id} non trouve"
            )

        # 2. Cree le devis
        result = await devis_service.create_devis(payload, lead)

        logger.info(
            f"Devis cree: {result['numero']} pour lead {payload.lead_id}"
        )

        # Update statut lead -> devis_envoye
        await lead_repo.update(payload.lead_id, {"statut": "devis_envoye"})

        return DevisResponse.success(
            devis_id=result["devis_id"],
            numero=result["numero"],
            url_pdf=result["url_pdf"]
        )

    except HTTPException:
        raise
    except ValidationError as e:
        logger.error(f"Erreur validation devis: {e}")
        raise HTTPException(
            status_code=422,
            detail=str(e)
        )
    except Exception as e:
        logger.exception(f"Erreur creation devis: {e}")
        # Log l'erreur pour le monitoring
        from app.core.error_handler import error_handler
        await error_handler.handle_error(
            error=e,
            workflow="devis_creation",
            node="create_devis"
        )
        raise HTTPException(
            status_code=500,
            detail="Erreur lors de la creation du devis"
        )


# === GET /api/v1/devis/{devis_id} ===
@router.get(
    "/{devis_id}",
    response_model=dict,
    summary="Recuperer un devis",
    description="Recupere les details d'un devis par son ID."
)
async def get_devis(
    devis_id: str,
    _: None = Depends(verify_webhook_secret)
):
    """Recupere un devis par son ID."""
    try:
        devis = await devis_repo.get_by_id(devis_id)

        if not devis:
            raise HTTPException(
                status_code=404,
                detail=f"Devis {devis_id} non trouve"
            )

        return {"status": "success", "devis": devis}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Erreur get devis: {e}")
        raise HTTPException(
            status_code=500,
            detail="Erreur lors de la recuperation du devis"
        )


# === GET /api/v1/devis/lead/{lead_id} ===
@router.get(
    "/lead/{lead_id}",
    response_model=dict,
    summary="Recuperer les devis d'un lead",
    description="Recupere tous les devis associes a un lead."
)
async def get_devis_by_lead(
    lead_id: str,
    _: None = Depends(verify_webhook_secret)
):
    """Recupere tous les devis d'un lead."""
    try:
        devis_list = await devis_repo.get_by_lead_id(lead_id)

        return {
            "status": "success",
            "count": len(devis_list),
            "devis": devis_list
        }

    except Exception as e:
        logger.exception(f"Erreur get devis by lead: {e}")
        raise HTTPException(
            status_code=500,
            detail="Erreur lors de la recuperation des devis"
        )


# === PATCH /api/v1/devis/{devis_id} ===
@router.patch(
    "/{devis_id}",
    response_model=dict,
    summary="Mettre a jour un devis",
    description="Met a jour les champs d'un devis (statut, notes, etc.)."
)
async def update_devis(
    devis_id: str,
    update_data: DevisUpdate,
    _: None = Depends(verify_webhook_secret)
):
    """Met a jour un devis."""
    try:
        # Verifie que le devis existe
        existing = await devis_repo.get_by_id(devis_id)

        if not existing:
            raise HTTPException(
                status_code=404,
                detail=f"Devis {devis_id} non trouve"
            )

        # Prepare les donnees de mise a jour
        update_dict = update_data.to_update_dict()

        if not update_dict:
            return {"status": "success", "message": "Aucune modification", "devis": existing}

        # Met a jour
        updated = await devis_repo.update(devis_id, update_dict)

        logger.info(f"Devis mis a jour: {devis_id}")

        return {"status": "success", "devis": updated}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Erreur update devis: {e}")
        raise HTTPException(
            status_code=500,
            detail="Erreur lors de la mise a jour du devis"
        )


# === DELETE /api/v1/devis/{devis_id} ===
@router.delete(
    "/{devis_id}",
    response_model=dict,
    summary="Supprimer un devis",
    description="Supprime un devis (soft delete ou hard delete selon config)."
)
async def delete_devis(
    devis_id: str,
    _: None = Depends(verify_webhook_secret)
):
    """Supprime un devis."""
    try:
        existing = await devis_repo.get_by_id(devis_id)

        if not existing:
            raise HTTPException(
                status_code=404,
                detail=f"Devis {devis_id} non trouve"
            )

        # Pour un soft delete, on pourrait juste changer le statut
        # Ici on fait un hard delete
        success = await devis_repo.delete(devis_id)

        if not success:
            raise HTTPException(
                status_code=500,
                detail="Echec de la suppression"
            )

        logger.info(f"Devis supprime: {devis_id}")

        return {"status": "success", "message": f"Devis {devis_id} supprime"}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Erreur delete devis: {e}")
        raise HTTPException(
            status_code=500,
            detail="Erreur lors de la suppression du devis"
        )


# === GET /api/v1/devis/stats ===
@router.get(
    "/stats/summary",
    response_model=dict,
    summary="Statistiques des devis",
    description="Retourne des statistiques sur les devis."
)
async def get_devis_stats(
    _: None = Depends(verify_webhook_secret)
):
    """Retourne des statistiques sur les devis."""
    try:
        # Compte par statut
        total = await devis_repo.count()
        envoyes = await devis_repo.count({"statut": "envoye"})
        signes = await devis_repo.count({"statut": "signe"})
        refuses = await devis_repo.count({"statut": "refuse"})
        expires = await devis_repo.count({"statut": "expire"})

        return {
            "status": "success",
            "stats": {
                "total": total,
                "envoyes": envoyes,
                "signes": signes,
                "refuses": refuses,
                "expires": expires,
                "taux_signature": round(signes / total * 100, 1) if total > 0 else 0
            }
        }

    except Exception as e:
        logger.exception(f"Erreur stats devis: {e}")
        raise HTTPException(
            status_code=500,
            detail="Erreur lors du calcul des statistiques"
        )
