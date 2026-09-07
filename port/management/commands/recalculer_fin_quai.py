# port/management/commands/recalculer_fin_quai.py

from django.core.management.base import BaseCommand
from port.models import Navire, Quai
from datetime import datetime, timedelta

class Command(BaseCommand):
    help = "Recalcule l'heure de fin des navires à quai avec les coefficients (quai, marchandise)."

    def handle(self, *args, **options):
        for n in Navire.objects.filter(etat='quai', heure_debut__isnull=False):
            # Récupérer le quai associé (pour avoir sa performance)
            quai = n.quai_attribue
            if quai is None:
                # Si pas de quai, on ne peut pas calculer
                continue

            volume = n.marchandise_volume

            # Taux de base
            taux_base = {
                'conteneur': 50,
                'cerealier': 300,
                'ferry': 50,
                'gazier': 200,
                'frigorifique': 30,
                'betail': 100,
                'essence': 200,
                'huilier': 200,
                'petrolier': 200,
                'cargo': 200,
                'roulier': 150,
                'chimiquier': 150,
            }.get(n.type, 150)

            coeff_quai = quai.performance

            coeff_marchandise = 1.0
            if n.marchandise_dangereuse:
                coeff_marchandise *= 0.8
            if n.marchandise_frigo:
                coeff_marchandise *= 0.9
            if n.marchandise_type and "VRAC" in n.marchandise_type.upper():
                coeff_marchandise *= 1.2
            elif n.marchandise_type and "BOIS" in n.marchandise_type.upper():
                coeff_marchandise *= 0.8

            taux_effectif = taux_base * coeff_quai * coeff_marchandise

            if volume > 0:
                duree = volume / taux_effectif
            else:
                duree = 1.0

            n.heure_fin = n.heure_debut + duree
            n.save()
            self.stdout.write(f"{n.nom} : fin = {n.heure_fin:.1f}h (taux={taux_effectif:.1f} t/h)")

        self.stdout.write(self.style.SUCCESS("Recalcul terminé."))