"""
Modeles Pydantic pour Rapport Mensuel.

Definit les schemas de validation pour:
- KPIs mensuels (leads, devis, CA)
- Top clients
- Donnees du rapport PDF
"""

from __future__ import annotations

from datetime import datetime, date
from typing import Optional, Literal
from decimal import Decimal

from pydantic import (
    BaseModel,
    Field,
    ConfigDict,
    computed_field,
)


# === KPIs Leads ===
class LeadKPIs(BaseModel):
    """KPIs relatifs aux leads."""

    model_config = ConfigDict(str_strip_whitespace=True)

    total: int = Field(default=0, description="Nombre total de leads")
    gagnes: int = Field(default=0, description="Leads convertis en clients")
    perdus: int = Field(default=0, description="Leads perdus")
    en_cours: int = Field(default=0, description="Leads en cours de traitement")

    @computed_field
    @property
    def taux_conversion(self) -> float:
        """Taux de conversion leads -> clients (%)."""
        if self.total == 0:
            return 0.0
        return round((self.gagnes / self.total) * 100, 1)

    @computed_field
    @property
    def taux_perte(self) -> float:
        """Taux de perte (%)."""
        if self.total == 0:
            return 0.0
        return round((self.perdus / self.total) * 100, 1)


# === KPIs Devis ===
class DevisKPIs(BaseModel):
    """KPIs relatifs aux devis."""

    model_config = ConfigDict(str_strip_whitespace=True)

    total: int = Field(default=0, description="Nombre total de devis")
    signes: int = Field(default=0, description="Devis signes")
    payes: int = Field(default=0, description="Devis payes")
    en_attente: int = Field(default=0, description="Devis en attente")
    refuses: int = Field(default=0, description="Devis refuses")

    @computed_field
    @property
    def taux_signature(self) -> float:
        """Taux de signature (%)."""
        if self.total == 0:
            return 0.0
        return round((self.signes / self.total) * 100, 1)

    @computed_field
    @property
    def taux_paiement(self) -> float:
        """Taux de paiement sur devis signes (%)."""
        if self.signes == 0:
            return 0.0
        return round((self.payes / self.signes) * 100, 1)


# === KPIs Financiers ===
class FinancialKPIs(BaseModel):
    """KPIs financiers."""

    model_config = ConfigDict(str_strip_whitespace=True)

    ca_mensuel: Decimal = Field(
        default=Decimal("0"),
        description="Chiffre d'affaires mensuel (devis signes)"
    )
    ca_encaisse: Decimal = Field(
        default=Decimal("0"),
        description="CA encaisse (devis payes)"
    )
    panier_moyen: Decimal = Field(
        default=Decimal("0"),
        description="Panier moyen par devis"
    )
    ca_potentiel: Decimal = Field(
        default=Decimal("0"),
        description="CA potentiel (devis en attente)"
    )

    @computed_field
    @property
    def ca_mensuel_formatted(self) -> str:
        """CA mensuel formate."""
        return f"{self.ca_mensuel:,.2f} EUR".replace(",", " ")

    @computed_field
    @property
    def ca_encaisse_formatted(self) -> str:
        """CA encaisse formate."""
        return f"{self.ca_encaisse:,.2f} EUR".replace(",", " ")

    @computed_field
    @property
    def panier_moyen_formatted(self) -> str:
        """Panier moyen formate."""
        return f"{self.panier_moyen:,.2f} EUR".replace(",", " ")


# === Top Client ===
class TopClient(BaseModel):
    """Client dans le top 10."""

    model_config = ConfigDict(str_strip_whitespace=True)

    rang: int = Field(..., description="Position dans le classement")
    nom: str = Field(..., description="Nom complet du client")
    email: str = Field(..., description="Email du client")
    nb_devis: int = Field(default=1, description="Nombre de devis")
    montant_total: Decimal = Field(..., description="Montant total des devis")
    ville: Optional[str] = Field(default=None, description="Ville du client")

    @computed_field
    @property
    def montant_formatted(self) -> str:
        """Montant formate."""
        return f"{self.montant_total:,.2f} EUR".replace(",", " ")


# === Lead Resume ===
class LeadResume(BaseModel):
    """Resume d'un lead pour le rapport."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(..., description="ID du lead")
    nom: str = Field(..., description="Nom complet")
    email: str = Field(..., description="Email")
    telephone: Optional[str] = Field(default=None, description="Telephone")
    ville: Optional[str] = Field(default=None, description="Ville")
    type_travaux: Optional[str] = Field(default=None, description="Type de travaux")
    statut: str = Field(..., description="Statut du lead")
    score: Optional[int] = Field(default=None, description="Score de qualification")
    date_creation: datetime = Field(..., description="Date de creation")

    @computed_field
    @property
    def date_formatted(self) -> str:
        """Date formatee."""
        return self.date_creation.strftime("%d/%m/%Y")


# === Devis Resume ===
class DevisResume(BaseModel):
    """Resume d'un devis pour le rapport."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(..., description="ID du devis")
    numero: str = Field(..., description="Numero du devis")
    client_nom: str = Field(..., description="Nom du client")
    client_email: str = Field(..., description="Email du client")
    montant_ttc: Decimal = Field(..., description="Montant TTC")
    statut: str = Field(..., description="Statut du devis")
    date_creation: datetime = Field(..., description="Date de creation")
    date_signature: Optional[datetime] = Field(default=None, description="Date signature")

    @computed_field
    @property
    def montant_formatted(self) -> str:
        """Montant formate."""
        return f"{self.montant_ttc:,.2f} EUR".replace(",", " ")

    @computed_field
    @property
    def date_formatted(self) -> str:
        """Date formatee."""
        return self.date_creation.strftime("%d/%m/%Y")


# === Periode du rapport ===
class RapportPeriode(BaseModel):
    """Periode couverte par le rapport."""

    model_config = ConfigDict(str_strip_whitespace=True)

    mois: int = Field(..., ge=1, le=12, description="Mois (1-12)")
    annee: int = Field(..., ge=2020, description="Annee")
    date_debut: date = Field(..., description="Date de debut de la periode")
    date_fin: date = Field(..., description="Date de fin de la periode")

    @computed_field
    @property
    def mois_nom(self) -> str:
        """Nom du mois en francais."""
        mois_noms = [
            "", "Janvier", "Fevrier", "Mars", "Avril", "Mai", "Juin",
            "Juillet", "Aout", "Septembre", "Octobre", "Novembre", "Decembre"
        ]
        return mois_noms[self.mois]

    @computed_field
    @property
    def titre(self) -> str:
        """Titre de la periode."""
        return f"{self.mois_nom} {self.annee}"

    @computed_field
    @property
    def periode_formatted(self) -> str:
        """Periode formatee."""
        return f"Du {self.date_debut.strftime('%d/%m/%Y')} au {self.date_fin.strftime('%d/%m/%Y')}"


# === Rapport Complet ===
class RapportMensuel(BaseModel):
    """Donnees completes du rapport mensuel."""

    model_config = ConfigDict(str_strip_whitespace=True)

    # Metadata
    genere_le: datetime = Field(
        default_factory=lambda: datetime.now(),
        description="Date de generation"
    )
    periode: RapportPeriode = Field(..., description="Periode du rapport")

    # KPIs
    lead_kpis: LeadKPIs = Field(
        default_factory=LeadKPIs,
        description="KPIs des leads"
    )
    devis_kpis: DevisKPIs = Field(
        default_factory=DevisKPIs,
        description="KPIs des devis"
    )
    financial_kpis: FinancialKPIs = Field(
        default_factory=FinancialKPIs,
        description="KPIs financiers"
    )

    # Top clients
    top_clients: list[TopClient] = Field(
        default_factory=list,
        description="Top 10 des clients"
    )

    # Listes detaillees
    leads: list[LeadResume] = Field(
        default_factory=list,
        description="Liste des leads du mois"
    )
    devis: list[DevisResume] = Field(
        default_factory=list,
        description="Liste des devis du mois"
    )

    @computed_field
    @property
    def genere_le_formatted(self) -> str:
        """Date de generation formatee."""
        return self.genere_le.strftime("%d/%m/%Y a %H:%M")


# === Payload pour generer un rapport ===
class RapportGeneratePayload(BaseModel):
    """Payload pour declencher la generation d'un rapport."""

    model_config = ConfigDict(str_strip_whitespace=True)

    mois: Optional[int] = Field(
        default=None,
        ge=1,
        le=12,
        description="Mois (1-12). Si non fourni, utilise le mois precedent."
    )
    annee: Optional[int] = Field(
        default=None,
        ge=2020,
        description="Annee. Si non fourni, utilise l'annee courante."
    )
    envoyer_email: bool = Field(
        default=True,
        description="Envoyer le rapport par email"
    )
    email_destinataire: Optional[str] = Field(
        default=None,
        description="Email du destinataire. Si non fourni, utilise l'admin."
    )


# === Reponse API ===
class RapportResponse(BaseModel):
    """Reponse de l'API pour la generation de rapport."""

    status: Literal["success", "error"] = "success"
    message: str = "Rapport genere avec succes"
    rapport_id: Optional[str] = None
    pdf_url: Optional[str] = None
    periode: Optional[str] = None
    email_envoye: bool = False

    @classmethod
    def success(
        cls,
        rapport_id: str,
        pdf_url: str,
        periode: str,
        email_envoye: bool = False
    ) -> "RapportResponse":
        """Cree une reponse de succes."""
        return cls(
            status="success",
            message="Rapport genere avec succes",
            rapport_id=rapport_id,
            pdf_url=pdf_url,
            periode=periode,
            email_envoye=email_envoye
        )

    @classmethod
    def error(cls, message: str) -> "RapportResponse":
        """Cree une reponse d'erreur."""
        return cls(
            status="error",
            message=message
        )


# === Modele pour stocker le rapport en DB ===
class RapportDB(BaseModel):
    """Modele pour stocker le rapport en base de donnees."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: Optional[str] = Field(default=None, description="UUID du rapport")
    mois: int = Field(..., description="Mois du rapport")
    annee: int = Field(..., description="Annee du rapport")
    url_pdf: str = Field(..., description="URL du PDF genere")

    # KPIs stockes
    nb_leads: int = Field(default=0)
    nb_leads_gagnes: int = Field(default=0)
    nb_devis: int = Field(default=0)
    nb_devis_signes: int = Field(default=0)
    ca_mensuel: Decimal = Field(default=Decimal("0"))
    panier_moyen: Decimal = Field(default=Decimal("0"))

    # Metadata
    created_at: Optional[datetime] = None
    envoye_a: Optional[str] = Field(default=None, description="Email du destinataire")
    envoye_le: Optional[datetime] = Field(default=None, description="Date d'envoi")
