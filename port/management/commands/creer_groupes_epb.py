from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from port.models import Navire

class Command(BaseCommand):
    help = 'Crée les groupes et attribue les permissions pour l\'EPB'

    def handle(self, *args, **options):
        # Récupérer toutes les permissions de l'application 'port'
        permissions = Permission.objects.filter(content_type__app_label='port')

        # Création des groupes
        groupes = {
            'Officier_port': ['can_manage_cpn', 'can_optimize', 'can_export', 'can_finish_ships',
                              'can_view_dashboard', 'can_view_lists', 'can_view_ship_details',
                              'can_view_history', 'can_view_stats'],
            'Officier_radio': ['can_validate_arrival', 'can_execute_decision', 'can_load_announcements',
                               'can_view_lists', 'can_view_ship_details', 'can_view_dashboard',
                               'can_view_history', 'can_view_cpn'],
            'Gestionnaire_escales': ['can_load_announcements', 'can_edit_ship', 'can_manage_cpn',
                                     'can_view_lists', 'can_view_ship_details', 'can_view_dashboard',
                                     'can_view_history', 'can_view_stats'],
            'Directeur': [p.codename for p in permissions],  # toutes les permissions
        }

        for group_name, perms in groupes.items():
            group, created = Group.objects.get_or_create(name=group_name)
            if created:
                self.stdout.write(f"Groupe '{group_name}' créé.")
            else:
                self.stdout.write(f"Groupe '{group_name}' existe déjà.")

            # Ajouter les permissions
            for codename in perms:
                try:
                    perm = Permission.objects.get(codename=codename)
                    group.permissions.add(perm)
                except Permission.DoesNotExist:
                    self.stdout.write(self.style.WARNING(f"Permission {codename} non trouvée."))

        self.stdout.write(self.style.SUCCESS("Groupes et permissions configurés."))