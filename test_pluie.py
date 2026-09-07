# test_pluie_5h.py
from port.models import Navire, Meteo, Quai, Affectation
from django.utils import timezone
from datetime import timedelta

# 1. Récupérer le navire céréalier
navire = Navire.objects.get(nom="DS MADRID")
print(f"Navire : {navire.nom} (état={navire.etat})")
print(f"Temps d'arrêt pluie AVANT : {navire.temps_arret_pluie} heures")
if navire.fin_datetime:
    print(f"Fin estimée AVANT : {navire.fin_datetime}")

# 2. Récupérer ou créer la météo
meteo, created = Meteo.objects.get_or_create(date=timezone.now().date())

# 3. Simuler le début de la pluie
print("\n--- Confirmation de la pluie ---")
meteo.pluie = True
meteo.pluie_active = True
meteo.pluie_debut_reelle = timezone.now()
meteo.precipitation = 5.0
quais_cereales = Quai.objects.filter(specialite='cerealier')
meteo.restrictions = ", ".join(quais_cereales.values_list('nom', flat=True))
meteo.save()
print(f"Pluie activée à {meteo.pluie_debut_reelle}")

# 4. DÉFINIR MANUELLEMENT LA DURÉE DE PLUIE (5 heures)
duree_pluie = 5.0  # heures
print(f"Durée simulée de la pluie : {duree_pluie} heures")

# 5. Simuler l'annulation de la pluie avec cette durée
print("\n--- Annulation de la pluie (ajout de la durée) ---")
if navire.etat == 'quai' and (navire.type == 'cerealier' or navire.marchandise_dangereuse):
    # Ajout du temps d'arrêt
    navire.temps_arret_pluie += duree_pluie
    navire.save()
    print(f"✅ Temps d'arrêt pluie ajouté à {navire.nom} : {duree_pluie}h")

    # Mise à jour de l'affectation en cours
    affect = Affectation.objects.filter(navire=navire).order_by('-date_creation').first()
    if affect:
        affect.heure_fin += duree_pluie
        affect.traitement += duree_pluie
        affect.save()
        navire.heure_fin = affect.heure_fin
        # Recalculer fin_datetime
        if navire.debut_datetime:
            base = navire.debut_datetime.replace(hour=0, minute=0, second=0, microsecond=0)
            navire.fin_datetime = base + timedelta(hours=navire.heure_fin)
        navire.save()
        print(f"   → Affectation : nouvelle fin = {affect.heure_fin:.2f}h")
        if affect.quai:
            affect.quai.occupation_jusqua = affect.heure_fin
            affect.quai.save()
    else:
        print("   → Aucune affectation trouvée")
else:
    print(f"⚠️ Navire non sensible ou pas à quai")

# Désactiver la pluie
meteo.pluie_active = False
meteo.pluie_debut_reelle = None
meteo.pluie = False
meteo.precipitation = 0.0
meteo.restrictions = ""
meteo.save()
print("Pluie désactivée.")

# Résultat final
print("\n--- Résultat final ---")
navire.refresh_from_db()
print(f"Temps d'arrêt pluie total : {navire.temps_arret_pluie} heures")
if navire.fin_datetime:
    print(f"Fin estimée (fin_datetime) : {navire.fin_datetime}")
affect = Affectation.objects.filter(navire=navire).order_by('-date_creation').first()
if affect:
    print(f"Fin dans l'affectation : {affect.heure_fin:.2f}h")