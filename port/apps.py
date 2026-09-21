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
        if any(cmd in sys.argv for cmd in ['migrate', 'makemigrations', 'test', 
                                            'collectstatic', 'shell', 'dbshell', 
                                            'createsuperuser', 'dumpdata', 'loaddata']):
            return
        
        if os.environ.get('SURVEILLANCE_ENABLED', 'true').lower() == 'false':
            return
        
        if os.environ.get('RUN_MAIN') == 'false':
            return
        
        try:
            from port.services.surveillance_auto import demarrer_surveillance
            demarrer_surveillance()
        except Exception as e:
            logger.error(f"Erreur démarrage surveillance : {e}")