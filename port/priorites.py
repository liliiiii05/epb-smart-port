# port/priorites.py
from .models import Navire

PRIORITES_MAPPING = {
    'sortant': 1,
    'passage': 2,
    'gazier': 3,      # attention : gazier hiver
    'essence': 4,
    'animalier': 5,
    'perissable': 6,
    'strategique': 7,
    'ligne_reguliere': 8,
    'convention': 9,
    'huilier': 10,
}

POIDS_NIVEAU = {
    1: 1000, 2: 900, 3: 800, 4: 700, 5: 600,
    6: 500, 7: 400, 8: 300, 9: 200, 10: 100,
}

def calculer_priorite_navire(navire: Navire) -> float:
    """Calcule le score de priorité strict selon l'ordre EPB (sans bonus)."""
    niveau_max = 100
    for champ, niveau in PRIORITES_MAPPING.items():
        if getattr(navire, champ, False):
            niveau_max = min(niveau_max, niveau)
    if niveau_max < 100:
        return float(POIDS_NIVEAU[niveau_max])
    return 0.0