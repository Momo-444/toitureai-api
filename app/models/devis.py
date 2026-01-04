"""
Modeles Pydantic pour les devis.

Definit les schemas de validation pour:
- Lignes de devis
- Payload de creation de devis
- Devis en base de donnees
- Reponse API
"""

from __future__ import annotations

import re
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    Field,
    EmailStr,
    field_validator,
    model_validator,
    ConfigDict,
    computed_field,
)


# === Types ===
DevisStatut = Literal[
    "brouillon",
    "genere",
    "envoye",
    "consulte",
    "signe",
    "paye",
    "refuse",
    "expire",
]

LigneSource = Literal[
    "custom_manual",   # Lignes manuelles du dashboard
    "budget_manuel",   # Genere depuis budget negocie
    "openai",          # Genere par IA
]


# === Ligne de Devis ===
class LigneDevis(BaseModel):
    """
    Une ligne de devis.

    Represente un poste de travail avec designation, quantite,
    unite et prix unitaire HT.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    designation: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Description du poste"
    )
    quantite: float = Field(
        ...,
        gt=0,
        description="Quantite"
    )
    unite: str = Field(
        default="unite",
        max_length=20,
        description="Unite de mesure (m2, forfait, unite, ml, etc.)"
    )
    prix_unitaire_ht: float = Field(
        ...,
        gt=0,
        description="Prix unitaire hors taxes"
    )

    @computed_field
    @property
    def total_ht(self) -> float:
        """Calcule le total HT de la ligne."""
        return round(self.quantite * self.prix_unitaire_ht, 2)

    @field_validator("unite")
    @classmethod
    def normalize_unite(cls, v: str) -> str:
        """Normalise l'unite de mesure."""
        mapping = {
            "m2": "m2",
            "m²": "m2",
            "metre carre": "m2",
            "ml": "ml",
            "metre lineaire": "ml",
            "u": "unite",
            "unite": "unite",
            "unité": "unite",
            "piece": "unite",
            "pce": "unite",
            "forfait": "forfait",
            "fft": "forfait",
            "h": "heure",
            "heure": "heure",
            "jour": "jour",
            "j": "jour",
        }
        normalized = v.lower().strip()
        return mapping.get(normalized, normalized)


# === Parametres TVA ===
class DevisParams(BaseModel):
    """Parametres de calcul du devis."""

    tva: float = Field(
        default=20.0,
        ge=0,
        le=100,
        description="Taux de TVA en pourcentage (20% taux normal)"
    )
    validite_jours: int = Field(
        default=30,
        ge=7,
        le=180,
        description="Validite du devis en jours"
    )


# === Payload pour creer un devis ===
class DevisCreatePayload(BaseModel):
    """
    Payload recu depuis le dashboard pour creer un devis.

    Peut contenir:
    - lignes_devis_custom: Lignes manuelles
    - OU budget_negocie: Budget pour generation automatique
    - OU rien: Generation IA basee sur les infos du lead
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    lead_id: str = Field(
        ...,
        description="UUID du lead associe"
    )

    # Mode 1: Lignes manuelles
    lignes_devis_custom: Optional[list[LigneDevis]] = Field(
        default=None,
        description="Lignes de devis personnalisees"
    )
    notes_devis_custom: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Notes personnalisees"
    )

    # Mode 2: Budget negocie
    budget_negocie: Optional[float] = Field(
        default=None,
        gt=0,
        description="Budget negocie avec le client (HT)"
    )

    # Parametres optionnels
    params: Optional[DevisParams] = Field(
        default_factory=DevisParams,
        description="Parametres de calcul"
    )

    @field_validator("lead_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        """Valide le format UUID."""
        try:
            UUID(v)
            return v
        except ValueError:
            raise ValueError("lead_id doit etre un UUID valide")

    @property
    def mode(self) -> LigneSource:
        """Determine le mode de generation des lignes."""
        if self.lignes_devis_custom:
            return "custom_manual"
        elif self.budget_negocie:
            return "budget_manuel"
        else:
            return "openai"


# === Resultat de generation IA ===
class AIDevisLignesResult(BaseModel):
    """
    Resultat de la generation IA des lignes de devis.

    Retourne par OpenAI GPT-4o-mini.
    """

    lignes: list[LigneDevis] = Field(
        default_factory=list,
        description="Lignes generees"
    )
    notes: str = Field(
        default="",
        max_length=2000,
        description="Notes generees par l'IA"
    )

    @classmethod
    def from_json_string(cls, json_str: str) -> "AIDevisLignesResult":
        """
        Parse une chaine JSON en AIDevisLignesResult.

        Gere les erreurs de parsing avec des valeurs par defaut.
        """
        import json

        try:
            # Nettoie la chaine
            content = json_str.strip()

            # Gere le cas ou c'est deja un dict
            if isinstance(content, dict):
                data = content
            else:
                data = json.loads(content)

            lignes_raw = data.get("lignes", [])
            lignes = []

            for ligne in lignes_raw:
                try:
                    lignes.append(LigneDevis(
                        designation=ligne.get("designation", "Poste non defini"),
                        quantite=float(ligne.get("quantite", 1)),
                        unite=ligne.get("unite", "unite"),
                        prix_unitaire_ht=float(ligne.get("prix_unitaire_ht", 0))
                    ))
                except (ValueError, TypeError):
                    continue

            return cls(
                lignes=lignes,
                notes=data.get("notes", "Devis genere automatiquement")
            )
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            return cls(
                lignes=[],
                notes=f"Erreur de parsing IA: {str(e)}"
            )


# === Devis calcule (apres calculs) ===
class DevisCalcule(BaseModel):
    """
    Devis avec tous les calculs effectues.

    Pret pour generation du PDF.
    """

    lignes: list[LigneDevis] = Field(default_factory=list)
    notes: str = Field(default="")
    source: LigneSource = Field(default="openai")

    # Parametres
    tva_pourcent: float = Field(default=20.0)
    validite_jours: int = Field(default=30)

    # Totaux calcules
    total_ht: float = Field(default=0)
    total_tva: float = Field(default=0)
    total_ttc: float = Field(default=0)

    @model_validator(mode="after")
    def calculate_totals(self) -> "DevisCalcule":
        """Calcule les totaux automatiquement."""
        # Recalcule total_ht
        self.total_ht = round(sum(
            ligne.total_ht for ligne in self.lignes
        ), 2)

        # Calcule TVA et TTC
        self.total_tva = round(self.total_ht * (self.tva_pourcent / 100), 2)
        self.total_ttc = round(self.total_ht + self.total_tva, 2)

        return self


# === Devis pour insertion en BDD ===
class DevisCreate(BaseModel):
    """Donnees pour creer un devis en base."""

    model_config = ConfigDict(str_strip_whitespace=True)

    lead_id: str
    numero: str
    date_creation: datetime

    # Montants
    montant_ht: float
    montant_ttc: float
    tva_pourcent: float = Field(default=20.0)

    # Client (copie depuis lead)
    client_nom: str
    client_prenom: Optional[str] = None
    client_email: EmailStr
    client_telephone: Optional[str] = None
    client_adresse: Optional[str] = None

    # Fichiers
    url_pdf: str

    # Notes et lignes
    notes: Optional[str] = None
    lignes_json: Optional[str] = None  # JSON stringifie

    # Statut
    statut: DevisStatut = Field(default="envoye")

    # Validite
    validite_jours: int = Field(default=30)

    def to_db_dict(self) -> dict:
        """Convertit en dictionnaire pour insertion Supabase."""
        from datetime import timedelta

        # Calcule la date de validite
        date_validite = self.date_creation + timedelta(days=self.validite_jours)

        # Construit le nom complet client (prenom + nom)
        client_nom_complet = self.client_nom
        if self.client_prenom:
            client_nom_complet = f"{self.client_prenom} {self.client_nom}"

        return {
            "lead_id": self.lead_id,
            "numero": self.numero,
            "date_creation": self.date_creation.isoformat(),
            "montant_ht": self.montant_ht,
            "montant_ttc": self.montant_ttc,
            "tva_pct": self.tva_pourcent,  # Colonne Supabase = tva_pct
            "client_nom": client_nom_complet,
            "client_email": self.client_email,
            "client_telephone": self.client_telephone,
            "client_adresse": self.client_adresse,
            "url_pdf": self.url_pdf,
            "notes": self.notes,
            "statut": self.statut,
            "date_validite": date_validite.isoformat(),  # Colonne Supabase = date_validite
        }


# === Devis en base de donnees ===
class DevisInDB(DevisCreate):
    """
    Devis tel que stocke en base de donnees.

    Inclut l'ID et les timestamps generes par Supabase.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None

    # Signature
    date_signature: Optional[datetime] = None
    docuseal_submission_id: Optional[str] = None


# === Reponse API ===
class DevisResponse(BaseModel):
    """Reponse API apres creation d'un devis."""

    status: Literal["success", "error"] = "success"
    message: str = "Devis cree et envoye avec succes"

    devis_id: Optional[str] = None
    numero: Optional[str] = None
    url_pdf: Optional[str] = None
    statut: Optional[DevisStatut] = None

    @classmethod
    def success(
        cls,
        devis_id: str,
        numero: str,
        url_pdf: str
    ) -> "DevisResponse":
        """Cree une reponse de succes."""
        return cls(
            status="success",
            message="Devis cree et envoye avec succes",
            devis_id=devis_id,
            numero=numero,
            url_pdf=url_pdf,
            statut="envoye"
        )

    @classmethod
    def error(cls, message: str) -> "DevisResponse":
        """Cree une reponse d'erreur."""
        return cls(
            status="error",
            message=message,
            devis_id=None,
            numero=None,
            url_pdf=None,
            statut=None
        )


# === Schema de mise a jour ===
class DevisUpdate(BaseModel):
    """Schema pour la mise a jour partielle d'un devis."""

    model_config = ConfigDict(str_strip_whitespace=True)

    statut: Optional[DevisStatut] = None
    notes: Optional[str] = Field(default=None, max_length=2000)
    url_pdf: Optional[str] = None
    date_signature: Optional[datetime] = None
    docuseal_submission_id: Optional[str] = None

    def to_update_dict(self) -> dict:
        """Retourne un dictionnaire avec seulement les champs non-None."""
        return {k: v for k, v in self.model_dump().items() if v is not None}


# === Generation du numero de devis ===
def generate_devis_numero() -> str:
    """
    Genere un numero de devis unique.

    Format: DEV-YYYYMMDD-XXXXXX
    Exemple: DEV-20250628-A1B2C3
    """
    import secrets

    date_part = datetime.now().strftime("%Y%m%d")
    random_part = secrets.token_hex(3).upper()

    return f"DEV-{date_part}-{random_part}"


# === Donnees client pour template ===
class ClientInfo(BaseModel):
    """Informations client pour le template de devis."""

    nom: str
    prenom: str = ""
    email: str
    telephone: str = ""
    adresse: str = ""
    ville: str = ""
    code_postal: str = ""

    @computed_field
    @property
    def nom_complet(self) -> str:
        """Retourne le nom complet."""
        if self.prenom:
            return f"{self.prenom} {self.nom}"
        return self.nom

    @computed_field
    @property
    def adresse_complete(self) -> str:
        """Retourne l'adresse complete formatee."""
        parts = [p for p in [self.adresse, self.code_postal, self.ville] if p]
        return ", ".join(parts) if parts else ""
