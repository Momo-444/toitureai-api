"""
Service HMAC pour la génération et vérification de signatures.

Utilisé pour sécuriser les liens de tracking (ouverture email, clic confirmation).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Tuple

from app.core.config import settings


class HMACService:
    """
    Service de génération et vérification de signatures HMAC.

    Utilise SHA-256 pour générer des signatures sécurisées
    pour les liens de tracking.
    """

    def __init__(self, secret: str | None = None):
        """
        Initialise le service HMAC.

        Args:
            secret: Secret pour la signature. Utilise TRACKING_SECRET par défaut.
        """
        self._secret = (secret or settings.tracking_secret).encode("utf-8")

    def sign(self, data: str) -> str:
        """
        Génère une signature HMAC-SHA256 pour les données.

        Args:
            data: Données à signer (ex: "lead_id" + "click").

        Returns:
            Signature hexadécimale.
        """
        return hmac.new(
            self._secret,
            data.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    def verify(self, data: str, signature: str) -> bool:
        """
        Vérifie une signature HMAC.

        Utilise une comparaison en temps constant pour éviter
        les attaques timing.

        Args:
            data: Données originales.
            signature: Signature à vérifier.

        Returns:
            True si la signature est valide.
        """
        expected = self.sign(data)
        return secrets.compare_digest(expected, signature)

    def generate_tracking_signatures(self, lead_id: str) -> Tuple[str, str]:
        """
        Génère les signatures pour le tracking d'un lead.

        Args:
            lead_id: UUID du lead.

        Returns:
            Tuple (sign_click, sign_open).
        """
        sign_click = self.sign(f"{lead_id}click")
        sign_open = self.sign(f"{lead_id}open")
        return sign_click, sign_open

    def verify_tracking_signature(
        self,
        lead_id: str,
        tracking_type: str,
        signature: str
    ) -> bool:
        """
        Vérifie une signature de tracking.

        Args:
            lead_id: UUID du lead.
            tracking_type: Type de tracking ("open" ou "click").
            signature: Signature à vérifier.

        Returns:
            True si la signature est valide.
        """
        if tracking_type not in ("open", "click"):
            return False

        data = f"{lead_id}{tracking_type}"
        return self.verify(data, signature)

    def generate_tracking_urls(
        self,
        lead_id: str,
        base_url: str | None = None
    ) -> Tuple[str, str]:
        """
        Génère les URLs de tracking complètes.

        Args:
            lead_id: UUID du lead.
            base_url: URL de base de l'API. Utilise settings.api_base_url par défaut.

        Returns:
            Tuple (click_url, open_url).
        """
        base = base_url or settings.api_base_url
        sign_click, sign_open = self.generate_tracking_signatures(lead_id)

        click_url = (
            f"{base}/api/v1/tracking/track-lead"
            f"?lead_id={lead_id}&type=click&s={sign_click}"
        )
        open_url = (
            f"{base}/api/v1/tracking/track-lead"
            f"?lead_id={lead_id}&type=open&s={sign_open}"
        )

        return click_url, open_url


class WebhookSecretValidator:
    """
    Validateur de secret webhook.

    Vérifie que les requêtes entrantes sont authentiques
    en comparant le header X-Webhook-Secret.
    """

    def __init__(self, secret: str | None = None):
        """
        Initialise le validateur.

        Args:
            secret: Secret attendu. Utilise WEBHOOK_SECRET par défaut.
        """
        self._secret = secret or settings.webhook_secret

    def validate(self, provided_secret: str | None) -> bool:
        """
        Valide le secret fourni.

        Utilise une comparaison en temps constant.

        Args:
            provided_secret: Secret fourni dans le header.

        Returns:
            True si le secret est valide.
        """
        if not provided_secret:
            return False
        return secrets.compare_digest(self._secret, provided_secret)


# Instances globales pour import direct
hmac_service = HMACService()
webhook_validator = WebhookSecretValidator()


def generate_tracking_signatures(lead_id: str) -> Tuple[str, str]:
    """
    Fonction utilitaire pour générer les signatures de tracking.

    Args:
        lead_id: UUID du lead.

    Returns:
        Tuple (sign_click, sign_open).
    """
    return hmac_service.generate_tracking_signatures(lead_id)


def verify_tracking_signature(
    lead_id: str,
    tracking_type: str,
    signature: str
) -> bool:
    """
    Fonction utilitaire pour vérifier une signature de tracking.

    Args:
        lead_id: UUID du lead.
        tracking_type: Type de tracking ("open" ou "click").
        signature: Signature à vérifier.

    Returns:
        True si la signature est valide.
    """
    return hmac_service.verify_tracking_signature(lead_id, tracking_type, signature)


def validate_webhook_secret(secret: str | None) -> bool:
    """
    Fonction utilitaire pour valider le secret webhook.

    Args:
        secret: Secret fourni dans le header X-Webhook-Secret.

    Returns:
        True si le secret est valide.
    """
    return webhook_validator.validate(secret)
