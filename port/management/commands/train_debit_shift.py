from django.core.management.base import BaseCommand
from port.models import HistoriqueOperation
from port.ml_debit_shift import DebitShiftModel

class Command(BaseCommand):
    help = "Entraîne le modèle de débit par shift"

    def handle(self, *args, **options):
        self.stdout.write("🔄 Entraînement du modèle de débit par shift...")
        historique = HistoriqueOperation.objects.exclude(debit_shift__isnull=True).exclude(debit_shift=0)
        if historique.count() < 30:
            self.stdout.write(self.style.WARNING(
                f"⚠️ Données insuffisantes : {historique.count()} enregistrements (min 30)"
            ))
            return
        model = DebitShiftModel()
        if model.entrainer(historique):
            self.stdout.write(self.style.SUCCESS("✅ Modèle de débit par shift entraîné"))
        else:
            self.stdout.write(self.style.ERROR("❌ Échec de l'entraînement"))