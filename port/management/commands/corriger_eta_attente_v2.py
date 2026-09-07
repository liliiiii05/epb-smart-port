from django.core.management.base import BaseCommand
from port.models import Navire
import random
from datetime import datetime

class Command(BaseCommand):
    help = "Corrige les heures d'arrivée (ETA) des navires en attente pour éviter 00:00"

    def handle(self, *args, **options):
        now = datetime.now()
        heure_actuelle = now.hour + now.minute / 60
        navires = Navire.objects.filter(etat='attente')
        if not navires:
            self.stdout.write("Aucun navire en attente.")
            return

        modif = 0
        for n in navires:
            # Si l'heure est 0, 24, 48, etc. (multiple de 24)
            if n.arrivee % 24 == 0:
                # Heure réaliste : entre maintenant + 2h et maintenant + 48h
                delta = random.uniform(2, 48)
                nouvelle_heure = heure_actuelle + delta
                n.arrivee = nouvelle_heure
                n.save()
                self.stdout.write(f"{n.nom} → arrivee = {n.arrivee:.1f}h (était {n.arrivee})")
                modif += 1
            else:
                self.stdout.write(f"{n.nom} : déjà {n.arrivee:.1f}h (gardé)")

        self.stdout.write(self.style.SUCCESS(f"Correction terminée : {modif} navires mis à jour."))