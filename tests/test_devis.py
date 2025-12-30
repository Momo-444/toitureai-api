"""
Tests pour le Workflow 2 - Devis & Facturation Automatique.

Teste:
- Modeles Pydantic (LigneDevis, DevisCreatePayload, etc.)
- Generation des lignes (custom, budget, OpenAI)
- Calculs (HT, TVA, TTC)
- Generation PDF (WeasyPrint)
- API endpoints
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.models.devis import (
    LigneDevis,
    DevisCreatePayload,
    DevisCalcule,
    DevisParams,
    AIDevisLignesResult,
    generate_devis_numero,
    ClientInfo,
)
from app.services.devis_service import (
    DevisLignesGenerator,
    DevisPDFGenerator,
)


# === Fixtures ===

@pytest.fixture
def test_client():
    """Client de test FastAPI."""
    return TestClient(app)


@pytest.fixture
def valid_webhook_headers():
    """Headers valides pour les webhooks."""
    return {"X-Webhook-Secret": settings.webhook_secret}


@pytest.fixture
def sample_lead():
    """Lead de test."""
    return {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "nom": "Dupont",
        "prenom": "Jean",
        "email": "jean.dupont@example.com",
        "telephone": "+33612345678",
        "adresse": "123 Rue de Paris",
        "ville": "Metz",
        "code_postal": "57000",
        "type_projet": "renovation",
        "surface": 120,
        "budget_estime": 15000,
        "description": "Renovation complete de la toiture",
    }


@pytest.fixture
def sample_ligne_devis():
    """Ligne de devis de test."""
    return LigneDevis(
        designation="Main d'oeuvre couvreur",
        quantite=120,
        unite="m2",
        prix_unitaire_ht=40.0
    )


@pytest.fixture
def sample_devis_payload(sample_lead):
    """Payload de creation de devis."""
    return DevisCreatePayload(
        lead_id=sample_lead["id"],
        budget_negocie=12000.0,
        params=DevisParams(tva=10.0, validite_jours=30)
    )


@pytest.fixture
def sample_custom_lignes():
    """Lignes custom pour devis."""
    return [
        LigneDevis(
            designation="Depose ancienne couverture",
            quantite=100,
            unite="m2",
            prix_unitaire_ht=15.0
        ),
        LigneDevis(
            designation="Pose nouvelles tuiles",
            quantite=100,
            unite="m2",
            prix_unitaire_ht=45.0
        ),
        LigneDevis(
            designation="Echafaudage",
            quantite=1,
            unite="forfait",
            prix_unitaire_ht=800.0
        ),
    ]


# === Tests des modeles ===

class TestLigneDevis:
    """Tests pour le modele LigneDevis."""

    def test_ligne_valid(self):
        """Test creation d'une ligne valide."""
        ligne = LigneDevis(
            designation="Test",
            quantite=10,
            unite="m2",
            prix_unitaire_ht=50.0
        )
        assert ligne.designation == "Test"
        assert ligne.quantite == 10
        assert ligne.total_ht == 500.0

    def test_ligne_total_calculation(self):
        """Test calcul du total HT."""
        ligne = LigneDevis(
            designation="Main d'oeuvre",
            quantite=25.5,
            unite="heure",
            prix_unitaire_ht=35.0
        )
        assert ligne.total_ht == 892.5  # 25.5 * 35

    def test_ligne_unite_normalization(self):
        """Test normalisation des unites."""
        ligne1 = LigneDevis(
            designation="Test",
            quantite=1,
            unite="m²",
            prix_unitaire_ht=10.0
        )
        assert ligne1.unite == "m2"

        ligne2 = LigneDevis(
            designation="Test",
            quantite=1,
            unite="Forfait",
            prix_unitaire_ht=10.0
        )
        assert ligne2.unite == "forfait"

    def test_ligne_quantite_negative_rejected(self):
        """Test rejet quantite negative."""
        with pytest.raises(Exception):
            LigneDevis(
                designation="Test",
                quantite=-5,
                unite="m2",
                prix_unitaire_ht=10.0
            )

    def test_ligne_prix_zero_rejected(self):
        """Test rejet prix zero."""
        with pytest.raises(Exception):
            LigneDevis(
                designation="Test",
                quantite=10,
                unite="m2",
                prix_unitaire_ht=0
            )


class TestDevisCalcule:
    """Tests pour les calculs de devis."""

    def test_calcul_totaux(self, sample_custom_lignes):
        """Test calcul automatique des totaux."""
        devis = DevisCalcule(
            lignes=sample_custom_lignes,
            tva_pourcent=10.0
        )

        # Total HT: 1500 + 4500 + 800 = 6800
        assert devis.total_ht == 6800.0
        # TVA 10%: 680
        assert devis.total_tva == 680.0
        # TTC: 7480
        assert devis.total_ttc == 7480.0

    def test_calcul_tva_20_pourcent(self, sample_custom_lignes):
        """Test avec TVA 20%."""
        devis = DevisCalcule(
            lignes=sample_custom_lignes,
            tva_pourcent=20.0
        )

        assert devis.total_ht == 6800.0
        assert devis.total_tva == 1360.0
        assert devis.total_ttc == 8160.0

    def test_devis_vide(self):
        """Test devis sans lignes."""
        devis = DevisCalcule(lignes=[])

        assert devis.total_ht == 0
        assert devis.total_tva == 0
        assert devis.total_ttc == 0


class TestDevisCreatePayload:
    """Tests pour le payload de creation."""

    def test_mode_detection_custom(self, sample_custom_lignes):
        """Test detection mode custom."""
        payload = DevisCreatePayload(
            lead_id="550e8400-e29b-41d4-a716-446655440000",
            lignes_devis_custom=sample_custom_lignes
        )
        assert payload.mode == "custom_manual"

    def test_mode_detection_budget(self):
        """Test detection mode budget."""
        payload = DevisCreatePayload(
            lead_id="550e8400-e29b-41d4-a716-446655440000",
            budget_negocie=10000.0
        )
        assert payload.mode == "budget_manuel"

    def test_mode_detection_openai(self):
        """Test detection mode OpenAI."""
        payload = DevisCreatePayload(
            lead_id="550e8400-e29b-41d4-a716-446655440000"
        )
        assert payload.mode == "openai"

    def test_invalid_lead_id(self):
        """Test rejet lead_id invalide."""
        with pytest.raises(Exception):
            DevisCreatePayload(
                lead_id="not-a-uuid"
            )


class TestGenerateDevisNumero:
    """Tests pour la generation du numero de devis."""

    def test_format(self):
        """Test format du numero."""
        numero = generate_devis_numero()

        assert numero.startswith("DEV-")
        parts = numero.split("-")
        assert len(parts) == 3
        assert len(parts[1]) == 8  # YYYYMMDD
        assert len(parts[2]) == 6  # Hex aleatoire

    def test_unique(self):
        """Test unicite des numeros."""
        numeros = [generate_devis_numero() for _ in range(100)]
        assert len(set(numeros)) == 100


class TestClientInfo:
    """Tests pour les infos client."""

    def test_nom_complet(self):
        """Test nom complet."""
        client = ClientInfo(
            nom="Dupont",
            prenom="Jean",
            email="test@test.com"
        )
        assert client.nom_complet == "Jean Dupont"

    def test_nom_seul(self):
        """Test avec nom seul."""
        client = ClientInfo(
            nom="Dupont",
            email="test@test.com"
        )
        assert client.nom_complet == "Dupont"

    def test_adresse_complete(self):
        """Test adresse complete."""
        client = ClientInfo(
            nom="Dupont",
            email="test@test.com",
            adresse="123 Rue de Paris",
            ville="Metz",
            code_postal="57000"
        )
        assert "123 Rue de Paris" in client.adresse_complete
        assert "Metz" in client.adresse_complete
        assert "57000" in client.adresse_complete


# === Tests de generation des lignes ===

class TestDevisLignesGenerator:
    """Tests pour la generation des lignes de devis."""

    def test_from_custom(self, sample_custom_lignes):
        """Test mode custom."""
        lignes, notes, source = DevisLignesGenerator.from_custom(
            lignes=sample_custom_lignes,
            notes="Notes personnalisees"
        )

        assert len(lignes) == 3
        assert source == "custom_manual"
        assert notes == "Notes personnalisees"

    def test_from_budget(self):
        """Test mode budget manuel."""
        lignes, notes, source = DevisLignesGenerator.from_budget(
            budget_negocie=10000.0,
            type_projet="renovation",
            surface=100.0
        )

        assert len(lignes) == 4
        assert source == "budget_manuel"

        # Verifie la repartition
        total_lignes = sum(l.total_ht for l in lignes)
        assert abs(total_lignes - 10000.0) < 0.01

    def test_from_budget_repartition(self):
        """Test repartition du budget."""
        lignes, _, _ = DevisLignesGenerator.from_budget(
            budget_negocie=10000.0,
            type_projet="renovation",
            surface=100.0
        )

        # Main d'oeuvre = 40%
        assert abs(lignes[0].total_ht - 4000.0) < 0.01

        # Materiaux = 35%
        assert abs(lignes[1].total_ht - 3500.0) < 0.01

        # Echafaudage = 15%
        assert abs(lignes[2].total_ht - 1500.0) < 0.01

        # Evacuation = 10%
        assert abs(lignes[3].total_ht - 1000.0) < 0.01

    @pytest.mark.asyncio
    async def test_from_openai_fallback(self):
        """Test fallback si OpenAI echoue."""
        with patch('app.services.devis_service.OpenAI') as mock_openai:
            mock_openai.return_value.chat.completions.create.side_effect = Exception("API Error")

            lignes, notes, source = await DevisLignesGenerator.from_openai(
                type_projet="renovation",
                surface=100.0
            )

            assert len(lignes) > 0
            assert source == "openai"
            assert "estimatif" in notes.lower()


class TestAIDevisLignesResult:
    """Tests pour le parsing des resultats IA."""

    def test_parse_valid_json(self):
        """Test parsing JSON valide."""
        json_str = json.dumps({
            "lignes": [
                {"designation": "Test", "quantite": 10, "unite": "m2", "prix_unitaire_ht": 50}
            ],
            "notes": "Notes de test"
        })

        result = AIDevisLignesResult.from_json_string(json_str)

        assert len(result.lignes) == 1
        assert result.lignes[0].designation == "Test"
        assert result.notes == "Notes de test"

    def test_parse_invalid_json(self):
        """Test parsing JSON invalide."""
        result = AIDevisLignesResult.from_json_string("not valid json")

        assert len(result.lignes) == 0
        assert "Erreur" in result.notes

    def test_parse_missing_fields(self):
        """Test parsing avec champs manquants."""
        json_str = json.dumps({"lignes": []})

        result = AIDevisLignesResult.from_json_string(json_str)

        assert len(result.lignes) == 0
        assert result.notes == "Devis genere automatiquement"


# === Tests du generateur PDF ===

class TestDevisPDFGenerator:
    """Tests pour la generation PDF."""

    @pytest.fixture
    def pdf_generator(self):
        """Instance du generateur PDF."""
        return DevisPDFGenerator()

    def test_format_euro(self, pdf_generator):
        """Test formatage euros."""
        assert "1 234,56" in pdf_generator._format_euro(1234.56)
        assert "0,00" in pdf_generator._format_euro(0)
        assert "0,00" in pdf_generator._format_euro(None)

    def test_escape_html(self, pdf_generator):
        """Test echappement HTML."""
        assert pdf_generator._escape_html("<script>") == "&lt;script&gt;"
        assert pdf_generator._escape_html('"test"') == "&quot;test&quot;"
        assert pdf_generator._escape_html("") == ""

    def test_generate_html(self, pdf_generator, sample_custom_lignes, sample_lead):
        """Test generation HTML."""
        devis = DevisCalcule(lignes=sample_custom_lignes, tva_pourcent=10.0)
        client = ClientInfo(
            nom=sample_lead["nom"],
            prenom=sample_lead["prenom"],
            email=sample_lead["email"]
        )

        html = pdf_generator.generate_html(
            devis=devis,
            client=client,
            type_projet="renovation"
        )

        assert "ToitureAI" in html
        assert sample_lead["nom"] in html
        assert "DEV-" in html

    @pytest.mark.skipif(True, reason="Necessite WeasyPrint installe")
    def test_html_to_pdf(self, pdf_generator):
        """Test conversion HTML vers PDF."""
        html = "<html><body><h1>Test</h1></body></html>"
        pdf_bytes = pdf_generator.html_to_pdf(html)

        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0
        assert pdf_bytes[:4] == b'%PDF'


# === Tests API ===

class TestDevisAPI:
    """Tests pour les endpoints API."""

    def test_create_devis_without_auth(self, test_client, sample_lead):
        """Test creation sans authentification."""
        response = test_client.post(
            "/api/v1/devis/webhook",
            json={"lead_id": sample_lead["id"]}
        )
        assert response.status_code == 401

    def test_create_devis_invalid_secret(self, test_client, sample_lead):
        """Test creation avec secret invalide."""
        response = test_client.post(
            "/api/v1/devis/webhook",
            headers={"X-Webhook-Secret": "invalid-secret"},
            json={"lead_id": sample_lead["id"]}
        )
        assert response.status_code == 401

    def test_create_devis_invalid_lead_id(self, test_client, valid_webhook_headers):
        """Test creation avec lead_id invalide."""
        response = test_client.post(
            "/api/v1/devis/webhook",
            headers=valid_webhook_headers,
            json={"lead_id": "not-a-uuid"}
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_devis_lead_not_found(self, test_client, valid_webhook_headers):
        """Test creation avec lead inexistant."""
        with patch('app.api.devis_webhook.lead_repo.get_by_id', new_callable=AsyncMock) as mock:
            mock.return_value = None

            response = test_client.post(
                "/api/v1/devis/webhook",
                headers=valid_webhook_headers,
                json={"lead_id": "550e8400-e29b-41d4-a716-446655440000"}
            )
            assert response.status_code == 404

    def test_get_devis_stats_without_auth(self, test_client):
        """Test stats sans authentification."""
        response = test_client.get("/api/v1/devis/stats/summary")
        assert response.status_code == 401


# === Tests d'integration ===

class TestDevisIntegration:
    """Tests d'integration pour le workflow devis."""

    @pytest.mark.asyncio
    async def test_full_devis_flow(self, sample_lead, sample_custom_lignes):
        """Test flux complet de creation de devis."""
        from app.services.devis_service import DevisService
        from app.models.devis import DevisCreatePayload

        service = DevisService()

        # Cree un payload custom
        payload = DevisCreatePayload(
            lead_id=sample_lead["id"],
            lignes_devis_custom=sample_custom_lignes,
            notes_devis_custom="Test integration"
        )

        # Mock les services externes
        with patch.object(service, 'pdf_generator') as mock_pdf:
            mock_pdf.generate_pdf.return_value = (b'%PDF-mock', 'DEV-TEST')

            with patch('app.services.devis_service.SupabaseStorageService.upload_pdf', new_callable=AsyncMock) as mock_upload:
                mock_upload.return_value = "https://example.com/test.pdf"

                with patch('app.services.devis_service.DevisRepository') as mock_repo:
                    mock_repo_instance = MagicMock()
                    mock_repo_instance.insert = AsyncMock(return_value={"id": "test-id"})
                    mock_repo.return_value = mock_repo_instance

                    with patch('app.services.devis_service.EmailService') as mock_email:
                        mock_email_instance = MagicMock()
                        mock_email_instance.send_devis = AsyncMock(return_value=(True, "msg-id"))
                        mock_email.return_value = mock_email_instance

                        result = await service.create_devis(payload, sample_lead)

                        assert "devis_id" in result
                        assert "numero" in result
                        assert "url_pdf" in result
