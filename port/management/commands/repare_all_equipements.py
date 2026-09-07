# port/management/commands/repare_all_equipements.py
from django.core.management.base import BaseCommand
from port.models import Equipement

class Command(BaseCommand):
    help = "Réparer tous les équipements"

    def handle(self, *args, **options):
        nb = Equipement.objects.filter(en_panne=True).update(en_panne=False, panne_debut=None)
        self.stdout.write(self.style.SUCCESS(f"✅ {nb} équipements réparés."))