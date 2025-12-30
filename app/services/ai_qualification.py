"""
Service de qualification IA des leads via OpenAI.

Utilise GPT-4o-mini pour analyser et scorer les leads entrants.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from openai import OpenAI, APIError, RateLimitError, APIConnectionError

from app.core.config import settings
from app.models.lead import LeadCreate, AIQualificationResult

logger = logging.getLogger(__name__)


class AIQualificationService:
    """
    Service de qualification IA des leads.

    Utilise OpenAI GPT-4o-mini pour:
    - Scorer les leads de 0 à 100
    - Déterminer l'urgence (faible/moyenne/haute)
    - Générer des recommandations de suivi
    - Classifier en segments
    """

    # Prompt système pour la qualification
    SYSTEM_PROMPT = """Tu es un assistant expert en qualification de leads pour travaux de toiture en France.
Tu dois analyser les informations du lead et retourner STRICTEMENT un JSON valide.

Critères de scoring:
- Budget élevé (>10000€) = +20 points
- Urgence déclarée = +15 points
- Surface importante (>100m²) = +10 points
- Contact téléphonique fourni = +10 points
- Description détaillée = +10 points
- Type de projet (rénovation/isolation > réparation > entretien) = +5 à +15 points
- Localisation précise = +5 points

Segments possibles:
- "particulier", "professionnel"
- "urgent", "planifié"
- "petit_budget", "budget_moyen", "gros_budget"
- "renovation_complete", "reparation_ponctuelle", "entretien_regulier"

Retourne EXACTEMENT ce format JSON, sans texte supplémentaire:
{
  "score": <0-100>,
  "urgence": "faible|moyenne|haute",
  "recommandation": "<texte concis max 100 caractères>",
  "segments": ["<segment1>", "<segment2>"]
}"""

    # Template du prompt utilisateur
    USER_PROMPT_TEMPLATE = """Analyse ce lead et retourne le JSON de qualification:

Nom: {nom} {prenom}
Email: {email}
Téléphone: {telephone}
Type de projet: {type_projet}
Surface: {surface} m²
Budget estimé: {budget} €
Délai souhaité: {delai}
Adresse: {adresse}, {code_postal} {ville}
Description: {description}"""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        """
        Initialise le service de qualification IA.

        Args:
            api_key: Clé API OpenAI. Utilise settings.openai_api_key par défaut.
            model: Modèle à utiliser. Utilise settings.openai_model par défaut.
        """
        self.client = OpenAI(api_key=api_key or settings.openai_api_key)
        self.model = model or settings.openai_model

    def _build_user_prompt(self, lead: LeadCreate) -> str:
        """
        Construit le prompt utilisateur à partir des données du lead.

        Args:
            lead: Données du lead.

        Returns:
            Prompt formaté.
        """
        return self.USER_PROMPT_TEMPLATE.format(
            nom=lead.nom,
            prenom=lead.prenom or "",
            email=lead.email,
            telephone=lead.telephone,
            type_projet=lead.type_projet,
            surface=lead.surface or "Non spécifié",
            budget=lead.budget_estime or "Non spécifié",
            delai=lead.delai,
            adresse=lead.adresse or "Non spécifié",
            code_postal=lead.code_postal or "",
            ville=lead.ville or "",
            description=lead.description or "Aucune description"
        )

    async def qualify_lead(
        self,
        lead: LeadCreate,
        temperature: float = 0.5
    ) -> tuple[AIQualificationResult, str]:
        """
        Qualifie un lead via OpenAI.

        Args:
            lead: Données du lead à qualifier.
            temperature: Température pour la génération (0-1).

        Returns:
            Tuple (résultat de qualification, réponse brute de l'IA).

        Raises:
            AIQualificationError: Si la qualification échoue.
        """
        try:
            user_prompt = self._build_user_prompt(lead)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                max_tokens=200,
                response_format={"type": "json_object"}
            )

            raw_content = response.choices[0].message.content or "{}"
            result = AIQualificationResult.from_json_string(raw_content)

            logger.info(
                f"Lead qualifié: {lead.email} - Score: {result.score}, "
                f"Urgence: {result.urgence}"
            )

            return result, raw_content

        except RateLimitError as e:
            logger.error(f"Rate limit OpenAI atteinte: {e}")
            # Fallback avec score neutre
            return self._get_fallback_result("Rate limit atteinte"), "{}"

        except APIConnectionError as e:
            logger.error(f"Erreur connexion OpenAI: {e}")
            return self._get_fallback_result("Erreur connexion"), "{}"

        except APIError as e:
            logger.error(f"Erreur API OpenAI: {e}")
            return self._get_fallback_result("Erreur API"), "{}"

        except Exception as e:
            logger.exception(f"Erreur inattendue lors de la qualification: {e}")
            return self._get_fallback_result("Erreur interne"), "{}"

    def qualify_lead_sync(
        self,
        lead: LeadCreate,
        temperature: float = 0.5
    ) -> tuple[AIQualificationResult, str]:
        """
        Version synchrone de qualify_lead.

        Args:
            lead: Données du lead à qualifier.
            temperature: Température pour la génération (0-1).

        Returns:
            Tuple (résultat de qualification, réponse brute de l'IA).
        """
        try:
            user_prompt = self._build_user_prompt(lead)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                max_tokens=200,
                response_format={"type": "json_object"}
            )

            raw_content = response.choices[0].message.content or "{}"
            result = AIQualificationResult.from_json_string(raw_content)

            logger.info(
                f"Lead qualifié: {lead.email} - Score: {result.score}, "
                f"Urgence: {result.urgence}"
            )

            return result, raw_content

        except Exception as e:
            logger.exception(f"Erreur lors de la qualification sync: {e}")
            return self._get_fallback_result(str(e)[:50]), "{}"

    @staticmethod
    def _get_fallback_result(reason: str) -> AIQualificationResult:
        """
        Retourne un résultat de fallback en cas d'erreur.

        Args:
            reason: Raison de l'utilisation du fallback.

        Returns:
            Résultat avec score neutre.
        """
        return AIQualificationResult(
            score=50,
            urgence="moyenne",
            recommandation=f"Revérifier manuellement - {reason}",
            segments=["a_verifier"]
        )

    def estimate_score_simple(self, lead: LeadCreate) -> int:
        """
        Estimation simple du score sans appel à l'IA.

        Utilisé en fallback ou pour les tests.

        Args:
            lead: Données du lead.

        Returns:
            Score estimé (0-100).
        """
        score = 30  # Score de base

        # Budget
        if lead.budget_estime:
            if lead.budget_estime >= 20000:
                score += 25
            elif lead.budget_estime >= 10000:
                score += 20
            elif lead.budget_estime >= 5000:
                score += 15
            else:
                score += 5

        # Surface
        if lead.surface:
            if lead.surface >= 150:
                score += 15
            elif lead.surface >= 100:
                score += 10
            elif lead.surface >= 50:
                score += 5

        # Type de projet
        type_scores = {
            "renovation": 15,
            "isolation": 12,
            "installation": 10,
            "reparation": 8,
            "entretien": 5,
            "autre": 3
        }
        score += type_scores.get(lead.type_projet, 5)

        # Délai urgent
        if lead.delai == "urgent":
            score += 15
        elif lead.delai in ("1-2 semaines", "1 mois"):
            score += 10

        # Coordonnées complètes
        if lead.telephone:
            score += 5
        if lead.adresse and lead.code_postal and lead.ville:
            score += 5

        # Description détaillée
        if lead.description and len(lead.description) > 50:
            score += 5

        return min(100, max(0, score))


# Instance globale
ai_qualification_service = AIQualificationService()


async def qualify_lead(
    lead: LeadCreate,
    temperature: float = 0.5
) -> tuple[AIQualificationResult, str]:
    """
    Fonction utilitaire pour qualifier un lead.

    Args:
        lead: Données du lead.
        temperature: Température pour l'IA.

    Returns:
        Tuple (résultat, réponse brute).
    """
    return await ai_qualification_service.qualify_lead(lead, temperature)


def qualify_lead_sync(
    lead: LeadCreate,
    temperature: float = 0.5
) -> tuple[AIQualificationResult, str]:
    """
    Version synchrone de qualify_lead.

    Args:
        lead: Données du lead.
        temperature: Température pour l'IA.

    Returns:
        Tuple (résultat, réponse brute).
    """
    return ai_qualification_service.qualify_lead_sync(lead, temperature)
