"""
Service de generation de devis.

Gere:
- Generation des lignes (custom, budget manuel, OpenAI)
- Calculs HT/TVA/TTC
- Generation HTML du devis
- Conversion PDF avec WeasyPrint
- Upload vers Supabase Storage
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa

from app.core.config import settings
from app.core.database import supabase_admin as supabase
from app.models.devis import (
    DevisCreatePayload,
    DevisCalcule,
    LigneDevis,
    AIDevisLignesResult,
    generate_devis_numero,
    ClientInfo,
)

logger = logging.getLogger(__name__)


class DevisLignesGenerator:
    """
    Generateur de lignes de devis.

    Supporte 3 modes:
    - custom_manual: Lignes fournies par le dashboard
    - budget_manuel: Generation basee sur budget negocie
    - openai: Generation IA basee sur les infos du projet
    """

    # Repartition du budget pour le mode budget_manuel
    BUDGET_REPARTITION = {
        "main_oeuvre": 0.40,      # 40% main d'oeuvre
        "materiaux": 0.35,        # 35% materiaux
        "echafaudage": 0.15,      # 15% echafaudage/securite
        "evacuation": 0.10,       # 10% evacuation dechets
    }

    @classmethod
    def from_custom(
        cls,
        lignes: list[LigneDevis],
        notes: Optional[str] = None
    ) -> tuple[list[LigneDevis], str, str]:
        """
        Retourne les lignes custom telles quelles.

        Args:
            lignes: Liste des lignes fournies
            notes: Notes optionnelles

        Returns:
            Tuple (lignes, notes, source)
        """
        return (
            lignes,
            notes or "Devis personnalise etabli apres entretien telephonique avec le client.",
            "custom_manual"
        )

    @classmethod
    def from_budget(
        cls,
        budget_negocie: float,
        type_projet: str = "Projet de toiture",
        surface: float = 100.0
    ) -> tuple[list[LigneDevis], str, str]:
        """
        Genere des lignes basees sur le budget negocie.

        Repartition: 40% main d'oeuvre, 35% materiaux,
        15% echafaudage, 10% evacuation.

        Args:
            budget_negocie: Budget HT negocie avec le client
            type_projet: Type de projet pour les designations
            surface: Surface en m2

        Returns:
            Tuple (lignes, notes, source)
        """
        lignes = []

        # 1. Main d'oeuvre (40%)
        main_oeuvre = round(budget_negocie * cls.BUDGET_REPARTITION["main_oeuvre"], 2)
        lignes.append(LigneDevis(
            designation=f"Main d'oeuvre - {type_projet}",
            quantite=1,
            unite="forfait",
            prix_unitaire_ht=main_oeuvre
        ))

        # 2. Materiaux (35%)
        materiaux = round(budget_negocie * cls.BUDGET_REPARTITION["materiaux"], 2)
        prix_m2 = round(materiaux / surface, 2) if surface > 0 else materiaux
        lignes.append(LigneDevis(
            designation="Fourniture materiaux (tuiles, isolation, etc.)",
            quantite=surface,
            unite="m2",
            prix_unitaire_ht=prix_m2
        ))

        # 3. Echafaudage (15%)
        echafaudage = round(budget_negocie * cls.BUDGET_REPARTITION["echafaudage"], 2)
        lignes.append(LigneDevis(
            designation="Echafaudage et mise en securite du chantier",
            quantite=1,
            unite="forfait",
            prix_unitaire_ht=echafaudage
        ))

        # 4. Evacuation (10%)
        evacuation = round(budget_negocie * cls.BUDGET_REPARTITION["evacuation"], 2)
        lignes.append(LigneDevis(
            designation="Evacuation des gravats et dechets",
            quantite=1,
            unite="forfait",
            prix_unitaire_ht=evacuation
        ))

        notes = (
            f"Budget negocie avec le client : {budget_negocie:.2f} EUR HT. "
            f"Devis etabli selon les specifications convenues lors de l'entretien telephonique."
        )

        return lignes, notes, "budget_manuel"

    @classmethod
    async def from_openai(
        cls,
        type_projet: str,
        surface: Optional[float] = None,
        contraintes: Optional[str] = None,
        description: Optional[str] = None
    ) -> tuple[list[LigneDevis], str, str]:
        """
        Genere des lignes via OpenAI GPT-4o-mini.

        Args:
            type_projet: Type de projet (renovation, reparation, etc.)
            surface: Surface en m2
            contraintes: Contraintes specifiques
            description: Description du projet

        Returns:
            Tuple (lignes, notes, source)
        """
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)

        system_prompt = """Tu es un estimateur de travaux toiture expert en France.
Tu generes des devis detailles, realistes et professionnels pour des projets de couverture.
Les prix doivent etre en euros HT et coherents avec le marche francais 2024-2025.
Reponds UNIQUEMENT en JSON valide sans texte supplementaire."""

        user_prompt = f"""Genere des lignes de devis coherentes au format JSON strict, basees sur:
- type_projet: {type_projet}
- surface: {surface or 'non specifiee'} m2
- contraintes: {contraintes or 'n/a'}
- description: {description or 'n/a'}

Format de reponse STRICT (JSON uniquement):
{{
  "lignes": [
    {{"designation": "Description du poste", "quantite": 10, "unite": "m2", "prix_unitaire_ht": 50.00}},
    ...
  ],
  "notes": "Notes complementaires courtes"
}}"""

        try:
            response = client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=1500,
                response_format={"type": "json_object"}
            )

            content = response.choices[0].message.content
            logger.info(f"OpenAI response for devis: {content[:200]}...")

            # Parse la reponse
            result = AIDevisLignesResult.from_json_string(content)

            if not result.lignes:
                # Fallback si pas de lignes generees
                return cls._fallback_lignes(type_projet, surface)

            return result.lignes, result.notes, "openai"

        except Exception as e:
            logger.error(f"Erreur OpenAI pour devis: {e}")
            return cls._fallback_lignes(type_projet, surface)

    @classmethod
    def _fallback_lignes(
        cls,
        type_projet: str,
        surface: Optional[float] = None
    ) -> tuple[list[LigneDevis], str, str]:
        """
        Lignes de fallback si OpenAI echoue.

        Genere un devis basique selon le type de projet.
        """
        surface = surface or 100.0
        base_price = 80.0  # Prix de base au m2

        lignes = [
            LigneDevis(
                designation=f"Travaux de {type_projet}",
                quantite=surface,
                unite="m2",
                prix_unitaire_ht=base_price
            ),
            LigneDevis(
                designation="Main d'oeuvre couvreur",
                quantite=surface,
                unite="m2",
                prix_unitaire_ht=40.0
            ),
            LigneDevis(
                designation="Echafaudage et securite",
                quantite=1,
                unite="forfait",
                prix_unitaire_ht=800.0
            ),
            LigneDevis(
                designation="Evacuation dechets",
                quantite=1,
                unite="forfait",
                prix_unitaire_ht=400.0
            ),
        ]

        notes = (
            "Devis estimatif genere automatiquement. "
            "Un devis detaille sera etabli apres visite technique."
        )

        return lignes, notes, "openai"


class DevisPDFGenerator:
    """
    Generateur de PDF pour les devis.

    Utilise Jinja2 pour le template HTML et WeasyPrint pour la conversion PDF.
    """

    def __init__(self, templates_dir: Optional[str] = None):
        """
        Initialise le generateur.

        Args:
            templates_dir: Chemin vers le dossier des templates.
                          Par defaut: ./templates
        """
        if templates_dir is None:
            templates_dir = str(Path(__file__).parent.parent.parent / "templates")

        self.env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=True
        )

        # Ajoute des filtres personnalises
        self.env.filters["format_euro"] = self._format_euro
        self.env.filters["escape_html"] = self._escape_html

    @staticmethod
    def _format_euro(value: float) -> str:
        """Formate un nombre en euros francais."""
        if value is None or not isinstance(value, (int, float)):
            return "0,00 EUR"
        return f"{value:,.2f} EUR".replace(",", " ").replace(".", ",")

    @staticmethod
    def _escape_html(value: str) -> str:
        """Echappe les caracteres HTML."""
        if not value:
            return ""
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#039;")
        )

    def generate_html(
        self,
        devis: DevisCalcule,
        client: ClientInfo,
        type_projet: str = "Projet de toiture",
        numero_devis: Optional[str] = None
    ) -> str:
        """
        Genere le HTML du devis.

        Args:
            devis: Devis avec calculs effectues
            client: Informations client
            type_projet: Type de projet
            numero_devis: Numero du devis (genere si non fourni)

        Returns:
            HTML du devis
        """
        numero = numero_devis or generate_devis_numero()
        today = datetime.now()

        # Date de validite
        from datetime import timedelta
        date_validite = today + timedelta(days=devis.validite_jours)

        # Prepare les lignes avec index
        lignes_indexed = [
            {
                "index": i + 1,
                "designation": ligne.designation,
                "quantite": ligne.quantite,
                "unite": ligne.unite,
                "prix_unitaire_ht": ligne.prix_unitaire_ht,
                "total_ht": ligne.total_ht
            }
            for i, ligne in enumerate(devis.lignes)
        ]

        template = self.env.get_template("devis_pdf.html")

        return template.render(
            # Numero et dates
            numero_devis=numero,
            today=today.strftime("%d %B %Y"),
            date_validite=date_validite.strftime("%d %B %Y"),
            validite_jours=devis.validite_jours,

            # Client
            client=client,

            # Projet
            type_projet=type_projet,

            # Lignes
            lignes=lignes_indexed,

            # Totaux
            total_ht=devis.total_ht,
            tva_pourcent=devis.tva_pourcent,
            total_tva=devis.total_tva,
            total_ttc=devis.total_ttc,

            # Notes
            notes=devis.notes,

            # Entreprise
            entreprise={
                "nom": "ToitureAI SAS",
                "adresse": "123 Rue des Couvreurs, 57000 Metz",
                "telephone": "06 44 99 32 31",
                "email": "contact@toitureai.fr",
                "siret": "123 456 789 00012",
                "tva_intracom": "FR12345678900",
                "rge": "2024-R-057-001",
                "capital": "50 000 EUR",
                "representant": "HARCHI ABOUFARIS Mohamed",
                "logo_url": "https://pnvnipgtydhlhgrjwzvu.supabase.co/storage/v1/object/public/assets/logo.png"
            }
        )

    def html_to_pdf(self, html: str) -> bytes:
        """
        Convertit du HTML en PDF avec xhtml2pdf.

        Args:
            html: Code HTML du devis

        Returns:
            PDF en bytes
        """
        result = BytesIO()

        # Convertit HTML en PDF
        pisa_status = pisa.CreatePDF(
            src=html,
            dest=result,
            encoding='utf-8'
        )

        if pisa_status.err:
            logger.error(f"Erreur lors de la generation PDF: {pisa_status.err}")
            raise Exception("Erreur lors de la generation du PDF")

        return result.getvalue()

    def generate_pdf(
        self,
        devis: DevisCalcule,
        client: ClientInfo,
        type_projet: str = "Projet de toiture",
        numero_devis: Optional[str] = None
    ) -> tuple[bytes, str]:
        """
        Genere le PDF complet du devis.

        Args:
            devis: Devis avec calculs
            client: Informations client
            type_projet: Type de projet
            numero_devis: Numero du devis

        Returns:
            Tuple (pdf_bytes, numero_devis)
        """
        numero = numero_devis or generate_devis_numero()

        # Genere HTML
        html = self.generate_html(devis, client, type_projet, numero)

        # Convertit en PDF
        pdf_bytes = self.html_to_pdf(html)

        return pdf_bytes, numero


class SupabaseStorageService:
    """Service pour uploader des fichiers vers Supabase Storage."""

    BUCKET_NAME = "devis"

    @classmethod
    async def upload_pdf(
        cls,
        pdf_bytes: bytes,
        lead_id: str,
        filename: str
    ) -> str:
        """
        Upload un PDF vers Supabase Storage.

        Args:
            pdf_bytes: Contenu du PDF
            lead_id: UUID du lead (pour organiser les fichiers)
            filename: Nom du fichier

        Returns:
            URL publique du fichier
        """
        file_path = f"{lead_id}/{filename}"

        try:
            # Upload le fichier
            result = supabase.storage.from_(cls.BUCKET_NAME).upload(
                path=file_path,
                file=pdf_bytes,
                file_options={
                    "content-type": "application/pdf",
                    "upsert": "true"  # Remplace si existe
                }
            )

            # Construit l'URL publique
            public_url = (
                f"{settings.supabase_url}/storage/v1/object/public/"
                f"{cls.BUCKET_NAME}/{file_path}"
            )

            logger.info(f"PDF uploaded to: {public_url}")
            return public_url

        except Exception as e:
            logger.error(f"Erreur upload Supabase Storage: {e}")
            raise


class DevisService:
    """
    Service principal de gestion des devis.

    Orchestre:
    - Generation des lignes
    - Calculs
    - Generation PDF
    - Upload Storage
    - Insertion BDD
    - Envoi email
    """

    def __init__(self):
        self.pdf_generator = DevisPDFGenerator()

    async def create_devis(
        self,
        payload: DevisCreatePayload,
        lead: dict
    ) -> dict:
        """
        Cree un devis complet.

        Args:
            payload: Payload de creation
            lead: Donnees du lead depuis Supabase

        Returns:
            Dictionnaire avec devis_id, numero, url_pdf
        """
        from app.core.database import DevisRepository
        from app.services.email_service import EmailService

        # 1. Genere les lignes selon le mode
        lignes, notes, source = await self._generate_lignes(payload, lead)

        # 2. Calcule les totaux
        tva = payload.params.tva if payload.params else 10.0
        validite = payload.params.validite_jours if payload.params else 30

        devis_calcule = DevisCalcule(
            lignes=lignes,
            notes=notes,
            source=source,
            tva_pourcent=tva,
            validite_jours=validite
        )

        # 3. Prepare les infos client
        client = ClientInfo(
            nom=lead.get("nom", "Client"),
            prenom=lead.get("prenom", ""),
            email=lead.get("email", ""),
            telephone=lead.get("telephone", ""),
            adresse=lead.get("adresse", ""),
            ville=lead.get("ville", ""),
            code_postal=lead.get("code_postal", "")
        )

        # 4. Genere le numero
        numero_devis = generate_devis_numero()

        # 5. Genere le PDF
        pdf_bytes, _ = self.pdf_generator.generate_pdf(
            devis=devis_calcule,
            client=client,
            type_projet=lead.get("type_projet", "Projet de toiture"),
            numero_devis=numero_devis
        )

        # 6. Genere le nom de fichier
        client_name = (
            client.nom.lower()
            .replace(" ", "_")
            .encode("ascii", "ignore")
            .decode()
        )
        date_str = datetime.now().strftime("%Y%m%d")
        filename = f"devis-{client_name}-{date_str}.pdf"

        # 7. Upload vers Supabase Storage
        url_pdf = await SupabaseStorageService.upload_pdf(
            pdf_bytes=pdf_bytes,
            lead_id=payload.lead_id,
            filename=filename
        )

        # 8. Insere en BDD
        from app.models.devis import DevisCreate

        devis_create = DevisCreate(
            lead_id=payload.lead_id,
            numero=numero_devis,
            date_creation=datetime.now(timezone.utc),
            montant_ht=devis_calcule.total_ht,
            montant_ttc=devis_calcule.total_ttc,
            tva_pourcent=devis_calcule.tva_pourcent,
            client_nom=client.nom,
            client_prenom=client.prenom,
            client_email=client.email,
            client_telephone=client.telephone,
            client_adresse=client.adresse_complete,
            url_pdf=url_pdf,
            notes=notes,
            lignes_json=json.dumps([l.model_dump() for l in lignes]),
            statut="envoye",
            validite_jours=validite
        )

        devis_repo = DevisRepository()
        devis_db = await devis_repo.insert(devis_create.to_db_dict())
        devis_id = devis_db.get("id")

        # 9. Envoie l'email avec le PDF
        email_service = EmailService()
        await email_service.send_devis(
            to_email=client.email,
            to_name=client.nom_complet,
            numero_devis=numero_devis,
            pdf_bytes=pdf_bytes,
            filename=filename
        )

        logger.info(f"Devis cree: {numero_devis} pour lead {payload.lead_id}")

        return {
            "devis_id": devis_id,
            "numero": numero_devis,
            "url_pdf": url_pdf,
            "statut": "envoye"
        }

    async def _generate_lignes(
        self,
        payload: DevisCreatePayload,
        lead: dict
    ) -> tuple[list[LigneDevis], str, str]:
        """
        Genere les lignes selon le mode detecte.

        Essaie de recuperer les donnees depuis:
        1. Le payload du webhook
        2. Les donnees du lead en BDD

        Args:
            payload: Payload de creation
            lead: Donnees du lead

        Returns:
            Tuple (lignes, notes, source)
        """
        import json as json_module

        # 1. Recuperer les lignes custom (payload d'abord, puis lead)
        lignes_custom = payload.lignes_devis_custom
        notes_custom = payload.notes_devis_custom

        if not lignes_custom:
            # Essayer de recuperer depuis le lead
            raw_lignes = lead.get("lignes_devis_custom")
            if raw_lignes:
                try:
                    if isinstance(raw_lignes, str):
                        lignes_data = json_module.loads(raw_lignes)
                    else:
                        lignes_data = raw_lignes

                    if isinstance(lignes_data, list) and len(lignes_data) > 0:
                        lignes_custom = [
                            LigneDevis(
                                designation=l.get("designation", "Poste"),
                                quantite=float(l.get("quantite", 1)),
                                unite=l.get("unite", "unite"),
                                prix_unitaire_ht=float(l.get("prix_unitaire_ht", 0))
                            )
                            for l in lignes_data
                        ]
                        logger.info(f"Lignes custom recuperees du lead: {len(lignes_custom)} lignes")
                except Exception as e:
                    logger.warning(f"Erreur parsing lignes_devis_custom: {e}")
                    lignes_custom = None

            # Notes custom depuis le lead
            if not notes_custom:
                notes_custom = lead.get("notes_devis_custom")

        # 2. Recuperer le budget negocie (payload d'abord, puis lead)
        budget = payload.budget_negocie
        if not budget or budget <= 0:
            budget_lead = lead.get("budget_negocie")
            if budget_lead and float(budget_lead) > 0:
                budget = float(budget_lead)
                logger.info(f"Budget negocie recupere du lead: {budget}")

        # 3. Determiner le mode et generer les lignes
        # Priorite: custom > budget > openai
        if lignes_custom and len(lignes_custom) > 0:
            logger.info(f"Mode custom_manual: {len(lignes_custom)} lignes")
            return DevisLignesGenerator.from_custom(
                lignes=lignes_custom,
                notes=notes_custom
            )

        elif budget and budget > 0:
            logger.info(f"Mode budget_manuel: budget={budget}")
            # Colonne Supabase = surface_m2, pas surface
            surface = lead.get("surface_m2") or lead.get("surface") or 100
            return DevisLignesGenerator.from_budget(
                budget_negocie=budget,
                type_projet=lead.get("type_projet", "Projet de toiture"),
                surface=float(surface)
            )

        else:
            logger.info("Mode openai: generation IA")
            surface = lead.get("surface_m2") or lead.get("surface") or 100
            return await DevisLignesGenerator.from_openai(
                type_projet=lead.get("type_projet", "renovation"),
                surface=float(surface),
                contraintes=lead.get("contraintes"),
                description=lead.get("description")
            )


# Instance singleton
devis_service = DevisService()
