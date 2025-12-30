"""
Tests pour le Workflow 3: Rapport Mensuel PDF.

Teste:
- Calcul des KPIs (leads, devis, financier)
- Generation du PDF
- Scheduler APScheduler
- Endpoints API rapport
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, date, timezone
from decimal import Decimal

from fastapi.testclient import TestClient


# === Fixtures specifiques Rapport ===

@pytest.fixture
def sample_leads_data():
    """Donnees de leads pour le rapport."""
    return [
        {
            "id": "lead-1",
            "prenom": "Jean",
            "nom": "Dupont",
            "email": "jean@example.com",
            "telephone": "+33612345678",
            "ville": "Paris",
            "type_travaux": "Renovation",
            "statut": "gagne",
            "score": 85,
            "created_at": "2024-01-10T10:00:00Z"
        },
        {
            "id": "lead-2",
            "prenom": "Marie",
            "nom": "Martin",
            "email": "marie@example.com",
            "telephone": "+33687654321",
            "ville": "Lyon",
            "type_travaux": "Reparation",
            "statut": "perdu",
            "score": 45,
            "created_at": "2024-01-15T14:00:00Z"
        },
        {
            "id": "lead-3",
            "prenom": "Pierre",
            "nom": "Durand",
            "email": "pierre@example.com",
            "telephone": "+33698765432",
            "ville": "Marseille",
            "type_travaux": "Neuf",
            "statut": "nouveau",
            "score": 70,
            "created_at": "2024-01-20T09:00:00Z"
        }
    ]


@pytest.fixture
def sample_devis_data():
    """Donnees de devis pour le rapport."""
    return [
        {
            "id": "devis-1",
            "numero": "DEV-2024-001",
            "client_email": "jean@example.com",
            "client_prenom": "Jean",
            "client_nom": "Dupont",
            "client_ville": "Paris",
            "total_ttc": 15000.00,
            "statut": "signe",
            "created_at": "2024-01-12T11:00:00Z",
            "date_signature": "2024-01-14T16:00:00Z"
        },
        {
            "id": "devis-2",
            "numero": "DEV-2024-002",
            "client_email": "jean@example.com",
            "client_prenom": "Jean",
            "client_nom": "Dupont",
            "client_ville": "Paris",
            "total_ttc": 8000.00,
            "statut": "paye",
            "created_at": "2024-01-18T10:00:00Z",
            "date_signature": "2024-01-19T14:00:00Z"
        },
        {
            "id": "devis-3",
            "numero": "DEV-2024-003",
            "client_email": "marie@example.com",
            "client_prenom": "Marie",
            "client_nom": "Martin",
            "client_ville": "Lyon",
            "total_ttc": 5000.00,
            "statut": "envoye",
            "created_at": "2024-01-22T09:00:00Z",
            "date_signature": None
        }
    ]


@pytest.fixture
def mock_rapport_db_response():
    """Reponse mock pour insertion rapport en DB."""
    return {
        "id": "rapport-uuid-123",
        "mois": 1,
        "annee": 2024,
        "url_pdf": "https://storage.example.com/rapports/2024/rapport-2024-01.pdf",
        "created_at": "2024-02-01T08:00:00Z"
    }


# === Tests Modeles KPIs ===

class TestLeadKPIs:
    """Tests des KPIs leads."""

    def test_lead_kpis_calculation(self):
        """Test calcul KPIs leads."""
        from app.models.rapport import LeadKPIs

        kpis = LeadKPIs(total=10, gagnes=3, perdus=2, en_cours=5)

        assert kpis.taux_conversion == 30.0  # 3/10 * 100
        assert kpis.taux_perte == 20.0  # 2/10 * 100

    def test_lead_kpis_zero_total(self):
        """Test KPIs avec zero leads."""
        from app.models.rapport import LeadKPIs

        kpis = LeadKPIs(total=0, gagnes=0, perdus=0, en_cours=0)

        assert kpis.taux_conversion == 0.0
        assert kpis.taux_perte == 0.0

    def test_lead_kpis_defaults(self):
        """Test valeurs par defaut."""
        from app.models.rapport import LeadKPIs

        kpis = LeadKPIs()

        assert kpis.total == 0
        assert kpis.gagnes == 0
        assert kpis.perdus == 0
        assert kpis.en_cours == 0


class TestDevisKPIs:
    """Tests des KPIs devis."""

    def test_devis_kpis_calculation(self):
        """Test calcul KPIs devis."""
        from app.models.rapport import DevisKPIs

        kpis = DevisKPIs(total=10, signes=5, payes=3, en_attente=4, refuses=1)

        assert kpis.taux_signature == 50.0  # 5/10 * 100
        assert kpis.taux_paiement == 60.0  # 3/5 * 100

    def test_devis_kpis_zero_signes(self):
        """Test taux paiement avec zero signes."""
        from app.models.rapport import DevisKPIs

        kpis = DevisKPIs(total=5, signes=0, payes=0, en_attente=5, refuses=0)

        assert kpis.taux_paiement == 0.0


class TestFinancialKPIs:
    """Tests des KPIs financiers."""

    def test_financial_kpis_formatting(self):
        """Test formatage des montants."""
        from app.models.rapport import FinancialKPIs

        kpis = FinancialKPIs(
            ca_mensuel=Decimal("15000.50"),
            ca_encaisse=Decimal("8000.00"),
            panier_moyen=Decimal("7500.25"),
            ca_potentiel=Decimal("5000.00")
        )

        assert "15" in kpis.ca_mensuel_formatted
        assert "EUR" in kpis.ca_mensuel_formatted


# === Tests Periode ===

class TestRapportPeriode:
    """Tests de la periode du rapport."""

    def test_periode_mois_nom(self):
        """Test nom du mois."""
        from app.models.rapport import RapportPeriode

        periode = RapportPeriode(
            mois=1,
            annee=2024,
            date_debut=date(2024, 1, 1),
            date_fin=date(2024, 1, 31)
        )

        assert periode.mois_nom == "Janvier"
        assert periode.titre == "Janvier 2024"

    def test_periode_formatted(self):
        """Test formatage de la periode."""
        from app.models.rapport import RapportPeriode

        periode = RapportPeriode(
            mois=12,
            annee=2024,
            date_debut=date(2024, 12, 1),
            date_fin=date(2024, 12, 31)
        )

        assert "01/12/2024" in periode.periode_formatted
        assert "31/12/2024" in periode.periode_formatted


# === Tests Service Rapport ===

class TestRapportService:
    """Tests du service de rapport."""

    def test_calculate_periode_previous_month(self):
        """Test calcul periode mois precedent."""
        from app.services.rapport_service import RapportService

        service = RapportService()

        with patch("app.services.rapport_service.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 2, 15, 10, 0, 0)

            periode = service._calculate_periode(None, None)

            assert periode.mois == 1
            assert periode.annee == 2024

    def test_calculate_periode_january_to_december(self):
        """Test passage janvier -> decembre annee precedente."""
        from app.services.rapport_service import RapportService

        service = RapportService()

        with patch("app.services.rapport_service.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 10, 10, 0, 0)

            periode = service._calculate_periode(None, None)

            assert periode.mois == 12
            assert periode.annee == 2023

    def test_calculate_periode_specific(self):
        """Test periode specifique."""
        from app.services.rapport_service import RapportService

        service = RapportService()
        periode = service._calculate_periode(6, 2024)

        assert periode.mois == 6
        assert periode.annee == 2024
        assert periode.date_debut == date(2024, 6, 1)
        assert periode.date_fin == date(2024, 6, 30)

    def test_calculate_lead_kpis(self, sample_leads_data):
        """Test calcul KPIs leads."""
        from app.services.rapport_service import RapportService

        service = RapportService()
        kpis = service._calculate_lead_kpis(sample_leads_data)

        assert kpis.total == 3
        assert kpis.gagnes == 1
        assert kpis.perdus == 1
        assert kpis.en_cours == 1

    def test_calculate_devis_kpis(self, sample_devis_data):
        """Test calcul KPIs devis."""
        from app.services.rapport_service import RapportService

        service = RapportService()
        kpis = service._calculate_devis_kpis(sample_devis_data)

        assert kpis.total == 3
        assert kpis.signes == 2  # signe + paye
        assert kpis.payes == 1
        assert kpis.en_attente == 1

    def test_calculate_financial_kpis(self, sample_devis_data):
        """Test calcul KPIs financiers."""
        from app.services.rapport_service import RapportService

        service = RapportService()
        kpis = service._calculate_financial_kpis(sample_devis_data)

        # CA = 15000 + 8000 = 23000 (signes + payes)
        assert kpis.ca_mensuel == Decimal("23000.00")
        # CA encaisse = 8000 (payes uniquement)
        assert kpis.ca_encaisse == Decimal("8000.00")
        # Panier moyen = 23000 / 2 = 11500
        assert kpis.panier_moyen == Decimal("11500.00")
        # CA potentiel = 5000 (en attente)
        assert kpis.ca_potentiel == Decimal("5000.00")

    def test_calculate_top_clients(self, sample_devis_data):
        """Test calcul top clients."""
        from app.services.rapport_service import RapportService

        service = RapportService()
        top_clients = service._calculate_top_clients(sample_devis_data, limit=5)

        assert len(top_clients) == 1  # Seul Jean Dupont a des devis signes
        assert top_clients[0].nom == "Jean Dupont"
        assert top_clients[0].nb_devis == 2
        assert top_clients[0].montant_total == Decimal("23000.00")


# === Tests API Endpoints ===

class TestRapportEndpoints:
    """Tests des endpoints API rapport."""

    def test_generate_rapport_requires_auth(self, test_client: TestClient):
        """Test que generation requiert auth."""
        response = test_client.post(
            "/api/v1/rapport/generate",
            json={"envoyer_email": False}
        )

        assert response.status_code == 401

    def test_generate_rapport_with_auth(
        self,
        test_client: TestClient,
        valid_webhook_headers,
        sample_leads_data,
        sample_devis_data,
        mock_rapport_db_response
    ):
        """Test generation rapport avec auth."""
        with patch("app.services.rapport_service.supabase") as mock_db, \
             patch("app.services.rapport_service.HTML") as mock_html:

            # Mock fetch leads
            mock_leads_response = MagicMock()
            mock_leads_response.data = sample_leads_data

            # Mock fetch devis
            mock_devis_response = MagicMock()
            mock_devis_response.data = sample_devis_data

            # Mock insert rapport
            mock_insert_response = MagicMock()
            mock_insert_response.data = [mock_rapport_db_response]

            # Configure les mocks
            mock_db.table.return_value.select.return_value.gte.return_value.lte.return_value.order.return_value.execute.side_effect = [
                mock_leads_response,
                mock_devis_response
            ]
            mock_db.table.return_value.insert.return_value.execute.return_value = mock_insert_response
            mock_db.storage.from_.return_value.upload.return_value = {"path": "test.pdf"}

            # Mock WeasyPrint
            mock_html.return_value.write_pdf.return_value = b"%PDF-1.4 test"

            response = test_client.post(
                "/api/v1/rapport/generate",
                json={"mois": 1, "annee": 2024, "envoyer_email": False},
                headers=valid_webhook_headers
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"

    def test_list_rapports_requires_auth(self, test_client: TestClient):
        """Test que liste requiert auth."""
        response = test_client.get("/api/v1/rapport")

        assert response.status_code == 401

    def test_list_rapports_with_auth(
        self,
        test_client: TestClient,
        valid_webhook_headers
    ):
        """Test liste rapports avec auth."""
        with patch("app.services.rapport_service.supabase") as mock_db:
            mock_db.table.return_value.select.return_value.order.return_value.order.return_value.limit.return_value.execute.return_value.data = [
                {"id": "1", "mois": 1, "annee": 2024},
                {"id": "2", "mois": 12, "annee": 2023}
            ]

            response = test_client.get(
                "/api/v1/rapport",
                headers=valid_webhook_headers
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert data["count"] == 2

    def test_get_rapport_not_found(
        self,
        test_client: TestClient,
        valid_webhook_headers
    ):
        """Test rapport non trouve."""
        with patch("app.services.rapport_service.supabase") as mock_db:
            mock_db.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = None

            response = test_client.get(
                "/api/v1/rapport/unknown-id",
                headers=valid_webhook_headers
            )

            assert response.status_code == 404

    def test_scheduler_status_endpoint(
        self,
        test_client: TestClient,
        valid_webhook_headers
    ):
        """Test endpoint statut scheduler."""
        response = test_client.get(
            "/api/v1/rapport/scheduler/status",
            headers=valid_webhook_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert "scheduler_running" in data
        assert "jobs" in data


# === Tests Scheduler ===

class TestSchedulerService:
    """Tests du service scheduler."""

    def test_scheduler_initialization(self):
        """Test initialisation scheduler."""
        from app.core.scheduler import SchedulerService

        scheduler = SchedulerService()

        assert scheduler._is_running is False
        assert scheduler.scheduler is not None

    def test_scheduler_list_jobs(self):
        """Test liste des jobs."""
        from app.core.scheduler import SchedulerService

        scheduler = SchedulerService()
        scheduler._register_jobs()

        jobs = scheduler.list_jobs()

        assert len(jobs) >= 1
        job_ids = [j["id"] for j in jobs]
        assert "monthly_report" in job_ids

    def test_scheduler_get_next_run_time(self):
        """Test prochaine execution."""
        from app.core.scheduler import SchedulerService

        scheduler = SchedulerService()
        scheduler._register_jobs()

        next_run = scheduler.get_next_run_time("monthly_report")

        assert next_run is not None
        assert next_run.day == 1  # 1er du mois
        assert next_run.hour == 8  # 8h


# === Tests Response Models ===

class TestRapportResponseModels:
    """Tests des modeles de reponse."""

    def test_success_response(self):
        """Test reponse succes."""
        from app.models.rapport import RapportResponse

        response = RapportResponse.success(
            rapport_id="rapport-123",
            pdf_url="https://storage.example.com/rapport.pdf",
            periode="Janvier 2024",
            email_envoye=True
        )

        assert response.status == "success"
        assert response.rapport_id == "rapport-123"
        assert response.email_envoye is True

    def test_error_response(self):
        """Test reponse erreur."""
        from app.models.rapport import RapportResponse

        response = RapportResponse.error("Generation failed")

        assert response.status == "error"
        assert response.message == "Generation failed"


# === Tests Generate Payload ===

class TestRapportGeneratePayload:
    """Tests du payload de generation."""

    def test_valid_payload(self):
        """Test payload valide."""
        from app.models.rapport import RapportGeneratePayload

        payload = RapportGeneratePayload(
            mois=6,
            annee=2024,
            envoyer_email=True,
            email_destinataire="admin@example.com"
        )

        assert payload.mois == 6
        assert payload.annee == 2024
        assert payload.envoyer_email is True

    def test_payload_defaults(self):
        """Test valeurs par defaut."""
        from app.models.rapport import RapportGeneratePayload

        payload = RapportGeneratePayload()

        assert payload.mois is None
        assert payload.annee is None
        assert payload.envoyer_email is True
        assert payload.email_destinataire is None

    def test_invalid_mois(self):
        """Test mois invalide."""
        from app.models.rapport import RapportGeneratePayload
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RapportGeneratePayload(mois=13)  # Mois > 12

        with pytest.raises(ValidationError):
            RapportGeneratePayload(mois=0)  # Mois < 1


# === Tests Preview Endpoint ===

class TestRapportPreview:
    """Tests de l'endpoint preview."""

    def test_preview_requires_auth(self, test_client: TestClient):
        """Test que preview requiert auth."""
        response = test_client.get("/api/v1/rapport/preview/1/2024")

        assert response.status_code == 401

    def test_preview_invalid_mois(
        self,
        test_client: TestClient,
        valid_webhook_headers
    ):
        """Test mois invalide."""
        response = test_client.get(
            "/api/v1/rapport/preview/13/2024",
            headers=valid_webhook_headers
        )

        assert response.status_code == 400

    def test_preview_with_data(
        self,
        test_client: TestClient,
        valid_webhook_headers,
        sample_leads_data,
        sample_devis_data
    ):
        """Test preview avec donnees."""
        with patch("app.services.rapport_service.supabase") as mock_db:
            mock_leads_response = MagicMock()
            mock_leads_response.data = sample_leads_data

            mock_devis_response = MagicMock()
            mock_devis_response.data = sample_devis_data

            mock_db.table.return_value.select.return_value.gte.return_value.lte.return_value.order.return_value.execute.side_effect = [
                mock_leads_response,
                mock_devis_response
            ]

            response = test_client.get(
                "/api/v1/rapport/preview/1/2024",
                headers=valid_webhook_headers
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "kpis" in data
            assert "leads" in data["kpis"]
            assert "devis" in data["kpis"]
            assert "financier" in data["kpis"]
