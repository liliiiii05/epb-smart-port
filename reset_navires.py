# reset_navires.py
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'epb_smart.settings')
django.setup()

from port.models import Navire, Affectation, CPN

print("🔄 Réinitialisation des navires...")

# 1. Supprimer les anciennes affectations
nb_affectations = Affectation.objects.count()
Affectation.objects.all().delete()
print(f"✅ {nb_affectations} affectations supprimées")

# 2. Supprimer les anciennes CPN
nb_cpn = CPN.objects.count()
CPN.objects.all().delete()
print(f"✅ {nb_cpn} CPN supprimées")

# 3. Remettre tous les navires en 'attente'
nb_navires = Navire.objects.update(etat='attente')
print(f"✅ {nb_navires} navires remis en attente")

print("\n🎉 Réinitialisation terminée !")