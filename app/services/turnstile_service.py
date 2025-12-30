"""
Service pour la validation Turnstile (Cloudflare).
"""
import logging
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def verify_turnstile(token: str, ip_address: str = None) -> bool:
    """
    Vérifie le token Turnstile auprès de Cloudflare.
    
    Args:
        token: Le token reçu du frontend.
        ip_address: L'IP du client (optionnel mais recommandé).
        
    Returns:
        True si le token est valide, False sinon.
    """
    # Bypass en local si pas de secret configuré
    if not settings.turnstile_secret_key:
        logger.debug("Turnstile bypass: Pas de secret key configuré")
        return True

    if not token:
        logger.warning("Turnstile check failed: Token manquant")
        return False

    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "secret": settings.turnstile_secret_key,
                "response": token,
            }
            if ip_address:
                payload["remoteip"] = ip_address
                
            response = await client.post(TURNSTILE_VERIFY_URL, json=payload, timeout=5.0)
            data = response.json()
            
            success = data.get("success", False)
            if not success:
                logger.warning(f"Turnstile invalid: {data.get('error-codes')}")
                
            return success
            
    except Exception as e:
        logger.error(f"Erreur validation Turnstile: {e}")
        # En cas d'erreur technique Cloudflare, on laisse passer pour ne pas bloquer les leads légitimes ?
        # Ou on bloque ? Pour un MVP, on laisse passer si c'est une erreur réseau, mais on logue.
        # Ici je retourne False par sécurité, car c'est un check de sécurité.
        return False
