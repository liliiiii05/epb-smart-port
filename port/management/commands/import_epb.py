# port/management/commands/import_epb.py
import re
import requests
from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from bs4 import BeautifulSoup

from port.models import Navire, Quai, SnapshotNavire, Poste

URL = "https://www.portdebejaia.dz/situation-des-navires/"

TYPE_MAPPING = {
    "PORTE CONTENEURS": "conteneur",
    "CEREALIER": "cerealier",
    "PETROLIER": "petrolier",
    "BETAILLER": "betail",
    "HUILIER": "huilier",
    "BITUMIER": "petrolier",
    "CARGO": "cargo",
    "CAR-FERRY": "ferry",
    "ROULIER": "roulier",
    "FRIGORIFIQUE": "frigorifique",
    "GAZIER": "gazier",
    "ESSENCE": "essence",
    "NAVIRE CARBURANT": "essence",
    "NAVIRE SUCRE": "cargo",
}

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
}

# Mapping des numéros de postes (web -> base de données)
POSTE_NUM_MAPPING = {
    '1': '01', '2': '02', '3': '03',
    '4': '04', '5': '05', '6': '06', '7': '07',
    '8': '08', '9': '09', '10': '10',
    '11': '11', '12': '12', '13': '13', '14': '14',
    '15': '15', '16': '16', '17': '17', '18': '18',
    '19': '19', '20': '20', '21': '21', '22': '22',
    '23': '23', '24': '24', '25': '25', '26': '26',
    '90': '90',
}

def extraire_tonnage(tonnage_str):
    if not tonnage_str:
        return 0.0
    cleaned = re.sub(r'[^\d,.]', '', tonnage_str)
    cleaned = cleaned.replace(',', '.')
    if cleaned.count('.') > 1:
        parts = cleaned.split('.')
        cleaned = ''.join(parts[:-1]) + '.' + parts[-1]
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def convertir_heure_decimal(heure_str):
    if not heure_str:
        return None
    try:
        return float(heure_str.replace(',', '.'))
    except ValueError:
        return None

def convertir_datetime(date_str):
    if not date_str:
        return None
    date_str = date_str.strip()
    date_str = re.sub(r'\s+', ' ', date_str)
    if ' ' in date_str:
        date_part, time_part = date_str.split(' ', 1)
        time_part = time_part.replace('.', ':')
        try:
            parts = list(map(int, time_part.split(':')))
            h, m = parts[0], parts[1] if len(parts) > 1 else 0
            s = parts[2] if len(parts) > 2 else 0
        except:
            try:
                h = int(float(time_part))
                m = int((float(time_part) - h) * 60)
                s = 0
            except:
                h, m, s = 8, 0, 0
        jour, mois, annee = map(int, date_part.split('/'))
        return datetime(annee, mois, jour, h, m, s)
    else:
        jour, mois, annee = map(int, date_str.split('/'))
        return datetime(annee, mois, jour, 8, 0, 0)

def get_priorites(type_nav, marchandise):
    p = {
        'sortant': False, 'passage': False, 'gazier': False,
        'essence': False, 'animalier': False, 'perissable': False,
        'strategique': False, 'ligne_reguliere': False,
        'convention': False, 'huilier': False
    }
    if type_nav == 'gazier':
        p['gazier'] = True
    if type_nav == 'essence':
        p['essence'] = True
    if type_nav == 'betail':
        p['animalier'] = True
    if type_nav == 'huilier':
        p['huilier'] = True
    if type_nav == 'ferry':
        p['ligne_reguliere'] = True
    if any(w in marchandise.lower() for w in ['ble', 'mais', 'cereale', 'sucre']):
        p['strategique'] = True
    if 'frigorifique' in marchandise.lower():
        p['perissable'] = True
    return p

def get_poste_by_numero(poste_num):
    """Récupère un poste en gérant les formats (1 -> 01, etc.)"""
    if not poste_num:
        return None
    
    poste_num_str = str(poste_num).strip()
    
    # Essayer avec le numéro original
    try:
        return Poste.objects.get(numero=poste_num_str)
    except Poste.DoesNotExist:
        pass
    
    # Essayer avec le mapping
    if poste_num_str in POSTE_NUM_MAPPING:
        try:
            return Poste.objects.get(numero=POSTE_NUM_MAPPING[poste_num_str])
        except Poste.DoesNotExist:
            pass
    
    # Essayer avec un zéro devant
    if len(poste_num_str) == 1 and poste_num_str.isdigit():
        try:
            return Poste.objects.get(numero=f"0{poste_num_str}")
        except Poste.DoesNotExist:
            pass
    
    return None

def extraire_navires_attente(table):
    navires = []
    rows = table.find_all('tr')
    if len(rows) < 2:
        return navires
    header = rows[0].find_all(['th', 'td'])
    col_map = {}
    for i, cell in enumerate(header):
        texte = cell.get_text(strip=True).upper()
        if 'NAVIRE' in texte:
            col_map['nom'] = i
        elif 'TYPE' in texte:
            col_map['type'] = i
        elif 'E.T.A' in texte or 'ETA' in texte:
            col_map['eta'] = i
        elif 'MARCHANDISE' in texte:
            col_map['marchandise'] = i
        elif 'TONNAGE' in texte:
            col_map['tonnage'] = i
        elif 'AGENT' in texte:
            col_map['agent'] = i
        elif 'RECEPTIONNAIRE' in texte:
            col_map['receptionnaire'] = i
    if 'nom' not in col_map or 'type' not in col_map:
        col_map = {'nom': 0, 'type': 1, 'eta': 2, 'marchandise': 4, 'tonnage': 5, 'agent': 7, 'receptionnaire': 8}
    for row in rows[1:]:
        cols = row.find_all('td')
        if len(cols) < max(col_map.values()) + 1:
            continue
        eta_str = cols[col_map['eta']].get_text(strip=True)
        eta_dt = convertir_datetime(eta_str)
        eta = eta_dt.hour + eta_dt.minute/60.0 if eta_dt else 0
        nav = {
            'nom': cols[col_map['nom']].get_text(strip=True),
            'type': TYPE_MAPPING.get(cols[col_map['type']].get_text(strip=True), 'cargo'),
            'eta_dt': eta_dt,
            'eta': eta,
            'marchandise': cols[col_map['marchandise']].get_text(strip=True),
            'tonnage': extraire_tonnage(cols[col_map['tonnage']].get_text(strip=True)),
            'agent': cols[col_map['agent']].get_text(strip=True) if 'agent' in col_map else '',
            'receptionnaire': cols[col_map['receptionnaire']].get_text(strip=True) if 'receptionnaire' in col_map else '',
        }
        navires.append(nav)
    return navires

def extraire_navires_rade(table):
    navires = []
    rows = table.find_all('tr')
    if len(rows) < 2:
        return navires
    header = rows[0].find_all(['th', 'td'])
    col_map = {}
    for i, cell in enumerate(header):
        texte = cell.get_text(strip=True).upper()
        if 'NAVIRE' in texte:
            col_map['nom'] = i
        elif 'TYPE' in texte:
            col_map['type'] = i
        elif 'D.H.R' in texte or 'DHR' in texte:
            col_map['dhr'] = i
        elif 'MARCHANDISE' in texte:
            col_map['marchandise'] = i
        elif 'TONNAGE' in texte:
            col_map['tonnage'] = i
        elif 'AGENT' in texte:
            col_map['agent'] = i
        elif 'RECEPTIONNAIRE' in texte:
            col_map['receptionnaire'] = i
    if 'nom' not in col_map or 'type' not in col_map:
        col_map = {'nom': 0, 'type': 1, 'dhr': 2, 'marchandise': 4, 'tonnage': 5, 'agent': 6, 'receptionnaire': 7}
    for row in rows[1:]:
        cols = row.find_all('td')
        if len(cols) < max(col_map.values()) + 1:
            continue
        dhr_str = cols[col_map['dhr']].get_text(strip=True)
        dhr_dt = convertir_datetime(dhr_str)
        arrivee = dhr_dt.hour + dhr_dt.minute/60.0 if dhr_dt else 0
        nav = {
            'nom': cols[col_map['nom']].get_text(strip=True),
            'type': TYPE_MAPPING.get(cols[col_map['type']].get_text(strip=True), 'cargo'),
            'dhr_dt': dhr_dt,
            'arrivee': arrivee,
            'marchandise': cols[col_map['marchandise']].get_text(strip=True),
            'tonnage': extraire_tonnage(cols[col_map['tonnage']].get_text(strip=True)),
            'agent': cols[col_map['agent']].get_text(strip=True) if 'agent' in col_map else '',
            'receptionnaire': cols[col_map['receptionnaire']].get_text(strip=True) if 'receptionnaire' in col_map else '',
        }
        navires.append(nav)
    return navires

def extraire_navires_quai(table):
    navires = []
    rows = table.find_all('tr')
    if len(rows) < 2:
        return navires
    header = rows[0].find_all(['th', 'td'])
    col_map = {}
    for i, cell in enumerate(header):
        texte = cell.get_text(strip=True).upper()
        if 'POSTE' in texte:
            col_map['poste'] = i
        elif 'NAVIRE' in texte:
            col_map['nom'] = i
        elif 'TYPE' in texte:
            col_map['type'] = i
        elif 'ACCOSTAGE' in texte:
            col_map['accostage'] = i
        elif 'T.E.D' in texte or 'TED' in texte:
            col_map['ted'] = i
        elif 'MARCHANDISE' in texte:
            col_map['marchandise'] = i
        elif 'TONNAGE' in texte:
            col_map['tonnage'] = i
        elif 'AGENT' in texte:
            col_map['agent'] = i
        elif 'RECEPTIONNAIRE' in texte:
            col_map['receptionnaire'] = i
    
    if 'nom' not in col_map or 'type' not in col_map:
        col_map = {'poste': 0, 'nom': 1, 'type': 2, 'accostage': 3, 'ted': 4, 
                   'marchandise': 5, 'tonnage': 6, 'agent': 7, 'receptionnaire': 8}
    
    # Mapping explicite des numéros de postes (web -> base)
    POSTE_MAPPING = {
        '1': '01', '2': '02', '3': '03',
        '4': '04', '5': '05', '6': '06', '7': '07',
        '8': '08', '9': '09',
        '10': '10', '11': '11', '12': '12', '13': '13', 
        '14': '14', '15': '15', '16': '16', '17': '17', 
        '18': '18', '19': '19', '20': '20', '21': '21', 
        '22': '22', '23': '23', '24': '24', '25': '25', 
        '26': '26', '90': '90',
    }
    
    for row in rows[1:]:
        cols = row.find_all('td')
        if len(cols) < max(col_map.values()) + 1:
            continue
        
        poste_str = cols[col_map['poste']].get_text(strip=True)
        poste_num = None
        m = re.search(r'\d+', poste_str)
        if m:
            poste_num = m.group()
        
        # Récupérer le poste avec mapping explicite
        poste = None
        if poste_num:
            # Chercher d'abord avec le numéro mappé (1 -> 01)
            mapped_num = POSTE_MAPPING.get(poste_num, poste_num)
            try:
                poste = Poste.objects.get(numero=mapped_num)
                print(f"  ✅ Poste trouvé: {poste_num} -> '{mapped_num}'")
            except Poste.DoesNotExist:
                # Essayer avec le numéro original
                try:
                    poste = Poste.objects.get(numero=poste_num)
                    print(f"  ✅ Poste trouvé: {poste_num} (original)")
                except Poste.DoesNotExist:
                    # Essayer avec un zéro devant
                    if len(poste_num) == 1 and poste_num.isdigit():
                        try:
                            poste = Poste.objects.get(numero=f"0{poste_num}")
                            print(f"  ✅ Poste trouvé: {poste_num} -> '0{poste_num}'")
                        except Poste.DoesNotExist:
                            print(f"  ⚠️ Poste {poste_num} non trouvé (cherché '{mapped_num}', '{poste_num}', '0{poste_num}')")
                    else:
                        print(f"  ⚠️ Poste {poste_num} non trouvé (cherché '{mapped_num}')")
                    continue
        
        # Si le poste n'existe pas, ignorer ce navire
        if poste is None:
            continue
        
        accostage_str = cols[col_map['accostage']].get_text(strip=True)
        accostage_dt = convertir_datetime(accostage_str)
        heure_debut = accostage_dt.hour + accostage_dt.minute/60.0 if accostage_dt else 0
        ted = convertir_heure_decimal(cols[col_map['ted']].get_text(strip=True))
        
        nav = {
            'nom': cols[col_map['nom']].get_text(strip=True),
            'type': TYPE_MAPPING.get(cols[col_map['type']].get_text(strip=True), 'cargo'),
            'accostage_dt': accostage_dt,
            'heure_debut': heure_debut,
            'ted': ted,
            'marchandise': cols[col_map['marchandise']].get_text(strip=True),
            'tonnage': extraire_tonnage(cols[col_map['tonnage']].get_text(strip=True)),
            'agent': cols[col_map['agent']].get_text(strip=True),
            'receptionnaire': cols[col_map['receptionnaire']].get_text(strip=True) if 'receptionnaire' in col_map else '',
            'quai': poste.quai if poste else None,
            'poste': poste,
            'poste_original': poste_str,
        }
        navires.append(nav)
    return navires

class Command(BaseCommand):
    help = "Importe les données du site EPB et crée un snapshot journalier"

    def handle(self, *args, **options):
        self.stdout.write("🌐 Téléchargement de la page...")
        try:
            response = requests.get(URL, timeout=30)
            response.raise_for_status()
            html = response.text
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Erreur HTTP : {e}"))
            return

        soup = BeautifulSoup(html, 'html.parser')
        all_tables = soup.find_all('table')
        self.stdout.write(f"🔍 Nombre de tableaux : {len(all_tables)}")

        tableau_attente = None
        tableau_quai = None
        tableau_rade = None

        for table in all_tables:
            rows = table.find_all('tr')
            if not rows:
                continue
            first_row = rows[0]
            cells = first_row.find_all(['th', 'td'])
            text_first_cell = ' '.join(c.get_text(strip=True).upper() for c in cells[:3])
            if 'NAVIRE' in text_first_cell and 'TYPE' in text_first_cell and 'E.T.A' in text_first_cell:
                tableau_attente = table
            elif 'POSTE' in text_first_cell and 'NAVIRE' in text_first_cell and 'ACCOSTAGE' in text_first_cell:
                tableau_quai = table
            elif 'NAVIRE' in text_first_cell and 'TYPE' in text_first_cell and 'D.H.R' in text_first_cell:
                tableau_rade = table

        if not tableau_attente and len(all_tables) > 0:
            self.stdout.write("⚠️ Tableau Attendus non trouvé, utilisation du premier")
            tableau_attente = all_tables[0]
        if not tableau_quai and len(all_tables) > 1:
            self.stdout.write("⚠️ Tableau Quai non trouvé, utilisation du second")
            tableau_quai = all_tables[1]
        if not tableau_rade and len(all_tables) > 2:
            self.stdout.write("⚠️ Tableau Rade non trouvé, utilisation du troisième")
            tableau_rade = all_tables[2]

        navires_attente = extraire_navires_attente(tableau_attente) if tableau_attente else []
        navires_quai = extraire_navires_quai(tableau_quai) if tableau_quai else []
        navires_rade = extraire_navires_rade(tableau_rade) if tableau_rade else []

        self.stdout.write(f"📥 Attendus : {len(navires_attente)}")
        self.stdout.write(f"📥 À quai   : {len(navires_quai)}")
        self.stdout.write(f"📥 En rade  : {len(navires_rade)}")

        if navires_attente:
            self.stdout.write("Exemples attendus :")
            for nav in navires_attente[:3]:
                self.stdout.write(f"  - {nav['nom']} : ETA {nav['eta_dt']}")

        date_today = timezone.now().date()
        SnapshotNavire.objects.filter(date=date_today).delete()

        noms_aujourdhui = set()
        for nav in navires_attente:
            noms_aujourdhui.add(nav['nom'])
        for nav in navires_quai:
            noms_aujourdhui.add(nav['nom'])
        for nav in navires_rade:
            noms_aujourdhui.add(nav['nom'])

        # Marquer comme terminés les navires actifs non présents
        navires_terminer = Navire.objects.exclude(etat='termine').exclude(nom__in=noms_aujourdhui)
        for navire in navires_terminer:
            if navire.quai_attribue:
                quai = navire.quai_attribue
                quai.disponible = True
                quai.occupation_jusqua = 0.0
                quai.save()
                navire.quai_attribue = None
            if navire.poste_attribue:
                poste = navire.poste_attribue
                poste.disponible = True
                poste.occupation_jusqua = 0.0
                poste.save()
            navire.etat = 'termine'
            navire.save()
            self.stdout.write(f"  ⚠️ {navire.nom} marqué comme terminé (plus sur le site)")

        # Supprimer les occupants fictifs
        Navire.objects.filter(nom__startswith="OCCUPANT_").delete()

        # --- Navires en rade ---
        for data in navires_rade:
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
                    'arrivee': data['arrivee'],
                    'arrivee_datetime': data['dhr_dt'],
                    'etat': 'rade',
                    'marchandise_type': data['marchandise'],
                    'marchandise_volume': data['tonnage'],
                    'agent': data.get('agent', ''),
                    **priorites
                }
            )
            SnapshotNavire.objects.create(
                date=date_today,
                navire=navire,
                etat='rade',
                arrivee=data['arrivee'],
                quai_attribue=None,
                heure_debut=None,
                heure_fin=None
            )
            self.stdout.write(f"  {'Créé' if created else 'Mis à jour'} {navire.nom} (rade)")

        # --- Navires à quai ---
        for data in navires_quai:
            # Si le poste n'existe pas, ignorer ce navire
            if data['poste'] is None:
                self.stdout.write(f"  ⚠️ {data['nom']} ignoré (poste {data['poste_original']} non trouvé)")
                continue
                
            type_nav = data['type']
            longueur = LONGUEUR_DEFAUT.get(type_nav, 120)
            tirant = TIRANT_DEFAUT.get(type_nav, 7)
            priorites = get_priorites(type_nav, data['marchandise'])
            heure_fin = None
            if data['heure_debut'] is not None and data['ted'] is not None:
                heure_fin = data['heure_debut'] + data['ted']

            navire, created = Navire.objects.update_or_create(
                nom=data['nom'],
                defaults={
                    'type': type_nav,
                    'longueur': longueur,
                    'tirant': tirant,
                    'arrivee': 0,
                    'arrivee_datetime': None,
                    'etat': 'quai',
                    'marchandise_type': data['marchandise'],
                    'marchandise_volume': data['tonnage'],
                    'quai_attribue': data['quai'],
                    'poste_attribue': data['poste'],
                    'heure_debut': data['heure_debut'],
                    'debut_datetime': data['accostage_dt'],
                    'heure_fin': heure_fin,
                    'agent': data.get('agent', ''),
                    **priorites
                }
            )
            # Mettre à jour le poste (occupé)
            if data['poste']:
                poste = data['poste']
                poste.disponible = False
                poste.occupation_jusqua = heure_fin if heure_fin is not None else 0.0
                poste.save()
            SnapshotNavire.objects.create(
                date=date_today,
                navire=navire,
                etat='quai',
                arrivee=0,
                quai_attribue=data['quai'],
                heure_debut=data['heure_debut'],
                heure_fin=heure_fin
            )
            self.stdout.write(f"  {'Créé' if created else 'Mis à jour'} {navire.nom} (quai {data['poste_original']})")

        # --- Navires en attente ---
        for data in navires_attente:
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
                    'arrivee': data['eta'],
                    'arrivee_datetime': data['eta_dt'],
                    'etat': 'attente',
                    'marchandise_type': data['marchandise'],
                    'marchandise_volume': data['tonnage'],
                    'agent': data.get('agent', ''),
                    **priorites
                }
            )
            SnapshotNavire.objects.create(
                date=date_today,
                navire=navire,
                etat='attente',
                arrivee=data['eta'],
                quai_attribue=None,
                heure_debut=None,
                heure_fin=None
            )
            self.stdout.write(f"  {'Créé' if created else 'Mis à jour'} {navire.nom} (attente)")

        self.stdout.write(self.style.SUCCESS("\n✅ Importation terminée"))