from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from port.models import Equipement

class Command(BaseCommand):
    help = "Réparer les équipements dont le temps de réparation est écoulé"

    def handle(self, *args, **options):
        maintenant = timezone.now()
        equipements = Equipement.objects.filter(en_panne=True)
        repares = 0
        for eq in equipements:
            if eq.panne_debut and eq.panne_debut + timedelta(hours=eq.temps_reparation) <= maintenant:
                eq.en_panne = False
                eq.panne_debut = None
                eq.save()
                repares += 1
                self.stdout.write(f"🛠️ {eq.type} réparé")
        
        if repares == 0:
            self.stdout.write("✅ Aucun équipement à réparer")