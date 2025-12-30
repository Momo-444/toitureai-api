"""
Utilitaires de validation et normalisation pour ToitureAI.

Fonctions réutilisables pour la validation des données entrantes.
"""

from __future__ import annotations

import re
from typing import Optional, Any
from email_validator import validate_email, EmailNotValidError


def normalize_phone_french(phone: str) -> str:
    """
    Normalise un numéro de téléphone au format français +33.

    Args:
        phone: Numéro de téléphone brut.

    Returns:
        Numéro normalisé au format +33XXXXXXXXX.

    Examples:
        >>> normalize_phone_french("06 12 34 56 78")
        '+33612345678'
        >>> normalize_phone_french("0612345678")
        '+33612345678'
        >>> normalize_phone_french("+33612345678")
        '+33612345678'
    """
    if not phone:
        return ""

    # Supprime tous les caractères non numériques sauf +
    cleaned = re.sub(r"[^\d+]", "", phone)

    # Convertit le format 0X en +33X
    if cleaned.startswith("0") and len(cleaned) >= 10:
        cleaned = "+33" + cleaned[1:]

    # Ajoute +33 si absent et commence par un chiffre
    if cleaned and not cleaned.startswith("+"):
        cleaned = "+33" + cleaned

    return cleaned


def normalize_email_address(email: str) -> str:
    """
    Normalise une adresse email.

    Args:
        email: Adresse email brute.

    Returns:
        Email normalisé en minuscules.
    """
    return email.strip().lower() if email else ""


def validate_email_address(email: str) -> tuple[bool, str]:
    """
    Valide une adresse email.

    Args:
        email: Adresse email à valider.

    Returns:
        Tuple (est_valide, email_normalisé ou message d'erreur).
    """
    try:
        result = validate_email(email, check_deliverability=False)
        return True, result.normalized
    except EmailNotValidError as e:
        return False, str(e)


def parse_to_int(value: Any) -> Optional[int]:
    """
    Parse une valeur en entier.

    Args:
        value: Valeur à parser (str, int, float, None).

    Returns:
        Entier ou None si non parsable ou <= 0.
    """
    if value is None or value == "":
        return None

    try:
        num = float(value)
        return int(num) if num > 0 else None
    except (ValueError, TypeError):
        return None


def parse_to_float(value: Any) -> Optional[float]:
    """
    Parse une valeur en float.

    Args:
        value: Valeur à parser.

    Returns:
        Float ou None si non parsable ou <= 0.
    """
    if value is None or value == "":
        return None

    try:
        num = float(value)
        return num if num > 0 else None
    except (ValueError, TypeError):
        return None


def sanitize_string(value: str, max_length: int = 500) -> str:
    """
    Nettoie et tronque une chaîne de caractères.

    Args:
        value: Chaîne à nettoyer.
        max_length: Longueur maximale.

    Returns:
        Chaîne nettoyée et tronquée.
    """
    if not value:
        return ""

    # Supprime les caractères de contrôle
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)

    # Normalise les espaces
    cleaned = " ".join(cleaned.split())

    # Tronque
    return cleaned[:max_length] if len(cleaned) > max_length else cleaned


def validate_code_postal_french(code: str) -> bool:
    """
    Valide un code postal français.

    Args:
        code: Code postal à valider.

    Returns:
        True si le code postal est valide.
    """
    if not code:
        return False

    cleaned = re.sub(r"\s", "", code)
    return bool(re.match(r"^\d{5}$", cleaned))


def normalize_type_projet(value: str) -> str:
    """
    Normalise le type de projet.

    Args:
        value: Type de projet brut.

    Returns:
        Type de projet normalisé.
    """
    if not value:
        return "autre"

    mapping = {
        "réparation (fuite, tuiles cassées...)": "reparation",
        "reparation (fuite, tuiles cassées...)": "reparation",
        "réparation": "reparation",
        "reparation": "reparation",
        "fuite": "reparation",
        "tuiles": "reparation",
        "rénovation complète": "renovation",
        "renovation complete": "renovation",
        "rénovation": "renovation",
        "renovation": "renovation",
        "isolation thermique": "isolation",
        "isolation": "isolation",
        "installation neuve": "installation",
        "installation": "installation",
        "neuve": "installation",
        "entretien / maintenance": "entretien",
        "entretien": "entretien",
        "maintenance": "entretien",
        "nettoyage": "entretien",
        "autre": "autre",
    }

    normalized = value.lower().strip()
    return mapping.get(normalized, "autre")


def normalize_delai(value: str) -> str:
    """
    Normalise le délai souhaité.

    Args:
        value: Délai brut.

    Returns:
        Délai normalisé.
    """
    if not value:
        return "flexible"

    mapping = {
        "urgent (sous 48h)": "urgent",
        "urgent": "urgent",
        "48h": "urgent",
        "dans 1-2 semaines": "1-2 semaines",
        "1-2 semaines": "1-2 semaines",
        "2 semaines": "1-2 semaines",
        "dans 1 mois": "1 mois",
        "1 mois": "1 mois",
        "dans 2-3 mois": "2-3 mois",
        "2-3 mois": "2-3 mois",
        "3 mois": "2-3 mois",
        "flexible / à convenir": "flexible",
        "flexible": "flexible",
        "à convenir": "flexible",
    }

    normalized = value.lower().strip()
    return mapping.get(normalized, "flexible")


def format_currency_fr(amount: float | int) -> str:
    """
    Formate un montant en euros (format français).

    Args:
        amount: Montant à formater.

    Returns:
        Montant formaté (ex: "1 234,56 €").
    """
    if amount is None:
        return "N/A"

    # Format avec séparateur de milliers
    formatted = f"{amount:,.2f}".replace(",", " ").replace(".", ",")
    return f"{formatted} €"


def format_surface(surface: int | float | None) -> str:
    """
    Formate une surface en m².

    Args:
        surface: Surface à formater.

    Returns:
        Surface formatée (ex: "150 m²").
    """
    if surface is None:
        return "Non spécifié"
    return f"{int(surface)} m²"


def extract_city_from_address(address: str) -> Optional[str]:
    """
    Tente d'extraire la ville d'une adresse.

    Args:
        address: Adresse complète.

    Returns:
        Ville extraite ou None.
    """
    if not address:
        return None

    # Cherche un code postal suivi d'un mot (ville)
    match = re.search(r"\d{5}\s+([A-Za-zÀ-ÿ\s-]+)", address)
    if match:
        return match.group(1).strip()

    return None


def is_valid_uuid(value: str) -> bool:
    """
    Vérifie si une chaîne est un UUID valide.

    Args:
        value: Chaîne à vérifier.

    Returns:
        True si c'est un UUID valide.
    """
    if not value:
        return False

    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        re.IGNORECASE
    )
    return bool(uuid_pattern.match(value))
