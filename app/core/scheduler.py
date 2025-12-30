"""
Gestionnaire de taches planifiees avec APScheduler.

Gere les jobs cron pour:
- Rapport mensuel (1er du mois a 8h)
- Autres taches periodiques futures
"""

from __future__ import annotations

import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, JobExecutionEvent

from app.core.config import settings

logger = logging.getLogger(__name__)


class SchedulerService:
    """
    Service de gestion des taches planifiees.

    Utilise APScheduler pour executer des jobs cron.
    """

    def __init__(self):
        """Initialise le scheduler."""
        self.scheduler = AsyncIOScheduler(
            timezone="Europe/Paris",
            job_defaults={
                "coalesce": True,  # Fusionne les jobs rates
                "max_instances": 1,  # Une seule instance par job
                "misfire_grace_time": 3600  # 1h de grace pour les jobs rates
            }
        )
        self._setup_event_listeners()
        self._is_running = False

    def _setup_event_listeners(self):
        """Configure les listeners d'evenements."""
        self.scheduler.add_listener(
            self._on_job_executed,
            EVENT_JOB_EXECUTED
        )
        self.scheduler.add_listener(
            self._on_job_error,
            EVENT_JOB_ERROR
        )

    def _on_job_executed(self, event: JobExecutionEvent):
        """Callback quand un job est execute avec succes."""
        logger.info(
            f"Job execute: {event.job_id} "
            f"(duree: {event.scheduled_run_time})"
        )

    def _on_job_error(self, event: JobExecutionEvent):
        """Callback quand un job echoue."""
        logger.error(
            f"Erreur job {event.job_id}: {event.exception}",
            exc_info=event.exception
        )

        # Notifie l'admin par email
        asyncio.create_task(self._notify_job_error(event))

    async def _notify_job_error(self, event: JobExecutionEvent):
        """Envoie une notification d'erreur."""
        try:
            from app.core.error_handler import error_handler

            await error_handler.handle_error(
                error=event.exception,
                workflow="scheduler",
                node=event.job_id
            )
        except Exception as e:
            logger.error(f"Erreur notification job error: {e}")

    def start(self):
        """Demarre le scheduler."""
        if self._is_running:
            logger.warning("Scheduler deja en cours d'execution")
            return

        self._register_jobs()
        self.scheduler.start()
        self._is_running = True
        logger.info("Scheduler demarre avec succes")

    def stop(self):
        """Arrete le scheduler."""
        if not self._is_running:
            return

        self.scheduler.shutdown(wait=False)
        self._is_running = False
        logger.info("Scheduler arrete")

    def _register_jobs(self):
        """Enregistre tous les jobs planifies."""
        # Job rapport mensuel
        # Cron: 0 8 1 * * = 8h00 le 1er de chaque mois
        self.scheduler.add_job(
            self._run_monthly_report,
            CronTrigger(
                day=1,
                hour=8,
                minute=0,
                timezone="Europe/Paris"
            ),
            id="monthly_report",
            name="Rapport Mensuel ToitureAI",
            replace_existing=True
        )
        logger.info("Job 'monthly_report' enregistre (1er du mois a 8h)")

    async def _run_monthly_report(self):
        """
        Execute la generation du rapport mensuel.

        Genere le rapport pour le mois precedent et l'envoie par email.
        """
        logger.info("Demarrage job rapport mensuel")

        try:
            from app.services.rapport_service import rapport_service

            result = await rapport_service.generate_rapport(
                mois=None,  # Mois precedent
                annee=None,  # Annee courante
                envoyer_email=True,
                email_destinataire=settings.admin_email
            )

            logger.info(
                f"Rapport mensuel genere: {result['rapport_id']}, "
                f"periode={result['periode']}, email={result['email_envoye']}"
            )

            return result

        except Exception as e:
            logger.exception(f"Erreur generation rapport mensuel: {e}")
            raise

    # === Methodes pour declencher manuellement ===

    async def trigger_monthly_report(
        self,
        mois: Optional[int] = None,
        annee: Optional[int] = None,
        email: Optional[str] = None
    ) -> dict:
        """
        Declenche manuellement la generation d'un rapport.

        Args:
            mois: Mois specifique (optionnel)
            annee: Annee specifique (optionnel)
            email: Email destinataire (optionnel)

        Returns:
            Resultat de la generation
        """
        from app.services.rapport_service import rapport_service

        return await rapport_service.generate_rapport(
            mois=mois,
            annee=annee,
            envoyer_email=True if email else False,
            email_destinataire=email
        )

    def get_next_run_time(self, job_id: str) -> Optional[datetime]:
        """
        Retourne la prochaine execution d'un job.

        Args:
            job_id: ID du job

        Returns:
            Date de prochaine execution ou None
        """
        job = self.scheduler.get_job(job_id)
        if job:
            return job.next_run_time
        return None

    def list_jobs(self) -> list[dict]:
        """
        Liste tous les jobs enregistres.

        Returns:
            Liste des jobs avec leurs infos
        """
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time) if job.next_run_time else None,
                "trigger": str(job.trigger)
            })
        return jobs


# Instance singleton
scheduler_service = SchedulerService()


def get_scheduler() -> SchedulerService:
    """Retourne l'instance du scheduler."""
    return scheduler_service
