"""
Gestionnaire d'erreurs centralisé pour ToitureAI.

Implémente le Workflow 6 - Error Handler:
- Logging des erreurs dans Supabase
- Alertes email à l'administrateur
- Formatage cohérent des erreurs
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Optional, Any
from functools import wraps

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger(__name__)


class ToitureAIError(Exception):
    """Exception de base pour ToitureAI."""

    def __init__(
        self,
        message: str,
        workflow: str = "unknown",
        node: str = "unknown",
        details: dict | None = None,
        status_code: int = 500
    ):
        self.message = message
        self.workflow = workflow
        self.node = node
        self.details = details or {}
        self.status_code = status_code
        self.timestamp = datetime.now(timezone.utc).isoformat()
        super().__init__(message)


class ValidationError(ToitureAIError):
    """Erreur de validation des données."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(
            message=message,
            workflow="validation",
            node="input_validation",
            details=details,
            status_code=400
        )


class AuthenticationError(ToitureAIError):
    """Erreur d'authentification webhook."""

    def __init__(self, message: str = "Secret webhook invalide"):
        super().__init__(
            message=message,
            workflow="authentication",
            node="webhook_secret_check",
            status_code=401
        )


class ExternalServiceError(ToitureAIError):
    """Erreur avec un service externe (OpenAI, SendGrid, etc.)."""

    def __init__(
        self,
        service: str,
        message: str,
        details: dict | None = None
    ):
        super().__init__(
            message=f"Erreur {service}: {message}",
            workflow="external_service",
            node=service,
            details=details,
            status_code=502
        )


class DatabaseError(ToitureAIError):
    """Erreur avec Supabase."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(
            message=message,
            workflow="database",
            node="supabase",
            details=details,
            status_code=503
        )


class ErrorHandler:
    """
    Gestionnaire centralisé des erreurs.

    Enregistre les erreurs dans Supabase et envoie des alertes email.
    """

    def __init__(self):
        self._supabase = None
        self._email_service = None

    @property
    def supabase(self):
        """Lazy loading du client Supabase (admin pour bypass RLS)."""
        if self._supabase is None:
            from app.core.database import supabase_admin
            self._supabase = supabase_admin
        return self._supabase

    @property
    def email_service(self):
        """Lazy loading du service email."""
        if self._email_service is None:
            from app.services.email_service import email_service
            self._email_service = email_service
        return self._email_service

    async def handle_error(
        self,
        error: Exception,
        workflow: str = "unknown",
        node: str = "unknown",
        execution_id: str | None = None,
        send_alert: bool = True
    ) -> dict:
        """
        Gère une erreur de manière centralisée.

        Args:
            error: L'exception capturée.
            workflow: Nom du workflow où l'erreur s'est produite.
            node: Nom du noeud/fonction.
            execution_id: ID d'exécution optionnel.
            send_alert: Si True, envoie une alerte email.

        Returns:
            Dictionnaire avec les détails de l'erreur loguée.
        """
        # Extraction des détails
        if isinstance(error, ToitureAIError):
            error_data = {
                "workflow": error.workflow,
                "node": error.node,
                "message": error.message,
                "details": error.details,
                "status_code": error.status_code,
                "timestamp": error.timestamp
            }
        else:
            error_data = {
                "workflow": workflow,
                "node": node,
                "message": str(error),
                "details": {
                    "type": type(error).__name__,
                    "traceback": traceback.format_exc()
                },
                "status_code": 500,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Log local
        logger.error(
            f"[{error_data['workflow']}:{error_data['node']}] "
            f"{error_data['message']}"
        )

        # Enregistrement en base
        try:
            await self._log_to_database(error_data, execution_id)
        except Exception as db_error:
            logger.error(f"Impossible de logger l'erreur en base: {db_error}")

        # Alerte email (en production ou si forcé)
        if send_alert and (settings.is_production or settings.debug):
            try:
                self._send_alert_email(error_data)
            except Exception as email_error:
                logger.error(f"Impossible d'envoyer l'alerte email: {email_error}")

        return error_data

    async def _log_to_database(
        self,
        error_data: dict,
        execution_id: str | None = None
    ) -> None:
        """Enregistre l'erreur dans la table error_logs."""
        import json

        try:
            self.supabase.table("error_logs").insert({
                "workflow": error_data["workflow"],
                "node": error_data["node"],
                "message": error_data["message"],
                "details": json.dumps(error_data.get("details", {})),
                "execution_id": execution_id,
                "created_at": error_data["timestamp"]
            }).execute()
        except Exception as e:
            # Si la table n'existe pas, on log juste
            logger.warning(f"Table error_logs non accessible: {e}")

    def _send_alert_email(self, error_data: dict) -> None:
        """Envoie une alerte email à l'administrateur."""
        self.email_service.send_error_alert(
            workflow=error_data["workflow"],
            node=error_data["node"],
            error_message=error_data["message"],
            details=error_data.get("details")
        )


# Instance globale
error_handler = ErrorHandler()


def handle_exceptions(workflow: str, node: str):
    """
    Décorateur pour gérer automatiquement les exceptions.

    Args:
        workflow: Nom du workflow.
        node: Nom du noeud/fonction.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except ToitureAIError:
                # Re-raise les erreurs ToitureAI
                raise
            except Exception as e:
                # Convertit les autres exceptions
                await error_handler.handle_error(e, workflow, node)
                raise ToitureAIError(
                    message=str(e),
                    workflow=workflow,
                    node=node,
                    details={"original_error": type(e).__name__}
                )
        return wrapper
    return decorator


async def global_exception_handler(
    request: Request,
    exc: Exception
) -> JSONResponse:
    """
    Handler global pour FastAPI.

    Capture toutes les exceptions non gérées et les formate en JSON.
    """
    if isinstance(exc, ToitureAIError):
        await error_handler.handle_error(exc)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": "error",
                "message": exc.message,
                "workflow": exc.workflow,
                "timestamp": exc.timestamp
            }
        )

    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": "error",
                "message": exc.detail,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

    # Erreur inattendue
    error_data = await error_handler.handle_error(
        exc,
        workflow="unhandled",
        node="global_handler"
    )

    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "message": "Une erreur interne s'est produite",
            "timestamp": error_data["timestamp"]
        }
    )
