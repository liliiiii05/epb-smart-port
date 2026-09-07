# convertir_planifie_en_historique.py
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'epb_smart.settings')
django.setup()

from port.models import Navire

nb = Navire.objects.filter(etat='planifie').update(etat='historique')
print(f"✅ {nb} navires convertis de 'planifie' à 'historique'")