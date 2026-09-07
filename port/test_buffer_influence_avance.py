import sys
import os
sys.path.append(r'C:\Users\AB\mon_projet_epb\epb_smart')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'epb_smart.settings')
import django
django.setup()

from port.optimiseur_epb_pro import PlanificateurEPB, ModeleCalcul, Quai, Navire, TypeNavire, PrioritesNavire, Marchandise, EquipementPropre
from port.models import Equipement
import random

# ----- Création de quais avec performances différentes -----
quais = [
    Quai(id=1, nom="Quai A", longueur=200, profondeur=10, specialite="general", libre=0.0, performance=1.0),   # rapide, libre immédiatement
    Quai(id=2, nom="Quai B", longueur=200, profondeur=10, specialite="general", libre=5.0, performance=0.5),   # lent, libre à 5h
]

# ----- Navire cargo avec volume fixe -----
navire = Navire(
    id=1, nom="TEST", type=TypeNavire.CARGO, longueur=100, tirant=5, arrivee=0,
    priorites=PrioritesNavire(), marchandise=Marchandise(type="standard", volume=3000),
    equipement_propre=EquipementPropre(), priorite_calculee=0, coeff_variation=0
)

# ----- Modification du modèle de calcul pour que la durée dépende de la performance -----
class ModeleCalculMod(ModeleCalcul):
    def calculer_temps_traitement(self, navire, quai):
        taux_base = 150  # tonnes/heure
        return navire.marchandise.volume / (taux_base * quai.performance)

# ----- Planificateur de test -----
class PlanificateurTest(PlanificateurEPB):
    def __init__(self, quais, equipements, pourcentage_buffer):
        super().__init__(quais, equipements, mois=3, incertitude=False, amplitude=0, pourcentage_buffer=pourcentage_buffer)
        self.modele = ModeleCalculMod(quais, equipements, incertitude=False, amplitude=0)

# ----- Exécution des tests pour différents buffers -----
print("="*80)
print("TEST DE L'INFLUENCE DU BUFFER SUR LE CHOIX DU QUAI")
print("="*80)
print("Quai A : libre à 0h, performance 1.0 (traitement = 20h)")
print("Quai B : libre à 5h, performance 0.5 (traitement = 40h)")
print()

for buffer_pct in [0, 0.15, 0.3, 0.5]:
    plan = PlanificateurTest(quais, [], pourcentage_buffer=buffer_pct)
    affs, score, attente = plan.planifier([navire])
    a = affs[0]
    buffer_debut = a.buffer_debut
    buffer_fin = a.buffer_fin
    penalite = max(0, (2.0 - buffer_debut) * 5) + max(0, (2.0 - buffer_fin) * 5)  # seuil 2h, coeff 5
    print(f"Buffer {buffer_pct*100:3.0f}% : quai {a.quai_nom} (début {a.heure_accostage:.1f}h, fin {a.heure_fin:.1f}h, buffer {buffer_debut:.1f}h, score {a.score_contribution:.2f})")
    print(f"   → Pénalité = {penalite:.1f} (seuil 2h, coeff 5)")

print("\n" + "="*80)
print("Si le quai choisi change avec le buffer, l'influence est visible.")
print("Avec buffer=0%, le quai A est choisi (début plus tôt).")
print("Avec buffer élevé, le quai B pourrait être préféré car son buffer (>2h) évite la pénalité.")
print("="*80)
