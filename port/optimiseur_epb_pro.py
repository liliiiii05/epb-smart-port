#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
OPTIMISEUR EPB - Version avec gestion des incertitudes et buffers
Version finale : prise en compte des occupations initiales, équipements multiples, créneaux futurs,
shifts, standards par entité, postes (numéro), préférences pour céréaliers, saturation des quais,
et score toujours positif.

=== CORRECTIONS APPLIQUÉES (voir commentaires "# >>> CORRECTION") ===
1. Le score de contribution intègre désormais l'attente liée aux équipements
   (auparavant calculée mais jamais utilisée dans la décision de choix de quai).
2. Certains types de navires (huilier, frigorifique, essence, chimiquier, roulier,
   ferry, betail) qui étaient figés sur toujours les 2 MÊMES équipements disposent
   désormais d'une liste de candidats plus large, et le code choisit automatiquement
   celui qui est le moins chargé au moment considéré (basé uniquement sur l'agenda
   de réservation interne du planificateur -- AUCUNE dépendance à une donnée de
   panne externe, puisque cette information n'est pas toujours disponible).
"""

import random
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta
import json
import csv
import logging
import hashlib
import time
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from .ml_model import DureeTraitementModel
import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# CONFIGURATION DU LOGGING
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('optimiseur_epb.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('EPB_Optimiseur')

# =============================================================================
# ÉNUMÉRATIONS ET CONSTANTES
# =============================================================================

class Saison(Enum):
    PRINTEMPS = "printemps"
    ETE = "ete"
    AUTOMNE = "automne"
    HIVER = "hiver"

class TypeNavire(Enum):
    CONTENEUR = "conteneur"
    CEREALIER = "cerealier"
    FERRY = "ferry"
    GAZIER = "gazier"
    FRIGORIFIQUE = "frigorifique"
    BETAIL = "betail"
    ESSENCE = "essence"
    HUILIER = "huilier"
    PETROLIER = "petrolier"
    CARGO = "cargo"
    ROULIER = "roulier"
    CHIMIQUIER = "chimiquier"

class Priorite(Enum):
    SORTANT = "sortant"
    PASSAGE = "passage"
    GAZIER_HIVER = "gazier_hiver"
    ESSENCE = "essence"
    ANIMALIER = "animalier"
    PERISSABLE = "perissable"
    STRATEGIQUE = "strategique"
    LIGNE_REGULIERE = "ligne_reguliere"
    CONVENTION = "convention"
    HUILIER = "huilier"

POIDS_PRIORITES = {
    Priorite.SORTANT: 100,
    Priorite.PASSAGE: 80,
    Priorite.GAZIER_HIVER: 150,
    Priorite.ESSENCE: 70,
    Priorite.ANIMALIER: 90,
    Priorite.PERISSABLE: 85,
    Priorite.STRATEGIQUE: 95,
    Priorite.LIGNE_REGULIERE: 75,
    Priorite.CONVENTION: 60,
    Priorite.HUILIER: 50
}

NIVEAUX_PRIORITE = {
    Priorite.SORTANT: 1,
    Priorite.PASSAGE: 2,
    Priorite.GAZIER_HIVER: 3,
    Priorite.ESSENCE: 4,
    Priorite.ANIMALIER: 5,
    Priorite.PERISSABLE: 6,
    Priorite.STRATEGIQUE: 7,
    Priorite.LIGNE_REGULIERE: 8,
    Priorite.CONVENTION: 9,
    Priorite.HUILIER: 10,
}

POIDS_NIVEAU = {
    1: 1000,
    2: 900,
    3: 800,
    4: 700,
    5: 600,
    6: 500,
    7: 400,
    8: 300,
    9: 200,
    10: 100,
}

# Standards d'exploitation par entité (coefficient de traitement, quais préférés, bonus priorité)
STANDARDS_ENTITE = {
    'EPB': {'quais_preferes': [], 'traitement_base': 1.0, 'priority_bonus': 0},
    'BMT': {'quais_preferes': [22, 24], 'traitement_base': 0.9, 'priority_bonus': 10},
    'CEVITAL': {'quais_preferes': [25], 'traitement_base': 1.2, 'priority_bonus': 20},
    'NAFTAL': {'quais_preferes': [1, 2, 3], 'traitement_base': 1.1, 'priority_bonus': 15},
    'STH': {'quais_preferes': [], 'traitement_base': 1.0, 'priority_bonus': 5},
    'OAIC': {'quais_preferes': [17, 18], 'traitement_base': 1.0, 'priority_bonus': 25},
}

# Groupes de postes adjacents (pour navires très longs)
GROUPES_POSTES = {
    (12, 13): {"longueur_totale": 250 + 250, "specialite": "ferry", "nom": "Postes 12+13"},
    (15, 16): {"longueur_totale": 234 + 234, "specialite": "cerealier", "nom": "Postes 15+16"},
}

# =============================================================================
# STRUCTURES DE DONNÉES
# =============================================================================

@dataclass
class Quai:
    id: int
    nom: str
    longueur: float
    profondeur: float
    specialite: str
    equipements_fixes: List[str] = field(default_factory=list)
    disponible: bool = True
    libre: float = 0.0
    performance: float = 1.0
    coeff_manoeuvre: float = 1.0
    poste_numero: int = 0
    est_groupe: bool = False
    postes_membres: List[int] = field(default_factory=list)

    def __post_init__(self):
        self.nom_complet = f"Quai {self.id} - {self.nom}"

@dataclass
class Marchandise:
    type: str
    volume: float
    dangereux: bool = False
    fragile: bool = False
    frigo: bool = False
    duree_limite: Optional[float] = None
    importance: int = 0

@dataclass
class EquipementPropre:
    a_grue_bord: bool = False
    type_grue: Optional[str] = None
    capacite: float = 0

@dataclass
class PrioritesNavire:
    sortant: bool = False
    passage: bool = False
    gazier: bool = False
    essence: bool = False
    animalier: bool = False
    perissable: bool = False
    strategique: bool = False
    ligne_reguliere: bool = False
    convention: bool = False
    huilier: bool = False

@dataclass
class Navire:
    id: int
    nom: str
    type: TypeNavire
    longueur: float
    tirant: float
    arrivee: float
    priorites: PrioritesNavire
    marchandise: Marchandise
    equipement_propre: EquipementPropre
    priorite_calculee: float = 0.0
    coeff_variation: float = 0.15
    arrivee_datetime: Optional[datetime] = None
    fin_prevue: Optional[float] = None
    agent: str = ""
    entite: str = ""
    est_en_rade: bool = False
    nb_equipes_requises: int = 1
    shift_requis: str = 'matin'

    def __post_init__(self):
        self.heure_arrivee_str = f"{int(self.arrivee)}h{int((self.arrivee % 1) * 60):02d}"
        self.categorie = self.type.value

@dataclass
class Equipement:
    id: int
    type: str
    capacite: float
    nombre: int
    dispo: int = 0
    libre_jusqua: float = 0.0
    en_panne: bool = False
    temps_reparation: float = 2.0
    panne_debut: Optional[datetime] = None

@dataclass
class AffectationResultat:
    navire_id: int
    navire_nom: str
    type_navire: str
    quai_id: int
    quai_nom: str
    heure_arrivee: float
    heure_accostage: float
    heure_fin: float
    attente: float
    traitement: float
    priorite_calculee: float
    priorites_speciale: str
    equipements: List[str]
    utilise_grues_bord: bool
    score_contribution: float
    buffer_debut: float = 0.0
    buffer_fin: float = 0.0
    heure_debut_securise: float = 0.0
    heure_fin_securise: float = 0.0
    agent: str = ""
    temps_manoeuvre: float = 1.2
    equipe_nom: str = None
    est_groupe: bool = False
    postes_ids: List[int] = field(default_factory=list)
    attente_equipements: float = 0.0

@dataclass
class RapportOptimisation:
    id: str
    date: datetime
    duree_calcul: float
    nb_navires: int
    nb_quais: int
    nb_equipements: int
    score_total: float
    attente_totale: float
    attente_moyenne: float
    traitement_total: float
    traitement_moyen: float
    taux_occupation: float
    navires_planifies: int
    affectations: List[AffectationResultat]
    convergence: List[float]

# =============================================================================
# GESTIONNAIRE DE DONNÉES (pour tests hors Django)
# =============================================================================

class GestionnaireDonnees:
    QUAIS_EPB = [
        {"id": 1, "nom": "Poste pétrolier 01", "longueur": 260, "profondeur": 13.5, "specialite": "petrolier", "libre": 0.0, "performance": 1.1,
         "equipements_fixes": ["bras_chargement_petrolier", "pompe_haute_capacite", "systeme_anti_deflagrant"]},
        {"id": 2, "nom": "Poste pétrolier 02", "longueur": 260, "profondeur": 13.5, "specialite": "petrolier", "libre": 0.0, "performance": 1.1,
         "equipements_fixes": ["bras_chargement_petrolier", "pompe_haute_capacite", "systeme_anti_deflagrant"]},
        {"id": 3, "nom": "Poste pétrolier 03", "longueur": 250, "profondeur": 13.0, "specialite": "petrolier", "libre": 0.0, "performance": 1.1,
         "equipements_fixes": ["bras_chargement_petrolier", "pompe_haute_capacite", "systeme_anti_deflagrant"]},
        {"id": 4, "nom": "Quai Céréalier 04", "longueur": 300, "profondeur": 12.0, "specialite": "cerealier", "libre": 0.0, "performance": 1.2,
         "equipements_fixes": ["suceuse_cereales", "convoyeur_bande", "tracteur_remorque_50t"]},
        {"id": 5, "nom": "Quai Céréalier 05", "longueur": 300, "profondeur": 12.0, "specialite": "cerealier", "libre": 0.0, "performance": 1.2,
         "equipements_fixes": ["suceuse_cereales", "convoyeur_bande", "tracteur_remorque_50t"]},
        {"id": 8, "nom": "Quai 8", "longueur": 290, "profondeur": 8.0, "specialite": "ferry", "libre": 0.0, "performance": 1.0,
         "equipements_fixes": ["passerelle_acces", "systeme_amarrage_rapide", "rampe_chargement"]},
        {"id": 11, "nom": "Quai 11", "longueur": 273, "profondeur": 8.0, "specialite": "general", "libre": 0.0, "performance": 1.0,
         "equipements_fixes": ["grue_mobile_50t", "chariot_10t"]},
        {"id": 12, "nom": "Quai 12", "longueur": 257, "profondeur": 8.0, "specialite": "ferry", "libre": 0.0, "performance": 1.0,
         "equipements_fixes": ["passerelle_acces", "systeme_amarrage_rapide", "rampe_chargement"]},
        {"id": 13, "nom": "Quai 13", "longueur": 273, "profondeur": 8.0, "specialite": "ferry", "libre": 0.0, "performance": 1.0,
         "equipements_fixes": ["passerelle_acces", "systeme_amarrage_rapide", "rampe_chargement"]},
        {"id": 14, "nom": "Quai 14", "longueur": 257, "profondeur": 8.0, "specialite": "general", "libre": 0.0, "performance": 1.0,
         "equipements_fixes": ["grue_mobile_50t", "chariot_10t"]},
        {"id": 15, "nom": "Quai 15", "longueur": 146, "profondeur": 8.5, "specialite": "general", "libre": 0.0, "performance": 1.0,
         "equipements_fixes": ["grue_mobile_50t", "chariot_10t"]},
        {"id": 16, "nom": "Quai 16", "longueur": 146, "profondeur": 8.5, "specialite": "general", "libre": 0.0, "performance": 1.0,
         "equipements_fixes": ["grue_mobile_50t", "chariot_10t"]},
        {"id": 17, "nom": "Quai 17", "longueur": 230, "profondeur": 10.0, "specialite": "conteneurs", "libre": 0.0, "performance": 1.0,
         "equipements_fixes": ["grue_gottwald_260e", "reach_stacker", "chariot_32t"]},
        {"id": 18, "nom": "Quai 18", "longueur": 230, "profondeur": 10.0, "specialite": "conteneurs", "libre": 0.0, "performance": 1.0,
         "equipements_fixes": ["grue_gottwald_260e", "reach_stacker", "chariot_32t"]},
        {"id": 19, "nom": "Quai 19", "longueur": 230, "profondeur": 10.0, "specialite": "essence", "libre": 0.0, "performance": 1.0,
         "equipements_fixes": ["bras_chargement_essence", "pompe_anti_deflagrante", "systeme_recuperation_vapeur"]},
        {"id": 21, "nom": "Quai 21", "longueur": 530, "profondeur": 10.0, "specialite": "grand", "libre": 0.0, "performance": 1.2,
         "equipements_fixes": ["grue_mobile_50t", "chariot_10t"]},
        {"id": 22, "nom": "Quai 22", "longueur": 530, "profondeur": 10.0, "specialite": "grand", "libre": 0.0, "performance": 1.2,
         "equipements_fixes": ["grue_mobile_50t", "chariot_10t"]},
        {"id": 23, "nom": "Quai 23", "longueur": 530, "profondeur": 10.0, "specialite": "grand", "libre": 0.0, "performance": 1.2,
         "equipements_fixes": ["grue_mobile_50t", "chariot_10t"]},
        {"id": 24, "nom": "Quai 24", "longueur": 530, "profondeur": 10.0, "specialite": "gazier", "libre": 0.0, "performance": 1.0,
         "equipements_fixes": ["bras_chargement_gnl", "tuyauterie_cryogenique"]},
        {"id": 25, "nom": "Quai 25", "longueur": 78, "profondeur": 12.0, "specialite": "huilier", "libre": 0.0, "performance": 1.0,
         "equipements_fixes": ["bras_chargement_huile", "pompe_alimentaire", "filtre"]},
        {"id": 26, "nom": "Quai 26", "longueur": 750, "profondeur": 12.0, "specialite": "grand", "libre": 0.0, "performance": 1.2,
         "equipements_fixes": ["grue_mobile_50t", "chariot_10t"]},
    ]

    EQUIPEMENTS_EPB = [
        {"id": 1, "type": "suceuse_cereales", "capacite": 550, "nombre": 2},
        {"id": 2, "type": "convoyeur_bande", "capacite": 550, "nombre": 2},
        {"id": 3, "type": "tracteur_remorque_50t", "capacite": 50, "nombre": 4},
        {"id": 4, "type": "bras_chargement_petrolier", "capacite": 500, "nombre": 3},
        {"id": 5, "type": "pompe_haute_capacite", "capacite": 500, "nombre": 3},
        {"id": 6, "type": "systeme_anti_deflagrant", "capacite": 1, "nombre": 3},
        {"id": 7, "type": "grue_gottwald_260e", "capacite": 260, "nombre": 2},
        {"id": 8, "type": "reach_stacker", "capacite": 38, "nombre": 2},
        {"id": 9, "type": "chariot_32t", "capacite": 32, "nombre": 1},
        {"id": 10, "type": "grue_mobile_50t", "capacite": 50, "nombre": 2},
        {"id": 11, "type": "chariot_10t", "capacite": 10, "nombre": 11},
        {"id": 12, "type": "bras_chargement_essence", "capacite": 250, "nombre": 1},
        {"id": 13, "type": "pompe_anti_deflagrante", "capacite": 250, "nombre": 1},
        {"id": 14, "type": "systeme_recuperation_vapeur", "capacite": 1, "nombre": 1},
        {"id": 15, "type": "bras_chargement_gnl", "capacite": 300, "nombre": 1},
        {"id": 16, "type": "tuyauterie_cryogenique", "capacite": 1, "nombre": 1},
        {"id": 17, "type": "bras_chargement_huile", "capacite": 250, "nombre": 1},
        {"id": 18, "type": "pompe_alimentaire", "capacite": 250, "nombre": 1},
        {"id": 19, "type": "filtre", "capacite": 1, "nombre": 1},
        {"id": 20, "type": "passerelle_acces", "capacite": 1, "nombre": 3},
        {"id": 21, "type": "systeme_amarrage_rapide", "capacite": 1, "nombre": 3},
        {"id": 22, "type": "rampe_chargement", "capacite": 1, "nombre": 3},
    ]

    @classmethod
    def charger_quais(cls, occupations: Dict[int, float] = None) -> List[Quai]:
        quais = []
        for q in cls.QUAIS_EPB:
            q_obj = Quai(**q)
            if occupations and q_obj.id in occupations:
                q_obj.libre = occupations[q_obj.id]
            quais.append(q_obj)
        return quais

    @classmethod
    def charger_equipements(cls) -> List[Equipement]:
        equipements = [Equipement(**e) for e in cls.EQUIPEMENTS_EPB]
        for e in equipements:
            e.dispo = e.nombre
        return equipements

    @classmethod
    def creer_navires_test(cls, nb: int) -> List[Navire]:
        navires = []
        types = list(TypeNavire)
        for i in range(1, nb + 1):
            t = random.choice(types)
            priorites = PrioritesNavire()
            if random.random() < 0.2:
                priorites.sortant = True
            if random.random() < 0.2:
                priorites.passage = True
            if random.random() < 0.2 and t == TypeNavire.GAZIER:
                priorites.gazier = True
            if random.random() < 0.2 and t == TypeNavire.ESSENCE:
                priorites.essence = True
            if random.random() < 0.2 and t == TypeNavire.BETAIL:
                priorites.animalier = True
            if random.random() < 0.2:
                priorites.perissable = True
            if random.random() < 0.2:
                priorites.strategique = True
            if random.random() < 0.2 and t == TypeNavire.FERRY:
                priorites.ligne_reguliere = True
            if random.random() < 0.2:
                priorites.convention = True
            if random.random() < 0.2 and t == TypeNavire.HUILIER:
                priorites.huilier = True

            marchandise = Marchandise(
                type=t.value,
                volume=random.uniform(500, 50000),
                dangereux=random.random() < 0.1,
                fragile=random.random() < 0.1,
                frigo=(t == TypeNavire.FRIGORIFIQUE) or (random.random() < 0.1)
            )
            equip_propre = EquipementPropre(
                a_grue_bord=random.random() < 0.3,
                type_grue="grue_bord" if random.random() < 0.3 else None,
                capacite=random.uniform(20, 100) if random.random() < 0.3 else 0
            )
            navire = Navire(
                id=i,
                nom=f"Navire-{i}",
                type=t,
                longueur=random.uniform(50, 300),
                tirant=random.uniform(5, 15),
                arrivee=random.uniform(0, 72),
                priorites=priorites,
                marchandise=marchandise,
                equipement_propre=equip_propre
            )
            navire.priorite_calculee = cls._calculer_priorite(navire)
            navires.append(navire)
        return navires

    @classmethod
    def creer_navires_realistes(cls) -> List[Navire]:
        navires_data = [
            ("MSC BEJAIA", TypeNavire.CONTENEUR, 280, 12, 5000, {"ligne_reguliere": True}),
            ("GAZ MED", TypeNavire.GAZIER, 260, 11, 12000, {"gazier": True}),
            ("ESSO ALGERIE", TypeNavire.PETROLIER, 250, 13, 30000, {}),
            ("CEREALIA", TypeNavire.CEREALIER, 220, 10, 15000, {}),
            ("FERRY EXPRESS", TypeNavire.FERRY, 180, 6, 800, {"ligne_reguliere": True}),
            ("ANIMAL SHIP", TypeNavire.BETAIL, 150, 7, 2000, {"animalier": True}),
            ("COLD STORAGE", TypeNavire.FRIGORIFIQUE, 160, 8, 3000, {"perissable": True}),
            ("HUILE D'OLIVE", TypeNavire.HUILIER, 100, 6, 500, {"huilier": True}),
            ("CARGO ALGER", TypeNavire.CARGO, 200, 9, 8000, {}),
            ("ROULIER MAGHREB", TypeNavire.ROULIER, 170, 7, 4000, {"convention": True}),
            ("CHIMIE ALGER", TypeNavire.CHIMIQUIER, 190, 8, 6000, {"strategique": True}),
        ]
        navires = []
        for i, (nom, t, longueur, tirant, volume, priorites_dict) in enumerate(navires_data, 1):
            priorites = PrioritesNavire(**priorites_dict)
            marchandise = Marchandise(type=t.value, volume=volume)
            if t == TypeNavire.GAZIER:
                marchandise.volume = 25000
            equip_propre = EquipementPropre()
            if t == TypeNavire.CONTENEUR and random.random() < 0.5:
                equip_propre.a_grue_bord = True
            arrivee = random.uniform(0, 48)
            navire = Navire(
                id=i,
                nom=nom,
                type=t,
                longueur=longueur,
                tirant=tirant,
                arrivee=arrivee,
                priorites=priorites,
                marchandise=marchandise,
                equipement_propre=equip_propre,
                agent=nom.split()[0]
            )
            navire.priorite_calculee = cls._calculer_priorite(navire)
            navires.append(navire)
        return navires

    @staticmethod
    def _calculer_priorite(navire: Navire) -> float:
        priorite = 0
        if navire.priorites.sortant:
            priorite += POIDS_PRIORITES[Priorite.SORTANT]
        if navire.priorites.passage:
            priorite += POIDS_PRIORITES[Priorite.PASSAGE]
        if navire.priorites.gazier:
            priorite += POIDS_PRIORITES[Priorite.GAZIER_HIVER]
        if navire.priorites.essence:
            priorite += POIDS_PRIORITES[Priorite.ESSENCE]
        if navire.priorites.animalier:
            priorite += POIDS_PRIORITES[Priorite.ANIMALIER]
        if navire.priorites.perissable:
            priorite += POIDS_PRIORITES[Priorite.PERISSABLE]
        if navire.priorites.strategique:
            priorite += POIDS_PRIORITES[Priorite.STRATEGIQUE]
        if navire.priorites.ligne_reguliere:
            priorite += POIDS_PRIORITES[Priorite.LIGNE_REGULIERE]
        if navire.priorites.convention:
            priorite += POIDS_PRIORITES[Priorite.CONVENTION]
        if navire.priorites.huilier:
            priorite += POIDS_PRIORITES[Priorite.HUILIER]
        priorite += navire.marchandise.volume / 10000
        return priorite


# =============================================================================
# MODÈLE DE CALCUL AVEC INCERTITUDE
# =============================================================================

class ModeleCalcul:
    def __init__(self, quais, equipements, incertitude=True, amplitude=0.2, coeffs_historiques=None):
        self.quais = quais
        self.equipements = equipements
        self.incertitude = incertitude
        self.amplitude = amplitude
        self.ml_model = DureeTraitementModel()
        self.coeffs_historiques = coeffs_historiques or {}

    def get_taux_par_produit(self, navire):
        """
        Retourne le taux de déchargement (tonnes/heure) selon le produit transporté.
        Compatible avec la dataclass Navire (optimiseur) et le modèle Django Navire (vues/shell).
        """
        import re
    
        # Récupération de la chaîne marchandise selon le type d'objet
        if hasattr(navire, 'marchandise_type'):
            marchandise_brute = navire.marchandise_type or ''
        elif hasattr(navire, 'marchandise') and hasattr(navire.marchandise, 'type'):
            marchandise_brute = navire.marchandise.type or ''
        else:
            marchandise_brute = ''
    
        # Normalisation : majuscules, suppression ponctuation, espaces multiples
        marchandise_norm = re.sub(r'[^\w\s]', '', marchandise_brute.upper())
        marchandise_norm = ' '.join(marchandise_norm.split())
    
        TAUX_PAR_PRODUIT = {
            # ========== CÉRÉALES ==========
            'BLE TENDRE': 550, 'BLE DUR': 550, 'BLE': 550,
            'MAIS EN VRAC': 500, 'MAIS': 500, 'MAIS ON VRAC': 500,
            'ORGE': 450, 'AVOINE': 400, 'TOURNESOL': 450,
            # ========== HYDROCARBURES ==========
            'BUTANE+PROPANE': 200, 'BUTANE & PROPANE': 200, 'PETROLE BRUT': 400,
            'GASOIL': 350, 'GASOIL+ESSENCE SANS PLOMB': 350, 'ESSENCE': 300,
            'FIUL': 350,
            # ========== BOIS ET DÉRIVÉS ==========
            'BOIS ROUGE': 200, 'BOIS BLANC': 200, 'BOIS': 200,
            'BOIS BLANC + BOIS HETRE': 200, 'HETRE+GRUMES': 150, 'GRUMES': 150,
            'GRUMES DE ETRE ET PRODUITS FERREUX': 150,
            'MDF+DOORSKIN': 200, 'MDF + BOIS MELAMINE': 200,
            'CHIPBOARD ON PALLETS': 200, 'PATE A PAPIER': 300,
            # ========== PRODUITS AGRICOLES ==========
            'SOYBEANS IN BULK': 400, 'HUILE DE SOJA': 250,
            'CRUDE DEGUMMED SOYBEAN OIL IN BULK': 250, 'CRUDE DEGUMMED SOYBEAN OIL': 250,
            'DEGUMMED SOYBEAN OIL IN BULK': 250, 'HUILE BRUTE DE SOJA DEGOMMEE': 250,
            'PALM OIL + HARD STEARIN + SOFT STEARIN': 250,
            'RBD PALM OIL + RBD SOFT STEARIN + RBD PALM KERNEL': 250,
            'HUILE D\'OLIVE': 150,
            'SUCRE ROUX EN VRAC': 350, 'SUCRE ROUX': 350, 'SUCRE': 350,
            # ========== MINERAIS ET MATÉRIAUX ==========
            'FELDSPATH': 250, 'FELDSPATH SODIQUE': 250, 'ARGILE EN VRAC': 200, 'ARGILE': 200,
            'ANHYDRITE IN BULK': 250, 'BLOCS DE MARBRE': 120,
            # ========== CONTENEURS (TCS) ==========
            '606 TCS': 300, '535 TCS': 300, '828 TCS': 300, '592 TCS': 300, '490 TCS': 300,
            '318 TCS': 300, '466 TCS': 300, '616 TCS': 300, '496 TCS': 300, '548 TCS': 300,
            '627 TCS': 300, '792 TCS': 300, '193 TCS': 300, '543 TCS': 300, 'LOT TCS': 300,
            '50 TCS PLEINS+ 06 COLIS DIVERS': 300,
            # ========== ACIER ET MÉTAUX ==========
            'EXP BARRES D\'ARMATURE EN ACIER': 200, 'CORNIERES + POUTRELLES': 200,
            'POUTRELLES ET PROFILES': 200, 'STEEL PROFILES': 200,
            'FERS DIVERS +01 ENGIN & ACCESSOIRES': 200,
            # ========== CIMENTS ==========
            'EXP CIMENT': 300,
            # ========== DIVERS / ANIMAUX / PASSAGERS ==========
            'BOVINS VIFS': 100, 'OVINS VIFS': 100, 'ALEVINS DES DAURADES': 80,
            'PASSAGERS+VHCLS': 100, '431 PASSAGERS ET 361 VEHICULES PASSAGERS +32 SEMI-': 100,
            '16 COLIS DIVERS': 50, 'NEANT': 0,
        }
    
        # Recherche par sous-chaîne (insensible à la casse, normalisé)
        for produit, taux in TAUX_PAR_PRODUIT.items():
            # Normaliser la clé (supprimer ponctuation, espaces multiples)
            produit_norm = re.sub(r'[^\w\s]', '', produit.upper())
            produit_norm = ' '.join(produit_norm.split())
            
            # Vérifier si le produit normalisé est dans la marchandise normalisée
            if produit_norm in marchandise_norm:
                return taux
            
            # Vérification directe (sans normalisation) pour les cas particuliers
            if produit.upper() in marchandise_brute.upper():
                return taux
            
            # Vérification avec le mot seul (pour éviter les erreurs de normale)
            mots_produit = produit.upper().split()
            for mot in mots_produit:
                if len(mot) > 2 and mot in marchandise_brute.upper():
                    return taux
    
        # Fallback par type de navire
        if hasattr(navire, 'type'):
            if hasattr(navire.type, 'value'):
                navire_type = navire.type.value
            else:
                navire_type = navire.type
        else:
            navire_type = getattr(navire, 'type', '')
    
        taux_par_type = {
            'cerealier': 550,
            'cargo': 400,
            'conteneur': 300,
            'gazier': 200,
            'huilier': 150,
            'petrolier': 400,
            'essence': 300,
            'ferry': 100,
        }
        
        return taux_par_type.get(navire_type, 250)
    
    def calculer_temps_traitement(self, navire, quai):
        import random
    
        # ========== DÉTERMINATION DU TYPE DU NAVIRE ==========
        if hasattr(navire, 'type'):
            if hasattr(navire.type, 'value'):
                navire_type = navire.type.value
            else:
                navire_type = navire.type
        else:
            navire_type = getattr(navire, 'type', '')
    
        # ===================== CONTENEURS (RÈGLES CONTRACTUELLES) =====================
        if navire_type == 'conteneur':
            agent = getattr(navire, 'agent', '').upper()
            if 'MSC' in agent:
                duree_estimee = 6 * 24   # 144 heures (6 jours)
            elif 'CMA' in agent or 'CGM' in agent:
                duree_estimee = 5 * 24   # 120 heures (5 jours)
            elif 'MAERSK' in agent:
                duree_estimee = 5 * 24   # 120 heures (5 jours)
            else:
                duree_estimee = 5 * 24   # 120 heures (5 jours)
            # Pas d'incertitude pour les conteneurs (durées contractuelles)
            return max(0.5, duree_estimee)
    
        # ========== VOLUME (compatible Django et dataclass) ==========
        if hasattr(navire, 'marchandise_volume'):
            volume = navire.marchandise_volume
        elif hasattr(navire, 'marchandise') and hasattr(navire.marchandise, 'volume'):
            volume = navire.marchandise.volume
        else:
            volume = 0
    
        # Conversion kg → tonnes (si > 100 000)
        if volume > 100000:
            volume = volume / 1000.0
            print(f"⚠️ Volume converti de kg à tonnes : {navire.nom} -> {volume:.0f} t")
    
        if volume <= 0:
            return 24.0
    
        # ========== TAUX PRODUIT (PRIORITAIRE - dictionnaire TAUX_PAR_PRODUIT) ==========
        taux = self.get_taux_par_produit(navire)
    
        # ========== FALLBACK : SI TAUX PRODUIT NON TROUVÉ, UTILISER TAUX PAR TYPE ==========
        if taux <= 0 or taux == 400:  # 400 est le fallback par défaut pour cargo
            taux_par_type = {
                'cerealier': 550,
                'cargo': 250,        # réduit de 400 à 250 pour être réaliste
                'petrolier': 400,
                'gazier': 200,
                'huilier': 150,
                'essence': 250,
                'ferry': 100,
                'betail': 150,
                'frigorifique': 200,
            }
            taux = taux_par_type.get(navire_type, 250)
            print(f"⚠️ Fallback pour {navire.nom} ({navire_type}): taux = {taux} t/h")
    
        # ========== VÉRIFICATION SPÉCIALE POUR MAÏS (correction directe) ==========
        # Si la marchandise est du maïs, forcer le taux à 500 t/h
        marchandise = getattr(navire, 'marchandise_type', '')
        if marchandise and 'MAIS' in marchandise.upper():
            taux = 500
            print(f"🌽 Forçage MAIS pour {navire.nom}: taux = 500 t/h")
    
        # ========== COEFFICIENTS ==========
        coeff_quai = quai.performance if quai and hasattr(quai, 'performance') else 1.0
        coeff_marchandise = 1.0
    
        # Compatibilité Django
        if hasattr(navire, 'marchandise_dangereuse') and navire.marchandise_dangereuse:
            coeff_marchandise *= 0.8
        if hasattr(navire, 'marchandise_frigo') and navire.marchandise_frigo:
            coeff_marchandise *= 0.9
    
        taux_effectif = taux * coeff_quai * coeff_marchandise
        if taux_effectif <= 0:
            return 24.0
    
        duree_estimee = volume / taux_effectif
    
        # ========== INCERTITUDE (réduite pour céréaliers) ==========
        if self.incertitude:
            if navire_type == 'cerealier':
                # Incertitude réduite pour les céréaliers (5% au lieu de 20%)
                variation = random.uniform(1 - min(self.amplitude, 0.05), 1 + min(self.amplitude, 0.05))
            else:
                variation = random.uniform(1 - self.amplitude, 1 + self.amplitude)
            duree_estimee *= variation
    
        # ========== DURÉE MINIMALE (sécurité) ==========
        if navire_type == 'cargo' and volume > 100:
            duree_estimee = max(duree_estimee, 2.0)
    
        return max(0.5, duree_estimee)

    def calculer_attente(self, navire, debut):
        """
        Calcule l'attente d'un navire en heures entre son arrivée et le début d'accostage.
        
        Args:
            navire: objet Navire avec arrivee_datetime
            debut: heure de début d'accostage (float en heures depuis minuit)
        
        Returns:
            float: temps d'attente en heures
        """
        if hasattr(navire, 'arrivee_datetime') and navire.arrivee_datetime:
            # Vérifier si on a aussi une date de début
            if hasattr(navire, 'debut_datetime') and navire.debut_datetime:
                # Calcul direct avec les datetime complets
                diff_seconds = (navire.debut_datetime - navire.arrivee_datetime).total_seconds()
                attente = max(0, diff_seconds / 3600)
                return attente
            
            # Sinon, calcul avec l'heure de début et la date d'arrivée
            arrivee_heure = navire.arrivee_datetime.hour + navire.arrivee_datetime.minute / 60.0
            
            # Différence d'heures dans la même journée
            attente = debut - arrivee_heure
            
            # Si l'attente est négative, ajouter 24h (passage au jour suivant)
            if attente < 0:
                attente += 24
            
            # Calculer la différence en jours entre aujourd'hui et l'arrivée
            # UTILISER LA DATE DE DÉBUT (debut_datetime) AU LIEU DE today
            if hasattr(navire, 'debut_datetime') and navire.debut_datetime:
                jours_diff = (navire.debut_datetime.date() - navire.arrivee_datetime.date()).days
            else:
                # Fallback: utiliser la date actuelle
                today = datetime.now().date()
                jours_diff = (today - navire.arrivee_datetime.date()).days
            
            attente += jours_diff * 24
            return max(0, attente)
        else:
            return max(0, debut - navire.arrivee)

    
    def get_coeff_historique(self, type_navire, quai_id):
        return self.coeffs_historiques.get((type_navire, quai_id), 1.0)


# =============================================================================
# PLANIFICATEUR PRINCIPAL AVEC INCERTITUDE ET BUFFERS
# =============================================================================

class PlanificateurEPB:
    VERSION = "7.7.0"  # >>> CORRECTION : version incrémentée suite aux correctifs score/équipements
    # Compteurs statiques pour répartir les grues entre types de navires
    _cerealier_grue_index = 0
    _conteneur_grue_index = 0
    _cargo_grue_index = 0
    _cargo_quai_index = 0 
    # En haut du fichier optimiseur_epb_pro.py, ajoute :

    UTILISER_BACKTRACKING = True  # Met à False pour utiliser l'algorithme original
    MAX_NAVIRES_BACKTRACKING = 6   # Nombre max de navires pour utiliser le backtracking

    def __init__(self, quais, equipements, mois=None,
                 incertitude=True, amplitude=0.2, pourcentage_buffer=0.15,
                 meteo_restrictions=None, meteo_pluie=False, meteo_vent_force=0,
                 meteo_temperature=20, scenario="equilibre",
                 coeffs_historiques=None, equipes=None,pluie_fin_prevue=None,pluie_debut_prevue=None):

        self.quais = quais
        self.equipements = equipements
        self.mois = mois or datetime.now().month
        self.logger = logging.getLogger(f'{__name__}.Planificateur')
        self.incertitude = incertitude
        self.amplitude = amplitude
        self.pourcentage_buffer = pourcentage_buffer
        self.meteo_restrictions = meteo_restrictions or []
        self.meteo_pluie = meteo_pluie
        self.meteo_vent_force = meteo_vent_force
        self.meteo_temperature = meteo_temperature
        self.scenario = scenario
        self.equipes = equipes or []

        # Initialisation des unités d'équipements (nombres réels, pas de multiplication virtuelle)
        self.equipement_unites = {}
        for eq in self.equipements:
            self.equipement_unites[eq.type] = [0.0] * eq.nombre
            eq.dispo = eq.nombre

        self.modele = ModeleCalcul(quais, equipements, incertitude, amplitude,
                                   coeffs_historiques=coeffs_historiques)

        # ---------- IA pour recommandation d'équipements ----------
        self.equipement_choice_model = None
        try:
            from port.ml_equipement import EquipementChoiceModel
            self.equipement_choice_model = EquipementChoiceModel()
            if self.equipement_choice_model.model is not None:
                print("✅ Modèle IA de recommandation d'équipements chargé")
            else:
                print("ℹ️ Modèle IA non entraîné (recommandation désactivée)")
        except ImportError:
            pass
        except Exception as e:
            print(f"⚠️ Erreur chargement modèle IA équipements: {e}")

        # ---------- IA pour choix de quai ----------
        self.quai_choice_model = None
        try:
            from port.ml_quai import QuaiChoiceModel
            self.quai_choice_model = QuaiChoiceModel()
            if self.quai_choice_model.model is not None:
                print("✅ Modèle IA de choix de quai chargé")
            else:
                print("ℹ️ Modèle IA de quai non entraîné")
        except ImportError:
            pass
        except Exception as e:
            print(f"⚠️ Erreur chargement modèle IA quai: {e}")

        # ---------- Création des groupes de postes virtuels ----------
        self.emplacements = self.quais.copy()
        for (p1, p2), infos in GROUPES_POSTES.items():
            poste1 = next((q for q in self.quais if q.poste_numero == p1), None)
            poste2 = next((q for q in self.quais if q.poste_numero == p2), None)
            if poste1 and poste2:
                quai_groupe = Quai(
                    id=-abs(p1 * 100 + p2),
                    nom=infos["nom"],
                    longueur=infos["longueur_totale"],
                    profondeur=min(poste1.profondeur, poste2.profondeur),
                    specialite=infos["specialite"],
                    disponible=poste1.disponible and poste2.disponible,
                    libre=max(poste1.libre, poste2.libre),
                    performance=(poste1.performance + poste2.performance) / 2,
                    coeff_manoeuvre=1.0,
                    est_groupe=True,
                    postes_membres=[p1, p2]
                )
                self.emplacements.append(quai_groupe)
                print(f"✅ Groupe créé : {quai_groupe.nom} (id={quai_groupe.id})")
            else:
                print(f"⚠️ Groupe {infos['nom']} non créé : poste {p1} trouvé={poste1 is not None}, poste {p2} trouvé={poste2 is not None}")
        self.pluie_fin_prevue = pluie_fin_prevue
        self.pluie_debut_prevue = pluie_debut_prevue
        
    def normaliser_numero_poste(self, valeur):
        """Convertit un numéro de poste en entier pour la comparaison"""
        if valeur is None:
            return 0
        if isinstance(valeur, int):
            return valeur
        if isinstance(valeur, str):
            try:
                return int(valeur)
            except ValueError:
                return 0
        return 0
        
    def est_hiver(self) -> bool:
        return self.mois in [11, 12, 1, 2, 3]

    def _get_priorite_text(self, navire: Navire) -> str:
        priorites = []
        if navire.priorites.sortant:
            priorites.append("Sortant")
        if navire.priorites.passage:
            priorites.append("Passage")
        if navire.priorites.gazier and self.est_hiver():
            priorites.append("Gazier hiver")
        elif navire.priorites.gazier:
            priorites.append("Gazier")
        if navire.priorites.essence:
            priorites.append("Caboteur essence")
        if navire.priorites.animalier:
            priorites.append("Animalier")
        if navire.priorites.perissable:
            priorites.append("Perissable")
        if navire.priorites.strategique:
            priorites.append("Strategique")
        if navire.priorites.ligne_reguliere:
            priorites.append("Ligne reguliere")
        if navire.priorites.convention:
            priorites.append("Convention")
        if navire.priorites.huilier:
            priorites.append("Huilier")
        if not priorites:
            return "Standard"
        return ", ".join(priorites)

    # >>> CORRECTION : nouvelle méthode utilitaire — choisit, parmi une liste de
    # candidats compatibles, celui/ceux dont l'agenda de réservation interne
    # (self.equipement_unites) est le moins chargé au moment de l'appel.
    # Ne dépend d'AUCUNE donnée de panne externe : uniquement des réservations
    # que le planificateur a lui-même déjà effectuées dans cette session.
    def _choisir_equipements_disponibles(self, candidats: List[str], nb: int = 1) -> List[str]:
        """
        Retourne les `nb` équipements les moins chargés parmi une liste de candidats.
        Si un candidat n'existe pas dans self.equipement_unites (pas dans le parc
        actuel), il est simplement ignoré. Si aucun candidat n'est trouvé, on
        retourne les `nb` premiers noms de la liste fournie (comportement de
        secours identique à l'ancien code figé, pour ne jamais planter).
        """
        scores = []
        for eq_type in candidats:
            unites = self.equipement_unites.get(eq_type)
            if not unites:
                continue
            charge_min = min(unites)  # heure de libération la plus proche pour ce type
            scores.append((charge_min, eq_type))

        if not scores:
            # Aucun candidat connu du parc actuel -> comportement de secours
            return candidats[:nb]

        scores.sort(key=lambda x: x[0])
        choisis = [eq_type for _, eq_type in scores[:nb]]

        # Si moins de candidats valides que demandé, compléter avec la liste d'origine
        if len(choisis) < nb:
            for c in candidats:
                if c not in choisis:
                    choisis.append(c)
                if len(choisis) >= nb:
                    break

        return choisis[:nb]

    def get_equipements_necessaires(self, navire, quai=None):
        type_nav = navire.type.value
        marchandise = getattr(navire.marchandise, 'type', '') or ''
        volume = navire.marchandise.volume if hasattr(navire.marchandise, 'volume') else 0

        # Liste de toutes les grues disponibles
        grues_toutes = [
            "Gottwald HMK 260 10",
            "LIEBHERR LHM 250 14",
            "KONECRANS SP 6 217",
            "LIEBHERR LHM 420 210",
            "LIEBHERR LHM 280 211",
            "Grue camion LIEBHERR 11",
            "Grue camion LIEBHERR 12",
            "Grue camion GROVE 13",
            "Grue camion GROVE 215",
            "Grue camion LIEBHERR 216",
            "Gottwald HMK 170E 09",
        ]

        # ========== CÉRÉALIERS ==========
        if type_nav == 'cerealier':
            idx = PlanificateurEPB._cerealier_grue_index % len(grues_toutes)
            PlanificateurEPB._cerealier_grue_index += 1
            grue = grues_toutes[idx]
            return [grue, "Chariots Élévateurs 05T", "Chariots Élévateurs 05T"]

        # ========== CONTENEURS ==========
        if type_nav == 'conteneur':
            idx = PlanificateurEPB._conteneur_grue_index % len(grues_toutes)
            PlanificateurEPB._conteneur_grue_index += 1
            grue_principale = grues_toutes[idx]
            if volume > 50000:
                grue_secondaire = grues_toutes[(idx + 1) % len(grues_toutes)]
                return [grue_principale, grue_secondaire]
            else:
                return [grue_principale, "Chariots Élévateurs 05T"]

        # ========== CARGO ==========
        if type_nav == 'cargo':
            idx = PlanificateurEPB._cargo_grue_index % len(grues_toutes)
            PlanificateurEPB._cargo_grue_index += 1
            grue = grues_toutes[idx]
            if volume < 10000:
                return ["Grue mobile 50t", "Chariot 10t"]
            else:
                return [grue, "Chariots Élévateurs 05T"]

        # ========== PÉTROLIERS ==========
        if type_nav == 'petrolier':
            if 'BRUT' in marchandise.upper():
                return ["Bras de chargement pétrolier", "Pompe haute capacité"]
            else:
                return ["Bras de chargement pétrolier"]

        # ========== GAZIERS ==========
        if type_nav == 'gazier':
            return ["Bras chargement GNL", "Tuyauterie cryogénique"]

        # ========== HUILIERS ==========
        # >>> CORRECTION : au lieu de renvoyer toujours les 2 mêmes grues (ce qui
        # créait une contention systématique entre huiliers proches dans le temps),
        # on propose une liste élargie de candidats compatibles et on choisit
        # dynamiquement les 2 les moins chargées au moment de l'appel.
        if type_nav == 'huilier':
            candidats_huilier = [
                "Gottwald HMK 260 10",
                "LIEBHERR LHM 250 15",
                "Grue camion GROVE 13",
                "LIEBHERR LHM 420 210",
                "KONECRANS SP 6 217",
            ]
            return self._choisir_equipements_disponibles(candidats_huilier, nb=2)

        # ========== FERRIES ==========
        if type_nav == 'ferry':
            return ["Tracteur RO/RO DAF 38T", "Chariots Élévateurs 05T", "Grue camion LIEBHERR 12"]

        # ========== BÉTAIL ==========
        if type_nav == 'betail':
            return ["Tracteur Volvo 50t", "Chariots Élévateurs 05T", "Grue camion GROVE 215"]

        # ========== FRIGORIFIQUES ==========
        # >>> CORRECTION : idem huilier, on élargit les candidats plutôt que de
        # figer sur 2 grues systématiquement identiques.
        if type_nav == 'frigorifique':
            candidats_frigo = [
                "Gottwald HMK 170E 09",
                "LIEBHERR LHM 250 14",
                "LIEBHERR LHM 280 211",
                "Grue camion LIEBHERR 216",
            ]
            return self._choisir_equipements_disponibles(candidats_frigo, nb=2)

        # ========== ESSENCE ==========
        # >>> CORRECTION : idem, candidats élargis avec choix dynamique.
        if type_nav == 'essence':
            candidats_essence = [
                "Grue camion LIEBHERR 11",
                "Grue camion LIEBHERR 12",
                "Grue camion GROVE 13",
            ]
            return self._choisir_equipements_disponibles(candidats_essence, nb=2)

        # ========== CHIMIQUIERS ==========
        if type_nav == 'chimiquier':
            return ["Bras de chargement pétrolier", "Pompe anti-acide", "Tuyauterie spéciale"]

        # ========== ROULEURS ==========
        if type_nav == 'roulier':
            return ["Tracteur RO/RO DAF 38T", "Chariots Élévateurs 05T"]

        # ========== FALLBACK ==========
        return ["Chariots Élévateurs 05T", "Tracteur Volvo 50t"]

    def calculer_temps_manoeuvre(self, navire: Navire, quai: Quai) -> float:
        return 1.0

    def initialiser_equipements_depuis_navires_quai(self, navires_quai: List[Navire]):
        for navire in navires_quai:
            if navire.fin_prevue is None:
                continue
            equip_types = self.get_equipements_necessaires(navire)
            for eq_type in equip_types:
                unites = self.equipement_unites.get(eq_type)
                if unites:
                    unites.sort()
                    unites[0] = max(unites[0], navire.fin_prevue)

    def equipements_disponibles(self, navire, quai, debut, fin=None):
        equip_types = self.get_equipements_necessaires(navire, quai)
        debut_possible = debut
        attente_max = 0.0
        reservation = {}

        for eq_type in equip_types:
            eq = next((e for e in self.equipements if e.type == eq_type), None)
            if eq is None:
                return False, debut, f"Équipement {eq_type} inexistant", 0.0

            unites = self.equipement_unites.get(eq_type, [])
            if not unites:
                return False, debut, f"Aucune unité pour {eq_type}", 0.0

            # Choix IA si disponible
            idx = None
            if self.equipement_choice_model and self.equipement_choice_model.model is not None:
                try:
                    type_navire = navire.type.value
                    heure_debut = (datetime.now().hour + datetime.now().minute / 60.0) % 24
                    jour_semaine = datetime.now().weekday()
                    recommended = self.equipement_choice_model.predire_unite(
                        type_navire, eq_type, quai.specialite, heure_debut, jour_semaine
                    )
                    if recommended is not None and 0 <= recommended < len(unites):
                        idx = recommended
                except Exception as e:
                    print(f"⚠️ Erreur IA: {e}")

            if idx is None:
                meilleure = min(unites)
                idx = unites.index(meilleure)

            if unites[idx] > debut_possible:
                attente = unites[idx] - debut_possible
                if attente > attente_max:
                    attente_max = attente
                debut_possible = unites[idx]
            reservation[eq_type] = idx

        return True, debut_possible, "OK", attente_max

    def get_nb_equipements_max(self, navire):
        if navire.type == TypeNavire.CEREALIER:
            return 3
        else:
            return 2

    def reserver_equipements(self, navire: Navire, quai: Quai, fin: float):
        equip_types = self.get_equipements_necessaires(navire, quai)
        from port.ml_equipement import EquipementChoiceModel
        from datetime import datetime
        import logging
        logger = logging.getLogger(__name__)

        model_ia = None
        try:
            model_ia = EquipementChoiceModel()
        except Exception:
            pass

        for eq_type in equip_types:
            unites = self.equipement_unites.get(eq_type)
            if not unites:
                continue

            idx = None
            if model_ia and model_ia.model is not None:
                try:
                    type_navire = navire.type.value
                    heure_debut = (datetime.now().hour + datetime.now().minute / 60.0) % 24
                    jour_semaine = datetime.now().weekday()
                    quai_specialite = quai.specialite
                    recommended = model_ia.predire_unite(
                        type_navire, eq_type, quai_specialite, heure_debut, jour_semaine
                    )
                    if recommended is not None and 0 <= recommended < len(unites):
                        idx = recommended
                except Exception as e:
                    logger.warning(f"Erreur prédiction IA pour {eq_type}: {e}")

            if idx is None:
                min_val = min(unites)
                idx = unites.index(min_val)

            unites[idx] = max(unites[idx], fin)

            try:
                from port.models import UtilisationEquipement, Navire as NavireModel, Poste
                navire_db = NavireModel.objects.get(id=navire.id)
                quai_db = None
                if quai.id > 0:
                    poste = Poste.objects.get(id=quai.id)
                    quai_db = poste.quai
                debut = fin - self.modele.calculer_temps_traitement(navire, quai)
                UtilisationEquipement.objects.create(
                    navire=navire_db,
                    equipement_type=eq_type,
                    unite_index=idx,
                    quai=quai_db,
                    debut=datetime.now() + timedelta(hours=debut),
                    fin=datetime.now() + timedelta(hours=fin),
                    conflit=False,
                    attente_navire=self.modele.calculer_attente(navire, debut)
                )
            except Exception as e:
                logger.warning(f"Erreur enregistrement utilisation: {e}")

    def verifier_compatibilite(self, navire: Navire, quai: Quai, debut: float = None, traitement: float = None) -> Tuple[bool, str]:
        # ====== VÉRIFICATION DE BASE : LE QUAI DOIT AVOIR UN NUMÉRO DE POSTE ======
        if not hasattr(quai, 'poste_numero') or quai.poste_numero is None:
            return False, f"Quai {quai.nom} sans numéro de poste – affectation impossible"

        # ====== Règles météo ======
        if self.meteo_restrictions and quai.nom in self.meteo_restrictions:
            return False, f"Quai {quai.nom} interdit pour cause météo"

        if self.meteo_pluie:
            if navire.type == TypeNavire.CEREALIER or navire.marchandise.dangereux:
                if (hasattr(self, 'pluie_debut_prevue') and self.pluie_debut_prevue is not None and
                    hasattr(self, 'pluie_fin_prevue') and self.pluie_fin_prevue is not None and
                    debut is not None and traitement is not None and
                    hasattr(self, 'date_reference') and self.date_reference is not None):

                    base = self.date_reference.replace(hour=0, minute=0, second=0, microsecond=0)
                    debut_dt = base + timedelta(hours=debut)
                    fin_dt = debut_dt + timedelta(hours=traitement)

                    if not (fin_dt <= self.pluie_debut_prevue or debut_dt >= self.pluie_fin_prevue):
                        return False, (f"🌧️ Pluie prévue de {self.pluie_debut_prevue.strftime('%H:%M')} à "
                                       f"{self.pluie_fin_prevue.strftime('%H:%M')} – opération impossible")
                else:
                    return False, "🌧️ Opérations sur céréales/produits dangereux interdites par temps de pluie"

        # ====== Contraintes physiques ======
        if navire.longueur > quai.longueur:
            return False, f"Longueur {navire.longueur}m > {quai.longueur}m"
        if navire.tirant > quai.profondeur:
            return False, f"Tirant d'eau {navire.tirant}m > {quai.profondeur}m"

        # ====== RÈGLES SPÉCIALES PAR TYPE DE NAVIRE (STRICTES) ======
        poste = self.normaliser_numero_poste(quai.poste_numero)

        # --- PÉTROLIERS : P.1, 2, 3 UNIQUEMENT ---
        if navire.type == TypeNavire.PETROLIER:
            POSTES_PETROLIERS = [1, 2, 3]
            if poste not in POSTES_PETROLIERS:
                return False, f"Pétrolier autorisé uniquement aux postes {POSTES_PETROLIERS} (poste actuel: {poste})"
            return True, "OK"

        # --- FERRIES : P.8, 12, 13 UNIQUEMENT ---
        if navire.type == TypeNavire.FERRY:
            POSTES_FERRY = [8, 12, 13]
            if poste not in POSTES_FERRY:
                return False, f"Ferry autorisé uniquement aux postes {POSTES_FERRY} (poste actuel: {poste})"
            return True, "OK"

        # --- GAZIERS : P.24, 26 UNIQUEMENT ---
        if navire.type == TypeNavire.GAZIER:
            POSTES_GAZIERS = [24, 26]
            if poste not in POSTES_GAZIERS:
                return False, f"Gazier autorisé uniquement aux postes {POSTES_GAZIERS} (poste actuel: {poste})"
            return True, "OK"

        # --- CÉRÉALIERS : P.15, 16, 17, 21, 23 UNIQUEMENT ---
        if navire.type == TypeNavire.CEREALIER:
            POSTES_CEREALIERS = [15, 16, 17, 21, 23]
            if poste not in POSTES_CEREALIERS:
                return False, f"Céréalier autorisé uniquement aux postes {POSTES_CEREALIERS} (poste actuel: {poste})"
            return True, "OK"

        # --- CONTENEURS : P.22, 24 UNIQUEMENT + règles contractuelles ---
        if navire.type == TypeNavire.CONTENEUR:
            POSTES_CONTENEURS = [22, 24]
            agent = getattr(navire, 'agent', '').upper()

            if 'MSC' in agent and poste != 22:
                return False, f"MSC doit être au poste 22 (poste actuel: {poste})"
            if ('CMA' in agent or 'CGM' in agent) and poste != 24:
                return False, f"CMA CGM doit être au poste 24 (poste actuel: {poste})"
            if 'MAERSK' in agent and poste not in [22, 24]:
                return False, f"MAERSK doit être aux postes 22 ou 24 (poste actuel: {poste})"

            if poste not in POSTES_CONTENEURS:
                return False, f"Conteneur doit être aux postes {POSTES_CONTENEURS} (poste actuel: {poste})"
            return True, "OK"

        # --- CARGO : P.11, 14, 18, 19 UNIQUEMENT ---
        if navire.type == TypeNavire.CARGO:
            POSTES_CARGO = [11, 14, 18, 19]
            if poste not in POSTES_CARGO:
                return False, f"Cargo autorisé uniquement aux postes {POSTES_CARGO} (poste actuel: {poste})"
            return True, "OK"

        # --- HUILIERS : P.23, 26 UNIQUEMENT ---
        if navire.type == TypeNavire.HUILIER:
            POSTES_HUILIER = [23, 26]
            if poste not in POSTES_HUILIER:
                return False, f"Huilier autorisé uniquement aux postes {POSTES_HUILIER} (poste actuel: {poste})"
            return True, "OK"

        # --- ESSENCE : P.19 UNIQUEMENT ---
        if navire.type == TypeNavire.ESSENCE:
            POSTES_ESSENCE = [19]
            if poste not in POSTES_ESSENCE:
                return False, f"Caboteur essence uniquement au poste {POSTES_ESSENCE[0]} (poste actuel: {poste})"
            return True, "OK"

        # --- ANIMALIERS : P.12, 13 UNIQUEMENT ---
        if navire.priorites.animalier:
            POSTES_ANIMALIERS = [12, 13]
            if poste not in POSTES_ANIMALIERS:
                return False, f"Navire animalier uniquement aux postes {POSTES_ANIMALIERS} (poste actuel: {poste})"
            return True, "OK"

        # --- GROUPES VIRTUELS ---
        if quai.est_groupe:
            if quai.specialite == "ferry" and navire.type != TypeNavire.FERRY:
                return False, "Ce groupe est réservé aux ferries"
            if quai.specialite == "cerealier" and navire.type != TypeNavire.CEREALIER:
                return False, "Ce groupe est réservé aux céréaliers"
            return True, "Compatible"

        # ====== RÈGLES GÉNÉRALES (fallback pour types non listés) ======
        regles = {
            TypeNavire.ROULIER: ["general", "grand"],
            TypeNavire.CHIMIQUIER: ["petrolier", "grand"],
            TypeNavire.FRIGORIFIQUE: ["general", "grand"],
            TypeNavire.BETAIL: ["ferry", "general"],
        }
        autorisees = regles.get(navire.type, ["general", "grand"])
        if quai.specialite not in autorisees:
            return False, f"Un {navire.type.value} ne peut pas utiliser un quai de type {quai.specialite}"

        return True, "Compatible"

    def shift_autorise(self, navire: Navire, debut: float) -> bool:
        heure = debut % 24
        if navire.type == TypeNavire.FERRY:
            return 7 <= heure < 19
        if navire.type == TypeNavire.CEREALIER:
            return not (1 <= heure < 7)
        return True

    def prochain_shift_autorise(self, navire: Navire, debut: float) -> float:
        heure = debut % 24
        if navire.type == TypeNavire.FERRY:
            if heure < 7:
                return debut + (7 - heure)
            elif heure >= 19:
                return debut + (24 - heure) + 7
        if navire.type == TypeNavire.CEREALIER:
            if 1 <= heure < 7:
                return debut + (7 - heure)
        return debut

    def get_shift_label(self, heure: float) -> str:
        h = heure % 24
        if 7 <= h < 13:
            return "07h-13h"
        elif 13 <= h < 19:
            return "13h-19h"
        elif 19 <= h < 24:
            return "19h-01h"
        else:
            return "01h-07h"

    # >>> CORRECTION : ajout du paramètre attente_equip, désormais intégré au
    # score final. Auparavant ce chiffre était calculé (equipements_disponibles)
    # mais jamais transmis ici, donc jamais utilisé pour choisir le meilleur quai.
    def calculer_score_contribution(self, navire, debut, traitement,
                                    buffer_debut, buffer_fin, 
                                    quai=None, quai_recommande=None,
                                    attente_equip: float = 0.0) -> float:
        attente = self.modele.calculer_attente(navire, debut)
        
        if self.scenario == "rapide":
            poids_attente = 2.0
            poids_securite = 0.5
            poids_equip = 1.5
        elif self.scenario == "securise":
            poids_attente = 0.5
            poids_securite = 2.0
            poids_equip = 1.0
        else:  # equilibre
            poids_attente = 1.0
            poids_securite = 1.0
            poids_equip = 1.0
        
        # Pénalité buffer (B_i)
        penalite_buffer = 0.0
        seuil = 1.0
        coeff = 20.0
        if buffer_debut < seuil:
            penalite_buffer += (seuil - buffer_debut) * coeff * poids_securite
        if buffer_fin < seuil:
            penalite_buffer += (seuil - buffer_fin) * coeff * poids_securite
        
        # ===== BONUS IA (Q_i) =====
        # Q_i = -50 si quai recommandé par l'IA, 0 sinon
        bonus_ia = 0.0
        if quai_recommande and quai and quai.id == quai_recommande:
            bonus_ia = -50

        # >>> CORRECTION : pénalité liée à l'attente équipement (E_i).
        # Sans cela, deux quais pouvaient être jugés équivalents alors que l'un
        # d'eux imposait au navire de longues heures d'attente sur une grue occupée.
        penalite_equip = attente_equip * poids_equip
        
        # Score total selon la formule théorique (mise à jour)
        score = traitement + (attente * poids_attente) + penalite_buffer + bonus_ia + penalite_equip
        
        return max(1.0, score)  # Score toujours positif

    def limiter_debut_excessif(self, debut, heure_actuelle, navire):
        max_attente = 168
        if debut > heure_actuelle + max_attente:
            print(f"      ⚠️ Début excessif pour {navire.nom}: {debut:.1f}h > {heure_actuelle + max_attente:.1f}h")
            print(f"      → Réinitialisation à {heure_actuelle + 2:.1f}h")
            return heure_actuelle + 2
        return debut

    
    def planifier(self, navires_a_planifier, navires_a_quai=None, date_reference=None):
        """Planifie l'affectation des navires aux quais avec prise en compte des prévisions météo (pluie) et des navires déjà à quai"""
        from datetime import datetime, timedelta
        
        if date_reference is None:
            date_reference = datetime.now()
        self.date_reference = date_reference
        base = date_reference.replace(hour=0, minute=0, second=0, microsecond=0)
    
        heure_actuelle = (date_reference - base).total_seconds() / 3600.0
    
        # Réinitialisation des équipements
        for eq in self.equipements:
            self.equipement_unites[eq.type] = [0.0] * eq.nombre
            eq.dispo = eq.nombre
    
        if navires_a_quai:
            self.initialiser_equipements_depuis_navires_quai(navires_a_quai)
    
        # ========== PRISE EN COMPTE DES NAVIRES DÉJÀ À QUAI ==========
        # Dictionnaire stockant la dernière heure de fin pour chaque quai (id)
        dernier_fin_par_quai = {}
        for nq in (navires_a_quai or []):
            # Récupérer l'id du quai (selon la structure de nq)
            quai_id = None
            if hasattr(nq, 'quai_attribue') and nq.quai_attribue:
                quai_id = nq.quai_attribue.id
            elif hasattr(nq, 'quai_id'):
                quai_id = nq.quai_id
            if quai_id is None:
                continue
            # Récupérer l'heure de fin
            fin = getattr(nq, 'heure_fin', None)
            if fin is None:
                fin = getattr(nq, 'fin_prevue', None)
            if fin is not None:
                dernier_fin_par_quai[quai_id] = max(dernier_fin_par_quai.get(quai_id, 0), fin)
                # Mettre à jour la disponibilité du quai dans self.quais
                for q in self.quais:
                    if q.id == quai_id:
                        q.libre = max(q.libre, fin)
                        break
    
        # Nettoyer les quais avec occupation aberrante (> 7 jours)
        for q in self.quais:
            if q.libre > 168:
                q.libre = 0
    
        print("\n=== Quais initiaux (avec occupations réelles) ===")
        for q in self.quais:
            print(f"  {q.nom} : libre = {q.libre:.2f}h")
    
        for nav in navires_a_planifier:
            if self.quais:
                nav.duree_estimee = self.modele.calculer_temps_traitement(nav, self.quais[0])
            else:
                nav.duree_estimee = 24.0
    
        def get_urgence(navire):
            if navire.arrivee_datetime:
                delta = (date_reference - navire.arrivee_datetime).total_seconds() / 3600
                return max(0, delta)
            return 0
    
        def get_anciennete(navire):
            if navire.arrivee_datetime:
                return navire.arrivee_datetime.timestamp()
            base_now = date_reference.replace(hour=0, minute=0, second=0, microsecond=0)
            return (base_now + timedelta(hours=navire.arrivee)).timestamp()
    
        navires_tries = sorted(
            navires_a_planifier,
            key=lambda n: (
                not getattr(n, 'est_en_rade', False),
                -n.priorite_calculee,
                -get_urgence(n),
                get_anciennete(n),
                n.duree_estimee
            )
        )
    
        affectations = []
        score_total = 0.0
        attente_totale = 0.0
    
        affectations_par_quai = {}
        cerealiers_par_quai = {}
    
        print("\n" + "=" * 100)
        print("ORDRE DE TRAITEMENT (rade + priorité + urgence + ancienneté)")
        print("=" * 100)
        for i, navire in enumerate(navires_tries, 1):
            priorite_text = self._get_priorite_text(navire)
            arrivee_str = navire.arrivee_datetime.strftime("%d/%m %H:%M") if navire.arrivee_datetime else f"{navire.arrivee:.1f}h"
            statut = "🔴 RADE" if getattr(navire, 'est_en_rade', False) else "⏳ ATTENDU"
            urgence = get_urgence(navire)
            print(f"{i:2d}. {navire.nom} - {statut} - Priorité: {navire.priorite_calculee:.0f} - Urgence: {urgence:.1f}h - Arrivée: {arrivee_str} - {priorite_text}")
    
        for navire in navires_tries:
            print(f"\nTraitement de {navire.nom}")
            print(f"   Priorités: {self._get_priorite_text(navire)}")
            print(f"   Arrivée: {navire.arrivee:.2f}h")
            print(f"   Type: {navire.type.value}")
    
            if getattr(navire, 'est_en_rade', False):
                navire.arrivee = 0
                print(f"   🚨 CORRECTION: Navire en rade - arrivée forcée à 0h")
    
            recommended_quai_id = None
            if hasattr(self, 'quai_choice_model') and self.quai_choice_model and self.quai_choice_model.model is not None:
                try:
                    approx_debut = max(navire.arrivee, heure_actuelle) if not getattr(navire, 'est_en_rade', False) else 0
                    shift_label = self.get_shift_label(approx_debut)
                    recommended_quai_id = self.quai_choice_model.predire_quai(
                        navire.type.value, navire.marchandise.volume,
                        navire.longueur, navire.tirant, navire.agent,
                        getattr(navire, 'entite', ''), shift_label
                    )
                    if recommended_quai_id:
                        print(f"🤖 IA recommande le quai {recommended_quai_id} pour {navire.nom}")
                except Exception as e:
                    print(f"⚠️ Erreur prédiction quai: {e}")
    
            emplacements_tries = list(self.emplacements)
            # Répartition circulaire des cargos
            if navire.type == TypeNavire.CARGO:
                postes_cargo = [11, 14, 18, 19]
                idx = PlanificateurEPB._cargo_quai_index % len(postes_cargo)
                quai_cible = next((q for q in emplacements_tries if q.poste_numero == postes_cargo[idx]), None)
                PlanificateurEPB._cargo_quai_index += 1
                if quai_cible and self.verifier_compatibilite(navire, quai_cible)[0]:
                    emplacements_tries.remove(quai_cible)
                    emplacements_tries.insert(0, quai_cible)
            if recommended_quai_id:
                for i, q in enumerate(emplacements_tries):
                    if q.id == recommended_quai_id:
                        emplacements_tries.insert(0, emplacements_tries.pop(i))
                        break
    
            # Équilibrage pour les cargos
            if navire.type == TypeNavire.CARGO:
                emplacements_tries.sort(key=lambda q: affectations_par_quai.get(q.id, 0))
    
            meilleur_debut = float('inf')
            meilleur_quai = None
            meilleur_fin = None
            meilleur_traitement = None
            meilleur_buffer_debut = 0.0
            meilleur_buffer_fin = 0.0
            meilleur_score = float('inf')
            meilleur_equipe = None
            meilleur_message = ""
            meilleur_attente_equip = 0.0
    
            for quai in emplacements_tries:
                nb_affectees = affectations_par_quai.get(quai.id, 0)
                if navire.type == TypeNavire.CEREALIER and nb_affectees >= 3:
                    continue
                if navire.type == TypeNavire.CONTENEUR and nb_affectees >= 2:
                    continue
                if navire.type == TypeNavire.CARGO and nb_affectees >= 2:
                    continue
                if navire.type not in [TypeNavire.CEREALIER, TypeNavire.CONTENEUR, TypeNavire.CARGO] and nb_affectees >= 1:
                    continue
    
                dernier_fin = dernier_fin_par_quai.get(quai.id, 0)
    
                if getattr(navire, 'est_en_rade', False):
                    debut = max(0, quai.libre, dernier_fin)
                else:
                    debut = max(navire.arrivee, quai.libre, dernier_fin)
    
                # Décalage après la pluie pour navires sensibles
                if (navire.type == TypeNavire.CEREALIER or navire.marchandise.dangereux) and self.meteo_pluie:
                    if hasattr(self, 'pluie_fin_prevue') and self.pluie_fin_prevue is not None:
                        base = self.date_reference.replace(hour=0, minute=0, second=0, microsecond=0)
                        fin_pluie_heure = (self.pluie_fin_prevue - base).total_seconds() / 3600.0
                        if fin_pluie_heure > debut:
                            debut = fin_pluie_heure
                            print(f"      🌧️ Début décalé à {debut:.2f}h (après la pluie)")
    
                # Délai d'équilibrage
                if navire.type == TypeNavire.CARGO:
                    debut += nb_affectees * 24
                else:
                    debut += nb_affectees * 12
    
                attente_candidate = debut - navire.arrivee
                if attente_candidate > 168:
                    print(f"      ⚠️ Attente très longue ({attente_candidate:.1f}h) – quai {quai.nom} considéré malgré tout")
    
                if not self.shift_autorise(navire, debut):
                    debut_shift = self.prochain_shift_autorise(navire, debut)
                    if debut_shift > debut:
                        debut = debut_shift
    
                traitement = self.modele.calculer_temps_traitement(navire, quai)
                fin = debut + traitement
    
                disponible, debut_ajuste, msg_equip, attente_equip = self.equipements_disponibles(navire, quai, debut, fin)
                if not disponible:
                    continue
                debut = debut_ajuste
                fin = debut + traitement
    
                coeff_ralentissement = 1.0
                if self.meteo_pluie:
                    coeff_ralentissement *= 1.2
                if self.meteo_vent_force >= 8:
                    coeff_ralentissement *= 1.3
                traitement *= coeff_ralentissement
                fin = debut + traitement
    
                buffer_debut = traitement * self.pourcentage_buffer
                buffer_fin = traitement * self.pourcentage_buffer
    
                compatible, raison = self.verifier_compatibilite(navire, quai, debut=debut, traitement=traitement)
                if not compatible:
                    print(f"      Quai {quai.nom} incompatible: {raison}")
                    continue
    
                # Conflit avec créneaux déjà réservés dans cette session
                conflit_poste = False
                for a in affectations:
                    if a.quai_id == quai.id:
                        if not (fin <= a.heure_accostage or debut >= a.heure_fin):
                            conflit_poste = True
                            break
                if conflit_poste:
                    continue
    
                equipe_choisie = None
                if self.equipes:
                    pass
    
                # >>> CORRECTION : attente_equip est désormais transmis au score
                contribution = self.calculer_score_contribution(
                    navire, debut, traitement, buffer_debut, buffer_fin,
                    quai=quai, quai_recommande=recommended_quai_id,
                    attente_equip=attente_equip
                )
    
                if contribution < meilleur_score:
                    meilleur_score = contribution
                    meilleur_debut = debut
                    meilleur_quai = quai
                    meilleur_fin = fin
                    meilleur_traitement = traitement
                    meilleur_buffer_debut = buffer_debut
                    meilleur_buffer_fin = buffer_fin
                    meilleur_equipe = equipe_choisie
                    meilleur_message = f"Choisi (score {contribution:.2f})"
                    meilleur_attente_equip = attente_equip
    
            # Fallback
            if meilleur_quai is None:
                for quai in emplacements_tries:
                    compatible, _ = self.verifier_compatibilite(navire, quai, debut=None, traitement=None)
                    if compatible:
                        nb_aff = affectations_par_quai.get(quai.id, 0)
                        if getattr(navire, 'est_en_rade', False):
                            debut = max(0, quai.libre, dernier_fin_par_quai.get(quai.id, 0))
                        else:
                            debut = max(navire.arrivee, quai.libre, dernier_fin_par_quai.get(quai.id, 0))
                        if navire.type == TypeNavire.CARGO:
                            debut += nb_aff * 24
                        else:
                            debut += nb_aff * 12
                        traitement = self.modele.calculer_temps_traitement(navire, quai)
                        fin = debut + traitement
                        buffer_debut = traitement * self.pourcentage_buffer
                        buffer_fin = traitement * self.pourcentage_buffer
                        disponible, debut_ajuste, msg_equip, attente_equip = self.equipements_disponibles(navire, quai, debut, fin)
                        if not disponible:
                            continue
                        debut = debut_ajuste
                        fin = debut + traitement
                        meilleur_debut = debut
                        meilleur_fin = fin
                        meilleur_traitement = traitement
                        meilleur_quai = quai
                        meilleur_buffer_debut = buffer_debut
                        meilleur_buffer_fin = buffer_fin
                        # >>> CORRECTION : attente_equip transmis aussi dans le fallback
                        meilleur_score = self.calculer_score_contribution(
                            navire, debut, traitement, buffer_debut, buffer_fin,
                            attente_equip=attente_equip
                        )
                        meilleur_message = "Affecté (fallback)"
                        meilleur_attente_equip = attente_equip
                        break
    
            if meilleur_quai is not None:
                affectations_par_quai[meilleur_quai.id] = affectations_par_quai.get(meilleur_quai.id, 0) + 1
                dernier_fin_par_quai[meilleur_quai.id] = meilleur_fin
                if navire.type == TypeNavire.CEREALIER:
                    cerealiers_par_quai[meilleur_quai.id] = cerealiers_par_quai.get(meilleur_quai.id, 0) + 1
    
                attente = self.modele.calculer_attente(navire, meilleur_debut)
                debut_securise = meilleur_debut + meilleur_buffer_debut
                fin_securise = meilleur_fin + meilleur_buffer_fin
    
                self.reserver_equipements(navire, meilleur_quai, meilleur_fin)
                temps_manoeuvre = self.calculer_temps_manoeuvre(navire, meilleur_quai)
                meilleur_quai.libre = meilleur_fin + temps_manoeuvre
    
                affectations.append(AffectationResultat(
                    navire_id=navire.id,
                    navire_nom=navire.nom,
                    type_navire=navire.type.value,
                    quai_id=meilleur_quai.id,
                    quai_nom=meilleur_quai.nom,
                    heure_arrivee=navire.arrivee,
                    heure_accostage=meilleur_debut,
                    heure_fin=meilleur_fin,
                    attente=attente,
                    traitement=meilleur_traitement,
                    priorite_calculee=navire.priorite_calculee,
                    priorites_speciale=self._get_priorite_text(navire),
                    equipements=self.get_equipements_necessaires(navire, meilleur_quai),
                    utilise_grues_bord=navire.equipement_propre.a_grue_bord,
                    score_contribution=meilleur_score,
                    buffer_debut=meilleur_buffer_debut,
                    buffer_fin=meilleur_buffer_fin,
                    heure_debut_securise=debut_securise,
                    heure_fin_securise=fin_securise,
                    agent=navire.agent,
                    temps_manoeuvre=temps_manoeuvre,
                    equipe_nom=meilleur_equipe.nom if meilleur_equipe else None,
                    est_groupe=meilleur_quai.est_groupe,
                    postes_ids=meilleur_quai.postes_membres if meilleur_quai.est_groupe else [],
                    attente_equipements=meilleur_attente_equip
                ))
                score_total += meilleur_score
                attente_totale += attente
    
                print(f"   ✅ Affecté au {meilleur_quai.nom}")
                print(f"      Début: {meilleur_debut:.2f}h, Fin: {meilleur_fin:.2f}h, Attente: {attente:.2f}h, Score: {meilleur_score:.2f}")
            else:
                print(f"   ❌ Aucune affectation possible - {meilleur_message}")
    
        return affectations, score_total, attente_totale

    def afficher_resultats(self, affectations: List[AffectationResultat], score_total: float, attente_totale: float):
        # identique à votre code existant (non modifié)
        print("\n" + "=" * 120)
        print("PLANNING FINAL D'ACCOSTAGE")
        print("=" * 120)
        print(f"{'Navire':<25} {'Type':<15} {'Quai':<12} {'Debut':<8} {'Fin':<8} {'Attente':<8} {'Priorite':<8} {'Contribution':<10}")
        print("-" * 120)
        for a in affectations:
            equipe_info = f" (Éq: {a.equipe_nom})" if hasattr(a, 'equipe_nom') and a.equipe_nom else ""
            print(f"{a.navire_nom:<25} {a.type_navire:<15} {a.quai_nom:<12}{equipe_info} {a.heure_accostage:6.2f}h {a.heure_fin:6.2f}h {a.attente:6.2f}h {a.priorite_calculee:6.0f} {a.score_contribution:8.2f}")
        print("-" * 120)
        print(f"{'TOTAUX':<25} {'':<15} {'':<12} {'':<8} {'':<8} {attente_totale:6.2f}h {'':<8} {score_total:8.2f}")
        print("=" * 120)
        nb_planifies = len(affectations)
        quais_utilises = len(set(a.quai_id for a in affectations))
        print(f"\nSTATISTIQUES")
        print(f"   - Navires planifies: {nb_planifies}")
        print(f"   - Quais utilises: {quais_utilises}/{len(self.quais)} (taux occupation: {quais_utilises / len(self.quais) * 100:.1f}%)")
        print(f"   - Attente totale: {attente_totale:.2f}h")
        if nb_planifies > 0:
            print(f"   - Attente moyenne: {attente_totale / nb_planifies:.2f}h")
        print(f"   - Score total: {score_total:.2f} (a minimiser)")
        if nb_planifies > 0:
            print(f"   - Score moyen par navire: {score_total / nb_planifies:.2f}")

    def exporter_csv(self, affectations: List[AffectationResultat], score_total: float, attente_totale: float, filename: str = None):
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"planning_epb_score_{timestamp}.csv"
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Navire', 'Type', 'Quai', 'Debut (h)', 'Fin (h)', 'Attente (h)', 'Traitement (h)', 'Priorite', 'Contribution Score', 'Priorites', 'Buffer Debut (h)', 'Buffer Fin (h)', 'Equipe'])
            for a in affectations:
                writer.writerow([
                    a.navire_nom,
                    a.type_navire,
                    a.quai_nom,
                    f"{a.heure_accostage:.2f}",
                    f"{a.heure_fin:.2f}",
                    f"{a.attente:.2f}",
                    f"{a.traitement:.2f}",
                    a.priorite_calculee,
                    f"{a.score_contribution:.2f}",
                    a.priorites_speciale,
                    f"{a.buffer_debut:.2f}",
                    f"{a.buffer_fin:.2f}",
                    getattr(a, 'equipe_nom', '')
                ])
            writer.writerow([])
            writer.writerow(['RESUME'])
            writer.writerow(['Navires planifies', len(affectations)])
            writer.writerow(['Attente totale (h)', f"{attente_totale:.2f}"])
            if len(affectations) > 0:
                writer.writerow(['Attente moyenne (h)', f"{attente_totale / len(affectations):.2f}"])
            writer.writerow(['Score total', f"{score_total:.2f}"])
            if len(affectations) > 0:
                writer.writerow(['Score moyen par navire', f"{score_total / len(affectations):.2f}"])
        print(f"\nPlanning sauvegarde dans {filename}")
        return filename
        
    # Les méthodes restantes (backtracking, genetique, etc.) sont conservées mais non affichées pour la lisibilité
    # ... (le reste du code est inchangé)
    # Dans optimiseur_epb_pro.py, ajoute cette méthode à ta classe PlanificateurEPB

    def planifier_avec_backtracking(self, navires_a_planifier, navires_a_quai=None, date_reference=None, max_permutations=50):
        """
        Version avec backtracking - Teste plusieurs ordres d'affectation
        et garde le meilleur résultat.
        
        Args:
            navires_a_planifier: liste des navires à planifier
            navires_a_quai: navires déjà à quai
            date_reference: date de référence
            max_permutations: nombre maximum de permutations à tester
        
        Returns:
            (meilleures_affectations, meilleur_score, meilleure_attente)
        """
        import random
        from copy import deepcopy
        from datetime import datetime
        
        if date_reference is None:
            date_reference = datetime.now()
        
        print(f"\n🔍 BACKTRACKING - Test de plusieurs ordres d'affectation")
        print(f"   Navires à planifier: {len(navires_a_planifier)}")
        print(f"   Permutations max: {max_permutations}")
        
        # Sauvegarder l'état initial des quais
        etat_initial_quais = deepcopy([(q.id, q.libre) for q in self.quais])
        
        # Générer différentes permutations à tester
        permutations_a_tester = []
        navires_list = list(navires_a_planifier)
        
        # 1. L'ordre original (tri par priorité)
        ordre_original = sorted(navires_list, key=lambda n: (-n.priorite_calculee, n.arrivee))
        permutations_a_tester.append(ordre_original)
        
        # 2. Ordre par durée (les plus courts d'abord)
        ordre_court = sorted(navires_list, key=lambda n: getattr(n, 'duree_estimee', 24))
        permutations_a_tester.append(ordre_court)
        
        # 3. Ordre par urgence (les plus urgents d'abord)
        def get_urgence(navire):
            if hasattr(navire, 'arrivee_datetime') and navire.arrivee_datetime and date_reference:
                return max(0, (date_reference - navire.arrivee_datetime).total_seconds() / 3600)
            return 0
        ordre_urgence = sorted(navires_list, key=lambda n: -get_urgence(n))
        permutations_a_tester.append(ordre_urgence)
        
        # 4. Permutations aléatoires
        nb_aleatoires = min(max_permutations - 3, 50)
        for _ in range(max(1, nb_aleatoires)):
            melange = navires_list.copy()
            random.shuffle(melange)
            permutations_a_tester.append(melange)
        
        meilleur_resultat = None
        meilleur_score = float('inf')
        meilleure_attente = 0
        tests_reussis = 0
        
        print(f"   Tests à effectuer: {len(permutations_a_tester)}")
        
        for i, ordre in enumerate(permutations_a_tester):
            # Restaurer l'état initial des quais
            for quai_id, libre in etat_initial_quais:
                for q in self.quais:
                    if q.id == quai_id:
                        q.libre = libre
                        break
            
            # Réinitialiser les équipements
            for eq in self.equipements:
                eq.dispo = eq.nombre
                self.equipement_unites[eq.type] = [0.0] * eq.nombre
            
            if navires_a_quai:
                self.initialiser_equipements_depuis_navires_quai(navires_a_quai)
            
            try:
                # Appeler la fonction planifier originale avec cet ordre
                resultat, score, attente = self.planifier(ordre, navires_a_quai, date_reference)
                
                if resultat and score < meilleur_score:
                    meilleur_score = score
                    meilleure_attente = attente
                    meilleur_resultat = resultat
                    tests_reussis += 1
                    print(f"   🎯 Test #{i+1}: Nouveau meilleur score = {score:.2f} (attente: {attente:.1f}h)")
            except Exception as e:
                # Ignorer les planifications qui échouent
                pass
            
            # Affichage progression
            if (i + 1) % 20 == 0:
                print(f"   📍 Progression: {i+1}/{len(permutations_a_tester)} tests, meilleur score: {meilleur_score:.2f}")
        
        print(f"\n✅ Backtracking terminé!")
        print(f"   Tests réussis: {tests_reussis}/{len(permutations_a_tester)}")
        print(f"   Meilleur score: {meilleur_score:.2f}")
        print(f"   Attente totale: {meilleure_attente:.1f}h")
        
        return meilleur_resultat, meilleur_score, meilleure_attente    
    

    def planifier_optimise(self, navires_a_planifier, navires_a_quai=None, date_reference=None, mode='auto'):
        """
        Planification avec choix automatique de la méthode
        
        Args:
            navires_a_planifier: liste des navires à planifier
            navires_a_quai: navires déjà à quai
            date_reference: date de référence
            mode: 'glouton', 'backtracking', ou 'auto'
        
        Returns:
            (affectations, score_total, attente_totale)
        """
        if mode == 'glouton':
            print("⚡ Utilisation du mode GLOUTON")
            return self.planifier(navires_a_planifier, navires_a_quai, date_reference)
        elif mode == 'backtracking':
            print("🔍 Utilisation du mode BACKTRACKING")
            return self.planifier_avec_backtracking(navires_a_planifier, navires_a_quai, date_reference)
        else:  # auto
            if len(navires_a_planifier) <= 6:
                print("🎯 Mode AUTO: backtracking (peu de navires)")
                return self.planifier_avec_backtracking(navires_a_planifier, navires_a_quai, date_reference)
            else:
                print("⚡ Mode AUTO: glouton (beaucoup de navires)")
                return self.planifier(navires_a_planifier, navires_a_quai, date_reference)

# Le reste du fichier (interface en ligne de commande) est inchangé et n'est pas réécrit ici pour éviter la longueur.

    def planifier_hybride(self, navires_a_planifier, navires_a_quai=None, date_reference=None, amelioration=True):
        """
        Algorithme GLOUTON amélioré par BACKTRACKING

        Args:
            navires_a_planifier: liste des navires à planifier
            navires_a_quai: navires déjà à quai  
            date_reference: date de référence
            amelioration: si True, applique le backtracking pour améliorer

        Returns:
            (affectations, score_total, attente_totale)
        """
        from datetime import datetime    
    
        if date_reference is None:
            date_reference = datetime.now()    
    
        print("\n" + "=" * 60)
        print("🏆 ALGORITHME GLOUTON AVEC BACKTRACKING")
        print("=" * 60)

        # ÉTAPE 1: Planification gloutonne
        print("\n📊 ÉTAPE 1 - Planification gloutonne...")
        affectations, score, attente = self.planifier(
            navires_a_planifier, navires_a_quai, date_reference
        )

        if not amelioration or not affectations:
            return affectations, score, attente

        print(f"   Score glouton: {score:.2f}")
        print(f"   Attente: {attente:.1f}h")

        # ÉTAPE 2: Identifier les parties problématiques
        print("\n📊 ÉTAPE 2 - Identification des points critiques...")

        mauvais_navires_ids = []
        seuil_attente = 168  # 7 jours
        for a in affectations:
            if a.attente > seuil_attente:
                mauvais_navires_ids.append(a.navire_id)

        if not mauvais_navires_ids:
            print("   ✅ Aucun point critique détecté")
            return affectations, score, attente

        print(f"   ⚠️ {len(mauvais_navires_ids)} navires avec attente > {seuil_attente}h")

        # ÉTAPE 3: Backtracking uniquement sur les problèmes
        print("\n📊 ÉTAPE 3 - Optimisation des points critiques...")

        # Récupérer les navires problématiques
        navires_a_optimiser = []
        for nav in navires_a_planifier:
            if nav.id in mauvais_navires_ids:
                navires_a_optimiser.append(nav)

        # Récupérer les navires non problématiques
        navires_stables = [n for n in navires_a_planifier if n.id not in mauvais_navires_ids]

        if len(navires_a_optimiser) <= 5:
            # Backtracking uniquement sur les navires problématiques
            print(f"   🔍 Backtracking sur {len(navires_a_optimiser)} navires...")
            meilleur_ordre = self._trouver_meilleur_ordre(navires_a_optimiser)

            if meilleur_ordre:
                # Replanifier avec le nouvel ordre
                tous_navires = meilleur_ordre + navires_stables
                affectations2, score2, attente2 = self.planifier(
                    tous_navires, navires_a_quai, date_reference
                )

                if affectations2 and score2 < score:
                    print(f"   ✅ Amélioration: {score:.2f} → {score2:.2f} (gain: {score - score2:.2f})")
                    return affectations2, score2, attente2
                else:
                    print(f"   ⚠️ Aucune amélioration trouvée")
            else:
                print(f"   ⚠️ Impossible de trouver un meilleur ordre")
        else:
            print(f"   ⚠️ Trop de navires problématiques ({len(navires_a_optimiser)}), backtracking complet")
            affectations2, score2, attente2 = self.planifier_avec_backtracking(
                navires_a_planifier, navires_a_quai, date_reference, max_permutations=30
            )

            if affectations2 and score2 < score:
                print(f"   ✅ Amélioration: {score:.2f} → {score2:.2f}")
                return affectations2, score2, attente2

        return affectations, score, attente


    def _trouver_meilleur_ordre(self, navires, max_tests=20):
        """
        Trouve le meilleur ordre pour une liste de navires    
    
        Args:
            navires: liste des navires à ordonner
            max_tests: nombre maximum de permutations à tester    
    
        Returns:
            liste ordonnée des navires
        """
        import random    
    
        if not navires:
            return navires    
    
        try:
            from itertools import permutations
        except ImportError:
            permutations = None    
    
        if len(navires) <= 4 and permutations:
            # Tester toutes les permutations
            meilleur_ordre = None
            meilleur_score = float('inf')
            
            for ordre in permutations(navires):
                # Score simplifié (somme des priorités × durée)
                score = 0
                for n in ordre:
                    duree = getattr(n, 'duree_estimee', 24)
                    score += n.priorite_calculee * duree
                
                if score < meilleur_score:
                    meilleur_score = score
                    meilleur_ordre = list(ordre)
            
            return meilleur_ordre if meilleur_ordre else list(navires)
        else:
            # Tests aléatoires
            meilleur_ordre = list(navires)
            meilleur_score = 0
            for n in navires:
                duree = getattr(n, 'duree_estimee', 24)
                meilleur_score += n.priorite_calculee * duree
            
            for _ in range(max_tests):
                melange = list(navires)
                random.shuffle(melange)
                score = 0
                for n in melange:
                    duree = getattr(n, 'duree_estimee', 24)
                    score += n.priorite_calculee * duree
                
                if score < meilleur_score:
                    meilleur_score = score
                    meilleur_ordre = melange
            
            return meilleur_ordre
    
    
    
    def planifier_genetique(self, navires_a_planifier, navires_a_quai=None, date_reference=None,
                        population_size=50, generations=100, mutation_rate=0.1, elite_rate=0.2):
        """
        ALGORITHME GÉNÉTIQUE pour l'optimisation de l'ordre des navires
        
        Args:
            navires_a_planifier: liste des navires à planifier
            navires_a_quai: navires déjà à quai
            date_reference: date de référence
            population_size: taille de la population
            generations: nombre de générations
            mutation_rate: taux de mutation (0-1)
            elite_rate: taux d'élite (0-1)
        
        Returns:
            (affectations, score_total, attente_totale)
        """
        import random
        from copy import deepcopy
        from datetime import datetime
        
        if date_reference is None:
            date_reference = datetime.now()
        
        print("\n" + "=" * 70)
        print("🧬 ALGORITHME GÉNÉTIQUE POUR PLANIFICATION PORTUAIRE")
        print("=" * 70)
        print(f"   Population: {population_size} | Générations: {generations}")
        print(f"   Mutation: {mutation_rate:.0%} | Élite: {elite_rate:.0%}")
        print(f"   Navires à planifier: {len(navires_a_planifier)}")
        
        # Sauvegarder l'état initial
        etat_initial_quais = deepcopy([(q.id, q.libre) for q in self.quais])
        
        # ============================================================
        # 1. CRÉATION DE LA POPULATION INITIALE
        # ============================================================
        print("\n📊 GÉNÉRATION 0 - Création de la population initiale...")
        
        population = []
        
        # Individu 1: Ordre glouton (tri par priorité)
        ordre_glouton = sorted(navires_a_planifier, key=lambda n: (-n.priorite_calculee, n.arrivee))
        population.append(ordre_glouton)
        
        # Individu 2: Ordre par date d'arrivée
        ordre_arrivee = sorted(navires_a_planifier, key=lambda n: n.arrivee)
        population.append(ordre_arrivee)
        
        # Individu 3: Ordre par durée (plus courts d'abord)
        ordre_court = sorted(navires_a_planifier, key=lambda n: getattr(n, 'duree_estimee', 24))
        population.append(ordre_court)
        
        # Individus aléatoires
        for _ in range(population_size - 3):
            individu = list(navires_a_planifier)
            random.shuffle(individu)
            population.append(individu)
        
        print(f"   ✅ Population initiale: {len(population)} individus")
        
        # ============================================================
        # 2. ÉVALUATION DE LA POPULATION
        # ============================================================
        def evaluer_individu(ordre):
            """Évalue un ordre d'affectation"""
            # Restaurer l'état
            for quai_id, libre in etat_initial_quais:
                for q in self.quais:
                    if q.id == quai_id:
                        q.libre = libre
                        break
            
            # Réinitialiser équipements
            for eq in self.equipements:
                eq.dispo = eq.nombre
                self.equipement_unites[eq.type] = [0.0] * eq.nombre
            
            if navires_a_quai:
                self.initialiser_equipements_depuis_navires_quai(navires_a_quai)
            
            try:
                resultats, score, attente = self.planifier(ordre, navires_a_quai, date_reference)
                return score if resultats else float('inf')
            except:
                return float('inf')
        
        # Évaluer la population initiale
        scores = []
        for i, individu in enumerate(population):
            score = evaluer_individu(individu)
            scores.append(score)
            if (i + 1) % 20 == 0:
                print(f"   Évaluation: {i+1}/{len(population)}")
        
        # ============================================================
        # 3. BOUCLE PRINCIPALE (Générations)
        # ============================================================
        print(f"\n🧬 ÉVOLUTION SUR {generations} GÉNÉRATIONS...")
        print("-" * 70)
        
        meilleur_score_global = min(scores)
        meilleur_ordre_global = population[scores.index(meilleur_score_global)]
        meilleur_resultat_global = None
        meilleurs_scores = [meilleur_score_global]
        
        for generation in range(1, generations + 1):
            # Tri par score (meilleurs d'abord)
            population_triee = sorted(zip(population, scores), key=lambda x: x[1])
            population = [p for p, _ in population_triee]
            scores = sorted(scores)
            
            # Mise à jour du meilleur global
            if scores[0] < meilleur_score_global:
                meilleur_score_global = scores[0]
                meilleur_ordre_global = population[0]
                print(f"   🎯 Génération {generation}: NOUVEAU RECORD! Score: {meilleur_score_global:.2f}")
            
            meilleurs_scores.append(meilleur_score_global)
            
            # Sélection des élites
            nb_elite = max(1, int(population_size * elite_rate))
            nouvelle_population = population[:nb_elite]
            nouveaux_scores = scores[:nb_elite]
            
            # Création de la nouvelle génération
            while len(nouvelle_population) < population_size:
                # Sélection par tournoi
                parent1 = self._selection_tournoi(population, scores)
                parent2 = self._selection_tournoi(population, scores)
                
                # Crossover (reproduction)
                enfant = self._crossover_ox(parent1, parent2)
                
                # Mutation
                if random.random() < mutation_rate:
                    enfant = self._mutation_echange(enfant)
                
                # Évaluation
                score_enfant = evaluer_individu(enfant)
                
                nouvelle_population.append(enfant)
                nouveaux_scores.append(score_enfant)
            
            population = nouvelle_population
            scores = nouveaux_scores
            
            # Affichage progression
            if generation % 20 == 0 or generation == generations:
                moyenne = sum(scores) / len(scores)
                print(f"   📍 Génération {generation}: Meilleur={scores[0]:.2f} | Moyenne={moyenne:.2f}")
        
        # ============================================================
        # 4. OBTENIR LE MEILLEUR RÉSULTAT
        # ============================================================
        print("\n📊 ÉVALUATION FINALE DE LA MEILLEURE SOLUTION...")
        
        # Restaurer l'état
        for quai_id, libre in etat_initial_quais:
            for q in self.quais:
                if q.id == quai_id:
                    q.libre = libre
                    break
        
        # Réinitialiser équipements
        for eq in self.equipements:
            eq.dispo = eq.nombre
            self.equipement_unites[eq.type] = [0.0] * eq.nombre
        
        if navires_a_quai:
            self.initialiser_equipements_depuis_navires_quai(navires_a_quai)
        
        meilleur_resultat, score_final, attente_final = self.planifier(
            meilleur_ordre_global, navires_a_quai, date_reference
        )
        
        print(f"\n" + "=" * 70)
        print("📊 RÉSULTAT DE L'ALGORITHME GÉNÉTIQUE")
        print("=" * 70)
        print(f"   Score final: {score_final:.2f}")
        print(f"   Attente totale: {attente_final:.1f}h")
        print(f"   Navires planifiés: {len(meilleur_resultat)}")
        print(f"   Meilleur score global: {meilleur_score_global:.2f}")
        
        return meilleur_resultat, score_final, attente_final
    
    
    def _selection_tournoi(self, population, scores, tournoi_size=3):
        """Sélection par tournoi"""
        import random
        indices = random.sample(range(len(population)), tournoi_size)
        meilleur_idx = min(indices, key=lambda i: scores[i])
        return population[meilleur_idx]
    
    
    def _crossover_ox(self, parent1, parent2):
        """
        Crossover OX (Order Crossover) pour problèmes d'ordonnancement
        Préserve l'ordre relatif des éléments
        """
        import random
        
        size = len(parent1)
        start, end = sorted(random.sample(range(size), 2))
        
        # Initialiser l'enfant avec des None
        enfant = [None] * size
        
        # Copier les gènes de parent1 entre start et end
        enfant[start:end+1] = parent1[start:end+1]
        
        # Remplir le reste avec les gènes de parent2 dans l'ordre
        pos = 0
        for gene in parent2:
            if gene not in enfant:
                while pos < size and enfant[pos] is not None:
                    pos += 1
                if pos < size:
                    enfant[pos] = gene
        
        return enfant
    
    
    def _mutation_echange(self, individu, prob=0.3):
        """Mutation par échange de deux positions"""
        import random
        if random.random() < prob:
            i, j = random.sample(range(len(individu)), 2)
            individu[i], individu[j] = individu[j], individu[i]
        return individu
    
    
    def _mutation_inversion(self, individu, prob=0.2):
        """Mutation par inversion d'une séquence"""
        import random
        if random.random() < prob:
            i, j = sorted(random.sample(range(len(individu)), 2))
            individu[i:j+1] = reversed(individu[i:j+1])
        return individu
# =============================================================================
# INTERFACE EN LIGNE DE COMMANDE (pour tests hors Django)
# =============================================================================

def afficher_banniere():
    print("\n" + "=" * 80)
    print("""
    ======================================================================
    OPTIMISEUR EPB - SYSTEME INTELLIGENT DE GESTION DES ACCOSTAGES
    Entreprise Portuaire de Bejaia (EPB)
    ======================================================================
    """)
    print("=" * 80)
    print(f"\nVersion 7.7.0 - Avec toutes les regles EPB, gestion des equipements et score corrige")
    print("-" * 70)


def afficher_grille_priorites():
    print("\n" + "=" * 60)
    print("GRILLE DES PRIORITES EPB")
    print("=" * 60)
    print(f"{'Priorite':<30} {'Poids':<10} {'Regle'}")
    print("-" * 70)
    print(f"{'Navire sortant':<30} {POIDS_PRIORITES[Priorite.SORTANT]:<10} Prioritaire sur tous")
    print(f"{'Navire de passage':<30} {POIDS_PRIORITES[Priorite.PASSAGE]:<10} Prioritaire")
    print(f"{'Gazier (hiver)':<30} {POIDS_PRIORITES[Priorite.GAZIER_HIVER]:<10} Quai 26 OBLIGATOIRE")
    print(f"{'Caboteur essence':<30} {POIDS_PRIORITES[Priorite.ESSENCE]:<10} Quai 19 de preference")
    print(f"{'Navire animalier':<30} {POIDS_PRIORITES[Priorite.ANIMALIER]:<10} Quais 12/13 UNIQUEMENT, <12h")
    print(f"{'Denrees perissables':<30} {POIDS_PRIORITES[Priorite.PERISSABLE]:<10} <24h")
    print(f"{'Produits strategiques':<30} {POIDS_PRIORITES[Priorite.STRATEGIQUE]:<10} Priorite nationale")
    print(f"{'Ligne reguliere (ferry)':<30} {POIDS_PRIORITES[Priorite.LIGNE_REGULIERE]:<10} Quais 8,12,13, <4h")
    print(f"{'Convention speciale':<30} {POIDS_PRIORITES[Priorite.CONVENTION]:<10} Selon contrat")
    print(f"{'Huilier':<30} {POIDS_PRIORITES[Priorite.HUILIER]:<10} Quais 25 de preference")
    print("=" * 70)


def afficher_quais(quais):
    print("\n" + "=" * 80)
    print("QUAIS DISPONIBLES")
    print("=" * 80)
    print(f"{'ID':<5} {'Nom':<12} {'Longueur':<10} {'Profondeur':<12} {'Specialite':<15} {'Etat'}")
    print("-" * 80)
    for q in quais:
        etat = "Libre" if q.libre == 0 else f"Occupe jusqu'a {q.libre:.1f}h"
        print(f"{q.id:<5} {q.nom:<12} {q.longueur:<10.0f}m {q.profondeur:<12.1f}m {q.specialite:<15} {etat}")
    print("=" * 80)


def afficher_equipements(equipements):
    print("\n" + "=" * 80)
    print("EQUIPEMENTS DE MANUTENTION")
    print("=" * 80)
    print(f"{'ID':<3} {'Type':<25} {'Capacite':<12} {'Disponibles'}")
    print("-" * 80)
    for e in equipements:
        print(f"{e.id:<3} {e.type:<25} {e.capacite:<6.1f}t       {e.dispo:<3}/{e.nombre:<3}")
    print("=" * 80)


def main():
    afficher_banniere()
    print("\nChargement des donnees du port...")
    occupations_exemple = {}
    quais = GestionnaireDonnees.charger_quais(occupations_exemple)
    equipements = GestionnaireDonnees.charger_equipements()
    print(f"{len(quais)} quais disponibles")
    print(f"{len(equipements)} types d'equipements")

    while True:
        print("\n" + "=" * 60)
        print("MENU PRINCIPAL")
        print("=" * 60)
        print("1. Lancer une planification")
        print("2. Afficher les quais")
        print("3. Afficher les equipements")
        print("4. Afficher la grille des priorites")
        print("5. A propos")
        print("6. Quitter")
        choix = input("\nVotre choix: ").strip()

        if choix == "1":
            for e in equipements:
                e.dispo = e.nombre
            print("\nTypes de navires disponibles:")
            print("   1. Navires realistes (basés sur le memoire EPB)")
            print("   2. Navires aleatoires (pour test)")
            type_nav = input("Votre choix (defaut: 1): ").strip() or "1"

            if type_nav == "2":
                nb = input("Nombre de navires (defaut: 10): ").strip()
                nb = int(nb) if nb else 10
                navires = GestionnaireDonnees.creer_navires_test(nb)
            else:
                navires = GestionnaireDonnees.creer_navires_realistes()
                print(f"\n{len(navires)} navires realistes charges")

            saison = input("Saison (hiver/ete) [defaut: hiver]: ").strip().lower()
            mois = 3 if saison == "hiver" or saison == "" else 7
            print(f"\nLancement de la planification (saison: {'HIVER' if mois in [11, 12, 1, 2, 3] else 'ETE'})...")

            planificateur = PlanificateurEPB(quais, equipements, mois=mois)
            affectations, score_total, attente_totale = planificateur.planifier(navires)
            planificateur.afficher_resultats(affectations, score_total, attente_totale)

            if affectations:
                planificateur.exporter_csv(affectations, score_total, attente_totale)
                print("\nPlanification terminee avec succes !")
            else:
                print("\nAucune affectation possible - verifiez les contraintes")

        elif choix == "2":
            afficher_quais(quais)
        elif choix == "3":
            afficher_equipements(equipements)
        elif choix == "4":
            afficher_grille_priorites()
        elif choix == "5":
            print("\n" + "=" * 60)
            print("A PROPOS")
            print("=" * 60)
            print("Systeme d'optimisation des creneaux d'accostage")
            print("Entreprise Portuaire de Bejaia (EPB)")
            print("\nVersion: 7.7.0")
            print("Auteur: Votre Nom - Master Genie Logiciel")
            print("Date: Avril 2026")
            print("\nBase sur le memoire:")
            print("'Minimisation du Temps de Sejour des Navires dans un Port'")
            print("HADJI Mohammed & MEDJAHEDI Ilham, 2015/2016")
            print("=" * 60)
        elif choix == "6":
            print("\nAu revoir !")
            break
        else:
            print("Choix invalide")


if __name__ == "__main__":
    main()