# test_notifications.py
from django.utils import timezone
from datetime import datetime, timedelta
from port.models import Meteo, Alerte

Alerte.objects.filter(source='Météo').delete()
print("🧹 Anciennes alertes supprimées.")

meteo, created = Meteo.objects.get_or_create(date=timezone.now().date())
print(f"Météo du {meteo.date} : pluie_active={meteo.pluie_active}")

def envoyer_alerte(message, niveau='warning'):
    alerte = Alerte.objects.create(
        message=message,
        niveau=niveau,
        source='Météo',
        est_lue=False
    )
    print(f"🔔 ALERTE ({niveau}) : {message}")

def verifier_alertes_pluie(meteo, forecast_list, reference_time):
    pluie_active = meteo.pluie_active
    fin_prevue = meteo.pluie_fin_prevue
    premiere_pluie = None
    for f in forecast_list:
        dt = f['datetime']
        if dt < reference_time:
            continue
        if f['precipitation'] > 0:
            premiere_pluie = dt
            break
    if premiere_pluie and not pluie_active:
        delta = (premiere_pluie - reference_time).total_seconds() / 60.0
        if 0 <= delta <= 30:
            envoyer_alerte(
                f"🌧️ Alerte pluie : risque de pluie dans moins de 30 minutes (début vers {premiere_pluie.strftime('%H:%M')}).",
                niveau='warning'
            )
        elif delta <= 5 and delta >= -5:
            envoyer_alerte(
                f"🌧️ Pluie en cours – Début à {premiere_pluie.strftime('%H:%M')}. Arrêt des navires céréaliers/dangereux.",
                niveau='danger'
            )
            meteo.pluie_active = True
            meteo.pluie_debut_reelle = reference_time
            meteo.save()
    if pluie_active and fin_prevue and reference_time >= fin_prevue:
        duree = (reference_time - meteo.pluie_debut_reelle).total_seconds() / 3600.0
        envoyer_alerte(
            f"✅ Fin de la pluie – Durée : {duree:.1f}h. Reprise des opérations.",
            niveau='success'
        )
        meteo.pluie_active = False
        meteo.pluie_debut_reelle = None
        meteo.pluie = False
        meteo.save()

def verifier_alertes_vent(meteo, forecast_list, reference_time):
    vent_actuel = meteo.vent_force
    seuil = 8
    premier_vent = None
    for f in forecast_list:
        dt = f['datetime']
        if dt < reference_time:
            continue
        vent_kmh = f['wind_speed']
        if vent_kmh / 3.6 >= 17.2:
            premier_vent = dt
            break
    if premier_vent and vent_actuel < seuil:
        delta = (premier_vent - reference_time).total_seconds() / 60.0
        if 0 <= delta <= 30:
            envoyer_alerte(
                f"💨 Alerte vent fort : vent ≥8 Bft dans moins de 30 minutes (vers {premier_vent.strftime('%H:%M')}). Quais sensibles (12-16) seront interdits.",
                niveau='warning'
            )
        elif delta <= 5 and delta >= -5:
            envoyer_alerte(
                f"💨 Vent fort (≥8 Bft) en cours – Début à {premier_vent.strftime('%H:%M')}. Quais sensibles interdits.",
                niveau='danger'
            )
            meteo.vent_force = max(meteo.vent_force, 8)
            meteo.save()

print("\n" + "="*60)
print("SIMULATION 1 : Alerte 30 minutes avant la pluie")
print("="*60)
now = timezone.now()
debut_pluie = now + timedelta(minutes=25)
forecast_avant = [
    {'datetime': now + timedelta(minutes=10), 'precipitation': 0, 'wind_speed': 10},
    {'datetime': debut_pluie, 'precipitation': 5.0, 'wind_speed': 10},
    {'datetime': debut_pluie + timedelta(hours=1), 'precipitation': 5.0, 'wind_speed': 10},
]
meteo.pluie_active = False
meteo.save()
verifier_alertes_pluie(meteo, forecast_avant, now)

print("\n" + "="*60)
print("SIMULATION 2 : Début de la pluie (alerte immédiate)")
print("="*60)
now = timezone.now()
debut_pluie = now - timedelta(minutes=2)
forecast_debut = [
    {'datetime': debut_pluie, 'precipitation': 5.0, 'wind_speed': 10},
]
meteo.pluie_active = False
meteo.save()
verifier_alertes_pluie(meteo, forecast_debut, now)

print("\n" + "="*60)
print("SIMULATION 3 : Fin de la pluie (alerte de fin)")
print("="*60)
now = timezone.now()
meteo.pluie_active = True
meteo.pluie_debut_reelle = now - timedelta(hours=2)
meteo.pluie_fin_prevue = now - timedelta(minutes=5)
meteo.save()
verifier_alertes_pluie(meteo, [], now)

print("\n" + "="*60)
print("SIMULATION 4 : Alerte vent fort 30 minutes avant")
print("="*60)
now = timezone.now()
debut_vent = now + timedelta(minutes=20)
forecast_vent = [
    {'datetime': now + timedelta(minutes=5), 'wind_speed': 10, 'precipitation': 0},
    {'datetime': debut_vent, 'wind_speed': 70, 'precipitation': 0},
    {'datetime': debut_vent + timedelta(hours=1), 'wind_speed': 70, 'precipitation': 0},
]
meteo.vent_force = 0
meteo.save()
verifier_alertes_vent(meteo, forecast_vent, now)

print("\n" + "="*60)
print("RÉCAPITULATIF DES ALERTES MÉTÉO CRÉÉES")
print("="*60)
alertes = Alerte.objects.filter(source='Météo').order_by('-date_creation')
for a in alertes:
    print(f"[{a.date_creation.strftime('%H:%M:%S')}] {a.get_niveau_display()} : {a.message}")
print(f"\n✅ {alertes.count()} alertes générées.")