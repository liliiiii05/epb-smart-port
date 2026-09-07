from django.core.management.base import BaseCommand
from port.models import Navire

class Command(BaseCommand):
    help = "Corrige les heures d'arrivée en rade des navires à quai (arrivee=0)"

    def handle(self, *args, **options):
        navires = Navire.objects.filter(etat='quai', arrivee=0, heure_debut__isnull=False)
        updated = 0
        for n in navires:
            # Estimer l'arrivée en rade : 2h avant début pour cargos, 4h pour céréaliers/pétroliers
            if n.type in ['cerealier', 'petrolier', 'gazier']:
                arrivee_estimee = n.heure_debut - 4
            else:
                arrivee_estimee = n.heure_debut - 2
            if arrivee_estimee < 0:
                arrivee_estimee = 0
            n.arrivee = arrivee_estimee
            n.save()
            updated += 1
            self.stdout.write(f"✅ {n.nom} : arrivee = {arrivee_estimee:.1f}h (début={n.heure_debut:.1f}h)")
        self.stdout.write(self.style.SUCCESS(f"Terminé : {updated} navires mis à jour."))