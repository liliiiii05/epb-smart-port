# port/management/commands/clean_equipements.py
from django.core.management.base import BaseCommand
from port.models import Equipement, Navire
from port.views import get_equipements_necessaires_par_type

class Command(BaseCommand):
    help = "Nettoie la base d'équipements : supprime les équipements non pertinents, recalcule les disponibilités"

    def handle(self, *args, **options):
        # Liste des types d'équipements à conserver (ceux qui peuvent être utilisés par les navires)
        types_pertinents = {
            # Céréalier
            "suceuse_cereales", "convoyeur_bande", "tracteur_remorque_50t",
            # Pétrolier
            "bras_chargement_petrolier", "pompe_haute_capacite", "systeme_anti_deflagrant",
            # Conteneur
            "grue_gottwald_260e", "reach_stacker", "chariot_32t",
            # Cargo / général
            "grue_mobile_50t", "chariot_10t",
            # Essence
            "bras_chargement_essence", "pompe_anti_deflagrante", "systeme_recuperation_vapeur",
            # Gazier
            "bras_chargement_gnl", "tuyauterie_cryogenique",
            # Huilier
            "bras_chargement_huile", "pompe_alimentaire", "filtre",
            # Ferry / Bétail
            "passerelle_acces", "systeme_amarrage_rapide", "rampe_chargement", "systeme_ventilation", "abreuvement",
            # Chariots
            "chariot_pince", "chariot_fourche",
            # Grues
            "grue_portuaire", "grue_telescopique", "portique_grains", "chargeur_pneus", "pelle_chenille",
            "pelle_chargeuse_excavatrice", "tracteur_semi_remorque", "tracteur_roro", "plateau_remorque",
            "benne_motorisee_lame", "benne_motorisee_dent", "benne_hydroelectrique", "spreader_auto",
            "grappin_motorise", "plateaux_semi-remorque_03_essieux", "chariot_elec", "pont_bascule",
        }

        # Supprimer les équipements non pertinents
        deleted_count = Equipement.objects.exclude(type__in=types_pertinents).delete()[0]
        self.stdout.write(f"🗑️ Supprimé {deleted_count} équipements non pertinents.")

        # Récupérer les navires à quai
        navires_quai = Navire.objects.filter(etat='quai')
        utilisation = {}
        for navire in navires_quai:
            if navire.a_grue_bord:
                continue
            equipements = get_equipements_necessaires_par_type(navire.type)
            for eq_type in equipements:
                utilisation[eq_type] = utilisation.get(eq_type, 0) + 1

        # Mettre à jour chaque équipement restant
        updated = 0
        for eq in Equipement.objects.all():
            utilises = utilisation.get(eq.type, 0)
            eq.disponibles = eq.nombre - utilises
            if eq.en_panne:
                eq.disponibles = max(0, eq.disponibles - 1)   # un exemplaire en panne
            else:
                eq.disponibles = max(0, eq.disponibles)
            eq.save()
            updated += 1
            self.stdout.write(f"   {eq.type}: total={eq.nombre}, utilisés={utilises}, disponibles={eq.disponibles}")

        self.stdout.write(self.style.SUCCESS(f"✅ {updated} équipements mis à jour."))