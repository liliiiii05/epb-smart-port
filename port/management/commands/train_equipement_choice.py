from django.core.management.base import BaseCommand
from port.models import UtilisationEquipement
from port.ml_equipement import EquipementChoiceModel

class Command(BaseCommand):
    help = "Entraîne le modèle de recommandation d'équipement"

    def handle(self, *args, **options):
        self.stdout.write("🔄 Entraînement du modèle de recommandation...")
        utilisations = UtilisationEquipement.objects.all()
        if utilisations.count() < 30:
            self.stdout.write(self.style.WARNING(
                f"⚠️ Données insuffisantes : {utilisations.count()} enregistrements (min 30)"
            ))
            return
        model = EquipementChoiceModel()
        if model.entrainer(utilisations):
            self.stdout.write(self.style.SUCCESS("✅ Modèle de recommandation entraîné"))
        else:
            self.stdout.write(self.style.ERROR("❌ Échec de l'entraînement"))