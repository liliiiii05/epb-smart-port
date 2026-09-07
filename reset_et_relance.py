# reset_et_relance.py
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'epb_smart.settings')
django.setup()

from optimiseur_db import OptimiseurEPB

print("="*60)
print("🚢 RÉINITIALISATION ET OPTIMISATION")
print("="*60)

# Créer l'optimiseur
opt = OptimiseurEPB()

# Réinitialiser
print("\n🔄 Réinitialisation des navires...")
opt.reset_navires()

# Lancer l'optimisation
print("\n🚀 Lancement d'une nouvelle optimisation...")
cpn = opt.optimiser()

if cpn:
    print(f"\n✅ Nouvelle optimisation terminée ! ID: {cpn.id}")
    print(f"   Score: {cpn.score:.2f} heures")
else:
    print("\n❌ Échec de l'optimisation")