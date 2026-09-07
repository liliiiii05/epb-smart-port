import os
import sys
import django
import re
from datetime import datetime
import time

# Configuration Django
sys.path.append(r'C:\Users\AB\mon_projet_epb\epb_smart')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'epb_smart.settings')
django.setup()

from port.models import Navire, Quai, Poste

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

# ------------------------------------------------------------------------------
# CONSTANTES
# ------------------------------------------------------------------------------
URL = "https://www.portdebejaia.dz/situation-des-navires/"

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

LONGUEUR_DEFAUT = {
    'conteneur': 300, 'cerealier': 180, 'ferry': 250, 'gazier': 280,
    'frigorifique': 150, 'betail': 140, 'essence': 110, 'huilier': 150,
    'petrolier': 250, 'cargo': 120, 'roulier': 200, 'chimiquier': 160,
}

TIRANT_DEFAUT = {
    'conteneur': 12, 'cerealier': 10, 'ferry': 7, 'gazier': 12,
    'frigorifique': 8, 'betail': 6, 'essence': 5, 'huilier': 8,
    'petrolier': 13, 'cargo': 7, 'roulier': 6, 'chimiquier': 9,
}

def get_priorites(type_navire, marchandise):
    priorites = {
        'sortant': False, 'passage': False, 'gazier': False, 'essence': False,
        'animalier': False, 'perissable': False, 'strategique': False,
        'ligne_reguliere': False, 'convention': False, 'huilier': False,
    }
    march = marchandise.lower()
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
    if any(w in march for w in ['ble', 'mais', 'cereale', 'sucre']):
        priorites['strategique'] = True
    if any(w in march for w in ['petrole', 'gaz', 'gnl', 'gpl']):
        priorites['strategique'] = True
    if 'frigorifique' in march or 'perissable' in march:
        priorites['perissable'] = True
    if 'passage' in march:
        priorites['passage'] = True
    return priorites

def convertir_heure_decimal(heure_str):
    if not heure_str:
        return None
    try:
        return float(heure_str.replace(',', '.'))
    except:
        return None

def convertir_datetime(date_str):
    if not date_str:
        return None
    date_str = date_str.strip()
    if ' ' in date_str:
        date_part, time_part = date_str.split(' ', 1)
        time_part = time_part.replace('.', ':')
        try:
            h, m = map(int, time_part.split(':'))
        except:
            h = int(float(time_part))
            m = int((float(time_part) - h) * 60)
        jour, mois, annee = map(int, date_part.split('/'))
        return datetime(annee, mois, jour, h, m, 0)
    else:
        jour, mois, annee = map(int, date_str.split('/'))
        return datetime(annee, mois, jour, 8, 0, 0)

def extraire_tonnage(tonnage_str):
    if not tonnage_str:
        return 0.0
    cleaned = re.sub(r'[^\d.,]', '', tonnage_str)
    cleaned = cleaned.replace(',', '.')
    if cleaned.count('.') > 1:
        parts = cleaned.split('.')
        cleaned = parts[0] + parts[1]
    try:
        return float(cleaned)
    except:
        return 0.0

# ------------------------------------------------------------------------------
# EXTRACTION
# ------------------------------------------------------------------------------
def extraire_navires_quai(table):
    navires = []
    rows = table.find_all('tr')[1:]
    for row in rows:
        cols = row.find_all('td')
        if len(cols) < 8:
            continue
        poste_str = cols[0].get_text(strip=True)
        poste_num = None
        if poste_str:
            match = re.search(r'\d+', poste_str)
            if match:
                poste_num = int(match.group())
        quai = None
        if poste_num:
            try:
                poste = Poste.objects.get(numero=str(poste_num))
                quai = poste.quai
            except Poste.DoesNotExist:
                pass
        nav = {
            'nom': cols[1].get_text(strip=True),
            'type': TYPE_MAPPING.get(cols[2].get_text(strip=True), 'cargo'),
            'accostage': convertir_datetime(cols[3].get_text(strip=True)),
            'ted': convertir_heure_decimal(cols[4].get_text(strip=True)),
            'marchandise': cols[5].get_text(strip=True),
            'tonnage': extraire_tonnage(cols[6].get_text(strip=True)),
            'agent': cols[7].get_text(strip=True),
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
            'tonnage': extraire_tonnage(cols[5].get_text(strip=True)),
            'agent': cols[6].get_text(strip=True) if len(cols) > 6 else '',
        }
        navires.append(nav)
    return navires

def extraire_navires_attendus(table):
    navires = []
    rows = table.find_all('tr')[1:]
    for row in rows:
        cols = row.find_all('td')
        if len(cols) < 6:
            continue
        nav = {
            'nom': cols[0].get_text(strip=True),
            'type': TYPE_MAPPING.get(cols[1].get_text(strip=True), 'cargo'),
            'eta': convertir_datetime(cols[2].get_text(strip=True)) if len(cols) > 2 else None,
            'ted': convertir_heure_decimal(cols[3].get_text(strip=True)) if len(cols) > 3 else None,
            'marchandise': cols[4].get_text(strip=True) if len(cols) > 4 else '',
            'tonnage': extraire_tonnage(cols[5].get_text(strip=True)) if len(cols) > 5 else 0,
            'agent': cols[6].get_text(strip=True) if len(cols) > 6 else '',
        }
        navires.append(nav)
    return navires

def determiner_categorie(table):
    first_row = table.find('tr')
    if not first_row:
        return None
    th_cells = first_row.find_all('th')
    if th_cells:
        header = " ".join([th.get_text(strip=True).lower() for th in th_cells])
        if "poste" in header:
            return "quai"
        if "d.h.r" in header or "dhr" in header:
            return "rade"
        if "e.t.a" in header or "eta" in header:
            return "attente"
    cells = first_row.find_all('td')
    nb_cols = len(cells)
    if nb_cols == 8:
        return "quai"
    elif nb_cols == 7:
        return "rade"
    elif nb_cols >= 6:
        return "attente"
    return None

# ------------------------------------------------------------------------------
# IMPORT SANS BASCULEMENT
# ------------------------------------------------------------------------------
def importer_donnees_epb():
    print("🌐 Lancement du navigateur...")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
    try:
        driver.get(URL)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        time.sleep(2)
        html = driver.page_source
        with open("debug_page_selenium.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("💾 Page sauvegardée")
    finally:
        driver.quit()

    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table')
    print(f"🔍 {len(tables)} tableaux trouvés")

    navires_attendus = []
    navires_quai = []
    navires_rade = []

    for idx, table in enumerate(tables):
        cat = determiner_categorie(table)
        print(f"Tableau {idx+1} : {cat}")
        if cat == "attente":
            navires_attendus = extraire_navires_attendus(table)
        elif cat == "quai":
            navires_quai = extraire_navires_quai(table)
        elif cat == "rade":
            navires_rade = extraire_navires_rade(table)

    print(f"📊 Attendus: {len(navires_attendus)}, Quai: {len(navires_quai)}, Rade: {len(navires_rade)}")

    # ---- Navires en rade (déjà rade sur le site) ----
    for data in navires_rade:
        type_nav = data['type']
        longueur = LONGUEUR_DEFAUT.get(type_nav, 120)
        tirant = TIRANT_DEFAUT.get(type_nav, 7)
        priorites = get_priorites(type_nav, data['marchandise'])
        heure_arrivee = 0
        if data['dhr']:
            heure_arrivee = data['dhr'].hour + data['dhr'].minute / 60.0
        navire, created = Navire.objects.update_or_create(
            nom=data['nom'],
            defaults={
                'type': type_nav,
                'longueur': longueur,
                'tirant': tirant,
                'arrivee': heure_arrivee,
                'arrivee_datetime': data['dhr'],
                'etat': 'rade',
                'marchandise_type': data['marchandise'],
                'marchandise_volume': data['tonnage'],
                'agent': data['agent'],
                **priorites
            }
        )
        print(f"  {'Créé' if created else 'Mis à jour'} {navire.nom} (rade)")

    # ---- Navires à quai ----
    for data in navires_quai:
        type_nav = data['type']
        longueur = LONGUEUR_DEFAUT.get(type_nav, 120)
        tirant = TIRANT_DEFAUT.get(type_nav, 7)
        priorites = get_priorites(type_nav, data['marchandise'])
        heure_debut = 0
        if data['accostage']:
            heure_debut = data['accostage'].hour + data['accostage'].minute / 60.0
        heure_fin = None
        if data['ted'] is not None:
            heure_fin = heure_debut + data['ted']
        navire, created = Navire.objects.update_or_create(
            nom=data['nom'],
            defaults={
                'type': type_nav,
                'longueur': longueur,
                'tirant': tirant,
                'arrivee': 0,
                'etat': 'quai',
                'marchandise_type': data['marchandise'],
                'marchandise_volume': data['tonnage'],
                'quai_attribue': data['quai'],
                'heure_debut': heure_debut,
                'heure_fin': heure_fin,
                'debut_datetime': data['accostage'],
                'agent': data['agent'],
                **priorites
            }
        )
        print(f"  {'Créé' if created else 'Mis à jour'} {navire.nom} (quai {data['poste_original']})")

    # ---- Navires attendus (ETA) : TOUJOURS en attente, JAMAIS en rade ----
    for data in navires_attendus:
        type_nav = data['type']
        longueur = LONGUEUR_DEFAUT.get(type_nav, 120)
        tirant = TIRANT_DEFAUT.get(type_nav, 7)
        priorites = get_priorites(type_nav, data['marchandise'])
        eta_hour = 0
        if data['eta']:
            eta_hour = data['eta'].hour + data['eta'].minute / 60.0
        navire, created = Navire.objects.update_or_create(
            nom=data['nom'],
            defaults={
                'type': type_nav,
                'longueur': longueur,
                'tirant': tirant,
                'arrivee': eta_hour,
                'arrivee_datetime': data['eta'],
                'etat': 'attente',   # ← FORCÉ à 'attente'
                'marchandise_type': data['marchandise'],
                'marchandise_volume': data['tonnage'],
                'agent': data['agent'],
                **priorites
            }
        )
        print(f"  {'Créé' if created else 'Mis à jour'} {navire.nom} (attente, ETA {data['eta']})")

    print("\n✅ Import terminé. Aucun basculement automatique en rade.")

if __name__ == "__main__":
    importer_donnees_epb()