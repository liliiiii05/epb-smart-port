# port/management/commands/fetch_weather.py
import requests
import os
import random
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.timezone import make_naive, is_naive
from port.models import Meteo, Alerte
from port.views import replanifier_automatique

class Command(BaseCommand):
    help = "Récupère la météo et les prévisions de pluie"

    def add_arguments(self, parser):
        parser.add_argument(
            '--silent',
            action='store_true',
            help="Mode silencieux : ne déclenche pas de replanification automatique"
        )

    def _get_weather_wttr(self):
        """Récupère la météo depuis wttr.in avec timeout augmenté et fallback"""
        url = "https://wttr.in/Bejaia?format=j1"
        
        try:
            response = requests.get(url, timeout=30)  # Timeout augmenté à 30s
            response.raise_for_status()
            data = response.json()
            current = data['current_condition'][0]

            # Extraction des données
            temp_str = current.get('temp_C', '20')
            try:
                temp = int(temp_str)
            except (ValueError, TypeError):
                temp = 20
            
            vent_kmh = int(current.get('windspeedKmph', 10))
            vent_ms = vent_kmh / 3.6
            force = self._ms_to_beaufort(vent_ms)
            wind_direction = current.get('winddir16Point', 'N')
            precip_mm = float(current.get('precipMM', 0))
            pluie = precip_mm > 0
            description = current.get('weatherDesc', [{}])[0].get('value', 'Ciel dégagé')

            # Prévisions
            weather_hourly = data.get('weather', [])
            today_str = timezone.now().date().strftime('%Y-%m-%d')
            pluie_debut = None
            pluie_fin = None
            now = timezone.now()
            forecast_list = []

            for day in weather_hourly:
                if day.get('date') == today_str:
                    hourly = day.get('hourly', [])
                    for h in hourly:
                        try:
                            heure = int(h.get('time', 0))
                            precip = float(h.get('precipMM', 0))
                            dt = datetime.combine(now.date(), datetime.min.time()) + timedelta(hours=heure)
                            forecast_list.append({
                                'datetime': dt,
                                'precipitation': precip,
                                'wind_speed': int(h.get('windspeedKmph', 0)) / 3.6,
                            })
                            if precip > 0 and pluie_debut is None:
                                pluie_debut = dt
                                pluie_fin = dt + timedelta(hours=1)
                        except (ValueError, TypeError):
                            continue
                    break

            restrictions = ""
            if force >= 8:
                restrictions = "Quai 12, Quai 13, Quai 14, Quai 15, Quai 16"
            elif pluie_debut is not None:
                restrictions = "Quai Céréalier 04, Quai Céréalier 05"

            return {
                'vent_force': force,
                'vent_direction': wind_direction,
                'hauteur_houle': 0,
                'pluie': pluie,
                'precipitation': precip_mm,
                'temperature': temp,
                'description': description,
                'restrictions': restrictions,
                'pluie_debut_prevue': pluie_debut,
                'pluie_fin_prevue': pluie_fin,
                'forecast_list': forecast_list,
            }
            
        except requests.Timeout:
            self.stdout.write(self.style.WARNING("⚠️ Timeout wttr.in, utilisation des données simulées"))
            return self._get_simulated_weather()
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"⚠️ Erreur wttr.in: {e}, utilisation des données simulées"))
            return self._get_simulated_weather()

    def _get_simulated_weather(self):
        """Génère des données météo simulées réalistes pour Béjaïa"""
        from datetime import datetime
        
        heure = datetime.now().hour
        
        # Température selon l'heure (réaliste pour Béjaïa)
        if 13 <= heure <= 15:
            temp = 28
        elif 11 <= heure <= 17:
            temp = 26
        elif 9 <= heure <= 19:
            temp = 24
        elif 20 <= heure <= 22:
            temp = 20
        else:
            temp = 18
        
        # Descriptions selon la température
        if temp >= 28:
            description = "Très chaud"
            vent_force = 2
        elif temp >= 24:
            description = "Chaud"
            vent_force = 3
        elif temp >= 18:
            description = "Doux"
            vent_force = 2
        else:
            description = "Frais"
            vent_force = 3
        
        # Vent direction aléatoire
        directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
        wind_direction = random.choice(directions)
        
        # Pluie : 10% de chance en hiver, 5% en été
        mois = datetime.now().month
        if mois in [11, 12, 1, 2, 3]:  # Hiver
            pluie_chance = 0.1
        else:  # Été
            pluie_chance = 0.05
        
        pluie = random.random() < pluie_chance
        precipitation = random.uniform(0, 5) if pluie else 0
        
        restrictions = ""
        if vent_force >= 8:
            restrictions = "Quai 12, Quai 13, Quai 14, Quai 15, Quai 16"
        
        return {
            'vent_force': vent_force,
            'vent_direction': wind_direction,
            'hauteur_houle': 0,
            'pluie': pluie,
            'precipitation': round(precipitation, 1),
            'temperature': temp,
            'description': description,
            'restrictions': restrictions,
            'pluie_debut_prevue': None,
            'pluie_fin_prevue': None,
            'forecast_list': [],
        }

    def _ms_to_beaufort(self, wind_ms: float) -> int:
        """Convertit la vitesse du vent en m/s en échelle de Beaufort"""
        if wind_ms < 0.3: return 0
        if wind_ms < 1.6: return 1
        if wind_ms < 3.4: return 2
        if wind_ms < 5.5: return 3
        if wind_ms < 8.0: return 4
        if wind_ms < 10.8: return 5
        if wind_ms < 13.9: return 6
        if wind_ms < 17.2: return 7
        if wind_ms < 20.8: return 8
        if wind_ms < 24.5: return 9
        if wind_ms < 28.5: return 10
        if wind_ms < 32.7: return 11
        return 12

    def _to_naive_safe(self, dt):
        """Convertit un datetime en naive de manière sécurisée"""
        if dt is None:
            return None
        if is_naive(dt):
            return dt
        return make_naive(dt)

    def _envoyer_alerte(self, message, niveau='warning'):
        """Crée une alerte en base"""
        Alerte.objects.create(
            message=message,
            niveau=niveau,
            source='Météo',
            est_lue=False
        )
        self.stdout.write(self.style.WARNING(f"🔔 ALERTE : {message}"))

    def _verifier_alertes_pluie(self, meteo, forecast_list=None, reference_time=None):
        """Vérifie les prévisions de pluie"""
        if reference_time is None:
            reference_time = timezone.now()
        
        reference_time = self._to_naive_safe(reference_time)
        
        pluie_active = meteo.pluie_active
        fin_prevue = meteo.pluie_fin_prevue
        
        if fin_prevue:
            fin_prevue = self._to_naive_safe(fin_prevue)

        if forecast_list:
            premiere_pluie = None
            for f in forecast_list:
                dt = f['datetime']
                dt = self._to_naive_safe(dt)
                
                if dt < reference_time:
                    continue
                if f['precipitation'] > 0:
                    premiere_pluie = dt
                    break

            if premiere_pluie and not pluie_active:
                delta = (premiere_pluie - reference_time).total_seconds() / 60.0
                if 0 <= delta <= 30:
                    self._envoyer_alerte(
                        f"🌧️ Alerte pluie : risque de pluie dans moins de 30 minutes (début vers {premiere_pluie.strftime('%H:%M')}).",
                        niveau='warning'
                    )
                elif delta <= 5 and delta >= -5:
                    if not pluie_active:
                        self._envoyer_alerte(
                            f"🌧️ Pluie en cours – Début à {premiere_pluie.strftime('%H:%M')}. Arrêt des navires céréaliers/dangereux.",
                            niveau='danger'
                        )
                        meteo.pluie_active = True
                        meteo.pluie_debut_reelle = reference_time
                        meteo.save()

        if pluie_active and fin_prevue and reference_time >= fin_prevue:
            duree = 0
            if meteo.pluie_debut_reelle:
                debut = self._to_naive_safe(meteo.pluie_debut_reelle)
                duree = (reference_time - debut).total_seconds() / 3600.0
            self._envoyer_alerte(
                f"✅ Fin de la pluie – Durée : {duree:.1f}h. Reprise des opérations.",
                niveau='success'
            )
            meteo.pluie_active = False
            meteo.pluie_debut_reelle = None
            meteo.pluie = False
            meteo.save()

    def _ms_to_beaufort_inverse(self, beaufort):
        """Retourne la vitesse en m/s correspondant à l'échelle de Beaufort"""
        vitesses = [0.0, 0.3, 1.6, 3.4, 5.5, 8.0, 10.8, 13.9, 17.2, 20.8, 24.5, 28.5, 32.7]
        if beaufort <= 12:
            return vitesses[beaufort]
        return 32.7

    def _verifier_alertes_vent(self, meteo, forecast_list=None, reference_time=None):
        """Vérifie les prévisions de vent fort"""
        if reference_time is None:
            reference_time = timezone.now()
        
        reference_time = self._to_naive_safe(reference_time)
        
        vent_actuel = meteo.vent_force
        seuil = 8

        if forecast_list:
            premier_vent_fort = None
            for f in forecast_list:
                dt = f['datetime']
                dt = self._to_naive_safe(dt)
                
                if dt < reference_time:
                    continue
                if f.get('wind_speed', 0) >= self._ms_to_beaufort_inverse(seuil):
                    premier_vent_fort = dt
                    break

            if premier_vent_fort and vent_actuel < seuil:
                delta = (premier_vent_fort - reference_time).total_seconds() / 60.0
                if 0 <= delta <= 30:
                    self._envoyer_alerte(
                        f"💨 Alerte vent fort : vent ≥8 Bft dans moins de 30 minutes (vers {premier_vent_fort.strftime('%H:%M')}). Quais sensibles (12-16) seront interdits.",
                        niveau='warning'
                    )
                elif delta <= 5 and delta >= -5:
                    self._envoyer_alerte(
                        f"💨 Vent fort (≥8 Bft) en cours – Début à {premier_vent_fort.strftime('%H:%M')}. Quais sensibles interdits.",
                        niveau='danger'
                    )
                    meteo.vent_force = max(meteo.vent_force, 8)
                    meteo.save()

        if vent_actuel >= seuil and forecast_list:
            future_vent_faible = True
            for f in forecast_list:
                dt = f['datetime']
                dt = self._to_naive_safe(dt)
                if dt > reference_time and f.get('wind_speed', 0) >= self._ms_to_beaufort_inverse(seuil):
                    future_vent_faible = False
                    break
            
            if future_vent_faible:
                self._envoyer_alerte(
                    f"✅ Vent fort terminé – Quais sensibles réactivés.",
                    niveau='success'
                )

    def handle(self, *args, **options):
        silent = options['silent']

        # Récupérer l'ancienne météo
        ancienne = Meteo.objects.filter(date=timezone.now().date()).first()
        ancienne_pluie = ancienne.pluie if ancienne else False
        anciennes_restrictions = ancienne.restrictions if ancienne else ""
        ancien_vent = ancienne.vent_force if ancienne else 0
        ancien_debut_pluie = getattr(ancienne, 'pluie_debut_prevue', None) if ancienne else None
        ancien_fin_pluie = getattr(ancienne, 'pluie_fin_prevue', None) if ancienne else None

        # Récupérer la météo
        self.stdout.write("🌤️ Récupération de la météo...")
        weather = self._get_weather_wttr()
        forecast_list = weather.pop('forecast_list', [])

        # Sauvegarder en base
        meteo, created = Meteo.objects.update_or_create(
            date=timezone.now().date(),
            defaults=weather
        )

        # Vérifier les changements
        changed = (
            ancienne_pluie != weather['pluie'] or
            anciennes_restrictions != weather['restrictions'] or
            abs(ancien_vent - weather['vent_force']) >= 2 or
            ancien_debut_pluie != weather.get('pluie_debut_prevue') or
            ancien_fin_pluie != weather.get('pluie_fin_prevue')
        )

        # Afficher le résultat
        pluie_str = "🌧️ Oui" if weather['pluie'] else "☀️ Non"
        self.stdout.write(self.style.SUCCESS(
            f"✅ Météo enregistrée : {weather['temperature']}°C, "
            f"{weather['description']}, "
            f"Vent {weather['vent_force']} Bft ({weather['vent_direction']}), "
            f"Pluie: {pluie_str}"
        ))

        # Vérifier les alertes
        now = timezone.now()
        self._verifier_alertes_pluie(meteo, forecast_list, now)
        self._verifier_alertes_vent(meteo, forecast_list, now)

        # Replanification si nécessaire
        if not silent and changed:
            from port.models import Navire
            if Navire.objects.filter(etat__in=['rade', 'quai']).exists():
                self.stdout.write("🔄 Replanification automatique en cours...")
                replanifier_automatique()
            else:
                self.stdout.write("ℹ️ Météo changée mais aucun navire actif")
        elif not silent and not changed:
            self.stdout.write("ℹ️ Aucun changement météo significatif")