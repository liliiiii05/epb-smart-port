# port/management/commands/corriger_etats.py

from django.core.management.base import BaseCommand
from port.models import Navire, Quai

class Command(BaseCommand):
    help = "Corrige les incohérences d'état des navires"

    def handle(self, *args, **options):
        # 1. Navires marqués 'quai' sans quai attribué -> remettre en 'rade'
        for n in Navire.objects.filter(etat='quai', quai_attribue=None):
            n.etat = 'rade'
            n.save()
            self.stdout.write(f"  {n.nom} : quai manquant -> rade")

        # 2. Navires marqués 'quai' mais avec une date de début trop ancienne
        #    (par exemple, début < aujourd'hui - 7 jours) -> à investiguer
        #    Ici, on ne fait rien, mais on affiche un avertissement.

        # 3. Navires marqués 'rade' sans arrivee_datetime -> mettre en attente
        for n in Navire.objects.filter(etat='rade', arrivee_datetime__isnull=True):
            n.etat = 'attente'
            n.save()
            self.stdout.write(f"  {n.nom} : arrivée inconnue -> attente")

        # 4. Navires marqués 'attente' avec arrivee_datetime dépassé de +24h -> passer en rade
        #    (à exécuter manuellement ou via une tâche périodique)
        #    Ici, on peut le faire manuellement.