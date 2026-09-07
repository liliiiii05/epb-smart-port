# port/management/commands/recalculer_heures_fin.py
from django.core.management.base import BaseCommand
from port.models import Navire

def estimer_temps_traitement(type_navire, volume):
    volume = float(volume) if volume else 0
    if type_navire == 'conteneur':
        return volume / 50 if volume > 0 else 10
    elif type_navire == 'ferry':
        return 4
    elif type_navire == 'gazier':
        return 24
    elif type_navire == 'frigorifique':
        return volume / 30 if volume > 0 else 12
    elif type_navire == 'essence':
        return volume / 200 if volume > 0 else 8
    elif type_navire == 'betail':
        return 6
    elif type_navire == 'cerealier':
        return volume / 300 if volume > 0 else 20
    elif type_navire == 'petrolier':
        return 12
    elif type_navire == 'huilier':
        return 8
    else:
        return 12

class Command(BaseCommand):
    help = 'Recalcule les heures de fin pour les navires à quai'

    def handle(self, *args, **options):
        navires = Navire.objects.filter(etat='quai', heure_debut__isnull=False, heure_fin__isnull=True)
        updated = 0
        for n in navires:
            traitement = estimer_temps_traitement(n.type, n.marchandise_volume)
            if traitement:
                n.heure_fin = n.heure_debut + traitement
                n.save()
                updated += 1
                self.stdout.write(f"✅ {n.nom} : fin = {n.heure_fin:.1f}h")
        self.stdout.write(self.style.SUCCESS(f"Terminé : {updated} navires mis à jour."))