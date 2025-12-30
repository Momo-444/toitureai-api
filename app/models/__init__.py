"""
Modèles Pydantic pour ToitureAI.

Modules:
- lead: Schémas pour les leads
- devis: Schémas pour les devis
- schemas: Schémas partagés et utilitaires
"""

from app.models.lead import (
    LeadCreate,
    LeadInDB,
    LeadResponse,
    LeadWebhookPayload,
    AIQualificationResult,
)

__all__ = [
    "LeadCreate",
    "LeadInDB",
    "LeadResponse",
    "LeadWebhookPayload",
    "AIQualificationResult",
]
