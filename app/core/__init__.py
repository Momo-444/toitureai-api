"""
Core components pour ToitureAI.

Modules:
- config: Configuration Pydantic Settings
- database: Client Supabase
- error_handler: Gestion centralisée des erreurs (Workflow 6)
"""

from app.core.config import settings
from app.core.database import get_supabase_client, supabase

__all__ = ["settings", "get_supabase_client", "supabase"]
