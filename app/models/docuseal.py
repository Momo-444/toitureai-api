"""
Modeles Pydantic pour DocuSeal.

Definit les schemas de validation pour:
- Webhook payload de DocuSeal
- Submitter (signataire)
- Document signe
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    Field,
    EmailStr,
    HttpUrl,
    field_validator,
    ConfigDict,
)


# === Types ===
DocuSealEventType = Literal[
    "submission.created",
    "submission.completed",
    "submission.archived",
    "form.started",
    "form.viewed",
    "form.completed",
]


# === Submitter (Signataire) ===
class DocuSealSubmitter(BaseModel):
    """
    Informations sur le signataire.

    Correspond a un signataire dans le payload DocuSeal.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    id: Optional[int] = Field(default=None, description="ID interne DocuSeal")
    uuid: Optional[str] = Field(default=None, description="UUID DocuSeal")
    email: EmailStr = Field(..., description="Email du signataire")
    phone: Optional[str] = Field(default=None, description="Telephone du signataire")
    name: Optional[str] = Field(default=None, description="Nom du signataire")
    role: Optional[str] = Field(default=None, description="Role du signataire")
    completed_at: Optional[datetime] = Field(default=None, description="Date de completion")
    status: Optional[str] = Field(default=None, description="Statut (pending, completed)")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        """Normalise l'email en minuscules."""
        return v.lower().strip()

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, v: Optional[str]) -> Optional[str]:
        """Normalise le telephone au format +33."""
        if not v:
            return None

        import re
        cleaned = re.sub(r"[^\d+]", "", v)

        if cleaned.startswith("0") and len(cleaned) >= 10:
            cleaned = "+33" + cleaned[1:]

        if not cleaned.startswith("+"):
            cleaned = "+33" + cleaned

        return cleaned


# === Document signe ===
class DocuSealDocument(BaseModel):
    """
    Document signe retourne par DocuSeal.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    id: Optional[int] = Field(default=None, description="ID du document")
    uuid: Optional[str] = Field(default=None, description="UUID du document")
    url: str = Field(..., description="URL de telechargement du PDF signe")
    filename: Optional[str] = Field(default=None, description="Nom du fichier")


# === Submission Data ===
class DocuSealSubmissionData(BaseModel):
    """
    Donnees de la submission DocuSeal.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    id: Optional[int] = Field(default=None, description="ID de la submission")
    submission_id: Optional[int] = Field(default=None, description="ID de la submission (alias)")
    submitters: list[DocuSealSubmitter] = Field(
        default_factory=list,
        description="Liste des signataires"
    )
    documents: list[DocuSealDocument] = Field(
        default_factory=list,
        description="Liste des documents signes"
    )
    template_id: Optional[int] = Field(default=None, description="ID du template")
    created_at: Optional[datetime] = Field(default=None, description="Date de creation")
    completed_at: Optional[datetime] = Field(default=None, description="Date de completion")
    status: Optional[str] = Field(default=None, description="Statut global")

    @property
    def first_submitter(self) -> Optional[DocuSealSubmitter]:
        """Retourne le premier signataire."""
        return self.submitters[0] if self.submitters else None

    @property
    def first_document(self) -> Optional[DocuSealDocument]:
        """Retourne le premier document."""
        return self.documents[0] if self.documents else None

    @property
    def signed_pdf_url(self) -> Optional[str]:
        """Retourne l'URL du PDF signe."""
        doc = self.first_document
        return doc.url if doc else None


# === Webhook Payload ===
class DocuSealWebhookPayload(BaseModel):
    """
    Payload complet du webhook DocuSeal.

    Recu lors d'un evenement (submission.completed, etc.)
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    event_type: DocuSealEventType = Field(
        ...,
        description="Type d'evenement"
    )
    timestamp: Optional[datetime] = Field(
        default=None,
        description="Timestamp de l'evenement"
    )
    data: DocuSealSubmissionData = Field(
        ...,
        description="Donnees de la submission"
    )

    @property
    def is_signature_completed(self) -> bool:
        """Verifie si c'est un evenement de signature completee."""
        return self.event_type == "submission.completed"

    @property
    def submitter_email(self) -> Optional[str]:
        """Email du premier signataire."""
        submitter = self.data.first_submitter
        return submitter.email if submitter else None

    @property
    def submitter_phone(self) -> Optional[str]:
        """Telephone du premier signataire."""
        submitter = self.data.first_submitter
        return submitter.phone if submitter else None

    @property
    def signed_pdf_url(self) -> Optional[str]:
        """URL du PDF signe."""
        return self.data.signed_pdf_url


# === Reponse API ===
class DocuSealWebhookResponse(BaseModel):
    """Reponse au webhook DocuSeal."""

    status: Literal["success", "ignored", "error"] = "success"
    message: str = "OK"
    devis_id: Optional[str] = None
    new_pdf_url: Optional[str] = None

    @classmethod
    def success(cls, devis_id: str, new_pdf_url: str) -> "DocuSealWebhookResponse":
        """Cree une reponse de succes."""
        return cls(
            status="success",
            message="Signature traitee avec succes",
            devis_id=devis_id,
            new_pdf_url=new_pdf_url
        )

    @classmethod
    def ignored(cls, reason: str) -> "DocuSealWebhookResponse":
        """Cree une reponse pour evenement ignore."""
        return cls(
            status="ignored",
            message=reason
        )

    @classmethod
    def error(cls, message: str) -> "DocuSealWebhookResponse":
        """Cree une reponse d'erreur."""
        return cls(
            status="error",
            message=message
        )


# === Modele pour creer une submission DocuSeal ===
class DocuSealSubmissionCreate(BaseModel):
    """
    Payload pour creer une submission DocuSeal.

    Utilise pour envoyer un devis a signer.
    """

    template_id: int = Field(..., description="ID du template DocuSeal")
    send_email: bool = Field(default=True, description="Envoyer email au signataire")
    submitters: list[dict] = Field(
        ...,
        description="Liste des signataires avec leurs infos"
    )
    # Champs pre-remplis
    fields: Optional[list[dict]] = Field(
        default=None,
        description="Champs pre-remplis du document"
    )

    @classmethod
    def for_devis(
        cls,
        template_id: int,
        client_email: str,
        client_name: str,
        client_phone: Optional[str] = None,
        devis_fields: Optional[dict] = None
    ) -> "DocuSealSubmissionCreate":
        """
        Cree une submission pour un devis.

        Args:
            template_id: ID du template DocuSeal
            client_email: Email du client
            client_name: Nom du client
            client_phone: Telephone optionnel
            devis_fields: Champs a pre-remplir (numero, montant, etc.)

        Returns:
            DocuSealSubmissionCreate configure
        """
        submitter = {
            "email": client_email,
            "name": client_name,
            "role": "Client",
        }

        if client_phone:
            submitter["phone"] = client_phone

        fields = []
        if devis_fields:
            for field_name, value in devis_fields.items():
                fields.append({
                    "name": field_name,
                    "default_value": str(value)
                })

        return cls(
            template_id=template_id,
            send_email=True,
            submitters=[submitter],
            fields=fields if fields else None
        )
