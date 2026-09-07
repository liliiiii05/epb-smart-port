from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from port.models import Navire, Quai

class Command(BaseCommand):
    help = "Termine automatiquement les navires dont la fin est dépassée"

    def handle(self, *args, **options):
        now = timezone.now()
        navires_a_terminer = Navire.objects.filter(
            etat='quai',
            heure_fin__isnull=False,
            quai_attribue__isnull=False
        )
        count = 0
        for navire in navires_a_terminer:
            if navire.debut_datetime:
                fin = navire.debut_datetime + timedelta(hours=navire.heure_fin - navire.heure_debut)
                if fin <= now:
                    quai = navire.quai_attribue
                    quai.disponible = True
                    quai.occupation_jusqua = 0.0
                    quai.save()
                    navire.etat = 'termine'
                    navire.quai_attribue = None
                    navire.save()
                    count += 1
        self.stdout.write(self.style.SUCCESS(f"✅ {count} navires terminés automatiquement."))