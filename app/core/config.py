"""
Configuration centralisée pour ToitureAI.

Utilise Pydantic Settings pour une validation stricte des variables d'environnement.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, EmailStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configuration de l'application ToitureAI.

    Toutes les variables sont chargées depuis l'environnement ou un fichier .env.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # === API Settings ===
    app_name: str = Field(default="ToitureAI", description="Nom de l'application")
    app_env: Literal["development", "staging", "production"] = Field(
        default="development",
        description="Environnement d'exécution"
    )
    debug: bool = Field(default=False, description="Mode debug")
    api_host: str = Field(default="0.0.0.0", description="Host de l'API")
    api_port: int = Field(default=8000, ge=1, le=65535, description="Port de l'API")

    # === Security ===
    webhook_secret: str = Field(
        ...,
        min_length=32,
        description="Secret pour authentifier les webhooks entrants"
    )
    tracking_secret: str = Field(
        ...,
        min_length=32,
        description="Secret pour signer les liens de tracking HMAC"
    )

    # === Supabase ===
    supabase_url: str = Field(..., description="URL du projet Supabase")
    supabase_key: str = Field(..., description="Clé anon Supabase")
    supabase_service_key: str = Field(
        default="",
        description="Clé service role Supabase (optionnelle)"
    )

    # === OpenAI ===
    openai_api_key: str = Field(..., description="Clé API OpenAI")
    openai_model: str = Field(
        default="gpt-4o-mini",
        description="Modèle OpenAI à utiliser"
    )

    # === SendGrid ===
    sendgrid_api_key: str = Field(..., description="Clé API SendGrid")
    sendgrid_from_email: EmailStr = Field(
        default="contact@toitureai.fr",
        description="Email d'expédition"
    )
    sendgrid_from_name: str = Field(
        default="ToitureAI",
        description="Nom d'expédition"
    )

    # === Admin ===
    admin_email: EmailStr = Field(
        default="partner.online10@gmail.com",
        description="Email de l'administrateur pour les notifications"
    )

    # === Cron ===
    cron_secret: str = Field(
        default="",
        description="Secret pour les tâches planifiées"
    )

    # === DocuSeal ===
    docuseal_api_key: str = Field(default="", description="Clé API DocuSeal")
    docuseal_webhook_secret: str = Field(
        default="",
        description="Secret webhook DocuSeal"
    )

    # === Turnstile (Cloudflare CAPTCHA) ===
    turnstile_secret_key: str = Field(
        default="",
        description="Clé secrète Turnstile pour validation CAPTCHA"
    )
    turnstile_site_key: str = Field(
        default="",
        description="Clé site Turnstile"
    )

    # === Google Maps ===
    google_maps_api_key: str = Field(
        default="",
        description="Clé API Google Maps"
    )

    # === Sentry (Error Monitoring) ===
    sentry_dsn: str = Field(
        default="",
        description="DSN Sentry pour le monitoring d'erreurs"
    )

    # === URLs ===
    api_base_url: str = Field(
        default="http://localhost:8000",
        description="URL de base de l'API"
    )
    website_url: str = Field(
        default="https://toitureai.fr",
        description="URL du site web"
    )
    dashboard_url: str = Field(
        default="https://app.toitureai.fr",
        description="URL du dashboard admin"
    )

    # === Lead Qualification ===
    hot_lead_threshold: int = Field(
        default=70,
        ge=0,
        le=100,
        description="Score minimum pour un lead chaud"
    )

    # === Rapport Mensuel ===
    monthly_report_hour: int = Field(
        default=8,
        ge=0,
        le=23,
        description="Heure d'envoi du rapport mensuel"
    )
    monthly_report_day: int = Field(
        default=1,
        ge=1,
        le=28,
        description="Jour du mois pour le rapport"
    )

    @field_validator("supabase_url")
    @classmethod
    def validate_supabase_url(cls, v: str) -> str:
        """Valide que l'URL Supabase est correcte."""
        if not v.startswith("https://") or "supabase" not in v.lower():
            raise ValueError("L'URL Supabase doit commencer par https:// et contenir 'supabase'")
        return v.rstrip("/")

    @field_validator("api_base_url", "website_url", "dashboard_url")
    @classmethod
    def validate_urls(cls, v: str) -> str:
        """Normalise les URLs en supprimant le slash final."""
        return v.rstrip("/")

    @property
    def is_production(self) -> bool:
        """Vérifie si l'environnement est en production."""
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        """Vérifie si l'environnement est en développement."""
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    """
    Retourne une instance singleton des settings.

    Utilise lru_cache pour éviter de recharger les settings à chaque appel.
    """
    return Settings()


# Instance globale pour import direct
settings = get_settings()
