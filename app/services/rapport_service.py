"""
Service de generation de rapports mensuels.

Gere:
- Calcul des KPIs mensuels
- Agregation des donnees leads/devis
- Generation du PDF avec WeasyPrint
- Upload vers Supabase Storage
- Envoi par email
"""

from __future__ import annotations

import logging
from datetime import datetime, date, timezone
from calendar import monthrange
from decimal import Decimal
from typing import Optional
from pathlib import Path
from io import BytesIO

from jinja2 import Environment, FileSystemLoader


from app.core.config import settings
from app.core.database import supabase_admin as supabase
from app.models.rapport import (
    RapportMensuel,
    RapportPeriode,
    LeadKPIs,
    DevisKPIs,
    FinancialKPIs,
    TopClient,
    LeadResume,
    DevisResume,
    RapportDB,
)

logger = logging.getLogger(__name__)

# Configuration Jinja2
TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=True
)


class RapportService:
    """
    Service pour generer les rapports mensuels.

    Orchestre la collecte des donnees, le calcul des KPIs,
    la generation PDF et l'envoi par email.
    """

    RAPPORT_BUCKET = "rapports"
    ADMIN_EMAIL = "contact@toitureai.fr"

    def __init__(self):
        """Initialise le service."""
        pass

    async def generate_rapport(
        self,
        mois: Optional[int] = None,
        annee: Optional[int] = None,
        envoyer_email: bool = True,
        email_destinataire: Optional[str] = None
    ) -> dict:
        """
        Genere le rapport mensuel complet.

        Args:
            mois: Mois du rapport (1-12). Par defaut: mois precedent
            annee: Annee du rapport. Par defaut: annee courante
            envoyer_email: Envoyer le rapport par email
            email_destinataire: Email du destinataire (defaut: admin)

        Returns:
            Dict avec rapport_id, pdf_url, et statut email
        """
        # 1. Determine la periode
        periode = self._calculate_periode(mois, annee)
        logger.info(f"Generation rapport pour {periode.titre}")

        # 2. Recupere les donnees
        leads_data = await self._fetch_leads(periode)
        devis_data = await self._fetch_devis(periode)

        logger.info(f"Donnees: {len(leads_data)} leads, {len(devis_data)} devis")

        # 3. Calcule les KPIs
        lead_kpis = self._calculate_lead_kpis(leads_data)
        devis_kpis = self._calculate_devis_kpis(devis_data)
        financial_kpis = self._calculate_financial_kpis(devis_data)

        # 4. Top 10 clients
        top_clients = self._calculate_top_clients(devis_data)

        # 5. Prepare les resumes
        leads_resume = self._prepare_leads_resume(leads_data)
        devis_resume = self._prepare_devis_resume(devis_data)

        # 6. Construit le rapport
        rapport = RapportMensuel(
            periode=periode,
            lead_kpis=lead_kpis,
            devis_kpis=devis_kpis,
            financial_kpis=financial_kpis,
            top_clients=top_clients,
            leads=leads_resume,
            devis=devis_resume
        )

        # 7. Genere le PDF
        pdf_bytes = await self._generate_pdf(rapport)

        # 8. Upload vers Storage
        pdf_url = await self._upload_pdf(pdf_bytes, periode)

        # 9. Sauvegarde en DB
        rapport_id = await self._save_rapport_db(rapport, pdf_url)

        # 10. Envoie email si demande
        email_envoye = False
        if envoyer_email:
            destinataire = email_destinataire or self.ADMIN_EMAIL
            email_envoye = await self._send_rapport_email(
                rapport=rapport,
                pdf_bytes=pdf_bytes,
                destinataire=destinataire
            )

            # Met a jour le statut d'envoi
            if email_envoye:
                await self._update_rapport_sent(rapport_id, destinataire)

        logger.info(f"Rapport genere: {rapport_id}, email={email_envoye}")

        return {
            "rapport_id": rapport_id,
            "pdf_url": pdf_url,
            "periode": periode.titre,
            "email_envoye": email_envoye
        }

    def _calculate_periode(
        self,
        mois: Optional[int] = None,
        annee: Optional[int] = None
    ) -> RapportPeriode:
        """
        Calcule la periode du rapport.

        Par defaut: mois precedent.
        """
        now = datetime.now()

        if mois is None or annee is None:
            # Mois precedent
            if now.month == 1:
                target_mois = 12
                target_annee = now.year - 1
            else:
                target_mois = now.month - 1
                target_annee = now.year
        else:
            target_mois = mois
            target_annee = annee

        # Calcule les dates de debut/fin
        _, last_day = monthrange(target_annee, target_mois)
        date_debut = date(target_annee, target_mois, 1)
        date_fin = date(target_annee, target_mois, last_day)

        return RapportPeriode(
            mois=target_mois,
            annee=target_annee,
            date_debut=date_debut,
            date_fin=date_fin
        )

    async def _fetch_leads(self, periode: RapportPeriode) -> list[dict]:
        """Recupere les leads de la periode."""
        start_date = periode.date_debut.isoformat()
        end_date = periode.date_fin.isoformat() + "T23:59:59"

        response = (
            supabase.table("leads")
            .select("*")
            .gte("created_at", start_date)
            .lte("created_at", end_date)
            .order("created_at", desc=True)
            .execute()
        )

        return response.data or []

    async def _fetch_devis(self, periode: RapportPeriode) -> list[dict]:
        """Recupere les devis de la periode."""
        start_date = periode.date_debut.isoformat()
        end_date = periode.date_fin.isoformat() + "T23:59:59"

        response = (
            supabase.table("devis")
            .select("*")
            .gte("created_at", start_date)
            .lte("created_at", end_date)
            .order("created_at", desc=True)
            .execute()
        )

        return response.data or []

    def _calculate_lead_kpis(self, leads: list[dict]) -> LeadKPIs:
        """Calcule les KPIs des leads."""
        total = len(leads)
        
        # Statuts consideres comme gagnes/succes
        WON_STATUSES = ["gagne", "gagné", "accepte", "accepté", "transforme", "transformé", "signe", "signé"]
        # Statuts consideres comme perdus
        LOST_STATUSES = ["perdu", "refuse", "refusé", "sans_suite", "rejete", "rejeté"]
        
        gagnes = sum(1 for l in leads if str(l.get("statut", "")).lower() in WON_STATUSES)
        perdus = sum(1 for l in leads if str(l.get("statut", "")).lower() in LOST_STATUSES)
        en_cours = total - gagnes - perdus

        return LeadKPIs(
            total=total,
            gagnes=gagnes,
            perdus=perdus,
            en_cours=en_cours
        )

    def _calculate_devis_kpis(self, devis: list[dict]) -> DevisKPIs:
        """Calcule les KPIs des devis."""
        total = len(devis)
        
        # Statuts
        parse_statut = lambda d: str(d.get("statut", "")).lower()
        
        PAID_STATUSES = ["paye", "payé", "payes", "payés", "paid"]
        SIGNED_STATUSES = ["signe", "signé", "signed", "accepte", "accepté"] + PAID_STATUSES
        REFUSED_STATUSES = ["refuse", "refusé", "rejete", "rejeté", "declined"]

        signes = sum(1 for d in devis if parse_statut(d) in SIGNED_STATUSES)
        payes = sum(1 for d in devis if parse_statut(d) in PAID_STATUSES)
        refuses = sum(1 for d in devis if parse_statut(d) in REFUSED_STATUSES)
        en_attente = total - signes - refuses

        return DevisKPIs(
            total=total,
            signes=signes,
            payes=payes,
            en_attente=en_attente,
            refuses=refuses
        )

    def _calculate_financial_kpis(self, devis: list[dict]) -> FinancialKPIs:
        """Calcule les KPIs financiers."""
        parse_statut = lambda d: str(d.get("statut", "")).lower()
        
        PAID_STATUSES = ["paye", "payé", "payes", "payés", "paid"]
        SIGNED_STATUSES = ["signe", "signé", "signed", "accepte", "accepté"] + PAID_STATUSES
        REFUSED_STATUSES = ["refuse", "refusé", "rejete", "rejeté", "declined"]

        # CA mensuel = total des devis signes (ou payes)
        devis_signes = [d for d in devis if parse_statut(d) in SIGNED_STATUSES]
        ca_mensuel = sum(
            Decimal(str(d.get("montant_ttc", 0)))
            for d in devis_signes
        )

        # CA encaisse = devis payes
        devis_payes = [d for d in devis if parse_statut(d) in PAID_STATUSES]
        ca_encaisse = sum(
            Decimal(str(d.get("montant_ttc", 0)))
            for d in devis_payes
        )

        # Panier moyen (sur les devis signes)
        if devis_signes:
            panier_moyen = ca_mensuel / len(devis_signes)
        else:
            panier_moyen = Decimal("0")

        # CA potentiel = devis en attente (pas signes, pas perdus)
        # On exclut ceux qui sont deja dans SIGNED ou REFUSED
        devis_attente = [
            d for d in devis
            if parse_statut(d) not in SIGNED_STATUSES + REFUSED_STATUSES
        ]
        ca_potentiel = sum(
            Decimal(str(d.get("montant_ttc", 0)))
            for d in devis_attente
        )

        return FinancialKPIs(
            ca_mensuel=ca_mensuel,
            ca_encaisse=ca_encaisse,
            panier_moyen=panier_moyen.quantize(Decimal("0.01")),
            ca_potentiel=ca_potentiel
        )

    def _calculate_top_clients(
        self,
        devis: list[dict],
        limit: int = 10
    ) -> list[TopClient]:
        """Calcule le top 10 des clients."""
        # Agrege par client (email)
        clients: dict[str, dict] = {}

        # Statuts
        parse_statut = lambda d: str(d.get("statut", "")).lower()
        PAID_STATUSES = ["paye", "payé", "payes", "payés", "paid"]
        SIGNED_STATUSES = ["signe", "signé", "signed", "accepte", "accepté"] + PAID_STATUSES

        for d in devis:
            if parse_statut(d) not in SIGNED_STATUSES:
                continue

            email = d.get("client_email", "").lower()
            if not email:
                continue

            if email not in clients:
                clients[email] = {
                    "nom": f"{d.get('client_prenom', '')} {d.get('client_nom', '')}".strip(),
                    "email": email,
                    "ville": d.get("client_ville"),
                    "nb_devis": 0,
                    "montant_total": Decimal("0")
                }

            clients[email]["nb_devis"] += 1
            clients[email]["montant_total"] += Decimal(str(d.get("montant_ttc", 0)))

        # Trie par montant decroissant
        sorted_clients = sorted(
            clients.values(),
            key=lambda x: x["montant_total"],
            reverse=True
        )[:limit]

        # Cree les TopClient
        return [
            TopClient(
                rang=i + 1,
                nom=c["nom"] or "Client",
                email=c["email"],
                nb_devis=c["nb_devis"],
                montant_total=c["montant_total"],
                ville=c["ville"]
            )
            for i, c in enumerate(sorted_clients)
        ]

    def _prepare_leads_resume(self, leads: list[dict]) -> list[LeadResume]:
        """Prepare les resumes des leads."""
        return [
            LeadResume(
                id=l["id"],
                nom=f"{l.get('prenom', '')} {l.get('nom', '')}".strip() or "N/A",
                email=l.get("email", ""),
                telephone=l.get("telephone"),
                ville=l.get("ville"),
                type_travaux=l.get("type_projet"), # Correction: type_projet dans la DB
                statut=l.get("statut", "nouveau"),
                score=l.get("score_qualification"), # Correction: score_qualification dans la DB
                date_creation=datetime.fromisoformat(
                    l["created_at"].replace("Z", "+00:00")
                )
            )
            for l in leads
            if l.get("email")
        ]

    def _prepare_devis_resume(self, devis: list[dict]) -> list[DevisResume]:
        """Prepare les resumes des devis."""
        result = []
        for d in devis:
            date_sig = None
            if d.get("date_signature"):
                try:
                    date_sig = datetime.fromisoformat(
                        d["date_signature"].replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass

            # Gestion du nom client (parfois separe, parfois groupe)
            prenom = d.get('client_prenom', '')
            nom = d.get('client_nom', '')
            if prenom:
                client_nom = f"{prenom} {nom}".strip()
            else:
                client_nom = nom.strip()

            result.append(DevisResume(
                id=d["id"],
                numero=d.get("numero", "N/A"),
                client_nom=client_nom or "N/A",
                client_email=d.get("client_email", ""),
                montant_ttc=Decimal(str(d.get("montant_ttc", 0))),
                statut=d.get("statut", "brouillon"),
                date_creation=datetime.fromisoformat(
                    d["created_at"].replace("Z", "+00:00")
                ),
                date_signature=date_sig
            ))

        return result

    async def _generate_pdf(self, rapport: RapportMensuel) -> bytes:
        """Genere le PDF du rapport avec WeasyPrint."""
        template = jinja_env.get_template("rapport_mensuel.html")

        html_content = template.render(
            rapport=rapport,
            periode=rapport.periode,
            lead_kpis=rapport.lead_kpis,
            devis_kpis=rapport.devis_kpis,
            financial_kpis=rapport.financial_kpis,
            top_clients=rapport.top_clients,
            leads=rapport.leads[:20],  # Limite pour le PDF
            devis=rapport.devis[:20],  # Limite pour le PDF
            genere_le=rapport.genere_le_formatted
        )

        # Genere le PDF avec WeasyPrint
        from weasyprint import HTML
        pdf_bytes = HTML(string=html_content).write_pdf()
        
        logger.info(f"PDF genere: {len(pdf_bytes)} bytes")

        return pdf_bytes

    async def _upload_pdf(
        self,
        pdf_bytes: bytes,
        periode: RapportPeriode
    ) -> str:
        """Upload le PDF vers Supabase Storage."""
        filename = f"rapport-{periode.annee}-{periode.mois:02d}.pdf"
        file_path = f"{periode.annee}/{filename}"

        try:
            result = supabase.storage.from_(self.RAPPORT_BUCKET).upload(
                path=file_path,
                file=pdf_bytes,
                file_options={
                    "content-type": "application/pdf",
                    "upsert": "true"
                }
            )

            public_url = (
                f"{settings.supabase_url}/storage/v1/object/public/"
                f"{self.RAPPORT_BUCKET}/{file_path}"
            )

            logger.info(f"PDF uploade: {public_url}")
            return public_url

        except Exception as e:
            logger.error(f"Erreur upload PDF: {e}")
            raise

    async def _save_rapport_db(
        self,
        rapport: RapportMensuel,
        pdf_url: str
    ) -> str:
        """Sauvegarde le rapport en base de donnees."""
        data = {
            "mois": rapport.periode.mois,
            "annee": rapport.periode.annee,
            "url_pdf": pdf_url,
            "nb_leads": rapport.lead_kpis.total,
            "nb_leads_gagnes": rapport.lead_kpis.gagnes,
            "nb_devis": rapport.devis_kpis.total,
            "nb_devis_signes": rapport.devis_kpis.signes,
            "ca_mensuel": float(rapport.financial_kpis.ca_mensuel),
            "panier_moyen": float(rapport.financial_kpis.panier_moyen),
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        response = supabase.table("rapports").insert(data).execute()

        if response.data:
            return response.data[0]["id"]

        raise ValueError("Erreur lors de la sauvegarde du rapport")

    async def _update_rapport_sent(
        self,
        rapport_id: str,
        destinataire: str
    ) -> None:
        """Met a jour le rapport apres envoi email."""
        supabase.table("rapports").update({
            "envoye_a": destinataire,
            "envoye_le": datetime.now(timezone.utc).isoformat()
        }).eq("id", rapport_id).execute()

    async def _send_rapport_email(
        self,
        rapport: RapportMensuel,
        pdf_bytes: bytes,
        destinataire: str
    ) -> bool:
        """Envoie le rapport par email."""
        import base64
        from app.services.email_service import EmailService

        email_service = EmailService()

        try:
            # Prepare l'attachment au format attendu par EmailService
            attachments = [{
                "content": base64.b64encode(pdf_bytes).decode("utf-8"),
                "filename": f"rapport-{rapport.periode.annee}-{rapport.periode.mois:02d}.pdf",
                "type": "application/pdf"
            }]

            success, _ = email_service.send_template_email(
                to_email=destinataire,
                subject=f"Rapport ToitureAI - {rapport.periode.titre}",
                template_name="email_rapport.html",
                context={
                    "periode": rapport.periode.titre,
                    "nb_leads": rapport.lead_kpis.total,
                    "nb_leads_gagnes": rapport.lead_kpis.gagnes,
                    "taux_conversion": rapport.lead_kpis.taux_conversion,
                    "nb_devis": rapport.devis_kpis.total,
                    "nb_devis_signes": rapport.devis_kpis.signes,
                    "ca_mensuel": rapport.financial_kpis.ca_mensuel_formatted,
                    "panier_moyen": rapport.financial_kpis.panier_moyen_formatted,
                    "website_url": settings.website_url,
                    "dashboard_url": settings.dashboard_url
                },
                attachments=attachments
            )

            return success

        except Exception as e:
            logger.error(f"Erreur envoi email rapport: {e}")
            return False

    async def get_rapport(self, rapport_id: str) -> Optional[dict]:
        """Recupere un rapport par son ID."""
        response = (
            supabase.table("rapports")
            .select("*")
            .eq("id", rapport_id)
            .single()
            .execute()
        )

        return response.data

    async def list_rapports(
        self,
        annee: Optional[int] = None,
        limit: int = 12
    ) -> list[dict]:
        """Liste les rapports."""
        query = supabase.table("rapports").select("*")

        if annee:
            query = query.eq("annee", annee)

        response = (
            query
            .order("annee", desc=True)
            .order("mois", desc=True)
            .limit(limit)
            .execute()
        )

        return response.data or []


# Instance singleton
rapport_service = RapportService()
