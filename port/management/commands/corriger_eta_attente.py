from django.core.management.base import BaseCommand
from port.models import Navire
import random
from datetime import datetime

class Command(BaseCommand):
    help = "Corrige les heures d'arrivée (ETA) des navires en attente pour qu'elles soient réalistes"

    def handle(self, *args, **options):
        now = datetime.now()
        heure_actuelle = now.hour + now.minute / 60
        navires = Navire.objects.filter(etat='attente')
        if not navires:
            self.stdout.write("Aucun navire en attente.")
            return

        for n in navires:
            # Si l'heure d'arrivée est 0, 24, ou une heure trop tôt/tard, on la remplace
            if n.arrivee <= 1 or n.arrivee >= 23:
                # Heure réaliste : entre maintenant + 2h et maintenant + 48h
                delta = random.uniform(2, 48)
                n.arrivee = heure_actuelle + delta
                n.save()
                self.stdout.write(f"{n.nom} → arrivee = {n.arrivee:.1f}h")
            else:
                self.stdout.write(f"{n.nom} : déjà {n.arrivee:.1f}h (gardé)")

        self.stdout.write(self.style.SUCCESS("Correction terminée."))