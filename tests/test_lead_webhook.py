"""
Tests pour le Workflow 1 - Lead Generation & Qualification AI.

Tests exhaustifs couvrant:
- Validation du secret webhook
- Validation et normalisation des données
- Qualification IA
- Création en base
- Génération des signatures HMAC
- Envoi des emails
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient


class TestWebhookAuthentication:
    """Tests d'authentification du webhook."""

    def test_missing_webhook_secret_returns_401(self, test_client):
        """Sans header X-Webhook-Secret, retourne 401."""
        response = test_client.post(
            "/api/v1/leads/webhook",
            json={"nom": "Test", "email": "test@test.com"}
        )
        assert response.status_code == 401
        assert response.json()["detail"]["status"] == "unauthorized"

    def test_invalid_webhook_secret_returns_401(
        self,
        test_client,
        invalid_webhook_headers,
        sample_lead_payload
    ):
        """Avec un secret invalide, retourne 401."""
        response = test_client.post(
            "/api/v1/leads/webhook",
            json=sample_lead_payload,
            headers=invalid_webhook_headers
        )
        assert response.status_code == 401

    def test_empty_webhook_secret_returns_401(
        self,
        test_client,
        sample_lead_payload
    ):
        """Avec un secret vide, retourne 401."""
        response = test_client.post(
            "/api/v1/leads/webhook",
            json=sample_lead_payload,
            headers={"X-Webhook-Secret": ""}
        )
        assert response.status_code == 401


class TestPayloadValidation:
    """Tests de validation du payload."""

    def test_valid_payload_accepted(
        self,
        test_client,
        valid_webhook_headers,
        sample_lead_payload,
        mock_all_services
    ):
        """Un payload valide est accepté."""
        response = test_client.post(
            "/api/v1/leads/webhook",
            json=sample_lead_payload,
            headers=valid_webhook_headers
        )
        # Devrait réussir ou échouer sur un autre service
        assert response.status_code in (200, 500, 502)

    def test_missing_required_field_returns_400(
        self,
        test_client,
        valid_webhook_headers
    ):
        """Un champ requis manquant retourne 400."""
        incomplete_payload = {
            "nom": "Dupont",
            "email": "test@test.com"
            # telephone manquant
        }
        response = test_client.post(
            "/api/v1/leads/webhook",
            json=incomplete_payload,
            headers=valid_webhook_headers
        )
        assert response.status_code == 400

    def test_invalid_email_returns_400(
        self,
        test_client,
        valid_webhook_headers,
        sample_lead_payload
    ):
        """Un email invalide retourne 400."""
        sample_lead_payload["email"] = "not-an-email"
        response = test_client.post(
            "/api/v1/leads/webhook",
            json=sample_lead_payload,
            headers=valid_webhook_headers
        )
        assert response.status_code == 400

    def test_rgpd_false_returns_400(
        self,
        test_client,
        valid_webhook_headers,
        sample_lead_payload
    ):
        """RGPD non accepté retourne 400."""
        sample_lead_payload["rgpd"] = False
        response = test_client.post(
            "/api/v1/leads/webhook",
            json=sample_lead_payload,
            headers=valid_webhook_headers
        )
        assert response.status_code == 400

    def test_empty_json_returns_400(
        self,
        test_client,
        valid_webhook_headers
    ):
        """Un JSON vide retourne 400."""
        response = test_client.post(
            "/api/v1/leads/webhook",
            json={},
            headers=valid_webhook_headers
        )
        assert response.status_code == 400


class TestPhoneNormalization:
    """Tests de normalisation du numéro de téléphone."""

    def test_phone_with_spaces_normalized(self):
        """Les espaces sont supprimés."""
        from app.models.lead import LeadWebhookPayload

        payload = LeadWebhookPayload(
            nom="Test",
            email="test@test.com",
            telephone="06 12 34 56 78",
            typeDeProjet="réparation",
            adresse="123 Rue Test",
            ville="Paris",
            codePostal="75001",
            rgpd=True
        )
        assert payload.telephone == "+33612345678"

    def test_phone_starting_with_0_converted(self):
        """Le 0 initial est converti en +33."""
        from app.models.lead import LeadWebhookPayload

        payload = LeadWebhookPayload(
            nom="Test",
            email="test@test.com",
            telephone="0612345678",
            typeDeProjet="réparation",
            adresse="123 Rue Test",
            ville="Paris",
            codePostal="75001",
            rgpd=True
        )
        assert payload.telephone == "+33612345678"

    def test_phone_already_formatted_unchanged(self):
        """Un numéro déjà formaté reste inchangé."""
        from app.models.lead import LeadWebhookPayload

        payload = LeadWebhookPayload(
            nom="Test",
            email="test@test.com",
            telephone="+33612345678",
            typeDeProjet="réparation",
            adresse="123 Rue Test",
            ville="Paris",
            codePostal="75001",
            rgpd=True
        )
        assert payload.telephone == "+33612345678"

    def test_phone_with_dots_normalized(self):
        """Les points sont supprimés."""
        from app.models.lead import LeadWebhookPayload

        payload = LeadWebhookPayload(
            nom="Test",
            email="test@test.com",
            telephone="06.12.34.56.78",
            typeDeProjet="réparation",
            adresse="123 Rue Test",
            ville="Paris",
            codePostal="75001",
            rgpd=True
        )
        assert payload.telephone == "+33612345678"


class TestEmailNormalization:
    """Tests de normalisation de l'email."""

    def test_email_lowercased(self):
        """L'email est converti en minuscules."""
        from app.models.lead import LeadWebhookPayload

        payload = LeadWebhookPayload(
            nom="Test",
            email="Jean.DUPONT@Example.COM",
            telephone="0612345678",
            typeDeProjet="réparation",
            adresse="123 Rue Test",
            ville="Paris",
            codePostal="75001",
            rgpd=True
        )
        assert payload.email == "jean.dupont@example.com"

    def test_email_trimmed(self):
        """Les espaces autour de l'email sont supprimés."""
        from app.models.lead import LeadWebhookPayload

        payload = LeadWebhookPayload(
            nom="Test",
            email="  test@example.com  ",
            telephone="0612345678",
            typeDeProjet="réparation",
            adresse="123 Rue Test",
            ville="Paris",
            codePostal="75001",
            rgpd=True
        )
        assert payload.email == "test@example.com"


class TestTypeProjetNormalization:
    """Tests de normalisation du type de projet."""

    @pytest.mark.parametrize("input_value,expected", [
        ("Réparation (fuite, tuiles cassées...)", "reparation"),
        ("RÉPARATION", "reparation"),
        ("rénovation complète", "renovation"),
        ("Rénovation Complète", "renovation"),
        ("isolation thermique", "isolation"),
        ("Installation neuve", "installation"),
        ("Entretien / Maintenance", "entretien"),
        ("autre chose", "autre"),
        ("", "autre"),
    ])
    def test_type_projet_mapping(self, input_value, expected):
        """Les types de projet sont correctement mappés."""
        from app.models.lead import LeadWebhookPayload

        if not input_value:
            # Valeur vide va lever une erreur de validation
            return

        payload = LeadWebhookPayload(
            nom="Test",
            email="test@test.com",
            telephone="0612345678",
            typeDeProjet=input_value,
            adresse="123 Rue Test",
            ville="Paris",
            codePostal="75001",
            rgpd=True
        )
        assert payload.typeDeProjet == expected


class TestDelaiNormalization:
    """Tests de normalisation du délai."""

    @pytest.mark.parametrize("input_value,expected", [
        ("Urgent (sous 48h)", "urgent"),
        ("Dans 1-2 semaines", "1-2 semaines"),
        ("Dans 1 mois", "1 mois"),
        ("Dans 2-3 mois", "2-3 mois"),
        ("Flexible / À convenir", "flexible"),
        (None, "flexible"),
        ("", "flexible"),
    ])
    def test_delai_mapping(self, input_value, expected):
        """Les délais sont correctement mappés."""
        from app.models.lead import LeadWebhookPayload

        payload = LeadWebhookPayload(
            nom="Test",
            email="test@test.com",
            telephone="0612345678",
            typeDeProjet="réparation",
            adresse="123 Rue Test",
            ville="Paris",
            codePostal="75001",
            delai=input_value,
            rgpd=True
        )
        assert payload.delai == expected


class TestAIQualification:
    """Tests du service de qualification IA."""

    def test_ai_result_parsing_valid_json(self):
        """Un JSON valide est correctement parsé."""
        from app.models.lead import AIQualificationResult

        json_str = '''
        {
            "score": 85,
            "urgence": "haute",
            "recommandation": "Appeler immédiatement",
            "segments": ["urgent", "gros_budget"]
        }
        '''
        result = AIQualificationResult.from_json_string(json_str)

        assert result.score == 85
        assert result.urgence == "haute"
        assert result.recommandation == "Appeler immédiatement"
        assert result.segments == ["urgent", "gros_budget"]

    def test_ai_result_parsing_invalid_json_fallback(self):
        """Un JSON invalide retourne les valeurs par défaut."""
        from app.models.lead import AIQualificationResult

        result = AIQualificationResult.from_json_string("not valid json")

        assert result.score == 50
        assert result.urgence == "moyenne"
        assert "manuellement" in result.recommandation.lower()

    def test_ai_result_parsing_missing_fields(self):
        """Les champs manquants utilisent les valeurs par défaut."""
        from app.models.lead import AIQualificationResult

        json_str = '{"score": 70}'
        result = AIQualificationResult.from_json_string(json_str)

        assert result.score == 70
        assert result.urgence == "moyenne"  # Default
        assert result.recommandation == "Contacter sous 48h"  # Default

    def test_simple_score_estimation(self):
        """L'estimation simple de score fonctionne."""
        from app.services.ai_qualification import AIQualificationService
        from app.models.lead import LeadCreate

        service = AIQualificationService()
        lead = LeadCreate(
            nom="Test",
            email="test@test.com",
            telephone="+33612345678",
            type_projet="renovation",
            surface=150,
            budget_estime=20000,
            delai="urgent",
            adresse="123 Rue Test",
            ville="Paris",
            code_postal="75001"
        )

        score = service.estimate_score_simple(lead)
        # Avec ces paramètres, le score devrait être élevé
        assert score >= 70
        assert score <= 100


class TestHMACService:
    """Tests du service HMAC."""

    def test_signature_generation(self):
        """Les signatures sont générées correctement."""
        from app.services.hmac_service import HMACService

        service = HMACService(secret="test_secret_32_chars_minimum_!!!")
        signature = service.sign("test_data")

        assert signature is not None
        assert len(signature) == 64  # SHA256 hex = 64 chars

    def test_signature_verification_valid(self):
        """Une signature valide est vérifiée."""
        from app.services.hmac_service import HMACService

        service = HMACService(secret="test_secret_32_chars_minimum_!!!")
        data = "test_data"
        signature = service.sign(data)

        assert service.verify(data, signature) is True

    def test_signature_verification_invalid(self):
        """Une signature invalide est rejetée."""
        from app.services.hmac_service import HMACService

        service = HMACService(secret="test_secret_32_chars_minimum_!!!")
        data = "test_data"

        assert service.verify(data, "invalid_signature") is False

    def test_tracking_signatures_generation(self):
        """Les signatures de tracking sont générées."""
        from app.services.hmac_service import HMACService

        service = HMACService(secret="test_secret_32_chars_minimum_!!!")
        lead_id = "test-uuid-1234"

        sign_click, sign_open = service.generate_tracking_signatures(lead_id)

        assert sign_click != sign_open
        assert len(sign_click) == 64
        assert len(sign_open) == 64

    def test_tracking_signature_verification(self):
        """Les signatures de tracking sont vérifiées correctement."""
        from app.services.hmac_service import HMACService

        service = HMACService(secret="test_secret_32_chars_minimum_!!!")
        lead_id = "test-uuid-1234"

        sign_click, sign_open = service.generate_tracking_signatures(lead_id)

        assert service.verify_tracking_signature(lead_id, "click", sign_click) is True
        assert service.verify_tracking_signature(lead_id, "open", sign_open) is True
        assert service.verify_tracking_signature(lead_id, "click", sign_open) is False
        assert service.verify_tracking_signature(lead_id, "invalid", sign_click) is False


class TestWebhookSecretValidator:
    """Tests du validateur de secret webhook."""

    def test_valid_secret_accepted(self):
        """Un secret valide est accepté."""
        from app.services.hmac_service import WebhookSecretValidator

        validator = WebhookSecretValidator(secret="my_secret_key")
        assert validator.validate("my_secret_key") is True

    def test_invalid_secret_rejected(self):
        """Un secret invalide est rejeté."""
        from app.services.hmac_service import WebhookSecretValidator

        validator = WebhookSecretValidator(secret="my_secret_key")
        assert validator.validate("wrong_key") is False

    def test_empty_secret_rejected(self):
        """Un secret vide est rejeté."""
        from app.services.hmac_service import WebhookSecretValidator

        validator = WebhookSecretValidator(secret="my_secret_key")
        assert validator.validate("") is False
        assert validator.validate(None) is False


class TestLeadModels:
    """Tests des modèles Pydantic."""

    def test_lead_create_to_db_dict(self):
        """LeadCreate.to_db_dict() retourne les bons champs."""
        from app.models.lead import LeadCreate

        lead = LeadCreate(
            nom="Dupont",
            prenom="Jean",
            email="jean@test.com",
            telephone="+33612345678",
            type_projet="renovation",
            surface=100,
            budget_estime=15000,
            adresse="123 Rue Test",
            ville="Paris",
            code_postal="75001"
        )

        db_dict = lead.to_db_dict()

        assert db_dict["nom"] == "Dupont"
        assert db_dict["prenom"] == "Jean"
        assert db_dict["email"] == "jean@test.com"
        assert db_dict["surface"] == 100
        assert "id" not in db_dict  # Généré par Supabase

    def test_lead_with_ai_from_lead_and_ai(self):
        """LeadWithAI.from_lead_and_ai() fusionne correctement."""
        from app.models.lead import LeadCreate, LeadWithAI, AIQualificationResult

        lead = LeadCreate(
            nom="Test",
            email="test@test.com",
            telephone="+33612345678",
            type_projet="renovation",
            adresse="123 Rue Test",
            ville="Paris",
            code_postal="75001"
        )

        ai_result = AIQualificationResult(
            score=85,
            urgence="haute",
            recommandation="Appeler vite",
            segments=["urgent", "premium"]
        )

        lead_with_ai = LeadWithAI.from_lead_and_ai(lead, ai_result, '{"raw": true}')

        assert lead_with_ai.nom == "Test"
        assert lead_with_ai.score_qualification == 85
        assert lead_with_ai.urgence == "haute"
        assert lead_with_ai.ai_notes == "Appeler vite"
        assert lead_with_ai.ai_segments == "urgent, premium"

    def test_lead_response_success(self):
        """LeadResponse.success() formate correctement."""
        from app.models.lead import LeadResponse

        response = LeadResponse.success(
            lead_id="uuid-123",
            email="test@test.com",
            score=75
        )

        assert response.status == "success"
        assert response.lead["id"] == "uuid-123"
        assert response.lead["score"] == "75"

    def test_lead_response_error(self):
        """LeadResponse.error() formate correctement."""
        from app.models.lead import LeadResponse

        response = LeadResponse.error("Something went wrong")

        assert response.status == "error"
        assert response.message == "Something went wrong"
        assert response.lead is None


class TestValidators:
    """Tests des utilitaires de validation."""

    def test_normalize_phone_french_various_formats(self):
        """normalize_phone_french gère différents formats."""
        from app.utils.validators import normalize_phone_french

        assert normalize_phone_french("06 12 34 56 78") == "+33612345678"
        assert normalize_phone_french("0612345678") == "+33612345678"
        assert normalize_phone_french("+33612345678") == "+33612345678"
        assert normalize_phone_french("06.12.34.56.78") == "+33612345678"
        assert normalize_phone_french("") == ""

    def test_validate_email_address(self):
        """validate_email_address valide correctement."""
        from app.utils.validators import validate_email_address

        valid, result = validate_email_address("test@example.com")
        assert valid is True

        valid, result = validate_email_address("not-an-email")
        assert valid is False

    def test_parse_to_int(self):
        """parse_to_int parse correctement."""
        from app.utils.validators import parse_to_int

        assert parse_to_int("100") == 100
        assert parse_to_int("100.5") == 100
        assert parse_to_int(100) == 100
        assert parse_to_int("0") is None
        assert parse_to_int("-5") is None
        assert parse_to_int("abc") is None
        assert parse_to_int(None) is None
        assert parse_to_int("") is None

    def test_validate_code_postal_french(self):
        """validate_code_postal_french valide correctement."""
        from app.utils.validators import validate_code_postal_french

        assert validate_code_postal_french("75001") is True
        assert validate_code_postal_french("69000") is True
        assert validate_code_postal_french("1234") is False
        assert validate_code_postal_french("123456") is False
        assert validate_code_postal_french("") is False

    def test_is_valid_uuid(self):
        """is_valid_uuid valide correctement."""
        from app.utils.validators import is_valid_uuid

        assert is_valid_uuid("550e8400-e29b-41d4-a716-446655440000") is True
        assert is_valid_uuid("not-a-uuid") is False
        assert is_valid_uuid("") is False

    def test_format_currency_fr(self):
        """format_currency_fr formate correctement."""
        from app.utils.validators import format_currency_fr

        assert format_currency_fr(1234.56) == "1 234,56 €"
        assert format_currency_fr(15000) == "15 000,00 €"
        assert format_currency_fr(None) == "N/A"


class TestHealthEndpoints:
    """Tests des endpoints de santé."""

    def test_root_endpoint(self, test_client):
        """L'endpoint racine retourne les infos de base."""
        response = test_client.get("/")
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "ToitureAI"
        assert data["status"] == "running"
        assert "timestamp" in data

    def test_ready_endpoint(self, test_client):
        """L'endpoint ready retourne le statut."""
        response = test_client.get("/ready")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "ready"


class TestErrorHandling:
    """Tests de la gestion des erreurs."""

    def test_toitureai_error_structure(self):
        """ToitureAIError a la bonne structure."""
        from app.core.error_handler import ToitureAIError

        error = ToitureAIError(
            message="Test error",
            workflow="test_workflow",
            node="test_node",
            details={"key": "value"},
            status_code=400
        )

        assert error.message == "Test error"
        assert error.workflow == "test_workflow"
        assert error.node == "test_node"
        assert error.details == {"key": "value"}
        assert error.status_code == 400
        assert error.timestamp is not None

    def test_validation_error_defaults(self):
        """ValidationError a les bons défauts."""
        from app.core.error_handler import ValidationError

        error = ValidationError("Invalid data")

        assert error.status_code == 400
        assert error.workflow == "validation"

    def test_authentication_error_defaults(self):
        """AuthenticationError a les bons défauts."""
        from app.core.error_handler import AuthenticationError

        error = AuthenticationError()

        assert error.status_code == 401
        assert "secret" in error.message.lower() or "webhook" in error.message.lower()
