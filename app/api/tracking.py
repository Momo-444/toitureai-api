"""
Endpoint de tracking des leads.

Implémente le Workflow 4 - Lead Tracking:
- Tracking d'ouverture d'email (pixel 1x1)
- Tracking de clic sur le bouton de confirmation
- Vérification HMAC des signatures
- Mise à jour du statut lead
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import Response, HTMLResponse

from app.core.config import settings
from app.core.database import LeadRepository
from app.core.error_handler import error_handler
from app.services.hmac_service import verify_tracking_signature, hmac_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tracking", tags=["tracking"])

# Repository pour les leads
lead_repo = LeadRepository()

# Pixel transparent 1x1 (GIF)
TRANSPARENT_PIXEL = bytes([
    0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 0x01, 0x00,
    0x01, 0x00, 0x80, 0x00, 0x00, 0xFF, 0xFF, 0xFF,
    0x00, 0x00, 0x00, 0x21, 0xF9, 0x04, 0x01, 0x00,
    0x00, 0x00, 0x00, 0x2C, 0x00, 0x00, 0x00, 0x00,
    0x01, 0x00, 0x01, 0x00, 0x00, 0x02, 0x02, 0x44,
    0x01, 0x00, 0x3B
])

# Template HTML de remerciement
THANK_YOU_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Merci ! - ToitureAI</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .container {
            background: white;
            border-radius: 20px;
            padding: 50px;
            text-align: center;
            max-width: 500px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        .icon {
            font-size: 80px;
            margin-bottom: 20px;
        }
        h1 {
            color: #27ae60;
            margin-bottom: 20px;
            font-size: 32px;
        }
        p {
            color: #666;
            font-size: 18px;
            line-height: 1.6;
            margin-bottom: 30px;
        }
        .highlight {
            background: #eafaf1;
            border-left: 4px solid #27ae60;
            padding: 15px 20px;
            border-radius: 8px;
            text-align: left;
            margin: 20px 0;
        }
        .highlight strong {
            color: #27ae60;
        }
        .button {
            display: inline-block;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 40px;
            border-radius: 30px;
            text-decoration: none;
            font-weight: bold;
            font-size: 16px;
            transition: transform 0.3s, box-shadow 0.3s;
        }
        .button:hover {
            transform: translateY(-3px);
            box-shadow: 0 10px 30px rgba(102, 126, 234, 0.4);
        }
        .footer {
            margin-top: 30px;
            color: #999;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">✅</div>
        <h1>Merci pour votre confirmation !</h1>
        <p>
            Votre intérêt a bien été enregistré. Notre équipe vous contactera
            très prochainement pour discuter de votre projet.
        </p>
        <div class="highlight">
            <strong>Prochaine étape :</strong><br>
            Un expert ToitureAI vous appellera sous 24-48h pour planifier
            une visite technique gratuite.
        </div>
        <a href="{website_url}" class="button">Visiter notre site</a>
        <div class="footer">
            ToitureAI - Votre toiture, notre expertise
        </div>
    </div>
</body>
</html>
"""


@router.get(
    "/track-lead",
    summary="Tracking des leads",
    description="Endpoint de tracking pour les ouvertures email et clics."
)
async def track_lead(
    lead_id: str = Query(..., description="UUID du lead"),
    type: str = Query(..., alias="type", description="Type de tracking: open ou click"),
    s: str = Query(..., description="Signature HMAC")
):
    if type not in ("open", "click"):
        logger.warning(f"Type de tracking invalide: {type}")
        raise HTTPException(status_code=400, detail="Type de tracking invalide")

    if not verify_tracking_signature(lead_id, type, s):
        logger.warning(f"Signature tracking invalide pour lead {lead_id}, type {type}")
        raise HTTPException(status_code=403, detail="Signature invalide")

    try:
        now = datetime.now(timezone.utc).isoformat()

        if type == "open":
            logger.info(f"Traitement tracking OPEN pour lead {lead_id}")

            lead = await lead_repo.get_by_id(lead_id)
            current_count = (lead.get("email_ouvert_count", 0) or 0) if lead else 0
            new_count = current_count + 1

            update_data = {
                "email_ouvert": True,
                "ouvert": "oui",
                "derniere_interaction": now,
                "email_ouvert_count": new_count
            }

            try:
                await lead_repo.update(lead_id, update_data)
                logger.info(f"✅ Tracking open RÉUSSI pour lead {lead_id}: email_ouvert_count={new_count}")
            except Exception as update_error:
                logger.exception(f"❌ ERREUR mise à jour tracking open pour lead {lead_id}: {update_error}")
                # On ne relance pas l'erreur pour le pixel, on retourne quand même le pixel

            return Response(
                content=TRANSPARENT_PIXEL,
                media_type="image/gif",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )

        else:  # type == "click"
            logger.info(f"Traitement tracking CLICK pour lead {lead_id}")

            lead = await lead_repo.get_by_id(lead_id)
            if not lead:
                logger.error(f"Lead {lead_id} non trouvé pour tracking click")
                raise HTTPException(status_code=404, detail="Lead non trouvé")

            # Calculer le nouveau count
            current_clic_count = lead.get("email_clic_count", 0) or 0
            new_clic_count = current_clic_count + 1

            update_data = {
                "ouvert": "oui",
                "clique": "oui",
                "email_clic_count": new_clic_count,
                "derniere_interaction": now,
                "lead_chaud": "oui",  # String, pas booléen (contrainte DB)
                "score_qualification": 100
            }

            logger.info(f"Lead {lead_id} - Mise à jour: clique=oui, email_clic_count={new_clic_count}, lead_chaud=True")

            try:
                result = await lead_repo.update(lead_id, update_data)
                logger.info(f"✅ Tracking click RÉUSSI pour lead {lead_id}: {result}")
            except Exception as update_error:
                logger.exception(f"❌ ERREUR mise à jour tracking click pour lead {lead_id}: {update_error}")
                raise

            html_content = THANK_YOU_HTML.replace("{website_url}", settings.website_url)
            return HTMLResponse(content=html_content)

    except Exception as e:
        logger.exception(f"❌ EXCEPTION GLOBALE tracking pour lead {lead_id}, type={type}: {e}")

        # Log l'erreur dans la base de données
        try:
            await error_handler.handle_error(
                e,
                workflow="lead_tracking",
                node=f"track_lead_{type}",
                send_alert=True  # Envoyer une alerte pour ces erreurs critiques
            )
        except Exception as log_error:
            logger.exception(f"Impossible de loguer l'erreur: {log_error}")

        # Même en cas d'erreur, on renvoie une réponse propre à l'utilisateur
        # Mais l'erreur est maintenant loguée et une alerte est envoyée
        if type == "open":
            return Response(content=TRANSPARENT_PIXEL, media_type="image/gif")
        else:
            html_content = THANK_YOU_HTML.replace("{website_url}", settings.website_url)
            return HTMLResponse(content=html_content)


@router.get(
    "/stats/{lead_id}",
    summary="Statistiques de tracking d'un lead",
    description="Récupère les statistiques de tracking d'un lead."
)
async def get_tracking_stats(lead_id: str):
    lead = await lead_repo.get_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead non trouvé")

    return {
        "lead_id": lead_id,
        "email_ouvert": lead.get("email_ouvert", False),
        "email_ouvert_count": lead.get("email_ouvert_count", 0),
        "email_clic_count": lead.get("email_clic_count", 0),
        "lead_chaud": lead.get("lead_chaud", False),
        "clique": lead.get("clique"),
        "statut": lead.get("statut"),
        "derniere_interaction": lead.get("derniere_interaction"),
        "created_at": lead.get("created_at")
    }


@router.get(
    "/debug/{lead_id}",
    summary="Debug tracking - génère les URLs et teste la mise à jour",
    description="Endpoint de diagnostic pour tester le tracking."
)
async def debug_tracking(lead_id: str, test_update: bool = False):
    """
    Endpoint de diagnostic pour le tracking.

    - Affiche les URLs générées pour ce lead
    - Optionnellement teste la mise à jour (test_update=true)
    """
    lead = await lead_repo.get_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead non trouvé")

    # Générer les URLs de tracking
    click_url, open_url = hmac_service.generate_tracking_urls(lead_id)

    result = {
        "lead_id": lead_id,
        "api_base_url": settings.api_base_url,
        "click_url": click_url,
        "open_url": open_url,
        "current_state": {
            "clique": lead.get("clique"),
            "email_clic_count": lead.get("email_clic_count", 0),
            "lead_chaud": lead.get("lead_chaud", False),
            "ouvert": lead.get("ouvert"),
            "email_ouvert_count": lead.get("email_ouvert_count", 0),
        }
    }

    # Test de mise à jour si demandé
    if test_update:
        try:
            now = datetime.now(timezone.utc).isoformat()
            current_clic_count = lead.get("email_clic_count", 0) or 0

            update_data = {
                "clique": "oui",
                "email_clic_count": current_clic_count + 1,
                "lead_chaud": "oui",  # String, pas booléen (contrainte DB)
                "derniere_interaction": now
            }

            updated = await lead_repo.update(lead_id, update_data)
            result["test_update"] = {
                "success": True,
                "updated_data": update_data,
                "result": updated
            }
        except Exception as e:
            result["test_update"] = {
                "success": False,
                "error": str(e)
            }

    return result
