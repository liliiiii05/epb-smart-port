from .models import HistoriqueAction
from django.utils import timezone

def ajouter_historique(utilisateur, type_action, description, navire=None, quai=None, equipement=None, details=None):
    """Enregistre une action dans l'historique."""
    HistoriqueAction.objects.create(
        utilisateur=utilisateur if utilisateur and utilisateur.is_authenticated else None,
        type_action=type_action,
        description=description,
        date_action=timezone.now(),
        navire=navire,
        quai=quai,
        equipement=equipement,
        details=details or {}
    )