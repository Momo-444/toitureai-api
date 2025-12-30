"""
API endpoints pour DocuSeal.

Workflow 5: DocuSeal Signature Completee
- POST /api/v1/docuseal/webhook : Reception du webhook DocuSeal
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Request, BackgroundTasks
from fastapi.responses import PlainTextResponse

from app.core.config import settings
from app.models.docuseal import (
    DocuSealWebhookPayload,
    DocuSealWebhookResponse,
)
from app.services.docuseal_service import docuseal_service
from app.core.error_handler import ErrorHandler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/docuseal", tags=["DocuSeal"])


# === POST /api/v1/docuseal/webhook ===
@router.post(
    "/webhook",
    response_class=PlainTextResponse,
    summary="Webhook DocuSeal",
    description="""
    Recoit les webhooks de DocuSeal.

    Evenements supportes:
    - `submission.completed`: Signature terminee

    Flux pour submission.completed:
    1. Telecharge le PDF signe
    2. Trouve le devis correspondant (par email/telephone)
    3. Upload le PDF vers Supabase Storage
    4. Met a jour le devis (statut=signe, url_pdf, date_signature)
    5. Envoie email de confirmation

    Retourne "OK" si traite avec succes.
    """,
    responses={
        200: {"description": "Webhook traite avec succes"},
        400: {"description": "Payload invalide"},
        404: {"description": "Devis non trouve"},
        500: {"description": "Erreur serveur"},
    }
)
async def docuseal_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Traite les webhooks DocuSeal.

    DocuSeal envoie un POST avec le payload JSON.
    On valide, traite et retourne "OK".
    """
    try:
        # Parse le body
        body = await request.json()
        logger.info(f"Webhook DocuSeal recu: {body.get('event_type', 'unknown')}")

        # Valide le payload
        try:
            payload = DocuSealWebhookPayload(**body)
        except Exception as e:
            logger.warning(f"Payload DocuSeal invalide: {e}")
            raise HTTPException(
                status_code=400,
                detail=f"Payload invalide: {str(e)}"
            )

        # Verifie si c'est un evenement de signature completee
        if not payload.is_signature_completed:
            logger.info(f"Evenement ignore: {payload.event_type}")
            return PlainTextResponse("OK", status_code=200)

        # Traite la signature
        try:
            result = await docuseal_service.process_signature_completed(payload)

            logger.info(
                f"Signature traitee: devis_id={result['devis_id']}, "
                f"pdf_url={result['new_pdf_url']}"
            )

            return PlainTextResponse("OK", status_code=200)

        except ValueError as e:
            # Devis non trouve ou autre erreur de validation
            logger.warning(f"Erreur traitement signature: {e}")
            raise HTTPException(
                status_code=404,
                detail=str(e)
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Erreur webhook DocuSeal: {e}")

        # Log l'erreur
        from app.core.error_handler import error_handler
        await error_handler.handle_error(
            error=e,
            workflow="docuseal_signature",
            node="docuseal_webhook"
        )

        raise HTTPException(
            status_code=500,
            detail="Erreur lors du traitement du webhook"
        )


# === POST /api/v1/docuseal/webhook/test ===
@router.post(
    "/webhook/test",
    response_model=DocuSealWebhookResponse,
    summary="Test du webhook DocuSeal",
    description="Endpoint de test pour simuler un webhook DocuSeal."
)
async def test_docuseal_webhook(
    payload: DocuSealWebhookPayload,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret")
):
    """
    Endpoint de test pour le webhook DocuSeal.

    Permet de tester le flux sans passer par DocuSeal.
    Necessite le header X-Webhook-Secret.
    """
    # Verifie le secret
    if not x_webhook_secret or x_webhook_secret != settings.webhook_secret:
        raise HTTPException(
            status_code=401,
            detail="Secret webhook invalide"
        )

    if not payload.is_signature_completed:
        return DocuSealWebhookResponse.ignored(
            f"Evenement {payload.event_type} ignore"
        )

    try:
        result = await docuseal_service.process_signature_completed(payload)

        return DocuSealWebhookResponse.success(
            devis_id=result["devis_id"],
            new_pdf_url=result["new_pdf_url"]
        )

    except ValueError as e:
        return DocuSealWebhookResponse.error(str(e))
    except Exception as e:
        logger.exception(f"Erreur test webhook: {e}")
        return DocuSealWebhookResponse.error(str(e))


# === GET /api/v1/docuseal/submission/{submission_id} ===
@router.get(
    "/submission/{submission_id}",
    response_model=dict,
    summary="Recuperer une submission DocuSeal",
    description="Recupere les details d'une submission DocuSeal."
)
async def get_submission(
    submission_id: int,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret")
):
    """
    Recupere une submission DocuSeal par son ID.

    Utile pour verifier le statut d'une signature.
    """
    # Verifie le secret
    if not x_webhook_secret or x_webhook_secret != settings.webhook_secret:
        raise HTTPException(
            status_code=401,
            detail="Secret webhook invalide"
        )

    try:
        result = await docuseal_service.get_submission(submission_id)
        return {"status": "success", "submission": result}

    except Exception as e:
        logger.exception(f"Erreur get submission: {e}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
