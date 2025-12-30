"""
Service d'envoi d'emails via SendGrid.

Gère tous les emails sortants de ToitureAI:
- Accusé de réception client
- Alertes équipe (lead chaud/standard)
- Envoi de devis
- Rapport mensuel
"""

from __future__ import annotations

import logging
from typing import Optional
from pathlib import Path

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Mail,
    Email,
    To,
    Content,
    Attachment,
    FileContent,
    FileName,
    FileType,
    Disposition,
)
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import settings

logger = logging.getLogger(__name__)

# Configuration Jinja2 pour les templates
TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


class EmailService:
    """
    Service d'envoi d'emails via SendGrid.

    Gère la composition et l'envoi des emails avec templates HTML.
    """

    def __init__(
        self,
        api_key: str | None = None,
        from_email: str | None = None,
        from_name: str | None = None
    ):
        """
        Initialise le service email.

        Args:
            api_key: Clé API SendGrid.
            from_email: Email d'expédition.
            from_name: Nom d'expédition.
        """
        self.client = SendGridAPIClient(api_key or settings.sendgrid_api_key)
        self.from_email = from_email or settings.sendgrid_from_email
        self.from_name = from_name or settings.sendgrid_from_name

    def _create_mail(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        attachments: list[dict] | None = None
    ) -> Mail:
        """
        Crée un objet Mail SendGrid.

        Args:
            to_email: Email destinataire.
            subject: Sujet de l'email.
            html_content: Contenu HTML.
            attachments: Liste de pièces jointes optionnelles.

        Returns:
            Objet Mail configuré.
        """
        message = Mail(
            from_email=Email(self.from_email, self.from_name),
            to_emails=To(to_email),
            subject=subject,
            html_content=Content("text/html", html_content)
        )

        if attachments:
            for att in attachments:
                attachment = Attachment(
                    FileContent(att["content"]),
                    FileName(att["filename"]),
                    FileType(att.get("type", "application/pdf")),
                    Disposition("attachment")
                )
                message.add_attachment(attachment)

        return message

    def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        attachments: list[dict] | None = None
    ) -> tuple[bool, str | None]:
        """
        Envoie un email via SendGrid.

        Args:
            to_email: Email destinataire.
            subject: Sujet.
            html_content: Contenu HTML.
            attachments: Pièces jointes optionnelles.

        Returns:
            Tuple (succès, message_id ou message d'erreur).
        """
        try:
            message = self._create_mail(to_email, subject, html_content, attachments)
            response = self.client.send(message)

            if response.status_code in (200, 201, 202):
                message_id = response.headers.get("X-Message-Id", "")
                logger.info(f"Email envoyé à {to_email}: {subject}")
                return True, message_id
            else:
                logger.error(
                    f"Erreur envoi email: {response.status_code} - {response.body}"
                )
                return False, f"Erreur {response.status_code}"

        except Exception as e:
            logger.exception(f"Exception lors de l'envoi email à {to_email}: {e}")
            return False, str(e)

    def send_template_email(
        self,
        to_email: str,
        subject: str,
        template_name: str,
        context: dict,
        attachments: list[dict] | None = None
    ) -> tuple[bool, str | None]:
        """
        Envoie un email basé sur un template Jinja2.

        Args:
            to_email: Email destinataire.
            subject: Sujet.
            template_name: Nom du fichier template (ex: "lead_confirmation.html").
            context: Dictionnaire de variables pour le template.
            attachments: Pièces jointes optionnelles.

        Returns:
            Tuple (succès, message_id ou message d'erreur).
        """
        try:
            template = jinja_env.get_template(template_name)
            html_content = template.render(**context)
            return self.send_email(to_email, subject, html_content, attachments)

        except Exception as e:
            logger.exception(f"Erreur template {template_name}: {e}")
            return False, str(e)

    # === Emails spécifiques au Workflow 1 ===

    def send_lead_confirmation(
        self,
        lead: dict,
        click_url: str,
        open_url: str
    ) -> tuple[bool, str | None]:
        """
        Envoie l'email de confirmation au client (accusé de réception).

        Args:
            lead: Données du lead (depuis Supabase).
            click_url: URL de tracking pour le clic.
            open_url: URL de tracking pour l'ouverture (pixel).

        Returns:
            Tuple (succès, message_id ou message d'erreur).
        """
        subject = (
            f"Merci {lead.get('prenom', '')} {lead.get('nom', '')} ! "
            f"Votre demande a été reçue ✅"
        )

        context = {
            "lead": lead,
            "click_url": click_url,
            "open_url": open_url,
            "website_url": settings.website_url,
        }

        return self.send_template_email(
            to_email=lead["email"],
            subject=subject,
            template_name="email_lead_confirmation.html",
            context=context
        )

    def send_team_alert_hot_lead(self, lead: dict) -> tuple[bool, str | None]:
        """
        Envoie une alerte urgente à l'équipe pour un lead chaud.

        Args:
            lead: Données du lead.

        Returns:
            Tuple (succès, message_id ou message d'erreur).
        """
        subject = (
            f"🚨 URGENT : Lead chaud - {lead.get('nom', '')} "
            f"{lead.get('prenom', '')} (Score : {lead.get('score_qualification', 0)})"
        )

        context = {
            "lead": lead,
            "is_hot": True,
        }

        return self.send_template_email(
            to_email=settings.admin_email,
            subject=subject,
            template_name="email_team_alert.html",
            context=context
        )

    def send_team_alert_standard(self, lead: dict) -> tuple[bool, str | None]:
        """
        Envoie une notification standard à l'équipe pour un nouveau lead.

        Args:
            lead: Données du lead.

        Returns:
            Tuple (succès, message_id ou message d'erreur).
        """
        subject = (
            f"📋 Nouveau lead : {lead.get('nom', '')} "
            f"{lead.get('prenom', '')} (Score : {lead.get('score_qualification', 0)})"
        )

        context = {
            "lead": lead,
            "is_hot": False,
        }

        return self.send_template_email(
            to_email=settings.admin_email,
            subject=subject,
            template_name="email_team_alert.html",
            context=context
        )

    # === Emails pour le Workflow 2 (Devis) ===

    async def send_devis(
        self,
        to_email: str,
        to_name: str,
        numero_devis: str,
        pdf_bytes: bytes,
        filename: str
    ) -> tuple[bool, str | None]:
        """
        Envoie un devis par email avec le PDF en piece jointe.

        Args:
            to_email: Email du destinataire.
            to_name: Nom complet du destinataire.
            numero_devis: Numero du devis.
            pdf_bytes: Contenu du PDF en bytes.
            filename: Nom du fichier PDF.

        Returns:
            Tuple (succes, message_id ou message d'erreur).
        """
        import base64

        subject = f"Votre devis ToitureAI n {numero_devis}"

        context = {
            "client_name": to_name,
            "numero_devis": numero_devis,
            "website_url": settings.website_url,
            "dashboard_url": settings.dashboard_url,
        }

        attachments = [{
            "content": base64.b64encode(pdf_bytes).decode("utf-8"),
            "filename": filename,
            "type": "application/pdf"
        }]

        return self.send_template_email(
            to_email=to_email,
            subject=subject,
            template_name="email_devis.html",
            context=context,
            attachments=attachments
        )

    def send_devis_sync(
        self,
        lead: dict,
        devis: dict,
        pdf_content: bytes
    ) -> tuple[bool, str | None]:
        """
        Version synchrone pour compatibilite.
        Envoie un devis par email avec le PDF en piece jointe.

        Args:
            lead: Donnees du lead/client.
            devis: Donnees du devis.
            pdf_content: Contenu du PDF en bytes.

        Returns:
            Tuple (succes, message_id ou message d'erreur).
        """
        import base64

        subject = (
            f"Votre devis ToitureAI n {devis.get('numero', 'N/A')} - "
            f"{lead.get('prenom', '')} {lead.get('nom', '')}"
        )

        context = {
            "lead": lead,
            "devis": devis,
            "client_name": f"{lead.get('prenom', '')} {lead.get('nom', '')}",
            "numero_devis": devis.get('numero', 'N/A'),
            "website_url": settings.website_url,
            "dashboard_url": settings.dashboard_url,
        }

        attachments = [{
            "content": base64.b64encode(pdf_content).decode("utf-8"),
            "filename": f"Devis_ToitureAI_{devis.get('numero', 'draft')}.pdf",
            "type": "application/pdf"
        }]

        return self.send_template_email(
            to_email=lead["email"],
            subject=subject,
            template_name="email_devis.html",
            context=context,
            attachments=attachments
        )

    # === Emails pour le Workflow 3 (Rapport mensuel) ===

    def send_monthly_report(
        self,
        report_data: dict,
        pdf_content: bytes,
        month: str,
        year: int
    ) -> tuple[bool, str | None]:
        """
        Envoie le rapport mensuel à l'administrateur.

        Args:
            report_data: Données du rapport (KPIs, stats).
            pdf_content: Contenu du PDF encodé.
            month: Nom du mois.
            year: Année.

        Returns:
            Tuple (succès, message_id ou message d'erreur).
        """
        import base64

        subject = f"📊 Rapport mensuel ToitureAI - {month} {year}"

        context = {
            "report": report_data,
            "month": month,
            "year": year,
        }

        attachments = [{
            "content": base64.b64encode(pdf_content).decode("utf-8"),
            "filename": f"Rapport_ToitureAI_{month}_{year}.pdf",
            "type": "application/pdf"
        }]

        return self.send_template_email(
            to_email=settings.admin_email,
            subject=subject,
            template_name="email_rapport.html",
            context=context,
            attachments=attachments
        )

    # === Email pour erreurs (Workflow 6) ===

    def send_error_alert(
        self,
        workflow: str,
        node: str,
        error_message: str,
        details: dict | None = None
    ) -> tuple[bool, str | None]:
        """
        Envoie une alerte d'erreur à l'administrateur.

        Args:
            workflow: Nom du workflow où l'erreur s'est produite.
            node: Nom du noeud/fonction.
            error_message: Message d'erreur.
            details: Détails supplémentaires.

        Returns:
            Tuple (succès, message_id ou message d'erreur).
        """
        subject = f"⚠️ Erreur ToitureAI - {workflow}"

        context = {
            "workflow": workflow,
            "node": node,
            "error_message": error_message,
            "details": details or {},
        }

        return self.send_template_email(
            to_email=settings.admin_email,
            subject=subject,
            template_name="email_error_alert.html",
            context=context
        )


# Instance globale
email_service = EmailService()


# Fonctions utilitaires pour import direct
def send_lead_confirmation(
    lead: dict,
    click_url: str,
    open_url: str
) -> tuple[bool, str | None]:
    """Envoie l'email de confirmation au client."""
    return email_service.send_lead_confirmation(lead, click_url, open_url)


def send_team_alert(lead: dict, is_hot: bool = False) -> tuple[bool, str | None]:
    """Envoie une alerte à l'équipe."""
    if is_hot:
        return email_service.send_team_alert_hot_lead(lead)
    return email_service.send_team_alert_standard(lead)


def send_error_alert(
    workflow: str,
    node: str,
    error_message: str,
    details: dict | None = None
) -> tuple[bool, str | None]:
    """Envoie une alerte d'erreur."""
    return email_service.send_error_alert(workflow, node, error_message, details)
