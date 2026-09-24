# port/apps.py
from django.apps import AppConfig
import os
import sys
import logging

logger = logging.getLogger(__name__)


class PortConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'port'

    def ready(self):
        """Démarre la surveillance automatique."""
        
        # ✅ 1. Ne PAS démarrer pour les commandes de gestion
        if any(cmd in sys.argv for cmd in ['migrate', 'makemigrations', 'test', 
                                            'collectstatic', 'shell', 'dbshell', 
                                            'createsuperuser', 'dumpdata', 'loaddata']):
            return
        
        # ✅ 2. Ne PAS démarrer sur Render (cron-job.org s'en charge)
        #    ⚠️ On garde le scheduler UNIQUEMENT en local pour tester
        if os.environ.get('RENDER'):
            logger.info("🚫 [SCHEDULER] Désactivé sur Render (cron-job.org actif)")
            print("🚫 [SCHEDULER] Désactivé sur Render (cron-job.org gère le scraping)")
            return
        
        # ✅ 3. Permettre la désactivation manuelle en local
        if os.environ.get('SURVEILLANCE_ENABLED', 'true').lower() == 'false':
            print("⏸️ [SCHEDULER] Désactivé manuellement")
            return
        
        # ✅ 4. Éviter le double démarrage avec Django autoreload
        if os.environ.get('RUN_MAIN') == 'false':
            return
        
        try:
            from port.services.surveillance_auto import demarrer_surveillance
            demarrer_surveillance()
            print("🛰️ [SCHEDULER] Surveillance automatique démarrée (local)")
        except Exception as e:
            logger.error(f"Erreur démarrage surveillance : {e}")