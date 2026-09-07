# port/management/commands/init_equipements.py
from django.core.management.base import BaseCommand
from port.models import Equipement

class Command(BaseCommand):
    help = "Crée les équipements normalisés nécessaires pour le système"

    def handle(self, *args, **options):
        equipements = [
            # Céréalier
            ("suceuse_cereales", 550, 2),
            ("convoyeur_bande", 550, 2),
            ("tracteur_remorque_50t", 50, 4),
            # Pétrolier
            ("bras_chargement_petrolier", 500, 3),
            ("pompe_haute_capacite", 500, 3),
            ("systeme_anti_deflagrant", 1, 3),
            # Conteneur
            ("grue_gottwald_260e", 260, 2),
            ("reach_stacker", 38, 2),
            ("chariot_32t", 32, 1),
            # Cargo / général
            ("grue_mobile_50t", 50, 2),
            ("chariot_10t", 10, 11),
            # Essence
            ("bras_chargement_essence", 250, 1),
            ("pompe_anti_deflagrante", 250, 1),
            ("systeme_recuperation_vapeur", 1, 1),
            # Gazier
            ("bras_chargement_gnl", 300, 1),
            ("tuyauterie_cryogenique", 1, 1),
            # Huilier
            ("bras_chargement_huile", 250, 1),
            ("pompe_alimentaire", 250, 1),
            ("filtre", 1, 1),
            # Ferry / Bétail (passerelles, amarrage)
            ("passerelle_acces", 1, 3),
            ("systeme_amarrage_rapide", 1, 3),
            ("rampe_chargement", 1, 3),
            ("systeme_ventilation", 1, 2),
            ("abreuvement", 1, 2),
        ]

        created = 0
        updated = 0
        for type_nom, capacite, nombre in equipements:
            obj, is_created = Equipement.objects.update_or_create(
                type=type_nom,
                defaults={
                    'capacite': capacite,
                    'nombre': nombre,
                    'disponibles': nombre,
                    'en_panne': False,
                    'temps_reparation': 2.0
                }
            )
            if is_created:
                created += 1
            else:
                updated += 1
        self.stdout.write(self.style.SUCCESS(f"✅ {created} équipements créés, {updated} mis à jour."))