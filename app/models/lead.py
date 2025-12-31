"""
Modèles Pydantic pour les leads.

Définit les schémas de validation pour:
- Payload du webhook entrant
- Création de lead
- Lead en base de données
- Réponse API
- Résultat de qualification IA
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, Literal, Union
from uuid import UUID

from pydantic import (
    BaseModel,
    Field,
    EmailStr,
    field_validator,
    model_validator,
    ConfigDict,
)


# === Types ===
LeadStatut = Literal[
    "nouveau",
    "contacte",
    "qualifie",
    "devis_envoye",
    "accepte",
    "refuse",
    "perdu"
]

Urgence = Literal["faible", "moyenne", "haute"]

TypeProjet = Literal[
    "reparation",
    "renovation",
    "isolation",
    "installation",
    "entretien",
    "autre"
]

Delai = Literal[
    "urgent",
    "1-2 semaines",
    "1 mois",
    "2-3 mois",
    "flexible"
]


# === Payload Webhook (depuis la landing page) ===
class LeadWebhookPayload(BaseModel):
    """
    Payload reçu depuis le formulaire de la landing page.

    Correspond exactement aux champs envoyés par ContactForm.tsx.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    # Champs requis
    nom: str = Field(..., min_length=2, max_length=100, description="Nom de famille")
    prenom: str = Field(default="", max_length=100, description="Prénom")
    email: EmailStr = Field(..., description="Adresse email")
    telephone: str = Field(..., min_length=10, max_length=20, description="Numéro de téléphone")
    typeDeProjet: str = Field(..., alias="typeDeProjet", description="Type de projet")
    adresse: str = Field(..., min_length=5, max_length=500, description="Adresse complète")
    ville: str = Field(..., min_length=2, max_length=100, description="Ville")
    codePostal: str = Field(..., alias="codePostal", min_length=5, max_length=10, description="Code postal")
    rgpd: bool = Field(..., description="Acceptation RGPD")

    # Champs optionnels (accepte string ou int depuis le frontend)
    surface: Optional[Union[str, int]] = Field(default=None, description="Surface en m²")
    budget: Optional[Union[str, int]] = Field(default=None, description="Budget estimé")
    delai: Optional[str] = Field(default="flexible", description="Délai souhaité")
    description: Optional[str] = Field(default="", max_length=2000, description="Description du projet")

    # Métadonnées
    timestamp: Optional[str] = Field(default=None, description="Timestamp de soumission")
    source: str = Field(default="landing-page-astro", description="Source du lead")
    turnstileToken: Optional[str] = Field(default=None, alias="turnstileToken", description="Token Turnstile")

    @field_validator("rgpd")
    @classmethod
    def validate_rgpd(cls, v: bool) -> bool:
        """RGPD doit être accepté."""
        if not v:
            raise ValueError("L'acceptation RGPD est obligatoire")
        return v

    @field_validator("telephone")
    @classmethod
    def normalize_phone(cls, v: str) -> str:
        """
        Normalise le numéro de téléphone au format français +33.

        Exemples:
        - "0612345678" → "+33612345678"
        - "06 12 34 56 78" → "+33612345678"
        - "+33612345678" → "+33612345678"
        """
        if not v:
            return ""

        # Supprime tous les caractères non numériques sauf +
        cleaned = re.sub(r"[^\d+]", "", v)

        # Convertit le format 0X en +33X
        if cleaned.startswith("0") and len(cleaned) >= 10:
            cleaned = "+33" + cleaned[1:]

        # Ajoute +33 si absent
        if not cleaned.startswith("+"):
            cleaned = "+33" + cleaned

        return cleaned

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        """Normalise l'email en minuscules."""
        return v.lower().strip()

    @field_validator("typeDeProjet")
    @classmethod
    def normalize_type_projet(cls, v: str) -> str:
        """Normalise le type de projet."""
        mapping = {
            "réparation (fuite, tuiles cassées...)": "reparation",
            "reparation (fuite, tuiles cassées...)": "reparation",
            "réparation": "reparation",
            "reparation": "reparation",
            "rénovation complète": "renovation",
            "renovation complete": "renovation",
            "rénovation": "renovation",
            "renovation": "renovation",
            "isolation thermique": "isolation",
            "isolation": "isolation",
            "installation neuve": "installation",
            "installation": "installation",
            "entretien / maintenance": "entretien",
            "entretien": "entretien",
            "maintenance": "entretien",
            "autre": "autre",
        }
        normalized = v.lower().strip()
        return mapping.get(normalized, "autre")

    @field_validator("delai")
    @classmethod
    def normalize_delai(cls, v: Optional[str]) -> str:
        """Normalise le délai."""
        if not v:
            return "flexible"

        mapping = {
            "urgent (sous 48h)": "urgent",
            "urgent": "urgent",
            "dans 1-2 semaines": "1-2 semaines",
            "1-2 semaines": "1-2 semaines",
            "dans 1 mois": "1 mois",
            "1 mois": "1 mois",
            "dans 2-3 mois": "2-3 mois",
            "2-3 mois": "2-3 mois",
            "flexible / à convenir": "flexible",
            "flexible": "flexible",
        }
        normalized = v.lower().strip()
        return mapping.get(normalized, "flexible")

    def to_lead_create(self) -> "LeadCreate":
        """Convertit le payload webhook en LeadCreate."""
        return LeadCreate(
            nom=self.nom,
            prenom=self.prenom,
            email=self.email,
            telephone=self.telephone,
            type_projet=self.typeDeProjet,
            adresse=self.adresse,
            ville=self.ville,
            code_postal=self.codePostal,
            description=self.description or "",
            surface=self._parse_number(self.surface),
            budget_estime=self._parse_number(self.budget),
            delai=self.delai or "flexible",
            source=self.source,
        )

    @staticmethod
    def _parse_number(value: Optional[Union[str, int]]) -> Optional[int]:
        """Parse une chaîne ou int en nombre entier."""
        if value is None:
            return None
        if isinstance(value, int):
            return value if value > 0 else None
        if isinstance(value, str) and value.strip():
            try:
                num = float(value)
                return int(num) if num > 0 else None
            except (ValueError, TypeError):
                return None
        return None


# === Création de Lead (données normalisées) ===
class LeadCreate(BaseModel):
    """
    Données normalisées pour créer un lead en base.

    Après validation et normalisation du webhook payload.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    # Contact
    nom: str = Field(..., min_length=2, max_length=100)
    prenom: str = Field(default="", max_length=100)
    email: EmailStr
    telephone: str = Field(..., min_length=10, max_length=20)

    # Projet
    type_projet: str = Field(..., max_length=50)
    surface: Optional[int] = Field(default=None, ge=1)
    budget_estime: Optional[int] = Field(default=None, ge=1)
    delai: str = Field(default="flexible", max_length=50)
    description: str = Field(default="", max_length=2000)

    # Localisation
    adresse: str = Field(default="", max_length=500)
    ville: str = Field(default="", max_length=100)
    code_postal: str = Field(default="", max_length=10)

    # Métadonnées
    source: str = Field(default="web", max_length=50)
    statut: LeadStatut = Field(default="nouveau")

    # Tracking (optionnel)
    user_agent: Optional[str] = Field(default=None, max_length=500)
    ip_address: Optional[str] = Field(default=None, max_length=50)

    def to_db_dict(self) -> dict:
        """Convertit en dictionnaire pour insertion Supabase."""
        # Colonnes qui existent dans le schema Supabase original
        data = {
            "nom": self.nom,
            "prenom": self.prenom,
            "email": self.email,
            "telephone": self.telephone,
            "type_projet": self.type_projet,
            "surface": self.surface,
            "description": self.description,
            "adresse": self.adresse,
            "ville": self.ville,
            "code_postal": self.code_postal,
            "source": self.source,
            "statut": self.statut,
            # Colonnes ajoutees par migration (optionnelles)
            "budget_estime": self.budget_estime,
            "delai": self.delai,
            "contraintes": None,
        }
        # Retire les valeurs None pour eviter les erreurs si colonnes pas encore creees
        # MAIS on garde budget s'il est present (0 est falsy mais on veut le garder)
        return {k: v for k, v in data.items() if v is not None}


# === Résultat de qualification IA ===
class AIQualificationResult(BaseModel):
    """
    Résultat de la qualification IA d'un lead.

    Retourné par OpenAI GPT-4o-mini.
    """

    score: int = Field(
        default=50,
        ge=0,
        le=100,
        description="Score de qualification (0-100)"
    )
    urgence: Urgence = Field(
        default="moyenne",
        description="Niveau d'urgence"
    )
    recommandation: str = Field(
        default="Contacter sous 48h",
        max_length=500,
        description="Recommandation de suivi"
    )
    segments: list[str] = Field(
        default_factory=list,
        description="Segments de classification"
    )

    @classmethod
    def from_json_string(cls, json_str: str) -> "AIQualificationResult":
        """
        Parse une chaîne JSON en AIQualificationResult.

        Gère les erreurs de parsing avec des valeurs par défaut.
        """
        import json

        try:
            data = json.loads(json_str.strip())
            return cls(
                score=data.get("score", 50),
                urgence=data.get("urgence", "moyenne"),
                recommandation=data.get("recommandation", "Contacter sous 48h"),
                segments=data.get("segments", []) if isinstance(data.get("segments"), list) else []
            )
        except (json.JSONDecodeError, TypeError, KeyError):
            # Fallback en cas d'erreur de parsing
            return cls(
                score=50,
                urgence="moyenne",
                recommandation="Revérifier manuellement",
                segments=[]
            )


# === Lead avec données IA (pour insertion) ===
class LeadWithAI(LeadCreate):
    """Lead enrichi avec les données de qualification IA."""

    score_qualification: int = Field(default=50, ge=0, le=100)
    urgence: Urgence = Field(default="moyenne")
    ai_notes: str = Field(default="", max_length=500)
    ai_segments: str = Field(default="", max_length=500)
    ai_raw: str = Field(default="", max_length=5000)

    @classmethod
    def from_lead_and_ai(
        cls,
        lead: LeadCreate,
        ai_result: AIQualificationResult,
        ai_raw: str = ""
    ) -> "LeadWithAI":
        """Combine un lead et un résultat IA."""
        return cls(
            **lead.model_dump(),
            score_qualification=ai_result.score,
            urgence=ai_result.urgence,
            ai_notes=ai_result.recommandation,
            ai_segments=", ".join(ai_result.segments),
            ai_raw=ai_raw
        )

    def to_db_dict(self) -> dict:
        """Convertit en dictionnaire pour insertion Supabase."""
        base = super().to_db_dict()
        # Colonnes ajoutees par migration
        base.update({
            "score_qualification": self.score_qualification,
            "urgence": self.urgence,
            "recommandation_ia": self.ai_notes,  # Colonne Supabase = recommandation_ia
            "segments": self.ai_segments.split(", ") if self.ai_segments else [],  # Array
        })
        # Note: ai_raw n'est pas stocke en base (trop volumineux)
        return base


# === Lead en base de données ===
class LeadInDB(LeadWithAI):
    """
    Lead tel que stocké en base de données.

    Inclut l'ID et les timestamps générés par Supabase.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None

    # Tracking email
    email_ouvert: bool = Field(default=False)
    email_ouvert_count: int = Field(default=0)
    email_clic_count: int = Field(default=0)
    pdf_consulte: bool = Field(default=False)
    sendgrid_message_id: Optional[str] = None
    derniere_interaction: Optional[datetime] = None

    # Statut lead chaud
    lead_chaud: bool = Field(default=False)

    # Champs custom pour devis
    lignes_devis_custom: Optional[list] = None
    notes_devis_custom: Optional[str] = None
    budget_negocie: Optional[int] = None


# === Réponse API ===
class LeadResponse(BaseModel):
    """Réponse API après création d'un lead."""

    status: Literal["success", "error"] = "success"
    message: str = "Votre demande a été enregistrée. Nous vous contacterons sous 24-48h."
    lead: Optional[dict] = None

    @classmethod
    def success(cls, lead_id: str, email: str, score: int) -> "LeadResponse":
        """Crée une réponse de succès."""
        return cls(
            status="success",
            message="Votre demande a été enregistrée. Nous vous contacterons sous 24-48h.",
            lead={
                "id": lead_id,
                "email": email,
                "score": str(score)
            }
        )

    @classmethod
    def error(cls, message: str) -> "LeadResponse":
        """Crée une réponse d'erreur."""
        return cls(
            status="error",
            message=message,
            lead=None
        )


# === Schéma de mise à jour ===
class LeadUpdate(BaseModel):
    """Schéma pour la mise à jour partielle d'un lead."""

    model_config = ConfigDict(str_strip_whitespace=True)

    nom: Optional[str] = Field(default=None, min_length=2, max_length=100)
    prenom: Optional[str] = Field(default=None, max_length=100)
    email: Optional[EmailStr] = None
    telephone: Optional[str] = Field(default=None, min_length=10, max_length=20)
    type_projet: Optional[str] = Field(default=None, max_length=50)
    surface: Optional[int] = Field(default=None, ge=1)
    budget_estime: Optional[int] = Field(default=None, ge=1)
    budget_negocie: Optional[int] = Field(default=None, ge=1)
    delai: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = Field(default=None, max_length=2000)
    adresse: Optional[str] = Field(default=None, max_length=500)
    ville: Optional[str] = Field(default=None, max_length=100)
    code_postal: Optional[str] = Field(default=None, max_length=10)
    statut: Optional[LeadStatut] = None
    lignes_devis_custom: Optional[list] = None
    notes_devis_custom: Optional[str] = None

    def to_update_dict(self) -> dict:
        """Retourne un dictionnaire avec seulement les champs non-None."""
        return {k: v for k, v in self.model_dump().items() if v is not None}
