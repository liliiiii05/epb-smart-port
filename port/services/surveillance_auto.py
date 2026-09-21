# port/services/surveillance_auto.py
"""
Service de surveillance automatique 24h/24.
Démarre automatiquement avec Django.
"""
import logging
import threading
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler = None
_lock = threading.Lock()


def executer_surveillance():
    """Fonction exécutée automatiquement toutes les 5 minutes."""
    from django.core.management import call_command
    from port.services.surveillance import detecter_changements_navires
    from django.utils import timezone

    maintenant = timezone.now()
    logger.info(f"🛰️ [SURVEILLANCE AUTO] Démarrage à {maintenant.strftime('%d/%m/%Y %H:%M:%S')}")

    try:
        # 1. Synchroniser depuis le site EPB
        logger.info("📡 Synchronisation avec le site EPB...")
        call_command('import_epb', verbosity=0)

        # 2. Détecter les changements
        logger.info("🔍 Détection des changements...")
        changements = detecter_changements_navires()

        # 3. Logger le résumé
        logger.info(
            f"✅ [SURVEILLANCE AUTO] Résumé : "
            f"{len(changements['entrees_rade'])} entrées rade, "
            f"{len(changements['entrees_quai'])} entrées quai, "
            f"{len(changements['sorties_quai'])} sorties quai, "
            f"{len(changements['sorties_port'])} sorties port"
        )

        return changements

    except Exception as e:
        logger.error(f"❌ [SURVEILLANCE AUTO] Erreur : {e}")
        import traceback
        traceback.print_exc()
        return None


def demarrer_surveillance():
    """Démarre le scheduler de surveillance en arrière-plan."""
    global _scheduler

    with _lock:
        if _scheduler is not None and _scheduler.running:
            logger.info("ℹ️ [SURVEILLANCE AUTO] Scheduler déjà en cours d'exécution")
            return _scheduler

        try:
            _scheduler = BackgroundScheduler()

            # Ajouter la tâche : toutes les 5 minutes
            _scheduler.add_job(
                executer_surveillance,
                trigger=IntervalTrigger(minutes=5),
                id='surveillance_epb',
                name='Surveillance EPB 24/7',
                replace_existing=True,
                max_instances=1,
                misfire_grace_time=60,
            )

            _scheduler.start()
            logger.info("✅ [SURVEILLANCE AUTO] Scheduler démarré (toutes les 5 minutes)")

            return _scheduler

        except Exception as e:
            logger.error(f"❌ [SURVEILLANCE AUTO] Erreur démarrage : {e}")
            return None


def arreter_surveillance():
    """Arrête le scheduler."""
    global _scheduler
    with _lock:
        if _scheduler and _scheduler.running:
            _scheduler.shutdown()
            logger.info("🛑 [SURVEILLANCE AUTO] Scheduler arrêté")
            _scheduler = None