# port/management/commands/train_ml.py
from django.core.management.base import BaseCommand
from port.models import HistoriqueOperation
from port.ml_model import DureeTraitementModel

class Command(BaseCommand):
    help = "Entraîne le modèle ML pour la durée de traitement"

    def handle(self, *args, **options):
        self.stdout.write("🔄 Entraînement du modèle ML...")
        historique = HistoriqueOperation.objects.all()
        if historique.count() < 30:
            self.stdout.write(self.style.WARNING(
                f"⚠️ Données insuffisantes : {historique.count()} enregistrements (min 30)"
            ))
            return

        model = DureeTraitementModel()
        if model.entrainer(historique):
            self.stdout.write(self.style.SUCCESS("✅ Modèle ML entraîné"))
        else:
            self.stdout.write(self.style.ERROR("❌ Échec de l'entraînement"))