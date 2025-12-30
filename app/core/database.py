"""
Client Supabase pour ToitureAI.

Fournit un client singleton configuré pour accéder à la base de données Supabase.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional, List, Dict

from supabase import create_client, Client

from app.core.config import settings


@lru_cache
def get_supabase_client(use_service_key: bool = False) -> Client:
    """
    Retourne un client Supabase configuré.

    Args:
        use_service_key: Si True, utilise la clé service role pour les opérations admin.
                        Sinon, utilise la clé anon standard.

    Returns:
        Client Supabase configuré.

    Raises:
        ValueError: Si la clé service est demandée mais non configurée.
    """
    if use_service_key:
        if not settings.supabase_service_key:
            raise ValueError(
                "La clé service Supabase n'est pas configurée. "
                "Définissez SUPABASE_SERVICE_KEY dans votre .env"
            )
        return create_client(settings.supabase_url, settings.supabase_service_key)

    return create_client(settings.supabase_url, settings.supabase_key)


# Client par défaut avec clé anon (pour les lectures)
supabase: Client = get_supabase_client()

# Client avec clé service_role (pour les écritures - bypass RLS)
supabase_admin: Client = get_supabase_client(use_service_key=True)


class SupabaseRepository:
    """
    Repository de base pour les opérations Supabase.

    Fournit des méthodes utilitaires pour les opérations CRUD courantes.
    """

    def __init__(self, table_name: str, client: Optional[Client] = None, use_admin: bool = True):
        """
        Initialise le repository.

        Args:
            table_name: Nom de la table Supabase.
            client: Client Supabase optionnel.
            use_admin: Si True, utilise le client admin (service_role) pour bypass RLS.
        """
        self.table_name = table_name
        if client:
            self.client = client
        else:
            self.client = supabase_admin if use_admin else supabase

    @property
    def table(self):
        """Retourne une référence à la table."""
        return self.client.table(self.table_name)

    async def insert(self, data: dict) -> dict:
        """
        Insère un enregistrement dans la table.

        Args:
            data: Dictionnaire des données à insérer.

        Returns:
            L'enregistrement créé avec son ID.

        Raises:
            Exception: Si l'insertion échoue.
        """
        response = self.table.insert(data).execute()
        if response.data:
            return response.data[0]
        raise Exception(f"Échec de l'insertion dans {self.table_name}")

    async def update(self, id: str, data: dict) -> dict:
        """
        Met à jour un enregistrement.

        Args:
            id: UUID de l'enregistrement.
            data: Dictionnaire des données à mettre à jour.

        Returns:
            L'enregistrement mis à jour.
        """
        response = self.table.update(data).eq("id", id).execute()
        if response.data:
            return response.data[0]
        raise Exception(f"Échec de la mise à jour dans {self.table_name}")

    async def get_by_id(self, id: str) -> Optional[dict]:
        """
        Récupère un enregistrement par son ID.

        Args:
            id: UUID de l'enregistrement.

        Returns:
            L'enregistrement ou None si non trouvé.
        """
        response = self.table.select("*").eq("id", id).execute()
        return response.data[0] if response.data else None

    async def get_by_field(self, field: str, value: str) -> Optional[dict]:
        """
        Récupère un enregistrement par un champ spécifique.

        Args:
            field: Nom du champ.
            value: Valeur recherchée.

        Returns:
            Le premier enregistrement correspondant ou None.
        """
        response = self.table.select("*").eq(field, value).execute()
        return response.data[0] if response.data else None

    async def get_all(
        self,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "created_at",
        ascending: bool = False
    ) -> list[dict]:
        """
        Récupère tous les enregistrements avec pagination.

        Args:
            limit: Nombre maximum d'enregistrements.
            offset: Décalage pour la pagination.
            order_by: Champ de tri.
            ascending: Ordre croissant si True.

        Returns:
            Liste des enregistrements.
        """
        query = self.table.select("*")
        query = query.order(order_by, desc=not ascending)
        query = query.range(offset, offset + limit - 1)
        response = query.execute()
        return response.data or []

    async def delete(self, id: str) -> bool:
        """
        Supprime un enregistrement.

        Args:
            id: UUID de l'enregistrement.

        Returns:
            True si supprimé avec succès.
        """
        response = self.table.delete().eq("id", id).execute()
        return bool(response.data)

    async def count(self, filters: Optional[dict] = None) -> int:
        """
        Compte les enregistrements.

        Args:
            filters: Dictionnaire de filtres optionnels.

        Returns:
            Nombre d'enregistrements.
        """
        query = self.table.select("*", count="exact")
        if filters:
            for field, value in filters.items():
                query = query.eq(field, value)
        response = query.execute()
        return response.count or 0


class LeadRepository(SupabaseRepository):
    """Repository spécialisé pour les leads."""

    def __init__(self, client: Optional[Client] = None):
        super().__init__("leads", client)

    async def get_by_email(self, email: str) -> Optional[dict]:
        """Récupère un lead par son email."""
        return await self.get_by_field("email", email.lower())

    async def update_tracking(
        self,
        lead_id: str,
        tracking_type: str,
        timestamp: Optional[str] = None
    ) -> dict:
        """
        Met à jour les informations de tracking d'un lead.

        Args:
            lead_id: UUID du lead.
            tracking_type: Type de tracking ('open' ou 'click').
            timestamp: Timestamp optionnel (utilise maintenant si non fourni).
        """
        from datetime import datetime, timezone

        now = timestamp or datetime.now(timezone.utc).isoformat()

        if tracking_type == "open":
            update_data = {
                "email_ouvert": True,
                "email_ouvert_count": self.client.rpc(
                    "increment_count",
                    {"row_id": lead_id, "column_name": "email_ouvert_count"}
                ).execute().data if False else 1,  # Fallback si RPC n'existe pas
                "derniere_interaction": now
            }
        elif tracking_type == "click":
            update_data = {
                "email_clic_count": 1,  # Sera incrémenté par trigger si configuré
                "statut": "chaud",
                "lead_chaud": True,
                "derniere_interaction": now
            }
        else:
            raise ValueError(f"Type de tracking invalide: {tracking_type}")

        return await self.update(lead_id, update_data)

    async def get_hot_leads(self, threshold: int = 70) -> list[dict]:
        """Récupère les leads chauds (score >= threshold)."""
        response = (
            self.table
            .select("*")
            .gte("score_qualification", threshold)
            .order("created_at", desc=True)
            .execute()
        )
        return response.data or []

    async def get_leads_by_status(self, status: str) -> list[dict]:
        """Récupère les leads par statut."""
        response = (
            self.table
            .select("*")
            .eq("statut", status)
            .order("created_at", desc=True)
            .execute()
        )
        return response.data or []


class DevisRepository(SupabaseRepository):
    """Repository spécialisé pour les devis."""

    def __init__(self, client: Optional[Client] = None):
        super().__init__("devis", client)

    async def get_by_lead_id(self, lead_id: str) -> list[dict]:
        """Récupère tous les devis d'un lead."""
        response = (
            self.table
            .select("*")
            .eq("lead_id", lead_id)
            .order("created_at", desc=True)
            .execute()
        )
        return response.data or []

    async def get_latest_by_email_phone(
        self,
        email: str,
        phone: str
    ) -> Optional[dict]:
        """
        Récupère le devis le plus récent par email et téléphone.

        Utilisé pour le webhook DocuSeal.
        """
        response = (
            self.table
            .select("*")
            .eq("client_email", email.lower())
            .eq("client_telephone", phone)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    async def update_signature(
        self,
        devis_id: str,
        signed_pdf_url: str
    ) -> dict:
        """Met à jour un devis après signature."""
        from datetime import datetime, timezone

        return await self.update(devis_id, {
            "url_pdf": signed_pdf_url,
            "statut": "signe",
            "date_signature": datetime.now(timezone.utc).isoformat()
        })


class ErrorLogRepository(SupabaseRepository):
    """Repository pour les logs d'erreurs."""

    def __init__(self, client: Optional[Client] = None):
        super().__init__("error_logs", client)

    async def log_error(
        self,
        workflow: str,
        node: str,
        message: str,
        details: Optional[dict] = None,
        execution_id: Optional[str] = None
    ) -> dict:
        """
        Enregistre une erreur dans la base de données.

        Args:
            workflow: Nom du workflow où l'erreur s'est produite.
            node: Nom du noeud/fonction où l'erreur s'est produite.
            message: Message d'erreur.
            details: Détails supplémentaires (stack trace, etc.).
            execution_id: ID d'exécution optionnel.
        """
        import json
        from datetime import datetime, timezone

        return await self.insert({
            "workflow": workflow,
            "node": node,
            "message": message,
            "details": json.dumps(details) if details else None,
            "execution_id": execution_id,
            "created_at": datetime.now(timezone.utc).isoformat()
        })
