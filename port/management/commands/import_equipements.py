# port/management/commands/import_equipements.py
import re
import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from port.models import Equipement

URL = "https://www.portdebejaia.dz/nos-equipements/"

TYPE_MAPPING = {
    "Chariots élévateurs à pinces": "chariot_pince",
    "Chariots élévateurs à fourches": "chariot_fourche",
    "Grues portuaires": "grue_portuaire",
    "Grues télescopiques": "grue_telescopique",
    "Portique à grains": "portique_grains",
    "Chargeurs sur pneus": "chargeur_pneus",
    "Pelles sur chenille": "pelle_chenille",
    "Pelles Chargeuses excavatrices": "pelle_chargeuse_excavatrice",
    "Tracteurs semi-remorques": "tracteur_semi_remorque",
    "Tracteurs Ro-Ro": "tracteur_roro",
    "Plateaux remorques": "plateau_remorque",
    "Bennes motorisées à lames": "benne_motorisee_lame",
    "Bennes motorisée à dents": "benne_motorisee_dent",
    "Bennes hydroélectriques": "benne_hydroelectrique",
    "Spreader automatique": "spreader_auto",
    "Grappin motorisé": "grappin_motorise",
    "Scanner mobile": "scanner_mobile",
    "Ponts bascules": "pont_bascule",
    "Grue de 50 Tonnes": "grue_50t",
    "Tracteurs semi-remorque": "tracteur_semi_remorque",
    "Chariots élévateurs": "chariot_elec",
    "Pont-bascule": "pont_bascule",
    "Reach stacker": "reach_stacker",
    "Grue automotrice": "grue_automotrice",
    "Bras de chargement GNL": "bras_chargement_gnl",
    "Tuyauterie cryogénique": "tuyauterie_cryogenique",
    "Bras de chargement pétrolier": "bras_chargement_petrolier",
    "Pompe haute capacité": "pompe_haute_capacite",
    "Système anti-déflagrant": "systeme_anti_deflagrant",
    "Bras de chargement essence": "bras_chargement_essence",
    "Pompe anti-déflagrante": "pompe_anti_deflagrante",
    "Système de récupération vapeur": "systeme_recuperation_vapeur",
    "Bras de chargement huile": "bras_chargement_huile",
    "Pompe alimentaire": "pompe_alimentaire",
    "Filtre": "filtre",
    "Rampe d'accès": "rampe_acces",
    "Système de ventilation": "systeme_ventilation",
    "Abreuvement": "abreuvement",
    "Passerelle d'accès": "passerelle_acces",
    "Système d'amarrage rapide": "systeme_amarrage_rapide",
    "Rampe de chargement": "rampe_chargement",
}

def extraire_nombre(cell):
    if not cell:
        return 0
    match = re.search(r'(\d+)', cell)
    return int(match.group(1)) if match else 0

def extraire_capacite(cell):
    if not cell:
        return 0.0
    cell_clean = cell.replace(',', '.')
    match = re.search(r'(\d+(?:\.\d+)?)', cell_clean)
    if match:
        return float(match.group(1))
    if 'à' in cell_clean:
        parts = cell_clean.split('à')
        for p in reversed(parts):
            m = re.search(r'(\d+(?:\.\d+)?)', p)
            if m:
                return float(m.group(1))
    return 0.0

class Command(BaseCommand):
    help = "Importe les équipements depuis le site EPB (uniquement manutention)"

    def handle(self, *args, **options):
        self.stdout.write("🌐 Récupération de la page des équipements...")
        try:
            response = requests.get(URL, timeout=15)
            response.raise_for_status()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Erreur HTTP : {e}"))
            return

        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table')
        self.stdout.write(f"🔍 Nombre de tableaux trouvés : {len(tables)}")

        equipements_par_type = {}

        # On s'arrête dès qu'on rencontre un titre contenant "AUTRES EQUIPEMENTS"
        stop = False
        for table in tables:
            # Vérifier le titre précédent
            prev = table.find_previous_sibling()
            titre = ""
            while prev and prev.name not in ['h2', 'h3']:
                prev = prev.find_previous_sibling()
            if prev:
                titre = prev.get_text(strip=True)
            if "AUTRES EQUIPEMENTS" in titre.upper():
                stop = True
                break

            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all('td')
                if len(cells) < 3:
                    continue
                designation = cells[0].get_text(strip=True)
                if not designation or "désignation" in designation.lower():
                    continue

                capacite_str = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                nombre_str = cells[2].get_text(strip=True) if len(cells) > 2 else ""

                type_norm = TYPE_MAPPING.get(designation, designation.lower().replace(' ', '_'))

                capacite = extraire_capacite(capacite_str)
                if capacite == 0:
                    capacite = 1.0

                nombre = extraire_nombre(nombre_str)

                if type_norm not in equipements_par_type:
                    equipements_par_type[type_norm] = {'capacite': capacite, 'nombre': 0}
                equipements_par_type[type_norm]['nombre'] += nombre

        # Mise à jour ou création dans la base
        created = 0
        updated = 0
        for type_norm, data in equipements_par_type.items():
            # Filtrer les équipements trop génériques ou mal nommés
            if type_norm in ["pont_bascule", "scanner_mobile", "grue_50t"]:
                continue  # à garder si nécessaire, mais souvent optionnels
            obj, created_flag = Equipement.objects.update_or_create(
                type=type_norm,
                defaults={
                    'capacite': data['capacite'],
                    'nombre': data['nombre'],
                    'disponibles': data['nombre'],
                    'en_panne': False,
                    'temps_reparation': 2.0,
                }
            )
            if created_flag:
                created += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"✅ Import terminé : {created} créés, {updated} mis à jour."))