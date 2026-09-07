from django.core.management.base import BaseCommand
from port.models import AffectationQuai
from port.ml_quai import QuaiChoiceModel

class Command(BaseCommand):
    help = "Entraîne le modèle de choix de quai"

    def handle(self, *args, **options):
        self.stdout.write("🔄 Entraînement du modèle de choix de quai...")
        historique = AffectationQuai.objects.all()
        if historique.count() < 30:
            self.stdout.write(self.style.WARNING(
                f"⚠️ Données insuffisantes : {historique.count()} enregistrements (min 30)"
            ))
            return
        model = QuaiChoiceModel()
        if model.entrainer(historique):
            self.stdout.write(self.style.SUCCESS("✅ Modèle de choix de quai entraîné"))
        else:
            self.stdout.write(self.style.ERROR("❌ Échec de l'entraînement"))