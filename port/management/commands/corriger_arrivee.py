from django.core.management.base import BaseCommand
from port.models import Navire
import random

class Command(BaseCommand):
    help = "Corrige les heures d'arrivée des navires qui en sont dépourvus"

    def handle(self, *args, **options):
        # Navires en attente avec arrivee=0
        attente = Navire.objects.filter(etat='attente', arrivee=0)
        for n in attente:
            # Heure réaliste entre 2h et 48h
            n.arrivee = random.uniform(2, 48)
            n.save()
            self.stdout.write(f"{n.nom} (attente) → arrivee = {n.arrivee:.1f}h")

        # Navires à quai avec arrivee=0 (mais ayant heure_debut)
        quai = Navire.objects.filter(etat='quai', arrivee=0, heure_debut__isnull=False)
        for n in quai:
            # Estimation simple
            attente_estimee = 2 if n.type == 'cargo' else (4 if n.type == 'cerealier' else 3)
            n.arrivee = max(0, n.heure_debut - attente_estimee)
            n.save()
            self.stdout.write(f"{n.nom} (quai) → arrivee = {n.arrivee:.1f}h (début à {n.heure_debut:.1f}h)")

        # Navires en rade avec arrivee=0 (normalement ne devrait pas arriver après import)
        rade = Navire.objects.filter(etat='rade', arrivee=0)
        for n in rade:
            n.arrivee = random.uniform(0, 24)
            n.save()
            self.stdout.write(f"{n.nom} (rade) → arrivee = {n.arrivee:.1f}h")

        self.stdout.write(self.style.SUCCESS("Correction terminée."))