# port/signals.py
from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from .models import Navire, NotificationConsignataire, Affectation
from .views import synchroniser_occupation_postes
import logging

logger = logging.getLogger(__name__)

@receiver(pre_save, sender=Navire)
def stocker_ancien_etat(sender, instance, **kwargs):
    """Stocke l'état actuel (avant modification) dans un attribut temporaire."""
    if instance.pk:
        try:
            instance._ancien_etat = Navire.objects.get(pk=instance.pk).etat
        except Navire.DoesNotExist:
            instance._ancien_etat = None
    else:
        instance._ancien_etat = None

@receiver(post_save, sender=Navire)
def verifier_changement_etat_et_fin(sender, instance, created, **kwargs):
    """
    Détecte les changements d'état et crée des notifications.
    """
    if created:
        return

    ancien_etat = getattr(instance, '_ancien_etat', None)
    if ancien_etat is None:
        return

    if ancien_etat == instance.etat:
        return

    if not instance.agent:
        return

    try:
        consignataire = User.objects.get(username=instance.agent)
    except User.DoesNotExist:
        return

    # --- Transition d'état ---
    if ancien_etat == 'attente' and instance.etat == 'rade':
        msg = f"Le navire {instance.nom} est maintenant en rade."
        notif_type = 'info'
    elif ancien_etat == 'rade' and instance.etat == 'quai':
        msg = f"Le navire {instance.nom} a accosté."
        notif_type = 'success'
    elif ancien_etat == 'quai' and instance.etat == 'termine':
        msg = f"Le navire {instance.nom} est terminé."
        notif_type = 'success'
    else:
        msg = f"Le navire {instance.nom} est passé à l'état {instance.get_etat_display()}."
        notif_type = 'info'

    # Éviter les doublons dans la dernière minute
    if not NotificationConsignataire.objects.filter(
        consignataire=consignataire,
        navire=instance,
        message=msg,
        date_creation__gte=timezone.now() - timedelta(minutes=1)
    ).exists():
        NotificationConsignataire.objects.create(
            consignataire=consignataire,
            navire=instance,
            message=msg,
            type=notif_type
        )

    # --- Fin imminente (moins de 30 minutes) ---
    if instance.etat == 'quai' and instance.heure_fin is not None:
        if instance.debut_datetime:
            fin_datetime = instance.debut_datetime + timedelta(hours=instance.heure_fin)
            maintenant = timezone.now()
            temps_restant = (fin_datetime - maintenant).total_seconds() / 60

            if 0 < temps_restant <= 30:
                msg = f"Le navire {instance.nom} sera terminé dans moins de 30 minutes."
                if not NotificationConsignataire.objects.filter(
                    consignataire=consignataire,
                    navire=instance,
                    message__icontains='terminé dans moins de 30 minutes',
                    date_creation__gte=timezone.now() - timedelta(minutes=30)
                ).exists():
                    NotificationConsignataire.objects.create(
                        consignataire=consignataire,
                        navire=instance,
                        message=msg,
                        type='warning'
                    )

            # Terminé (fin dépassée)
            if fin_datetime <= maintenant:
                if instance.etat != 'termine':
                    msg = f"Le navire {instance.nom} a terminé son opération à quai (heure prévue dépassée)."
                    if not NotificationConsignataire.objects.filter(
                        consignataire=consignataire,
                        navire=instance,
                        message=msg,
                        date_creation__gte=timezone.now() - timedelta(hours=1)
                    ).exists():
                        NotificationConsignataire.objects.create(
                            consignataire=consignataire,
                            navire=instance,
                            message=msg,
                            type='success'
                        )


@receiver(post_save, sender=Affectation)
@receiver(post_delete, sender=Affectation)
def on_change_affectation(sender, instance, **kwargs):
    """Signal déclenché quand une affectation est modifiée"""
    try:
        synchroniser_occupation_postes()
    except Exception as e:
        logger.error(f"Erreur dans on_change_affectation: {e}")


@receiver(post_save, sender=Navire)
def on_change_navire_occupation(sender, instance, created, **kwargs):
    """
    Signal déclenché quand un navire est sauvegardé.
    Met à jour l'occupation des postes, mais ignore les erreurs pendant l'import.
    """
    # Ignorer pendant l'import massif (on peut ajouter un flag)
    import sys
    if 'manage.py' in ' '.join(sys.argv) and 'import_epb' in ' '.join(sys.argv):
        return  # Ne pas exécuter pendant l'import EPB
    
    try:
        # Vérifier que le navire a un poste valide
        if instance.etat == 'quai' and instance.poste_attribue:
            # Vérifier que le poste existe toujours
            if instance.poste_attribue.pk:
                synchroniser_occupation_postes()
        elif instance.etat != 'quai':
            # Le navire n'est plus à quai, mettre à jour
            synchroniser_occupation_postes()
    except Exception as e:
        logger.error(f"Erreur dans on_change_navire_occupation pour {instance.nom}: {e}")