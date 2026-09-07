from django.core.management.base import BaseCommand
from port.alertes import generer_toutes_alertes

class Command(BaseCommand):
    help = "Génère les alertes intelligentes"

    def handle(self, *args, **options):
        generer_toutes_alertes()
        self.stdout.write(self.style.SUCCESS("✅ Alertes générées"))