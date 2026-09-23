# port/management/commands/corriger_quais_postes.py
"""
Correction complète des quais et postes selon le document officiel EPB.

RÈGLES :
- Les QUAIS ont une longueur + profondeur
- Les POSTES n'ont PAS de longueur/profondeur (sauf exception poste 25 = 180m)
- "L" (barre) = 9999 (illimité)
- "Sans restriction" = 9999
- Postes en travaux = disponible=False

Usage :
    python manage.py corriger_quais_postes --dry-run    # Test
    python manage.py corriger_quais_postes              # Applique
    python manage.py corriger_quais_postes --delete     # Reset complet
"""
from django.core.management.base import BaseCommand
from port.models import Quai, Poste
from django.db import transaction


ILLIMITE = 9999.0  # symbole "L" (barre) = illimité, "Sans restriction" = illimité


# =============================================================================
# DONNÉES OFFICIELLES EPB
# =============================================================================
# Structure :
#   - quai : { longueur, profondeur, specialite, type_navire_autorise, bassin,
#              postes: [ { numero, disponible, note, longueur? } ] }
#   - longueur optionnelle sur un poste = exception (ex: poste 25 = 180m)
# =============================================================================

DONNEES_QUAIS = {

    # ========================== BOUÉE SPM ==========================
    "Bouée SPM": {
        "longueur": ILLIMITE,        # L = illimité
        "profondeur": ILLIMITE,      # "Sans restriction"
        "specialite": "petrolier",
        "type_navire_autorise": "petrolier",
        "bassin": "Rade",
        "postes": [
            {
                "numero": "90",
                "disponible": True,
                "note": "Chargement pétrole brut pour VLCC - Jusqu'à 320 000 t - Longueur sans restriction",
            },
        ],
    },

    # ====================== APPONTEMENT N°01 =======================
    "Appontement N°01": {
        "longueur": ILLIMITE,        # L = illimité
        "profondeur": 10.0,
        "specialite": "essence",
        "type_navire_autorise": "essence,carburant",
        "bassin": "Avant-port (75h)",
        "postes": [
            {
                "numero": "01",
                "disponible": True,
                "note": "Déchargement gasoil - Navires ≤ 200m LOA, tirant ≤ 9.50m",
            },
        ],
    },

    # ====================== APPONTEMENT N°02 =======================
    "Appontement N°02": {
        "longueur": ILLIMITE,        # L = illimité
        "profondeur": 13.5,
        "specialite": "petrolier",
        "type_navire_autorise": "petrolier",
        "bassin": "Avant-port",
        "postes": [
            {
                "numero": "02",
                "disponible": True,
                "note": "Chargement pétrole brut - Navires ≤ 260m LOA, tirant ≤ 10m accostage, ≤ 12.50m charge",
            },
            {
                "numero": "03",
                "disponible": True,
                "note": "Chargement pétrole brut - Navires ≤ 260m LOA, tirant ≤ 10m accostage, ≤ 12.88m charge",
            },
        ],
    },

    # ========================= QUAI NORD ===========================
    "Quai nord": {
        "longueur": ILLIMITE,        # L = illimité
        "profondeur": 13.5,
        "specialite": "petrolier",
        "type_navire_autorise": "petrolier",
        "bassin": "Vieux port (26h)",
        "postes": [
            {
                "numero": "06",
                "disponible": False,   # 🚧 En travaux
                "note": "🚧 En travaux - Réalignement + poste RO/RO pour Car-ferries",
            },
            {
                "numero": "07",
                "disponible": False,   # 🚧 En travaux
                "note": "🚧 En travaux - Réalignement + poste RO/RO pour Car-ferries",
            },
        ],
    },

    # ===================== QUAI NORD-OUEST =========================
    "Quai nord-ouest": {
        "longueur": 383.0,
        "profondeur": 8.80,
        "specialite": "general",
        "type_navire_autorise": "ferry,general",
        "bassin": "Vieux port",
        "postes": [
            {
                "numero": "08",
                "disponible": True,
                "note": "Car-ferries + Général cargo - Navires ≤ 108m, tirant ≤ 8.30m",
            },
            {
                "numero": "09",
                "disponible": False,   # 🚧 En chantier
                "note": "🚧 En chantier - Car-ferries + Général cargo",
            },
            {
                "numero": "10",
                "disponible": False,   # 🚧 En chantier
                "note": "🚧 En chantier - Car-ferries + Général cargo",
            },
            {
                "numero": "11",
                "disponible": True,
                "note": "Général cargo - Navires ≤ 108m, tirant ≤ 8.30m",
            },
        ],
    },

    # ===================== QUAI DE LA CASBAH =======================
    "Quai de la Casbah": {
        "longueur": 254.0,
        "profondeur": 8.80,
        "specialite": "general",
        "type_navire_autorise": "ferry,general",
        "bassin": "Vieux port",
        "postes": [
            {
                "numero": "12",
                "disponible": True,
                "note": "Car-ferries + Général cargo - Navires ≤ 108m, tirant ≤ 8.30m",
            },
            {
                "numero": "13",
                "disponible": True,
                "note": "Car-ferries + Général cargo - Navires ≤ 108m, tirant ≤ 8.30m",
            },
        ],
    },

    # ====================== QUAI DE LA PASSE =======================
    "Quai de la Passe": {
        "longueur": 154.0,
        "profondeur": 10.0,
        "specialite": "general",
        "type_navire_autorise": "general",
        "bassin": "Vieux port",
        "postes": [
            {
                "numero": "14",
                "disponible": True,
                "note": "Général cargo - Navires ≤ 109m, tirant ≤ 9.50m",
            },
        ],
    },

    # ===================== QUAI SUD-OUEST ==========================
    "Quai Sud-Ouest": {
        "longueur": 238.0,
        "profondeur": 10.80,
        "specialite": "cerealier",
        "type_navire_autorise": "cerealier,general",
        "bassin": "Arrière port (55h)",
        "postes": [
            {
                "numero": "15",
                "disponible": True,
                "note": "Céréales + Général cargo - Navires ≤ 110m, tirant ≤ 10.30m",
            },
            {
                "numero": "16",
                "disponible": True,
                "note": "Céréales + Général cargo - Navires ≤ 110m, tirant ≤ 10.30m",
            },
        ],
    },

    # ===================== QUAI DE LA GARE =========================
    "Quai de la Gare": {
        "longueur": 430.0,
        "profondeur": 10.50,
        "specialite": "cerealier",
        "type_navire_autorise": "cerealier,general",
        "bassin": "Arrière port",
        "postes": [
            {
                "numero": "17",
                "disponible": True,
                "note": "Céréales + Général cargo - Navires ≤ 140m LOA, tirant ≤ 10.30m",
            },
            {
                "numero": "18",
                "disponible": True,
                "note": "Général cargo - Navires ≤ 140m LOA, tirant ≤ 9.50m",
            },
            {
                "numero": "19",
                "disponible": True,
                "note": "Général cargo + Essence + Gasoil + Bitume - Navires ≤ 140m LOA, tirant ≤ 6.40m",
            },
        ],
    },

    # ======================= NOUVEAU QUAI ==========================
    "Nouveau quai": {
        "longueur": 750.0,
        "profondeur": 12.0,
        "specialite": "general",
        "type_navire_autorise": "cerealier,conteneur,huilier,gazier,general",
        "bassin": "Arrière port",
        "postes": [
            {
                "numero": "20",
                "disponible": True,
                "note": "Dock flottant (réparation navale) - ERENAV 180x40m, capacité 15 000 t",
            },
            {
                "numero": "21",
                "disponible": True,
                "note": "Céréales + Général cargo (affecté OAIC) - Navires ≤ 11.30m de tirant",
            },
            {
                "numero": "22",
                "disponible": True,
                "note": "Conteneurs - Navires ≤ 11.30m de tirant",
            },
            {
                "numero": "23",
                "disponible": True,
                "note": "Conteneurs + Huiliers - Navires ≤ 11.30m de tirant",
            },
            {
                "numero": "24",
                "disponible": True,
                "note": "Huiliers + Conteneurs + Gaz + Général cargo - Navires ≤ 11.30m de tirant",
            },
            {
                "numero": "25",
                "disponible": True,
                "note": "Sucre + Huile de Palme + Général cargo - Navires ≤ 185m LOA",
                "longueur": 180.0,   # ✅ EXCEPTION : poste 25 = 180m (au lieu de 750m)
            },
        ],
    },

    # ==================== QUAI JETÉE DU LARGE ======================
    "Quai jetée du large": {
        "longueur": ILLIMITE,        # L = illimité
        "profondeur": 12.50,
        "specialite": "gazier",
        "type_navire_autorise": "gazier,huilier",
        "bassin": "Arrière port",
        "postes": [
            {
                "numero": "26",
                "disponible": True,
                "note": "Gaz + Huile - Navires ≤ 185m LOA",
            },
        ],
    },
}


class Command(BaseCommand):
    help = "Corrige les quais et postes selon le document officiel EPB"

    def add_arguments(self, parser):
        parser.add_argument('--delete', action='store_true',
                            help='Supprime TOUT avant de recréer')
        parser.add_argument('--dry-run', action='store_true',
                            help='Affiche sans modifier')

    def handle(self, *args, **options):
        dry = options['dry_run']
        delete = options['delete']

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n" + "="*70 + "\n"
            "CORRECTION DES QUAIS ET POSTES EPB (Document officiel)\n"
            + "="*70
        ))

        if dry:
            self.stdout.write(self.style.WARNING(
                "🔍 MODE DRY-RUN : Aucune modification ne sera enregistrée\n"
            ))

        if delete and not dry:
            self.stdout.write(self.style.WARNING(
                "\n⚠️  SUPPRESSION DE TOUS LES QUAIS ET POSTES...\n"
            ))
            with transaction.atomic():
                Poste.objects.all().delete()
                Quai.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("✅ Ancien contenu supprimé\n"))

        stats = {'q_crees': 0, 'q_maj': 0, 'p_crees': 0, 'p_maj': 0}
        numeros_valides = set()

        for nom_quai, data in DONNEES_QUAIS.items():
            # Affichage
            longueur_affichee = ("ILLIMITÉ (L)"
                                 if data['longueur'] == ILLIMITE
                                 else f"{data['longueur']} m")
            profondeur_affichee = ("SANS RESTRICTION"
                                   if data['profondeur'] == ILLIMITE
                                   else f"{data['profondeur']} m")

            self.stdout.write(f"\n{'='*70}")
            self.stdout.write(f"🏗️  {self.style.HTTP_INFO(nom_quai)}")
            self.stdout.write(f"    Longueur   : {longueur_affichee}")
            self.stdout.write(f"    Profondeur : {profondeur_affichee}")
            self.stdout.write(f"    Spécialité : {data['specialite']}")
            self.stdout.write(f"    Bassin     : {data.get('bassin', '-')}")
            self.stdout.write(f"    Postes     : {', '.join(p['numero'] for p in data['postes'])}")

            if dry:
                if Quai.objects.filter(nom=nom_quai).exists():
                    stats['q_maj'] += 1
                else:
                    stats['q_crees'] += 1
                for p in data['postes']:
                    numeros_valides.add(p['numero'])
                    if Poste.objects.filter(numero=p['numero']).exists():
                        stats['p_maj'] += 1
                    else:
                        stats['p_crees'] += 1
                continue

            # ============ CRÉER / METTRE À JOUR LE QUAI ============
            quai, created = Quai.objects.update_or_create(
                nom=nom_quai,
                defaults={
                    'longueur': data['longueur'],
                    'profondeur': data['profondeur'],
                    'specialite': data['specialite'],
                    'type_navire_autorise': data['type_navire_autorise'],
                    'disponible': True,
                }
            )
            if created:
                stats['q_crees'] += 1
                self.stdout.write(self.style.SUCCESS(f"    ✅ Quai créé"))
            else:
                stats['q_maj'] += 1
                self.stdout.write(self.style.SUCCESS(f"    ✅ Quai mis à jour"))

            # ============ CRÉER / METTRE À JOUR LES POSTES ============
            # ⚠️ PAS de longueur/profondeur sur les postes (sauf exception poste 25)
            for p_data in data['postes']:
                numero = p_data['numero']
                numeros_valides.add(numero)

                defaults = {
                    'quai': quai,
                    'specialite': data['specialite'],
                    'type_navire_autorise': p_data.get('note',
                                                       data['type_navire_autorise']),
                    'disponible': p_data.get('disponible', True),
                }

                # ✅ EXCEPTION : longueur spécifique sur le poste (ex: poste 25 = 180m)
                if 'longueur' in p_data:
                    defaults['longueur'] = p_data['longueur']
                    defaults['profondeur'] = data['profondeur']  # hérite
                else:
                    # Par défaut, pas de longueur/profondeur sur les postes
                    # (on met 0 pour éviter les NOT NULL, mais ce champ ne sera pas utilisé)
                    defaults['longueur'] = 0.0
                    defaults['profondeur'] = 0.0

                poste, p_created = Poste.objects.update_or_create(
                    numero=numero,
                    defaults=defaults,
                )

                etat_icone = "✅" if p_data.get('disponible', True) else "🚧"
                exception = ""
                if 'longueur' in p_data:
                    exception = f"  ⚠️ longueur spécifique = {p_data['longueur']} m"

                if p_created:
                    stats['p_crees'] += 1
                    self.stdout.write(f"       └─ {etat_icone} Poste {numero} créé{exception}")
                else:
                    stats['p_maj'] += 1
                    self.stdout.write(f"       └─ {etat_icone} Poste {numero} mis à jour{exception}")

        # ============ SIGNALER LES POSTES ORPHELINS ============
        if not dry:
            orphelins = Poste.objects.exclude(numero__in=numeros_valides)
            if orphelins.exists():
                self.stdout.write(self.style.WARNING(
                    f"\n⚠️  {orphelins.count()} poste(s) orphelin(s) détecté(s) :"
                ))
                for p in orphelins:
                    quai_nom = p.quai.nom if p.quai else 'AUCUN'
                    self.stdout.write(f"    - Poste {p.numero} (quai: {quai_nom})")
                self.stdout.write(
                    "    → Ces postes ne sont pas dans le document officiel.\n"
                    "      Pour les supprimer : Poste.objects.filter(numero__in=[...]).delete()"
                )

        # ============ RÉSUMÉ ============
        self.stdout.write("\n" + "="*70)
        self.stdout.write(self.style.MIGRATE_HEADING("RÉSUMÉ"))
        self.stdout.write("="*70)
        self.stdout.write(f"  Quais créés       : {stats['q_crees']}")
        self.stdout.write(f"  Quais mis à jour  : {stats['q_maj']}")
        self.stdout.write(f"  Postes créés      : {stats['p_crees']}")
        self.stdout.write(f"  Postes mis à jour : {stats['p_maj']}")
        self.stdout.write("="*70)

        if dry:
            self.stdout.write(self.style.WARNING(
                "\n🔍 DRY-RUN terminé. Relancez sans --dry-run pour appliquer.\n"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                "\n✅ Correction terminée avec succès !\n"
            ))