# port/management/commands/simuler_pannes.py
import random
import time
from django.core.management.base import BaseCommand
from django.utils import timezone
from port.models import Equipement, Navire
from port.views import replanifier_apres_panne, get_equipements_necessaires_par_type

class Command(BaseCommand):
    help = "Simule des pannes aléatoires sur les équipements utilisés par les navires actifs"

    def add_arguments(self, parser):
        parser.add_argument('--prob', type=float, default=0.1, help='Probabilité de panne par équipement')
        parser.add_argument('--duree', type=float, default=2.0, help='Durée de réparation (heures)')
        parser.add_argument('--loop', action='store_true', help='Exécuter en boucle continue')

    def handle(self, *args, **options):
        prob = options['prob']
        duree = options['duree']
        loop = options['loop']
        
        if loop:
            self.stdout.write("🔁 Mode boucle active (Ctrl+C pour arrêter)")
            try:
                while True:
                    self.simuler(prob, duree)
                    time.sleep(3600)  # toutes les heures
            except KeyboardInterrupt:
                self.stdout.write("\n🛑 Arrêt de la simulation")
        else:
            self.simuler(prob, duree)

    def simuler(self, prob, duree):
        # Récupérer les types d'équipements nécessaires aux navires actifs
        navires_actifs = Navire.objects.filter(etat__in=['rade', 'quai'])
        equipements_utilises = set()
        for navire in navires_actifs:
            for eq in get_equipements_necessaires_par_type(navire.type):
                equipements_utilises.add(eq)
        
        # Ne simuler les pannes que sur ces équipements
        equipements_cibles = Equipement.objects.filter(type__in=equipements_utilises, en_panne=False)
        
        panne_declenchee = False
        for eq in equipements_cibles:
            if random.random() < prob:
                eq.en_panne = True
                eq.temps_reparation = duree
                eq.panne_debut = timezone.now()
                eq.save()
                self.stdout.write(f"🔧 PANNE : {eq.type} en panne pour {duree}h")
                panne_declenchee = True
                # Replanification
                session = replanifier_apres_panne(eq)
                if session:
                    self.stdout.write(f"   → Replanification effectuée (session #{session.id})")
                else:
                    self.stdout.write(f"   → Aucun navire impacté")
        
        if not panne_declenchee:
            self.stdout.write("✅ Aucune panne déclenchée")