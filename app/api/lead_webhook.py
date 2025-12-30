"""
Endpoint webhook pour la réception des leads.

Implémente le Workflow 1 - Lead Generation & Qualification AI:
1. Réception du webhook POST depuis la landing page
2. Validation du secret webhook
3. Normalisation des données
4. Qualification IA via OpenAI
5. Enregistrement dans Supabase
6. Génération des signatures HMAC
7. Envoi emails (confirmation client + alerte équipe)
8. Réponse JSON
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, Header, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.database import LeadRepository
from app.core.error_handler import (
    handle_exceptions,
    AuthenticationError,
    ValidationError,
    ExternalServiceError,
    error_handler
)
from app.models.lead import (
    LeadWebhookPayload,
    LeadCreate,
    LeadWithAI,
    LeadResponse,
    AIQualificationResult
)
from app.services.hmac_service import (
    validate_webhook_secret,
    generate_tracking_signatures,
    hmac_service
)
from app.services.ai_qualification import qualify_lead_sync
from app.services.email_service import (
    send_lead_confirmation,
    send_team_alert,
    email_service
)
from app.services.turnstile_service import verify_turnstile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/lead", tags=["leads"])

# Repository pour les leads
lead_repo = LeadRepository()


@router.post(
    "/webhook",
    response_model=LeadResponse,
    summary="Réception d'un nouveau lead",
    description="Endpoint webhook pour recevoir les leads depuis la landing page."
)
async def receive_lead_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret")
):
    """
    Endpoint principal pour la réception des leads.

    Flux:
    1. Valide le secret webhook
    2. Parse et valide le payload
    3. Qualifie le lead via IA
    4. Enregistre en base
    5. Envoie les emails en background

    Args:
        request: Requête FastAPI.
        background_tasks: Tâches en arrière-plan.
        x_webhook_secret: Secret d'authentification.

    Returns:
        LeadResponse avec statut et infos du lead créé.

    Raises:
        HTTPException 401: Secret invalide.
        HTTPException 400: Données invalides.
        HTTPException 500: Erreur interne.
    """
    # 1. Validation du secret webhook
    if not validate_webhook_secret(x_webhook_secret):
        logger.warning(f"Tentative d'accès avec secret invalide depuis {request.client.host}")
        raise HTTPException(
            status_code=401,
            detail={"status": "unauthorized", "message": "Secret webhook invalide"}
        )

    try:
        # 2. Parse et valide le payload
        body = await request.json()
        payload = LeadWebhookPayload(**body)
        
        # Extraction IP pour Turnstile et Logging
        client_ip = (
            request.headers.get("x-real-ip") or
            request.headers.get("x-forwarded-for") or
            request.client.host if request.client else None
        )

        # Validation Turnstile (si activé)
        if settings.turnstile_secret_key:
            if not await verify_turnstile(payload.turnstileToken, client_ip):
                logger.warning(f"Turnstile invalid pour IP {client_ip}")
                raise HTTPException(
                    status_code=400, 
                    detail={"status": "error", "message": "Vérification de sécurité échouée. Veuillez rafraîchir la page."}
                )

        lead_create = payload.to_lead_create()

        # Ajout des métadonnées de la requête
        lead_create.user_agent = request.headers.get("user-agent")
        lead_create.ip_address = client_ip

        logger.info(f"Nouveau lead reçu: {lead_create.email}")

    except Exception as e:
        logger.error(f"Erreur validation payload: {e}")
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "message": f"Données invalides: {str(e)}"}
        )

    try:
        # 3. Qualification IA
        ai_result, ai_raw = qualify_lead_sync(lead_create)
        logger.info(
            f"Lead qualifié: {lead_create.email} - "
            f"Score: {ai_result.score}, Urgence: {ai_result.urgence}"
        )

        # 4. Fusion des données lead + IA
        lead_with_ai = LeadWithAI.from_lead_and_ai(lead_create, ai_result, ai_raw)

        # 5. Enregistrement en base
        lead_data = lead_with_ai.to_db_dict()
        created_lead = await lead_repo.insert(lead_data)
        lead_id = created_lead["id"]

        logger.info(f"Lead enregistré: {lead_id}")

        # 6. Génération des signatures HMAC pour le tracking
        sign_click, sign_open = generate_tracking_signatures(lead_id)
        click_url, open_url = hmac_service.generate_tracking_urls(lead_id)

        # 7. Ajout des URLs de tracking aux données du lead pour les emails
        created_lead["sign_click"] = sign_click
        created_lead["sign_open"] = sign_open

        # 8. Envoi des emails en background
        is_hot = ai_result.score >= settings.hot_lead_threshold

        background_tasks.add_task(
            send_emails_background,
            lead=created_lead,
            click_url=click_url,
            open_url=open_url,
            is_hot=is_hot
        )

        # 9. Réponse
        return LeadResponse.success(
            lead_id=str(lead_id),
            email=created_lead["email"],
            score=ai_result.score
        )

    except Exception as e:
        logger.exception(f"Erreur traitement lead: {e}")

        # Log l'erreur de manière centralisée
        await error_handler.handle_error(
            e,
            workflow="lead_generation",
            node="receive_lead_webhook"
        )

        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "message": "Erreur lors du traitement de votre demande"
            }
        )


async def send_emails_background(
    lead: dict,
    click_url: str,
    open_url: str,
    is_hot: bool
) -> None:
    """
    Envoie les emails en arrière-plan.

    Args:
        lead: Données du lead créé.
        click_url: URL de tracking pour le clic.
        open_url: URL de tracking pour l'ouverture.
        is_hot: True si le lead est chaud (score >= threshold).
    """
    try:
        # Email de confirmation au client
        success, message_id = send_lead_confirmation(lead, click_url, open_url)
        if success:
            logger.info(f"Email confirmation envoyé: {lead['email']}")
            # Mise à jour du message_id SendGrid si nécessaire
            if message_id:
                try:
                    await lead_repo.update(lead["id"], {"sendgrid_message_id": message_id})
                except Exception:
                    pass  # Non critique

        # Alerte équipe
        success, _ = send_team_alert(lead, is_hot=is_hot)
        if success:
            alert_type = "urgent" if is_hot else "standard"
            logger.info(f"Alerte équipe ({alert_type}) envoyée pour: {lead['email']}")

    except Exception as e:
        logger.exception(f"Erreur envoi emails pour lead {lead.get('id')}: {e}")
        # Log mais ne pas faire échouer le traitement
        await error_handler.handle_error(
            e,
            workflow="lead_generation",
            node="send_emails_background",
            send_alert=True
        )


# === Endpoints additionnels pour l'admin ===

@router.get(
    "/{lead_id}",
    summary="Récupère un lead par ID",
    description="Endpoint admin pour récupérer les détails d'un lead."
)
async def get_lead(
    lead_id: str,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret")
):
    """
    Récupère un lead par son ID.

    Args:
        lead_id: UUID du lead.
        x_webhook_secret: Secret d'authentification admin.

    Returns:
        Données du lead.
    """
    if not validate_webhook_secret(x_webhook_secret):
        raise HTTPException(status_code=401, detail="Non autorisé")

    lead = await lead_repo.get_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead non trouvé")

    return lead


@router.get(
    "",
    summary="Liste les leads",
    description="Endpoint admin pour lister les leads avec pagination."
)
async def list_leads(
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None
):
    """
    Liste les leads avec pagination et filtres.

    Args:
        x_webhook_secret: Secret d'authentification admin.
        limit: Nombre de résultats (max 100).
        offset: Décalage pour pagination.
        status: Filtre par statut optionnel.

    Returns:
        Liste des leads.
    """
    if not validate_webhook_secret(x_webhook_secret):
        raise HTTPException(status_code=401, detail="Non autorisé")

    limit = min(limit, 100)  # Cap à 100

    if status:
        leads = await lead_repo.get_leads_by_status(status)
        return leads[offset:offset + limit]

    leads = await lead_repo.get_all(limit=limit, offset=offset)
    return leads


@router.patch(
    "/{lead_id}",
    summary="Met à jour un lead",
    description="Endpoint admin pour mettre à jour un lead."
)
async def update_lead(
    lead_id: str,
    request: Request,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret")
):
    """
    Met à jour un lead.

    Args:
        lead_id: UUID du lead.
        request: Corps de la requête avec les champs à mettre à jour.
        x_webhook_secret: Secret d'authentification admin.

    Returns:
        Lead mis à jour.
    """
    if not validate_webhook_secret(x_webhook_secret):
        raise HTTPException(status_code=401, detail="Non autorisé")

    body = await request.json()

    # Filtrer les champs autorisés
    allowed_fields = {
        "nom", "prenom", "email", "telephone", "type_projet",
        "surface", "budget_estime", "budget_negocie", "delai",
        "description", "adresse", "ville", "code_postal", "statut",
        "lignes_devis_custom", "notes_devis_custom"
    }

    update_data = {k: v for k, v in body.items() if k in allowed_fields}

    if not update_data:
        raise HTTPException(status_code=400, detail="Aucun champ valide à mettre à jour")

    # Ajout du timestamp de mise à jour
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    updated_lead = await lead_repo.update(lead_id, update_data)
    return updated_lead


@router.delete(
    "/{lead_id}",
    summary="Supprime un lead",
    description="Endpoint admin pour supprimer un lead."
)
async def delete_lead(
    lead_id: str,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret")
):
    """
    Supprime un lead.

    Args:
        lead_id: UUID du lead.
        x_webhook_secret: Secret d'authentification admin.

    Returns:
        Confirmation de suppression.
    """
    if not validate_webhook_secret(x_webhook_secret):
        raise HTTPException(status_code=401, detail="Non autorisé")

    success = await lead_repo.delete(lead_id)
    if not success:
        raise HTTPException(status_code=404, detail="Lead non trouvé")

    return {"status": "success", "message": "Lead supprimé"}


@router.get(
    "/stats/hot",
    summary="Leads chauds",
    description="Récupère les leads avec un score >= threshold."
)
async def get_hot_leads(
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
    threshold: int = None
):
    """
    Récupère les leads chauds.

    Args:
        x_webhook_secret: Secret d'authentification admin.
        threshold: Score minimum (défaut: settings.hot_lead_threshold).

    Returns:
        Liste des leads chauds.
    """
    if not validate_webhook_secret(x_webhook_secret):
        raise HTTPException(status_code=401, detail="Non autorisé")

    threshold = threshold or settings.hot_lead_threshold
    leads = await lead_repo.get_hot_leads(threshold)
    return leads
