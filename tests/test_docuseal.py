"""
Tests pour le Workflow 5: DocuSeal Signature Completee.

Teste:
- Webhook DocuSeal (reception, validation, traitement)
- Telechargement PDF signe
- Upload vers Storage
- Mise a jour devis
- Envoi email confirmation
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone

from fastapi.testclient import TestClient


# === Fixtures specifiques DocuSeal ===

@pytest.fixture
def sample_docuseal_payload():
    """Payload webhook DocuSeal valide."""
    return {
        "event_type": "submission.completed",
        "timestamp": "2024-01-15T14:30:00Z",
        "data": {
            "id": 12345,
            "submission_id": 12345,
            "template_id": 100,
            "status": "completed",
            "created_at": "2024-01-15T10:00:00Z",
            "completed_at": "2024-01-15T14:30:00Z",
            "submitters": [
                {
                    "id": 1,
                    "uuid": "submitter-uuid-123",
                    "email": "client@example.com",
                    "phone": "+33612345678",
                    "name": "Jean Dupont",
                    "role": "Client",
                    "status": "completed",
                    "completed_at": "2024-01-15T14:30:00Z"
                }
            ],
            "documents": [
                {
                    "id": 1,
                    "uuid": "doc-uuid-456",
                    "url": "https://api.docuseal.co/documents/signed.pdf",
                    "filename": "devis-signe.pdf"
                }
            ]
        }
    }


@pytest.fixture
def sample_docuseal_form_viewed_payload():
    """Payload pour evenement form.viewed (doit etre ignore)."""
    return {
        "event_type": "form.viewed",
        "timestamp": "2024-01-15T14:00:00Z",
        "data": {
            "id": 12345,
            "submitters": [
                {
                    "email": "client@example.com",
                    "status": "pending"
                }
            ],
            "documents": []
        }
    }


@pytest.fixture
def mock_devis_found():
    """Mock d'un devis trouve en base."""
    return {
        "id": "devis-uuid-789",
        "numero": "DEV-2024-001",
        "client_email": "client@example.com",
        "client_telephone": "+33612345678",
        "client_nom": "Dupont",
        "client_prenom": "Jean",
        "client_ville": "Paris",
        "total_ttc": 15000.00,
        "statut": "envoye",
        "created_at": "2024-01-10T09:00:00Z"
    }


# === Tests Validation Payload ===

class TestDocuSealPayloadValidation:
    """Tests de validation du payload DocuSeal."""

    def test_valid_submission_completed_payload(self, sample_docuseal_payload):
        """Test payload submission.completed valide."""
        from app.models.docuseal import DocuSealWebhookPayload

        payload = DocuSealWebhookPayload(**sample_docuseal_payload)

        assert payload.event_type == "submission.completed"
        assert payload.is_signature_completed is True
        assert payload.submitter_email == "client@example.com"
        assert payload.submitter_phone == "+33612345678"
        assert payload.signed_pdf_url == "https://api.docuseal.co/documents/signed.pdf"

    def test_form_viewed_not_signature_completed(self, sample_docuseal_form_viewed_payload):
        """Test que form.viewed n'est pas considere comme signature."""
        from app.models.docuseal import DocuSealWebhookPayload

        payload = DocuSealWebhookPayload(**sample_docuseal_form_viewed_payload)

        assert payload.event_type == "form.viewed"
        assert payload.is_signature_completed is False

    def test_phone_normalization(self):
        """Test normalisation du telephone."""
        from app.models.docuseal import DocuSealSubmitter

        # Format 0612...
        submitter1 = DocuSealSubmitter(email="test@test.com", phone="0612345678")
        assert submitter1.phone == "+33612345678"

        # Deja au format +33
        submitter2 = DocuSealSubmitter(email="test@test.com", phone="+33612345678")
        assert submitter2.phone == "+33612345678"

        # Avec espaces
        submitter3 = DocuSealSubmitter(email="test@test.com", phone="06 12 34 56 78")
        assert submitter3.phone == "+33612345678"

    def test_email_normalization(self):
        """Test normalisation de l'email."""
        from app.models.docuseal import DocuSealSubmitter

        submitter = DocuSealSubmitter(email="  CLIENT@EXAMPLE.COM  ", phone=None)
        assert submitter.email == "client@example.com"

    def test_invalid_event_type_rejected(self):
        """Test qu'un event_type invalide est rejete."""
        from app.models.docuseal import DocuSealWebhookPayload
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DocuSealWebhookPayload(
                event_type="invalid.event",
                data={"id": 1, "submitters": [], "documents": []}
            )

    def test_missing_required_fields(self):
        """Test champs requis manquants."""
        from app.models.docuseal import DocuSealWebhookPayload
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DocuSealWebhookPayload(
                # event_type manquant
                data={"id": 1, "submitters": [], "documents": []}
            )


# === Tests Webhook Endpoint ===

class TestDocuSealWebhookEndpoint:
    """Tests de l'endpoint webhook DocuSeal."""

    def test_webhook_submission_completed_success(
        self,
        test_client: TestClient,
        sample_docuseal_payload,
        mock_devis_found
    ):
        """Test webhook avec signature completee."""
        with patch("app.services.docuseal_service.supabase") as mock_db, \
             patch("app.services.docuseal_service.httpx.AsyncClient") as mock_http, \
             patch("app.services.email_service.SendGridAPIClient"):

            # Mock recherche devis
            mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [mock_devis_found]

            # Mock telechargement PDF
            mock_response = MagicMock()
            mock_response.content = b"%PDF-1.4 fake pdf content"
            mock_response.raise_for_status = MagicMock()
            mock_http.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

            # Mock upload storage
            mock_db.storage.from_.return_value.upload.return_value = {"path": "test.pdf"}

            # Mock update devis
            mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [mock_devis_found]

            response = test_client.post(
                "/api/v1/docuseal/webhook",
                json=sample_docuseal_payload
            )

            assert response.status_code == 200
            assert response.text == "OK"

    def test_webhook_form_viewed_ignored(
        self,
        test_client: TestClient,
        sample_docuseal_form_viewed_payload
    ):
        """Test que form.viewed est ignore."""
        response = test_client.post(
            "/api/v1/docuseal/webhook",
            json=sample_docuseal_form_viewed_payload
        )

        assert response.status_code == 200
        assert response.text == "OK"

    def test_webhook_invalid_payload(self, test_client: TestClient):
        """Test payload invalide."""
        response = test_client.post(
            "/api/v1/docuseal/webhook",
            json={"invalid": "payload"}
        )

        assert response.status_code == 400

    def test_webhook_devis_not_found(
        self,
        test_client: TestClient,
        sample_docuseal_payload
    ):
        """Test devis non trouve."""
        with patch("app.services.docuseal_service.supabase") as mock_db:
            # Mock aucun devis trouve
            mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = []

            response = test_client.post(
                "/api/v1/docuseal/webhook",
                json=sample_docuseal_payload
            )

            assert response.status_code == 404


# === Tests Endpoint Test (avec auth) ===

class TestDocuSealTestEndpoint:
    """Tests de l'endpoint de test DocuSeal."""

    def test_test_endpoint_requires_auth(
        self,
        test_client: TestClient,
        sample_docuseal_payload
    ):
        """Test que l'endpoint de test requiert auth."""
        response = test_client.post(
            "/api/v1/docuseal/webhook/test",
            json=sample_docuseal_payload
        )

        assert response.status_code == 401

    def test_test_endpoint_invalid_secret(
        self,
        test_client: TestClient,
        sample_docuseal_payload,
        invalid_webhook_headers
    ):
        """Test avec secret invalide."""
        response = test_client.post(
            "/api/v1/docuseal/webhook/test",
            json=sample_docuseal_payload,
            headers=invalid_webhook_headers
        )

        assert response.status_code == 401

    def test_test_endpoint_valid_auth(
        self,
        test_client: TestClient,
        sample_docuseal_payload,
        valid_webhook_headers,
        mock_devis_found
    ):
        """Test endpoint avec auth valide."""
        with patch("app.services.docuseal_service.supabase") as mock_db, \
             patch("app.services.docuseal_service.httpx.AsyncClient") as mock_http, \
             patch("app.services.email_service.SendGridAPIClient"):

            # Mock recherche devis
            mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [mock_devis_found]

            # Mock telechargement PDF
            mock_response = MagicMock()
            mock_response.content = b"%PDF-1.4 fake pdf content"
            mock_response.raise_for_status = MagicMock()
            mock_http.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

            # Mock upload storage
            mock_db.storage.from_.return_value.upload.return_value = {"path": "test.pdf"}

            # Mock update devis
            mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [mock_devis_found]

            response = test_client.post(
                "/api/v1/docuseal/webhook/test",
                json=sample_docuseal_payload,
                headers=valid_webhook_headers
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"


# === Tests Service DocuSeal ===

class TestDocuSealService:
    """Tests du service DocuSeal."""

    @pytest.mark.asyncio
    async def test_find_devis_by_email(self, mock_devis_found):
        """Test recherche devis par email."""
        from app.services.docuseal_service import DocuSealService

        service = DocuSealService()

        with patch("app.services.docuseal_service.supabase") as mock_db:
            mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [mock_devis_found]

            devis = await service._find_devis("client@example.com", None)

            assert devis is not None
            assert devis["id"] == "devis-uuid-789"

    @pytest.mark.asyncio
    async def test_find_devis_not_found(self):
        """Test devis non trouve."""
        from app.services.docuseal_service import DocuSealService

        service = DocuSealService()

        with patch("app.services.docuseal_service.supabase") as mock_db:
            mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = []

            devis = await service._find_devis("unknown@example.com", None)

            assert devis is None

    @pytest.mark.asyncio
    async def test_download_signed_pdf(self):
        """Test telechargement PDF signe."""
        from app.services.docuseal_service import DocuSealService

        service = DocuSealService()

        with patch("app.services.docuseal_service.httpx.AsyncClient") as mock_http:
            mock_response = MagicMock()
            mock_response.content = b"%PDF-1.4 test content"
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_http.return_value.__aenter__.return_value = mock_client

            pdf_bytes, filename = await service._download_signed_pdf(
                "https://example.com/signed.pdf",
                "devis-123"
            )

            assert pdf_bytes == b"%PDF-1.4 test content"
            assert "devis-signe" in filename
            assert filename.endswith(".pdf")

    @pytest.mark.asyncio
    async def test_upload_to_storage(self):
        """Test upload vers Supabase Storage."""
        from app.services.docuseal_service import DocuSealService

        service = DocuSealService()

        with patch("app.services.docuseal_service.supabase") as mock_db, \
             patch("app.services.docuseal_service.settings") as mock_settings:

            mock_settings.supabase_url = "https://test.supabase.co"
            mock_db.storage.from_.return_value.upload.return_value = {"path": "test.pdf"}

            url = await service._upload_to_storage(
                pdf_bytes=b"%PDF-1.4 content",
                devis_id="devis-123",
                filename="test.pdf"
            )

            assert "devis_signes" in url
            assert "devis-123" in url


# === Tests Response Models ===

class TestDocuSealResponseModels:
    """Tests des modeles de reponse."""

    def test_success_response(self):
        """Test creation reponse succes."""
        from app.models.docuseal import DocuSealWebhookResponse

        response = DocuSealWebhookResponse.success(
            devis_id="devis-123",
            new_pdf_url="https://storage.example.com/signed.pdf"
        )

        assert response.status == "success"
        assert response.devis_id == "devis-123"
        assert response.new_pdf_url == "https://storage.example.com/signed.pdf"

    def test_ignored_response(self):
        """Test creation reponse ignore."""
        from app.models.docuseal import DocuSealWebhookResponse

        response = DocuSealWebhookResponse.ignored("Event type not supported")

        assert response.status == "ignored"
        assert "not supported" in response.message

    def test_error_response(self):
        """Test creation reponse erreur."""
        from app.models.docuseal import DocuSealWebhookResponse

        response = DocuSealWebhookResponse.error("Devis not found")

        assert response.status == "error"
        assert response.message == "Devis not found"


# === Tests Submission Create ===

class TestDocuSealSubmissionCreate:
    """Tests du modele de creation de submission."""

    def test_create_submission_for_devis(self):
        """Test creation submission pour devis."""
        from app.models.docuseal import DocuSealSubmissionCreate

        submission = DocuSealSubmissionCreate.for_devis(
            template_id=100,
            client_email="client@example.com",
            client_name="Jean Dupont",
            client_phone="+33612345678",
            devis_fields={
                "numero": "DEV-2024-001",
                "montant": "15000"
            }
        )

        assert submission.template_id == 100
        assert submission.send_email is True
        assert len(submission.submitters) == 1
        assert submission.submitters[0]["email"] == "client@example.com"
        assert submission.submitters[0]["phone"] == "+33612345678"
        assert len(submission.fields) == 2

    def test_create_submission_without_phone(self):
        """Test creation sans telephone."""
        from app.models.docuseal import DocuSealSubmissionCreate

        submission = DocuSealSubmissionCreate.for_devis(
            template_id=100,
            client_email="client@example.com",
            client_name="Jean Dupont"
        )

        assert "phone" not in submission.submitters[0]


# === Tests Get Submission ===

class TestGetSubmission:
    """Tests de recuperation de submission."""

    def test_get_submission_requires_auth(self, test_client: TestClient):
        """Test que get submission requiert auth."""
        response = test_client.get("/api/v1/docuseal/submission/12345")

        assert response.status_code == 401

    def test_get_submission_with_auth(
        self,
        test_client: TestClient,
        valid_webhook_headers
    ):
        """Test get submission avec auth."""
        with patch("app.services.docuseal_service.httpx.AsyncClient") as mock_http:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "id": 12345,
                "status": "completed"
            }
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_http.return_value.__aenter__.return_value = mock_client

            response = test_client.get(
                "/api/v1/docuseal/submission/12345",
                headers=valid_webhook_headers
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
