"""
Configuration et fixtures pytest pour ToitureAI.

Fournit des fixtures réutilisables pour tous les tests.
"""

import os
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Generator, Dict, Any

from fastapi.testclient import TestClient


# Configuration des variables d'environnement pour les tests
os.environ.setdefault("WEBHOOK_SECRET", "test_webhook_secret_at_least_32_chars_long")
os.environ.setdefault("TRACKING_SECRET", "test_tracking_secret_at_least_32_chars")
os.environ.setdefault("SUPABASE_URL", "https://test-project.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test_supabase_anon_key_for_testing")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-openai-key-for-testing")
os.environ.setdefault("SENDGRID_API_KEY", "SG.test_sendgrid_key_for_testing")
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DEBUG", "true")


@pytest.fixture(scope="session")
def test_settings():
    """Fixture pour accéder aux settings de test."""
    from app.core.config import Settings
    return Settings()


@pytest.fixture
def test_client() -> Generator[TestClient, None, None]:
    """
    Fixture pour le client de test FastAPI.

    Crée un client HTTP pour tester les endpoints.
    """
    from app.main import app
    with TestClient(app) as client:
        yield client


@pytest.fixture
def valid_webhook_headers() -> Dict[str, str]:
    """Headers valides pour les requêtes webhook."""
    return {
        "X-Webhook-Secret": os.environ["WEBHOOK_SECRET"],
        "Content-Type": "application/json",
        "User-Agent": "TestClient/1.0"
    }


@pytest.fixture
def invalid_webhook_headers() -> Dict[str, str]:
    """Headers avec secret invalide."""
    return {
        "X-Webhook-Secret": "invalid_secret",
        "Content-Type": "application/json"
    }


@pytest.fixture
def sample_lead_payload() -> Dict[str, Any]:
    """Payload de lead valide pour les tests."""
    return {
        "nom": "Dupont",
        "prenom": "Jean",
        "email": "jean.dupont@example.com",
        "telephone": "06 12 34 56 78",
        "typeDeProjet": "Rénovation complète",
        "adresse": "123 Rue de la Paix",
        "ville": "Paris",
        "codePostal": "75001",
        "surface": "120",
        "budget": "15000",
        "delai": "1-2 semaines",
        "description": "Rénovation complète de la toiture avec isolation.",
        "rgpd": True,
        "source": "landing-page-test",
        "timestamp": "2024-01-15T10:30:00Z"
    }


@pytest.fixture
def sample_lead_minimal_payload() -> Dict[str, Any]:
    """Payload minimal valide (champs obligatoires uniquement)."""
    return {
        "nom": "Martin",
        "email": "martin@test.fr",
        "telephone": "0612345678",
        "typeDeProjet": "Réparation",
        "adresse": "45 Avenue Test",
        "ville": "Lyon",
        "codePostal": "69001",
        "rgpd": True
    }


@pytest.fixture
def sample_lead_invalid_payload() -> Dict[str, Any]:
    """Payload invalide pour tester la validation."""
    return {
        "nom": "A",  # Trop court
        "email": "invalid-email",  # Email invalide
        "telephone": "123",  # Trop court
        "typeDeProjet": "",  # Vide
        "adresse": "AB",  # Trop court
        "ville": "X",  # Trop court
        "codePostal": "123",  # Trop court
        "rgpd": False  # Doit être True
    }


@pytest.fixture
def mock_supabase():
    """
    Mock du client Supabase.

    Simule les opérations de base de données.
    """
    mock = MagicMock()

    # Mock pour insert
    mock_insert_response = MagicMock()
    mock_insert_response.data = [{
        "id": "test-uuid-1234-5678-9012",
        "nom": "Dupont",
        "prenom": "Jean",
        "email": "jean.dupont@example.com",
        "telephone": "+33612345678",
        "type_projet": "renovation",
        "score_qualification": 75,
        "urgence": "moyenne",
        "created_at": "2024-01-15T10:30:00Z"
    }]
    mock.table.return_value.insert.return_value.execute.return_value = mock_insert_response

    # Mock pour select
    mock_select_response = MagicMock()
    mock_select_response.data = mock_insert_response.data
    mock.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_select_response

    return mock


@pytest.fixture
def mock_openai():
    """
    Mock du client OpenAI.

    Simule les réponses de GPT-4o-mini.
    """
    mock = MagicMock()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '''
    {
        "score": 75,
        "urgence": "moyenne",
        "recommandation": "Contacter sous 48h, potentiel élevé",
        "segments": ["particulier", "budget_moyen", "renovation_complete"]
    }
    '''

    mock.chat.completions.create.return_value = mock_response

    return mock


@pytest.fixture
def mock_sendgrid():
    """
    Mock du client SendGrid.

    Simule l'envoi d'emails.
    """
    mock = MagicMock()

    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.headers = {"X-Message-Id": "test-message-id-123"}

    mock.send.return_value = mock_response

    return mock


@pytest.fixture
def mock_all_services(mock_supabase, mock_openai, mock_sendgrid):
    """
    Mock tous les services externes.

    Utilise ce fixture pour des tests d'intégration isolés.
    """
    with patch("app.core.database.supabase", mock_supabase), \
         patch("app.services.ai_qualification.OpenAI", return_value=mock_openai), \
         patch("app.services.email_service.SendGridAPIClient", return_value=mock_sendgrid):
        yield {
            "supabase": mock_supabase,
            "openai": mock_openai,
            "sendgrid": mock_sendgrid
        }


@pytest.fixture
def created_lead_data() -> Dict[str, Any]:
    """Données d'un lead créé en base pour les tests."""
    return {
        "id": "test-uuid-1234-5678-9012",
        "nom": "Dupont",
        "prenom": "Jean",
        "email": "jean.dupont@example.com",
        "telephone": "+33612345678",
        "type_projet": "renovation",
        "surface": 120,
        "budget_estime": 15000,
        "delai": "1-2 semaines",
        "description": "Rénovation complète de la toiture",
        "adresse": "123 Rue de la Paix",
        "ville": "Paris",
        "code_postal": "75001",
        "source": "landing-page-test",
        "statut": "nouveau",
        "score_qualification": 75,
        "urgence": "moyenne",
        "ai_notes": "Contacter sous 48h",
        "ai_segments": "particulier, budget_moyen",
        "ai_raw": '{"score": 75, "urgence": "moyenne"}',
        "created_at": "2024-01-15T10:30:00Z",
        "email_ouvert": False,
        "email_ouvert_count": 0,
        "email_clic_count": 0,
        "lead_chaud": False
    }


# === Markers personnalisés ===

def pytest_configure(config):
    """Configuration des markers pytest."""
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow running"
    )
    config.addinivalue_line(
        "markers", "security: marks tests as security-related"
    )
