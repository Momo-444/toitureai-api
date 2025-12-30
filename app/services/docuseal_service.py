"""
Service DocuSeal pour la gestion des signatures electroniques.

Gere:
- Reception des webhooks DocuSeal
- Telechargement des PDFs signes
- Upload vers Supabase Storage
- Mise a jour des devis
- Envoi des confirmations
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from io import BytesIO

import httpx

from app.core.config import settings
from app.core.database import supabase_admin as supabase, DevisRepository
from app.models.docuseal import (
    DocuSealWebhookPayload,
    DocuSealSubmissionCreate,
)

logger = logging.getLogger(__name__)


class DocuSealService:
    """
    Service pour interagir avec DocuSeal.

    Gere les webhooks de signature et les appels API.
    """

    API_BASE_URL = "https://api.docuseal.co"
    SIGNED_PDF_BUCKET = "devis_signes"

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialise le service DocuSeal.

        Args:
            api_key: Cle API DocuSeal. Utilise settings si non fourni.
        """
        self.api_key = api_key or settings.docuseal_api_key
        self.devis_repo = DevisRepository()

    async def process_signature_completed(
        self,
        payload: DocuSealWebhookPayload
    ) -> dict:
        """
        Traite un webhook de signature completee.

        Flux:
        1. Extrait email/telephone du signataire
        2. Trouve le devis correspondant
        3. Telecharge le PDF signe
        4. Upload vers Supabase Storage
        5. Met a jour le devis
        6. Envoie email de confirmation

        Args:
            payload: Payload du webhook DocuSeal

        Returns:
            Dict avec devis_id et new_pdf_url

        Raises:
            ValueError: Si le devis n'est pas trouve
            Exception: Si le traitement echoue
        """
        # 1. Extrait les infos du signataire
        email = payload.submitter_email
        phone = payload.submitter_phone
        pdf_url = payload.signed_pdf_url

        if not email:
            raise ValueError("Email du signataire manquant dans le payload")

        if not pdf_url:
            raise ValueError("URL du PDF signe manquante dans le payload")

        logger.info(f"Traitement signature pour: {email}")

        # 2. Trouve le devis
        devis = await self._find_devis(email, phone)

        if not devis:
            raise ValueError(
                f"Aucun devis trouve pour email={email}, phone={phone}"
            )

        devis_id = devis["id"]
        logger.info(f"Devis trouve: {devis_id}")

        # 3. Telecharge le PDF signe
        pdf_bytes, filename = await self._download_signed_pdf(pdf_url, devis_id)

        # 4. Upload vers Supabase Storage
        new_pdf_url = await self._upload_to_storage(
            pdf_bytes=pdf_bytes,
            devis_id=devis_id,
            filename=filename
        )

        # 5. Met a jour le devis
        await self._update_devis_signed(
            devis_id=devis_id,
            new_pdf_url=new_pdf_url,
            submission_id=str(payload.data.id) if payload.data.id else None
        )

        # 6. Envoie email de confirmation
        await self._send_signature_confirmation(devis, new_pdf_url)

        logger.info(f"Signature traitee avec succes pour devis {devis_id}")

        return {
            "devis_id": devis_id,
            "new_pdf_url": new_pdf_url
        }

    async def _find_devis(
        self,
        email: str,
        phone: Optional[str]
    ) -> Optional[dict]:
        """
        Trouve le devis le plus recent par email et telephone.

        Args:
            email: Email du client
            phone: Telephone du client (optionnel)

        Returns:
            Le devis le plus recent ou None
        """
        # Recherche par email d'abord
        response = (
            supabase.table("devis")
            .select("*")
            .eq("client_email", email.lower())
            .order("created_at", desc=True)
            .execute()
        )

        devis_list = response.data or []

        if not devis_list:
            return None

        # Si telephone fourni, filtre
        if phone:
            matching = [
                d for d in devis_list
                if d.get("client_telephone") == phone
            ]
            if matching:
                return matching[0]

        # Sinon retourne le plus recent
        return devis_list[0]

    async def _download_signed_pdf(
        self,
        pdf_url: str,
        devis_id: str
    ) -> tuple[bytes, str]:
        """
        Telecharge le PDF signe depuis DocuSeal.

        Args:
            pdf_url: URL du PDF
            devis_id: ID du devis (pour le nom de fichier)

        Returns:
            Tuple (pdf_bytes, filename)
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(pdf_url)
            response.raise_for_status()

            pdf_bytes = response.content

            # Genere un nom de fichier
            date_str = datetime.now().strftime("%Y%m%d")
            filename = f"devis-signe-{date_str}.pdf"

            logger.info(f"PDF telecharge: {len(pdf_bytes)} bytes")

            return pdf_bytes, filename

    async def _upload_to_storage(
        self,
        pdf_bytes: bytes,
        devis_id: str,
        filename: str
    ) -> str:
        """
        Upload le PDF signe vers Supabase Storage.

        Args:
            pdf_bytes: Contenu du PDF
            devis_id: ID du devis
            filename: Nom du fichier

        Returns:
            URL publique du fichier
        """
        file_path = f"{devis_id}/{filename}"

        try:
            # Upload
            result = supabase.storage.from_(self.SIGNED_PDF_BUCKET).upload(
                path=file_path,
                file=pdf_bytes,
                file_options={
                    "content-type": "application/pdf",
                    "upsert": "true"
                }
            )

            # URL publique
            public_url = (
                f"{settings.supabase_url}/storage/v1/object/public/"
                f"{self.SIGNED_PDF_BUCKET}/{file_path}"
            )

            logger.info(f"PDF signe uploade: {public_url}")
            return public_url

        except Exception as e:
            logger.error(f"Erreur upload Storage: {e}")
            raise

    async def _update_devis_signed(
        self,
        devis_id: str,
        new_pdf_url: str,
        submission_id: Optional[str] = None
    ) -> dict:
        """
        Met a jour le devis apres signature.

        Args:
            devis_id: ID du devis
            new_pdf_url: Nouvelle URL du PDF signe
            submission_id: ID de la submission DocuSeal

        Returns:
            Devis mis a jour
        """
        update_data = {
            "url_pdf": new_pdf_url,
            "statut": "signe",
            "date_signature": datetime.now(timezone.utc).isoformat()
        }

        if submission_id:
            update_data["docuseal_submission_id"] = submission_id

        updated = await self.devis_repo.update(devis_id, update_data)

        logger.info(f"Devis {devis_id} mis a jour: statut=signe")

        return updated

    async def _send_signature_confirmation(
        self,
        devis: dict,
        pdf_url: str
    ) -> None:
        """
        Envoie un email de confirmation de signature.

        Args:
            devis: Donnees du devis
            pdf_url: URL du PDF signe
        """
        from app.services.email_service import EmailService

        email_service = EmailService()

        client_email = devis.get("client_email")
        client_name = f"{devis.get('client_prenom', '')} {devis.get('client_nom', '')}".strip()
        numero = devis.get("numero", "N/A")

        if not client_email:
            logger.warning("Pas d'email client pour confirmation")
            return

        try:
            success, _ = email_service.send_template_email(
                to_email=client_email,
                subject=f"Votre devis ToitureAI {numero} a ete signe",
                template_name="email_signature_confirmation.html",
                context={
                    "client_name": client_name or "Client",
                    "numero_devis": numero,
                    "pdf_url": pdf_url,
                    "website_url": settings.website_url,
                }
            )

            if success:
                logger.info(f"Email de confirmation envoye a {client_email}")
            else:
                logger.warning(f"Echec envoi email confirmation a {client_email}")

        except Exception as e:
            logger.error(f"Erreur envoi email confirmation: {e}")


    # === Methodes pour creer des submissions ===

    async def create_submission(
        self,
        template_id: int,
        client_email: str,
        client_name: str,
        client_phone: Optional[str] = None,
        fields: Optional[dict] = None
    ) -> dict:
        """
        Cree une nouvelle submission DocuSeal.

        Envoie un document a signer au client.

        Args:
            template_id: ID du template DocuSeal
            client_email: Email du client
            client_name: Nom du client
            client_phone: Telephone optionnel
            fields: Champs a pre-remplir

        Returns:
            Reponse de l'API DocuSeal
        """
        submission = DocuSealSubmissionCreate.for_devis(
            template_id=template_id,
            client_email=client_email,
            client_name=client_name,
            client_phone=client_phone,
            devis_fields=fields
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.API_BASE_URL}/submissions",
                headers={
                    "X-Auth-Token": self.api_key,
                    "Content-Type": "application/json"
                },
                json=submission.model_dump(exclude_none=True)
            )
            response.raise_for_status()

            result = response.json()
            logger.info(f"Submission DocuSeal creee: {result.get('id')}")

            return result

    async def get_submission(self, submission_id: int) -> dict:
        """
        Recupere une submission par son ID.

        Args:
            submission_id: ID de la submission

        Returns:
            Donnees de la submission
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.API_BASE_URL}/submissions/{submission_id}",
                headers={"X-Auth-Token": self.api_key}
            )
            response.raise_for_status()

            return response.json()


# Instance singleton
docuseal_service = DocuSealService()
