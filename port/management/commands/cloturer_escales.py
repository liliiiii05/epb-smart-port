# port/management/commands/cloturer_escales.py
"""
Commande pour clôturer automatiquement les escales des navires
qui ont quitté le port (état = 'termine').
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from port.models import Escale
from port.utils_escales import cloturer_escale


class Command(BaseCommand):
    help = "Cloture les escales des navires qui ont quitte le port"
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--heures',
            type=int,
            default=168,
            help="Delai maximum en heures avant cloture forcee (defaut: 168h = 7 jours)"
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="Simulation sans modification"
        )
        parser.add_argument(
            '--navire',
            type=str,
            default=None,
            help="Cloturer uniquement les escales d'un navire specifique (par nom)"
        )
    
    def handle(self, *args, **options):
        heures_max = options['heures']
        dry_run = options['dry_run']
        nom_navire = options['navire']
        
        self.stdout.write("=" * 60)
        self.stdout.write("CLOTURE DES ESCALES")
        self.stdout.write("=" * 60)
        
        escales_query = Escale.objects.filter(active=True).select_related('navire')
        
        if nom_navire:
            escales_query = escales_query.filter(navire__nom__icontains=nom_navire)
            self.stdout.write(f"Filtre navire : {nom_navire}")
        
        escales_actives = escales_query.all()
        self.stdout.write(f"Escales actives trouvees : {escales_actives.count()}")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("MODE DRY-RUN (aucune modification)"))
        
        nb_cloturees = 0
        nb_ignorees = 0
        
        for escale in escales_actives:
            navire = escale.navire
            
            doit_cloturer = False
            raison = ""
            
            if navire.etat == 'termine':
                doit_cloturer = True
                raison = "Navire termine"
            elif navire.etat not in ['attente', 'rade', 'quai']:
                doit_cloturer = True
                raison = f"Etat inconnu ({navire.etat})"
            else:
                ecart = (timezone.now() - escale.date_debut).total_seconds() / 3600
                if ecart > heures_max:
                    doit_cloturer = True
                    raison = f"Escale inactive depuis {ecart:.1f}h (>{heures_max}h)"
            
            if doit_cloturer:
                if dry_run:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [DRY-RUN] Cloturerait escale {escale.id} "
                            f"({navire.nom}) - {raison}"
                        )
                    )
                else:
                    result = cloturer_escale(navire)
                    if result:
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  [OK] Escale {escale.id} cloturee "
                                f"({navire.nom}) - {raison}"
                            )
                        )
                        self.stdout.write(
                            f"        Attente: {result.attente_totale:.1f}h | "
                            f"Duree: {result.duree_reelle:.1f}h | "
                            f"Debit: {result.debit_reel:.1f} t/h"
                        )
                        nb_cloturees += 1
                    else:
                        self.stdout.write(
                            self.style.ERROR(
                                f"  [ERREUR] Impossible de cloturer l'escale {escale.id}"
                            )
                        )
            else:
                nb_ignorees += 1
        
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write("RESUME")
        self.stdout.write("=" * 60)
        self.stdout.write(f"Escales cloturees : {nb_cloturees}")
        self.stdout.write(f"Escales ignorees  : {nb_ignorees}")
        self.stdout.write(f"Total traite      : {len(escales_actives)}")
        
        self.stdout.write("")
        stats = Escale.objects.all()
        self.stdout.write(f"Escales totales   : {stats.count()}")
        self.stdout.write(f"Escales actives   : {stats.filter(active=True).count()}")
        self.stdout.write(f"Escales cloturees : {stats.filter(active=False).count()}")
        
        if not dry_run and nb_cloturees > 0:
            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(f"[OK] {nb_cloturees} escale(s) cloturee(s)")
            )