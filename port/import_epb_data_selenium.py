# import_epb_data.py
import os
import sys
import django
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re

# Django setup
sys.path.append(r'C:\Users\AB\mon_projet_epb\epb_smart')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'epb_smart.settings')
django.setup()

from port.models import Navire, Quai, Equipement, Affectation, SessionOptimisation

# =============================================================================
# CONSTANTES ET FONCTIONS UTILITAIRES
# =============================================================================
URL_SITUATION = "https://www.portdebejaia.dz/situation-des-navires/"

# Mapping des types de navires
TYPE_MAPPING = {
    "PORTE CONTENEURS": "conteneur",
    "PETROLIER": "petrolier",
    "BETAILLER": "betail",
    "CEREALIER": "cerealier",
    "HUILIER": "huilier",
    "BITUMIER": "petrolier",
    "CARGO": "cargo",
    "CAR-FERRY": "ferry",
    "ROULIER": "roulier",
    "FRIGORIFIQUE": "frigorifique",
    "GAZIER": "gazier",
    "ESSENCE": "essence",
}

# Valeurs par défaut réalistes pour chaque type de navire
LONGUEUR_DEFAUT = {
    'conteneur': 300,
    'cerealier': 180,
    'ferry': 250,
    'gazier': 280,
    'frigorifique': 150,
    'betail': 140,
    'essence': 110,
    'huilier': 150,
    'petrolier': 250,
    'cargo': 120,
    'roulier': 200,
    'chimiquier': 160,
}

TIRANT_DEFAUT = {
    'conteneur': 12,
    'cerealier': 10,
    'ferry': 7,
    'gazier': 12,
    'frigorifique': 8,
    'betail': 6,
    'essence': 5,
    'huilier': 8,
    'petrolier': 13,
    'cargo': 7,
    'roulier': 6,
    'chimiquier': 9,
}

def estimer_temps_traitement(type_navire, volume):
    """Estime le temps de traitement en heures selon le type."""
    volume = float(volume) if volume else 0
    if type_navire == 'conteneur':
        return volume / 50 if volume > 0 else 10
    elif type_navire == 'ferry':
        return 4
    elif type_navire == 'gazier':
        return 24
    elif type_navire == 'frigorifique':
        return volume / 30 if volume > 0 else 12
    elif type_navire == 'essence':
        return volume / 200 if volume > 0 else 8
    elif type_navire == 'betail':
        return 6
    elif type_navire == 'cerealier':
        return volume / 300 if volume > 0 else 20
    elif type_navire == 'petrolier':
        return 12
    elif type_navire == 'huilier':
        return 8
    else:
        return 12

def get_priorites(type_navire, marchandise):
    priorites = {
        'sortant': False, 'passage': False, 'gazier': False, 'essence': False,
        'animalier': False, 'perissable': False, 'strategique': False,
        'ligne_reguliere': False, 'convention': False, 'huilier': False,
    }
    if type_navire == 'gazier':
        priorites['gazier'] = True
    if type_navire == 'essence':
        priorites['essence'] = True
    if type_navire == 'betail':
        priorites['animalier'] = True
    if type_navire == 'huilier':
        priorites['huilier'] = True
    if type_navire == 'ferry':
        priorites['ligne_reguliere'] = True
    if type_navire in ['cerealier', 'petrolier']:
        priorites['strategique'] = True
    if 'frigorifique' in type_navire or 'perissable' in marchandise.lower():
        priorites['perissable'] = True
    if 'passage' in marchandise.lower():
        priorites['passage'] = True
    return priorites

def extraire_tableaux_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    tableaux = []
    for table in soup.find_all('table'):
        titre = ""
        prev = table.find_previous_sibling()
        while prev and prev.name not in ('h2', 'h3'):
            prev = prev.find_previous_sibling()
        if prev:
            titre = prev.get_text(strip=True)
        tableaux.append((titre, table))
    return tableaux

def convertir_heure_decimal(heure_str):
    try:
        return float(heure_str)
    except:
        return None

def convertir_datetime(date_str):
    try:
        parts = date_str.strip().split()
        if len(parts) >= 2:
            date_part, time_part = parts[0], parts[1]
            jour, mois, annee = map(int, date_part.split('/'))
            heure, minute, seconde = map(int, time_part.split(':'))
            return datetime(annee, mois, jour, heure, minute, seconde)
        elif len(parts) == 1:
            jour, mois, annee = map(int, parts[0].split('/'))
            return datetime(annee, mois, jour, 0, 0, 0)
    except:
        return None
    return None

def extraire_navires_attendus(table):
    navires = []
    rows = table.find_all('tr')[1:]
    for row in rows:
        cols = row.find_all('td')
        if len(cols) < 8:
            continue
        nav = {
            'nom': cols[0].get_text(strip=True),
            'type': TYPE_MAPPING.get(cols[1].get_text(strip=True), 'cargo'),
            'eta': convertir_heure_decimal(cols[2].get_text(strip=True)),
            'ted': convertir_heure_decimal(cols[3].get_text(strip=True)),
            'marchandise': cols[4].get_text(strip=True),
            'tonnage': cols[5].get_text(strip=True).replace(' ', ''),
            'provenance': cols[6].get_text(strip=True),
            'agent': cols[7].get_text(strip=True),
            'receptionnaire': cols[8].get_text(strip=True) if len(cols) > 8 else '',
        }
        navires.append(nav)
    return navires

def extraire_navires_quai(table):
    navires = []
    rows = table.find_all('tr')[1:]
    for row in rows:
        cols = row.find_all('td')
        if len(cols) < 8:
            continue
        poste_str = cols[0].get_text(strip=True)
        poste_id = None
        if poste_str:
            match = re.search(r'\d+', poste_str)
            if match:
                poste_id = int(match.group())
        quai = None
        if poste_id:
            try:
                quai = Quai.objects.get(id=poste_id)
            except Quai.DoesNotExist:
                pass
        nav = {
            'nom': cols[1].get_text(strip=True),
            'type': TYPE_MAPPING.get(cols[2].get_text(strip=True), 'cargo'),
            'accostage': convertir_datetime(cols[3].get_text(strip=True)),
            'ted': convertir_heure_decimal(cols[4].get_text(strip=True)),
            'marchandise': cols[5].get_text(strip=True),
            'tonnage': cols[6].get_text(strip=True).replace(' ', ''),
            'agent': cols[7].get_text(strip=True),
            'receptionnaire': cols[8].get_text(strip=True) if len(cols) > 8 else '',
            'quai': quai,
            'poste_original': poste_str,
        }
        navires.append(nav)
    return navires

def extraire_navires_rade(table):
    navires = []
    rows = table.find_all('tr')[1:]
    for row in rows:
        cols = row.find_all('td')
        if len(cols) < 6:
            continue
        nav = {
            'nom': cols[0].get_text(strip=True),
            'type': TYPE_MAPPING.get(cols[1].get_text(strip=True), 'cargo'),
            'dhr': convertir_datetime(cols[2].get_text(strip=True)),
            'ted': convertir_heure_decimal(cols[3].get_text(strip=True)),
            'marchandise': cols[4].get_text(strip=True),
            'tonnage': cols[5].get_text(strip=True).replace(' ', ''),
            'agent': cols[6].get_text(strip=True) if len(cols) > 6 else '',
            'receptionnaire': cols[7].get_text(strip=True) if len(cols) > 7 else '',
        }
        navires.append(nav)
    return navires

def importer_donnees_epb():
    print("🌐 Téléchargement de la situation des navires...")
    try:
        response = requests.get(URL_SITUATION, timeout=10)
        response.raise_for_status()
        html = response.text
    except Exception as e:
        print(f"❌ Erreur lors du téléchargement : {e}")
        return

    tableaux = extraire_tableaux_html(html)

    navires_attendus = []
    navires_quai = []
    navires_rade = []

    for titre, table in tableaux:
        if "Attendus" in titre:
            navires_attendus = extraire_navires_attendus(table)
        elif "à quai" in titre or "A quai" in titre:
            navires_quai = extraire_navires_quai(table)
        elif "rade" in titre or "Rade" in titre:
            navires_rade = extraire_navires_rade(table)

    print(f"📥 Navires attendus : {len(navires_attendus)}")
    print(f"📥 Navires à quai   : {len(navires_quai)}")
    print(f"📥 Navires en rade  : {len(navires_rade)}")

    # --- Navires en rade ---
    for data in navires_rade:
        type_nav = data['type']
        longueur = LONGUEUR_DEFAUT.get(type_nav, 120)
        tirant = TIRANT_DEFAUT.get(type_nav, 7)
        priorites = get_priorites(type_nav, data['marchandise'])
        heure_arrivee = 0
        if data['dhr']:
            heure_arrivee = data['dhr'].hour + data['dhr'].minute / 60
        navire, created = Navire.objects.update_or_create(
            nom=data['nom'],
            defaults={
                'type': type_nav,
                'longueur': longueur,
                'tirant': tirant,
                'arrivee': heure_arrivee,
                'etat': 'rade',
                'marchandise_type': data['marchandise'],
                'marchandise_volume': float(data['tonnage']) if data['tonnage'] else 0,
                **priorites
            }
        )
        print(f"  {'✅' if created else '🔄'} {navire.nom} (rade)")

    # --- Navires à quai ---
    for data in navires_quai:
        type_nav = data['type']
        longueur = LONGUEUR_DEFAUT.get(type_nav, 120)
        tirant = TIRANT_DEFAUT.get(type_nav, 7)
        priorites = get_priorites(type_nav, data['marchandise'])

        # Heure de début
        heure_debut = 0
        if data['accostage']:
            heure_debut = data['accostage'].hour + data['accostage'].minute / 60

        # Temps de traitement estimé
        traitement = estimer_temps_traitement(type_nav, data['tonnage'])
        heure_fin = heure_debut + traitement if traitement else None

        # Quai
        quai = data['quai']  # déjà un objet Quai ou None

        navire, created = Navire.objects.update_or_create(
            nom=data['nom'],
            defaults={
                'type': type_nav,
                'longueur': longueur,
                'tirant': tirant,
                'arrivee': 0,  # pas d'arrivée spécifique
                'etat': 'quai',
                'marchandise_type': data['marchandise'],
                'marchandise_volume': float(data['tonnage']) if data['tonnage'] else 0,
                'quai_attribue': quai,
                'heure_debut': heure_debut,
                'heure_fin': heure_fin,
                **priorites
            }
        )
        print(f"  {'✅' if created else '🔄'} {navire.nom} (quai {data['poste_original']})")

    # --- Navires attendus ---
    for data in navires_attendus:
        type_nav = data['type']
        longueur = LONGUEUR_DEFAUT.get(type_nav, 120)
        tirant = TIRANT_DEFAUT.get(type_nav, 7)
        priorites = get_priorites(type_nav, data['marchandise'])
        navire, created = Navire.objects.update_or_create(
            nom=data['nom'],
            defaults={
                'type': type_nav,
                'longueur': longueur,
                'tirant': tirant,
                'arrivee': data['eta'] if data['eta'] else 0,
                'etat': 'attente',
                'marchandise_type': data['marchandise'],
                'marchandise_volume': float(data['tonnage']) if data['tonnage'] else 0,
                **priorites
            }
        )
        print(f"  {'✅' if created else '🔄'} {navire.nom} (attente)")

    print("\n✅ Importation terminée.")

if __name__ == "__main__":
    importer_donnees_epb()