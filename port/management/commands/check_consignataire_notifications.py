from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from port.models import Navire, NotificationConsignataire
from django.contrib.auth.models import User

class Command(BaseCommand):
    help = 'Vérifie les changements d’état et les fins de navires pour générer des notifications'

    def handle(self, *args, **options):
        now = timezone.now()
        # Récupérer tous les consignataires
        consignataires = User.objects.filter(groups__name='Consignataire')
        
        # Pour chaque consignataire, on regarde ses navires
        for user in consignataires:
            navires = Navire.objects.filter(agent=user.username)  # ou user.first_name selon votre mapping
            
            for navire in navires:
                # --- 1) Navire à quai : fin dans moins de 30 minutes ---
                if navire.etat == 'quai' and navire.heure_fin:
                    fin_datetime = navire.fin_datetime if hasattr(navire, 'fin_datetime') else None
                    if not fin_datetime:
                        # recalculer à partir de heure_fin (décimal) + date de début
                        if navire.debut_datetime:
                            fin_datetime = navire.debut_datetime + timedelta(hours=navire.heure_fin)
                    if fin_datetime:
                        temps_restant = (fin_datetime - now).total_seconds() / 60
                        if 0 < temps_restant <= 30:
                            self.creer_notification(
                                user, navire,
                                f"Le navire {navire.nom} sera terminé dans moins de 30 minutes.",
                                'warning'
                            )
                
                # --- 2) Navire à quai : terminé (fin passée) ---
                if navire.etat == 'quai' and navire.heure_fin:
                    fin_datetime = ... # même calcul
                    if fin_datetime and fin_datetime <= now:
                        # Vérifier qu'on n'a pas déjà notifié la fin
                        if not NotificationConsignataire.objects.filter(
                            consignataire=user, navire=navire, message__icontains='terminé'
                        ).exists():
                            self.creer_notification(
                                user, navire,
                                f"Le navire {navire.nom} a terminé son opération à quai.",
                                'success'
                            )
                
                # --- 3) Transition d'état (attente -> rade, rade -> quai, etc.) ---
                # Pour cela, il faut conserver l'état précédent. Soit on le stocke dans un champ du navire,
                # soit on compare avec le dernier historique. On peut ajouter un champ `dernier_etat_notifie`.
                # Simplification : comparer avec la dernière affectation ou avec un historique simple.
                # Nous allons ajouter un champ `etat_precedent` dans le modèle Navire.
                if hasattr(navire, 'etat_precedent') and navire.etat_precedent != navire.etat:
                    if navire.etat_precedent == 'attente' and navire.etat == 'rade':
                        msg = f"Le navire {navire.nom} est maintenant en rade."
                        type_notif = 'info'
                    elif navire.etat_precedent == 'rade' and navire.etat == 'quai':
                        msg = f"Le navire {navire.nom} a accosté."
                        type_notif = 'success'
                    elif navire.etat_precedent == 'quai' and navire.etat == 'termine':
                        msg = f"Le navire {navire.nom} est terminé."
                        type_notif = 'success'
                    else:
                        msg = f"Le navire {navire.nom} est passé à l'état {navire.get_etat_display()}."
                        type_notif = 'info'
                    self.creer_notification(user, navire, msg, type_notif)
                    # Mettre à jour l'état précédent
                    navire.etat_precedent = navire.etat
                    navire.save(update_fields=['etat_precedent'])

        self.stdout.write(self.style.SUCCESS('Notifications générées'))

    def creer_notification(self, user, navire, message, notif_type):
        # Éviter les doublons récents (dans les 5 minutes)
        recent = NotificationConsignataire.objects.filter(
            consignataire=user, navire=navire, message=message,
            date_creation__gte=timezone.now() - timedelta(minutes=5)
        ).exists()
        if not recent:
            NotificationConsignataire.objects.create(
                consignataire=user,
                navire=navire,
                message=message,
                type=notif_type
            )