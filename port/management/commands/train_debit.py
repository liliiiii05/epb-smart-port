from django.core.management.base import BaseCommand
from port.models import HistoriqueOperation
from port.ml_debit import DebitModel

class Command(BaseCommand):
    help = "Entraîne le modèle de prédiction du débit (tonnes/heure)"

    def handle(self, *args, **options):
        self.stdout.write("🔄 Entraînement du modèle de débit...")
        historique = HistoriqueOperation.objects.exclude(debit_reel__isnull=True).exclude(debit_reel=0)
        if historique.count() < 30:
            self.stdout.write(self.style.WARNING(
                f"⚠️ Données insuffisantes : {historique.count()} enregistrements (min 30)"
            ))
            return
        model = DebitModel()
        if model.entrainer(historique):
            self.stdout.write(self.style.SUCCESS("✅ Modèle de débit entraîné"))
        else:
            self.stdout.write(self.style.ERROR("❌ Échec de l'entraînement"))