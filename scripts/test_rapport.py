import asyncio
import os
import sys

# Ajoute le dossier parent au PYTHONPATH pour importer app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.rapport_service import rapport_service
from app.core.config import settings

async def main():
    print(f"🚀 Démarrage du test de rapport mensuel...")
    print(f"Environnement: {settings.app_env}")
    print(f"Email admin configuré: {settings.admin_email}")

    # On force la génération pour le mois dernier (pour avoir des données)
    # ou le mois en cours si vous préférez.
    # Ici: None = automatique (mois précédent)
    try:
        result = await rapport_service.generate_rapport(
            envoyer_email=True,
            email_destinataire=settings.admin_email # Envoie à l'admin configuré
        )
        
        print("\n✅ Rapport généré avec succès !")
        print(f"ID Rapport: {result['rapport_id']}")
        print(f"Période: {result['periode']}")
        print(f"URL PDF: {result['pdf_url']}")
        print(f"Email envoyé: {'Oui' if result['email_envoye'] else 'Non'}")
        
    except Exception as e:
        print(f"\n❌ Erreur lors du test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
