from django.db.models import Avg, F
from port.models import HistoriqueOperation

def get_correction_coefficient(type_navire, quai_id):
    """
    Retourne le coefficient moyen (réel / estimé) pour un type de navire et un quai.
    Si pas assez de données, retourne 1.0 (pas de correction).
    """
    qs = HistoriqueOperation.objects.filter(
        type_navire=type_navire,
        quai_id=quai_id,
        duree_estimee__gt=0
    ).exclude(duree_reelle__isnull=True).values('duree_reelle', 'duree_estimee')
    
    # Calcul du ratio réel/estimé pour chaque opération
    ratios = []
    for op in qs:
        if op['duree_estimee'] > 0:
            ratios.append(op['duree_reelle'] / op['duree_estimee'])
    
    if len(ratios) >= 3:   # seuil minimal de confiance
        return sum(ratios) / len(ratios)
    return 1.0