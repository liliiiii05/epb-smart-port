from django.core.management.base import BaseCommand
from django.core.management import call_command

class Command(BaseCommand):
    help = "Entraîne tous les modèles de Machine Learning"

    def handle(self, *args, **options):
        self.stdout.write("=" * 60)
        self.stdout.write("🤖 ENTRAÎNEMENT DE TOUS LES MODÈLES ML")
        self.stdout.write("=" * 60)
        
        models = [
            ('train_quai', 'Modèle de choix de quai', 'AffectationQuai'),
            ('train_equipement', 'Modèle de recommandation équipement', 'UtilisationEquipement'),
            ('train_debit', 'Modèle de débit', 'HistoriqueOperation (débit réel)'),
            ('train_debit_shift', 'Modèle de débit par shift', 'HistoriqueOperation (débit shift)'),
            ('train_ml', 'Modèle de durée de traitement', 'HistoriqueOperation'),
        ]
        
        results = []
        for command, name, source in models:
            self.stdout.write(f"\n📊 {name}")
            self.stdout.write(f"   Source: {source}")
            try:
                call_command(command)
                results.append((name, '✅ Succès'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"   ❌ Erreur: {e}"))
                results.append((name, f'❌ Erreur: {e}'))
        
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("📈 RÉSUMÉ DE L'ENTRAÎNEMENT")
        self.stdout.write("=" * 60)
        for name, status in results:
            self.stdout.write(f"  {status} - {name}")
        
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("✅ Processus terminé!"))