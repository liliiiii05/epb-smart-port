# port/management/commands/entrainer_ia_attente.py
"""
Commande pour entraîner le modèle Random Forest de prédiction d'attente.
Utilise les escales archivées (archive=True).
"""
from django.core.management.base import BaseCommand
from port.ml_attente import AttentePredictor


class Command(BaseCommand):
    help = "Entraine le modele Random Forest de prediction d'attente"
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--test-size',
            type=float,
            default=0.2,
            help="Proportion du test set (defaut: 0.2)"
        )
        parser.add_argument(
            '--min-exemples',
            type=int,
            default=5,
            help="Nombre minimum d'exemples pour entrainer (defaut: 5)"
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help="Forcer l'entrainement meme si peu de donnees"
        )
    
    def handle(self, *args, **options):
        test_size = options['test_size']
        min_exemples = options['min_exemples']
        force = options['force']
        
        self.stdout.write("=" * 60)
        self.stdout.write("ENTRAINEMENT DU MODELE IA")
        self.stdout.write("=" * 60)
        
        # 1. Charger le dataset
        self.stdout.write("")
        self.stdout.write("Chargement du dataset...")
        
        from port.utils_escales import construire_dataset_attentes
        df = construire_dataset_attentes()
        
        if df is None or df.empty:
            self.stdout.write(self.style.ERROR("Dataset vide"))
            return
        
        self.stdout.write(f"Dataset : {len(df)} exemples")
        
        # 2. Verifier le nombre minimum
        if len(df) < min_exemples and not force:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"Seulement {len(df)} exemples (< {min_exemples})"
                )
            )
            self.stdout.write(
                "Utilisez --force pour entrainer malgre tout, ou attendez "
                "d'avoir plus d'escales cloturees."
            )
            return
        
        # 3. Afficher un apercu
        self.stdout.write("")
        self.stdout.write("Apercu du dataset :")
        self.stdout.write(f"  Colonnes : {list(df.columns)}")
        self.stdout.write(f"  Types de navires : {df['type_navire'].value_counts().to_dict()}")
        
        if 'duree_attente' in df.columns:
            self.stdout.write(
                f"  Attente : min={df['duree_attente'].min()}h, "
                f"max={df['duree_attente'].max()}h, "
                f"moy={df['duree_attente'].mean():.1f}h"
            )
        
        # 4. Entrainer
        self.stdout.write("")
        self.stdout.write("Entrainement en cours...")
        
        predictor = AttentePredictor()
        metrics = predictor.entrainer(df=df, test_size=test_size)
        
        # 5. Afficher les resultats
        self.stdout.write("")
        
        if 'error' in metrics:
            self.stdout.write(
                self.style.ERROR(
                    f"Erreur : {metrics['error']} (taille: {metrics.get('size', 0)})"
                )
            )
            return
        
        self.stdout.write("=" * 60)
        self.stdout.write("RESULTATS DE L'ENTRAINEMENT")
        self.stdout.write("=" * 60)
        self.stdout.write(f"Exemples totaux : {metrics['nb_exemples']}")
        self.stdout.write(f"Train           : {metrics['nb_train']}")
        self.stdout.write(f"Test            : {metrics['nb_test']}")
        self.stdout.write(f"MAE             : {metrics['mae']} heures")
        self.stdout.write(f"R2              : {metrics['r2']}")
        self.stdout.write("")
        
        # 6. Evaluation qualitative
        if metrics['r2'] > 0.7:
            self.stdout.write(self.style.SUCCESS("Excellent modele !"))
        elif metrics['r2'] > 0.3:
            self.stdout.write(self.style.SUCCESS("Bon modele"))
        elif metrics['r2'] > 0:
            self.stdout.write(self.style.WARNING("Modele faible (peu de donnees)"))
        else:
            self.stdout.write(
                self.style.WARNING(
                    "Modele tres faible - attendez plus de donnees"
                )
            )
        
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS("Modele sauvegarde dans port/ml_models/")
        )