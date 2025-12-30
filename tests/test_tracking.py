"""
Tests pour le Workflow 4 - Lead Tracking.

Tests couvrant:
- Validation des signatures HMAC
- Tracking d'ouverture (pixel)
- Tracking de clic (page de remerciement)
- Mise à jour des statuts
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestTrackingEndpoint:
    """Tests de l'endpoint de tracking."""

    def test_missing_parameters_returns_422(self, test_client):
        """Paramètres manquants retourne 422."""
        response = test_client.get("/api/v1/tracking/track-lead")
        assert response.status_code == 422

    def test_invalid_type_returns_400(self, test_client):
        """Type invalide retourne 400."""
        response = test_client.get(
            "/api/v1/tracking/track-lead",
            params={
                "lead_id": "test-uuid",
                "type": "invalid",
                "s": "fake_signature"
            }
        )
        assert response.status_code == 400

    def test_invalid_signature_returns_403(self, test_client):
        """Signature invalide retourne 403."""
        response = test_client.get(
            "/api/v1/tracking/track-lead",
            params={
                "lead_id": "test-uuid",
                "type": "open",
                "s": "invalid_signature"
            }
        )
        assert response.status_code == 403

    def test_valid_open_tracking_returns_pixel(self, test_client):
        """Tracking open valide retourne un pixel GIF."""
        from app.services.hmac_service import hmac_service

        lead_id = "test-uuid-1234"
        sign_click, sign_open = hmac_service.generate_tracking_signatures(lead_id)

        # Mock la mise à jour en base
        with patch("app.api.tracking.lead_repo") as mock_repo:
            mock_repo.get_by_id = AsyncMock(return_value={
                "id": lead_id,
                "email_ouvert_count": 0
            })
            mock_repo.update = AsyncMock(return_value={})

            response = test_client.get(
                "/api/v1/tracking/track-lead",
                params={
                    "lead_id": lead_id,
                    "type": "open",
                    "s": sign_open
                }
            )

            assert response.status_code == 200
            assert response.headers["content-type"] == "image/gif"
            # Vérifie que c'est bien un GIF (magic bytes)
            assert response.content[:3] == b"GIF"

    def test_valid_click_tracking_returns_html(self, test_client):
        """Tracking click valide retourne une page HTML."""
        from app.services.hmac_service import hmac_service

        lead_id = "test-uuid-5678"
        sign_click, sign_open = hmac_service.generate_tracking_signatures(lead_id)

        # Mock la mise à jour en base
        with patch("app.api.tracking.lead_repo") as mock_repo:
            mock_repo.get_by_id = AsyncMock(return_value={
                "id": lead_id,
                "email_clic_count": 0
            })
            mock_repo.update = AsyncMock(return_value={})

            response = test_client.get(
                "/api/v1/tracking/track-lead",
                params={
                    "lead_id": lead_id,
                    "type": "click",
                    "s": sign_click
                }
            )

            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
            assert "Merci" in response.text
            assert "confirmation" in response.text.lower()


class TestTrackingSignatures:
    """Tests des signatures de tracking."""

    def test_open_and_click_signatures_different(self):
        """Les signatures open et click sont différentes."""
        from app.services.hmac_service import HMACService

        service = HMACService(secret="test_secret_32_chars_at_minimum!")
        lead_id = "test-uuid"

        sign_click, sign_open = service.generate_tracking_signatures(lead_id)

        assert sign_click != sign_open

    def test_signature_verification_correct_type(self):
        """La signature est vérifiée pour le bon type."""
        from app.services.hmac_service import HMACService

        service = HMACService(secret="test_secret_32_chars_at_minimum!")
        lead_id = "test-uuid"

        sign_click, sign_open = service.generate_tracking_signatures(lead_id)

        # Correct type
        assert service.verify_tracking_signature(lead_id, "click", sign_click) is True
        assert service.verify_tracking_signature(lead_id, "open", sign_open) is True

        # Wrong type
        assert service.verify_tracking_signature(lead_id, "open", sign_click) is False
        assert service.verify_tracking_signature(lead_id, "click", sign_open) is False

    def test_signature_verification_wrong_lead_id(self):
        """La signature échoue avec un mauvais lead_id."""
        from app.services.hmac_service import HMACService

        service = HMACService(secret="test_secret_32_chars_at_minimum!")
        lead_id = "test-uuid"

        sign_click, sign_open = service.generate_tracking_signatures(lead_id)

        # Wrong lead_id
        assert service.verify_tracking_signature("other-uuid", "click", sign_click) is False

    def test_urls_generation(self):
        """Les URLs de tracking sont correctement générées."""
        from app.services.hmac_service import HMACService

        service = HMACService(secret="test_secret_32_chars_at_minimum!")
        lead_id = "test-uuid-1234"
        base_url = "https://api.test.com"

        click_url, open_url = service.generate_tracking_urls(lead_id, base_url)

        assert lead_id in click_url
        assert lead_id in open_url
        assert "type=click" in click_url
        assert "type=open" in open_url
        assert base_url in click_url
        assert base_url in open_url
        assert "&s=" in click_url
        assert "&s=" in open_url


class TestTrackingDatabaseUpdates:
    """Tests des mises à jour en base pour le tracking."""

    @pytest.mark.asyncio
    async def test_open_tracking_updates_fields(self):
        """Le tracking open met à jour les bons champs."""
        from app.core.database import LeadRepository

        repo = LeadRepository()

        # Mock le client Supabase
        mock_response = MagicMock()
        mock_response.data = [{
            "id": "test-uuid",
            "email_ouvert": True,
            "email_ouvert_count": 1
        }]

        with patch.object(repo, "table") as mock_table:
            mock_table.update.return_value.eq.return_value.execute.return_value = mock_response
            mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
                data=[{"id": "test-uuid", "email_ouvert_count": 0}]
            )

            # Appel de la méthode
            result = await repo.update("test-uuid", {
                "email_ouvert": True,
                "email_ouvert_count": 1
            })

            # Vérification
            mock_table.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_click_tracking_sets_lead_hot(self):
        """Le tracking click marque le lead comme chaud."""
        from app.core.database import LeadRepository

        repo = LeadRepository()

        mock_response = MagicMock()
        mock_response.data = [{
            "id": "test-uuid",
            "statut": "chaud",
            "lead_chaud": True
        }]

        with patch.object(repo, "table") as mock_table:
            mock_table.update.return_value.eq.return_value.execute.return_value = mock_response

            result = await repo.update("test-uuid", {
                "statut": "chaud",
                "lead_chaud": True,
                "email_clic_count": 1
            })

            mock_table.update.assert_called_once()


class TestTrackingPixel:
    """Tests du pixel de tracking."""

    def test_pixel_is_valid_gif(self):
        """Le pixel est un GIF valide."""
        from app.api.tracking import TRANSPARENT_PIXEL

        # GIF89a magic bytes
        assert TRANSPARENT_PIXEL[:6] == b"GIF89a"

        # Taille 1x1
        assert TRANSPARENT_PIXEL[6] == 1  # width
        assert TRANSPARENT_PIXEL[7] == 0
        assert TRANSPARENT_PIXEL[8] == 1  # height
        assert TRANSPARENT_PIXEL[9] == 0

    def test_pixel_size(self):
        """Le pixel a la bonne taille."""
        from app.api.tracking import TRANSPARENT_PIXEL

        # Un GIF 1x1 transparent fait 43 bytes
        assert len(TRANSPARENT_PIXEL) == 43


class TestThankYouPage:
    """Tests de la page de remerciement."""

    def test_thank_you_html_contains_required_elements(self):
        """La page de remerciement contient les éléments requis."""
        from app.api.tracking import THANK_YOU_HTML

        assert "Merci" in THANK_YOU_HTML
        assert "{website_url}" in THANK_YOU_HTML
        assert "ToitureAI" in THANK_YOU_HTML
        assert "confirmation" in THANK_YOU_HTML.lower()

    def test_thank_you_html_is_valid_html(self):
        """La page de remerciement est du HTML valide."""
        from app.api.tracking import THANK_YOU_HTML

        assert "<!DOCTYPE html>" in THANK_YOU_HTML
        assert "<html" in THANK_YOU_HTML
        assert "</html>" in THANK_YOU_HTML
        assert "<head>" in THANK_YOU_HTML
        assert "</head>" in THANK_YOU_HTML
        assert "<body>" in THANK_YOU_HTML
        assert "</body>" in THANK_YOU_HTML
