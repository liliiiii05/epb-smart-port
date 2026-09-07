#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
OPTIMISEUR EPB - Version avec gestion des incertitudes et buffers
Version finale : prise en compte des occupations initiales, équipements multiples, créneaux futurs,
shifts, standards par entité, postes (numéro), préférences pour céréaliers, saturation des quais,
et score toujours positif.
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
    'BMT': {'quais_preferes': [22,24], 'traitement_base': 0.9, 'priority_bonus': 10},
    'CEVITAL': {'quais_preferes': [25], 'traitement_base': 1.2, 'priority_bonus': 20},
    'NAFTAL': {'quais_preferes': [1,2,3], 'traitement_base': 1.1, 'priority_bonus': 15},
    'STH': {'quais_preferes': [], 'traitement_base': 1.0, 'priority_bonus': 5},
    'OAIC': {'quais_preferes': [17,18], 'traitement_base': 1.0, 'priority_bonus': 25},
}
# Groupes de postes adjacents (pour navires très longs)
GROUPES_POSTES = {
    # (poste1_id, poste2_id): {"longueur_totale": float, "specialite": str, "nom": str}
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
    poste_numero: int = 0          # Numéro du poste (ex: "22" -> 22)
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
        self.heure_arrivee_str = f"{int(self.arrivee)}h{int((self.arrivee%1)*60):02d}"
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
        for i in range(1, nb+1):
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
                agent=nom.split()[0]  # Agent = premier mot du nom
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

        def calculer_temps_traitement(self, navire, quai):
        # ===================== CONTENEURS (durée fixe selon agent) =====================
            if navire.type == TypeNavire.CONTENEUR:
                agent = getattr(navire, 'agent', '').upper()
                if 'MSC' in agent:
                    duree_estimee = 6 * 24  # 6 jours
                elif 'CMA' in agent or 'CGM' in agent:
                    duree_estimee = 5 * 24  # 5 jours
                elif 'MAERSK' in agent:
                    duree_estimee = 5 * 24  # 5 jours
                else:
                    duree_estimee = 5 * 24  # 5 jours par défaut
                
                # Incertitude
                if self.incertitude:
                    variation = random.uniform(1 - self.amplitude, 1 + self.amplitude)
                    duree_estimee *= variation
                
                return max(0.5, duree_estimee)
        

        # ========== PRÉDICTION PAR DÉBIT (tonnes/heure) ==========
        try:
            from port.ml_debit import DebitModel
            debit_model = DebitModel()
            if debit_model.model is not None:
                nb_equipes = getattr(navire, 'nb_equipes_requises', 1)
                shift = getattr(navire, 'shift_requis', 'matin')
                debit = debit_model.predire_debit(
                    navire.type.value,
                    volume,
                    nb_equipes,
                    shift
                )
                if debit is not None and debit > 0:
                    print(f"🔄 IA débit utilisé : {debit:.0f} t/h pour {navire.nom}")
                    duree_estimee = volume / debit
                    if self.incertitude:
                        variation = random.uniform(1 - self.amplitude, 1 + self.amplitude)
                        duree_estimee *= variation
                    return max(0.5, duree_estimee)
        except Exception:
            pass    

        # ========== MÉTHODE CLASSIQUE ==========
        taux_base = {
            TypeNavire.CEREALIER: 550,
            TypeNavire.FERRY: 100,
            TypeNavire.GAZIER: 200,
            TypeNavire.FRIGORIFIQUE: 120,
            TypeNavire.BETAIL: 80,
            TypeNavire.ESSENCE: 300,
            TypeNavire.HUILIER: 150,
            TypeNavire.PETROLIER: 400,
            TypeNavire.CARGO: 400,
            TypeNavire.ROULIER: 100,
            TypeNavire.CHIMIQUIER: 120,
        }.get(navire.type, 150)    

        coeff_quai = quai.performance
        coeff_marchandise = 1.0
        if navire.marchandise.dangereux:
            coeff_marchandise *= 0.8
        if navire.marchandise.frigo:
            coeff_marchandise *= 0.9    

        taux_effectif = taux_base * coeff_quai * coeff_marchandise
        duree_classique = volume / taux_effectif if volume > 0 else 1.0    

        # Coefficient d'apprentissage historique
        coeff_histo = self.coeffs_historiques.get((navire.type.value, quai.id), 1.0)
        duree_classique *= coeff_histo    

        # Standard d'entité
        entite = getattr(navire, 'entite', '')
        if entite in STANDARDS_ENTITE:
            duree_classique *= STANDARDS_ENTITE[entite]['traitement_base']    

        # ========== PRÉDICTION ML EXISTANTE (durée) ==========
        duree_ml = self.ml_model.predire(navire, duree_classique)
        if duree_ml is not None:
            duree_estimee = duree_ml
        else:
            duree_estimee = duree_classique    

        # Incertitude
        if self.incertitude:
            variation = random.uniform(1 - self.amplitude, 1 + self.amplitude)
            duree_estimee *= variation    

        return max(0.5, duree_estimee)

            
    def calculer_attente(self, navire, debut):
        if hasattr(navire, 'arrivee_datetime') and navire.arrivee_datetime:
            arrivee_heure = navire.arrivee_datetime.hour + navire.arrivee_datetime.minute / 60.0
            attente = debut - arrivee_heure
            if attente < 0:
                attente += 24
            today = datetime.now().date()
            jours_diff = (today - navire.arrivee_datetime.date()).days
            attente += jours_diff * 24
            return max(0, attente)
        else:
            return max(0, debut - navire.arrivee)

    def calculer_score_contribution(self, navire: Navire, debut: float, traitement: float,
                                 buffer_debut: float, buffer_fin: float) -> float:
        attente = self.calculer_attente(navire, debut)
        # Poids fixe pour l'attente (indépendant du scénario)
        poids_attente = 3.0
        # Pénalité si l'attente dépasse 48h
        penalite_retard = max(0, attente - 48) * 1.0
        # Pénalité pour buffers insuffisants
        penalite_buffer = 0.0
        if buffer_debut < 1.0:
            penalite_buffer += (1.0 - buffer_debut) * 20.0
        if buffer_fin < 1.0:
            penalite_buffer += (1.0 - buffer_fin) * 20.0
        # Score = durée de traitement + attente pondérée + pénalités
        score = traitement + attente * poids_attente + penalite_retard + penalite_buffer
        # Garantir un score positif (≥ 1)
        return max(1.0, score)

    def get_coeff_historique(self, navire_type, quai_id):
        """Récupère le coefficient historique pour un type de navire et un quai"""
        return self.coeffs_historiques.get((navire_type.value if hasattr(navire_type, 'value') else navire_type, quai_id), 1.0)

# =============================================================================
# PLANIFICATEUR PRINCIPAL AVEC INCERTITUDE ET BUFFERS
# =============================================================================

class PlanificateurEPB:
    VERSION = "7.6.0"

    def __init__(self, quais, equipements, mois=None,
             incertitude=True, amplitude=0.2, pourcentage_buffer=0.15,
             meteo_restrictions=None, meteo_pluie=False, meteo_vent_force=0,
             meteo_temperature=20, scenario="equilibre",
             coeffs_historiques=None, equipes=None):
             
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
                     id=-abs(p1*100 + p2),
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

    def get_equipements_necessaires(self, navire, quai=None):
        """Retourne la liste des équipements réels nécessaires pour ce navire."""
        
        # Règle 5: Si le navire a ses propres grues, pas besoin d'équipements
        if type_navire == 'conteneur':
           return ["Gottwald HMK 260 10", "KONECRANS SP 6 217"]
        
        from port.views import get_equipements_necessaires_par_type
        return get_equipements_necessaires_par_type(navire.type.value)

    def calculer_temps_manoeuvre(self, navire: Navire, quai: Quai) -> float:
        """Temps de manœuvre fixé à 2 heures pour tous les navires."""
        return 2.0 

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

    def equipements_disponibles(self, navire, quai, debut, fin):
        """Vérifie la disponibilité des équipements et utilise l'IA pour choisir l'unité."""
        equip_types = self.get_equipements_necessaires(navire, quai)
        debut_possible = debut
        reservation = {}    

        for _ in range(10):
            max_libre = debut_possible
            reservation.clear()    

            for eq_type in equip_types:
                eq = next((e for e in self.equipements if e.type == eq_type), None)
                if eq is None:
                    return False, debut_possible, f"Équipement {eq_type} inexistant", 0.0    

                if eq.en_panne:
                    if eq.panne_debut:
                        duree_panne = (datetime.now() - eq.panne_debut).total_seconds() / 3600
                        if duree_panne < eq.temps_reparation:
                            fin_panne = eq.panne_debut + timedelta(hours=eq.temps_reparation)
                            libre = (fin_panne - datetime.now()).total_seconds() / 3600
                            libre = max(0, libre)
                            if libre > max_libre:
                                max_libre = libre
                        else:
                            eq.en_panne = False
                            eq.panne_debut = None
                    continue    

                unites = self.equipement_unites.get(eq_type, [])
                if not unites:
                    return False, debut_possible, f"Aucune unité pour {eq_type}", 0.0    

                # --- Choix de l'unité avec IA ---
                idx = None
                if self.equipement_choice_model and self.equipement_choice_model.model is not None:
                    try:
                        navire_type = navire.type.value
                        heure_debut = (datetime.now().hour + datetime.now().minute/60.0) % 24
                        jour_semaine = datetime.now().weekday()
                        quai_specialite = quai.specialite
                        recommended = self.equipement_choice_model.predire_unite(
                            navire_type, eq_type, quai_specialite, heure_debut, jour_semaine
                        )
                        if recommended is not None and 0 <= recommended < len(unites):
                            # Vérifier si l'unité recommandée est disponible
                            if unites[recommended] <= max_libre:
                                idx = recommended
                                print(f"🔮 IA recommande unité {idx} pour {eq_type} (navire {navire.nom})")
                            else:
                                print(f"⚠️ Unité {recommended} recommandée mais non disponible (libre à {unites[recommended]:.1f}h > {max_libre:.1f}h)")
                    except Exception as e:
                        print(f"⚠️ Erreur prédiction IA: {e}")    

                if idx is None:
                    # Fallback : unité avec la plus petite date de libération
                    meilleure_unite = min(unites)
                    idx = unites.index(meilleure_unite)
                    print(f"⚙️ Fallback: unité {idx} (date {meilleure_unite:.2f}h) pour {eq_type}")    

                meilleure_unite = unites[idx]
                if meilleure_unite > max_libre:
                    max_libre = meilleure_unite
                reservation[eq_type] = idx    

            if max_libre <= debut_possible:
                break
            debut_possible = max_libre    

        traitement = self.modele.calculer_temps_traitement(navire, quai)
        fin_possible = debut_possible + traitement    

        if debut_possible < quai.libre:
            debut_possible = quai.libre
            fin_possible = debut_possible + traitement    

        for eq_type, idx in reservation.items():
            unites = self.equipement_unites.get(eq_type, [])
            if debut_possible < unites[idx]:
                return False, debut_possible, f"Conflit sur {eq_type} unité {idx}", 0.0    

        attente_equip = max(0.0, debut_possible - debut)
        return True, debut_possible, "OK", attente_equip
        
    def get_nb_equipements_max(self, navire):
        """Retourne le nombre maximal d'équipements que ce navire peut utiliser simultanément."""
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

        # Charger le modèle IA (si disponible)
        model_ia = None
        try:
            model_ia = EquipementChoiceModel()
        except Exception:
            pass

        for eq_type in equip_types:
            unites = self.equipement_unites.get(eq_type)
            if not unites:
                continue

            # --- Choix de l'unité avec IA (si possible) ---
            idx = None
            if model_ia and model_ia.model is not None:
                try:
                    navire_type = navire.type.value
                    heure_debut = (datetime.now().hour + datetime.now().minute/60.0) % 24
                    jour_semaine = datetime.now().weekday()
                    quai_specialite = quai.specialite
                    recommended = model_ia.predire_unite(
                        navire_type, eq_type, quai_specialite, heure_debut, jour_semaine
                    )
                    if recommended is not None and 0 <= recommended < len(unites):
                        idx = recommended
                except Exception as e:
                    logger.warning(f"Erreur prédiction IA pour {eq_type}: {e}")

            # Fallback : unité avec la plus petite date de libération
            if idx is None:
                # On ne trie pas la liste pour conserver les indices stables
                min_val = min(unites)
                idx = unites.index(min_val)

            # --- Réservation de l'unité choisie ---
            unites[idx] = max(unites[idx], fin)

            # --- Enregistrement de l'utilisation (pour l'historique IA) ---
            try:
                from port.models import UtilisationEquipement, Navire as NavireModel, Poste
                navire_db = NavireModel.objects.get(id=navire.id)
                quai_db = None
                if quai.id > 0:  # id positif = poste réel
                    poste = Poste.objects.get(id=quai.id)
                    quai_db = poste.quai
                # Récupérer la date de début (fin - traitement)
                debut = fin - self.modele.calculer_temps_traitement(navire, quai)
                UtilisationEquipement.objects.create(
                    navire=navire_db,
                    equipement_type=eq_type,
                    unite_index=idx,
                    quai=quai_db,
                    debut=datetime.now() + timedelta(hours=debut),  # conversion approximative
                    fin=datetime.now() + timedelta(hours=fin),
                    conflit=False,  # à renseigner si détecté
                    attente_navire=self.modele.calculer_attente(navire, debut)
                )
            except Exception as e:
                logger.warning(f"Erreur enregistrement utilisation: {e}")

    def verifier_compatibilite(self, navire: Navire, quai: Quai) -> Tuple[bool, str]:
    # ====== Règles météo ======
        if self.meteo_restrictions and quai.nom in self.meteo_restrictions:
            return False, f"Quai {quai.nom} interdit pour cause météo"
        if self.meteo_pluie:
            if navire.type == TypeNavire.CEREALIER:
                return False, "🌧️ Déchargement de céréales interdit par temps de pluie"
            if navire.marchandise.dangereux:
                return False, "⚠️ Opérations sur produits dangereux interdites par temps de pluie"
    
        # ====== Contraintes physiques ======
        if navire.longueur > quai.longueur:
            return False, f"Longueur {navire.longueur}m > {quai.longueur}m"
        if navire.tirant > quai.profondeur:
            return False, f"Tirant d'eau {navire.tirant}m > {quai.profondeur}m"
    
        # ====== RÈGLES SPÉCIALES POUR GAZIERS ======
        if navire.type == TypeNavire.GAZIER:
            # En hiver : uniquement poste 26
            if self.est_hiver():
                if quai.poste_numero != 26:
                    return False, f"Gazier en hiver doit être au poste 26 (poste actuel: {quai.poste_numero})"
            else:
                # Hors hiver : postes 24 ou 26
                if quai.poste_numero not in [24, 26]:
                    return False, f"Gazier doit être aux postes 24 ou 26 (poste actuel: {quai.poste_numero})"
            
            # Vérifier la spécialité
            if quai.specialite not in ["gazier", "grand"]:
                return False, f"Gazier nécessite un quai gazier ou grand (spécialité: {quai.specialite})"
    
        # ====== RÈGLES SPÉCIALES POUR CÉRÉALIERS ======
        if navire.type == TypeNavire.CEREALIER:
            # Postes autorisés pour céréaliers
            postes_autorises = [15, 16, 17, 21, 22, 23]
            if quai.poste_numero not in postes_autorises:
                return False, f"Céréalier doit être aux postes {postes_autorises} (poste actuel: {quai.poste_numero})"
            
            # Vérifier la spécialité
            if quai.specialite not in ["cerealier", "grand"]:
                return False, f"Céréalier nécessite un quai céréalier ou grand (spécialité: {quai.specialite})"
    
        # ====== RÈGLES SPÉCIALES POUR CONTENEURS ======
        if navire.type == TypeNavire.CONTENEUR:
            agent = getattr(navire, 'agent', '').upper()
            
            # Règle MSC : poste 22 obligatoire
            if 'MSC' in agent and quai.poste_numero != 22:
                return False, f"MSC doit être au poste 22 (poste actuel: {quai.poste_numero})"
            
            # Règle CMA CGM : poste 24 obligatoire
            if ('CMA' in agent or 'CGM' in agent) and quai.poste_numero != 24:
                return False, f"CMA CGM doit être au poste 24 (poste actuel: {quai.poste_numero})"
            
            # Règle MAERSK : postes 22 ou 24
            if 'MAERSK' in agent and quai.poste_numero not in [22, 24]:
                return False, f"MAERSK doit être aux postes 22 ou 24 (poste actuel: {quai.poste_numero})"
            
            # Règle générale conteneurs : postes 22 ou 24
            if quai.poste_numero not in [22, 24]:
                return False, f"Conteneur doit être aux postes 22 ou 24 (poste actuel: {quai.poste_numero})"
            
            # Vérifier la spécialité
            if quai.specialite not in ["conteneurs", "grand"]:
                return False, f"Conteneur nécessite un quai conteneurs ou grand (spécialité: {quai.specialite})"
    
        # ====== RÈGLES SPÉCIALES POUR CARGO ET HUILIERS ======
        if navire.type in [TypeNavire.CARGO, TypeNavire.HUILIER]:
            # Postes autorisés pour cargos/huiliers
            postes_autorises = [11, 14, 18, 19]
            if quai.poste_numero not in postes_autorises:
                return False, f"{navire.type.value.upper()} doit être aux postes généraux {postes_autorises} (poste actuel: {quai.poste_numero})"
            
            # Vérifier la spécialité
            if quai.specialite not in ["general", "grand"]:
                return False, f"{navire.type.value.upper()} nécessite un quai général ou grand (spécialité: {quai.specialite})"
    
        # ====== Autres règles spéciales ======
        if navire.type == TypeNavire.PETROLIER and quai.poste_numero not in [1, 2, 3] and quai.specialite != "grand":
            return False, "Pétrolier doit être aux postes 1-3 ou quais grands"
        
        if navire.priorites.animalier and quai.poste_numero not in [12, 13]:
            return False, "Animalier doit être aux postes 12 ou 13"
    
        # ====== Gestion des groupes virtuels ======
        if quai.est_groupe:
            if quai.specialite == "ferry" and navire.type != TypeNavire.FERRY:
                return False, "Ce groupe est réservé aux ferries"
            if quai.specialite == "cerealier" and navire.type != TypeNavire.CEREALIER:
                return False, "Ce groupe est réservé aux céréaliers"
            return True, "Compatible"
    
        # ====== Règles générales par spécialité (fallback) ======
        regles = {
            TypeNavire.GAZIER: ["gazier", "grand"],
            TypeNavire.PETROLIER: ["petrolier", "grand"],
            TypeNavire.CEREALIER: ["cerealier", "grand"],
            TypeNavire.CONTENEUR: ["conteneurs", "grand"],
            TypeNavire.FERRY: ["ferry", "general"],
            TypeNavire.ESSENCE: ["essence", "grand"],
            TypeNavire.HUILIER: ["huilier", "huiliers", "grand"],
            TypeNavire.CARGO: ["general", "grand"],
            TypeNavire.ROULIER: ["general", "grand"],
            TypeNavire.CHIMIQUIER: ["petrolier", "grand"],
            TypeNavire.FRIGORIFIQUE: ["general", "grand"],
            TypeNavire.BETAIL: ["ferry", "general"],
        }
        autorisees = regles.get(navire.type, ["general", "grand"])
        
        # Vérification stricte : la spécialité du quai doit être dans la liste autorisée
        if quai.specialite not in autorisees:
            return False, f"Un {navire.type.value} ne peut pas utiliser un quai de type {quai.specialite} (autorisé: {', '.join(autorisees)})"
    
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
        """Retourne le nom du shift pour une heure décimale."""
        h = heure % 24
        if 7 <= h < 13:
            return "07h-13h"
        elif 13 <= h < 19:
            return "13h-19h"
        elif 19 <= h < 24:
            return "19h-01h"
        else:
            return "01h-07h"

    def calculer_score_contribution(self, navire: Navire, debut: float, traitement: float,
                                     buffer_debut: float, buffer_fin: float) -> float:
        attente = self.modele.calculer_attente(navire, debut)
        if self.scenario == "rapide":
            poids_attente = 2.0
            poids_securite = 0.5
        elif self.scenario == "securise":
            poids_attente = 0.5
            poids_securite = 2.0
        else:
            poids_attente = 1.0
            poids_securite = 1.0
        penalite_buffer = 0.0
        seuil = 1.0
        coeff = 20.0
        if buffer_debut < seuil:
            penalite_buffer += (seuil - buffer_debut) * coeff * poids_securite
        if buffer_fin < seuil:
            penalite_buffer += (seuil - buffer_fin) * coeff * poids_securite
        score = traitement + (attente * poids_attente) + penalite_buffer
        return max(1.0, score)

    def planifier(self, navires_a_planifier, navires_a_quai=None, date_reference=None):
        """Planifie l'affectation des navires aux quais"""
        if date_reference is None:
            date_reference = datetime.now()
        base = date_reference.replace(hour=0, minute=0, second=0, microsecond=0)       

        # Heure actuelle en heures décimales
        heure_actuelle = (date_reference - base).total_seconds() / 3600.0       

        # Réinitialiser les listes de libération des équipements
        for eq in self.equipements:
            self.equipement_unites[eq.type] = [0.0] * eq.dispo
            eq.dispo = eq.nombre       

        # Initialiser avec les navires déjà à quai
        if navires_a_quai:
            self.initialiser_equipements_depuis_navires_quai(navires_a_quai)       

        print("\n=== Quais initiaux (avec occupations réelles) ===")
        for q in self.quais:
            print(f"  {q.nom} : libre = {q.libre:.2f}h")       

        # ========== ESTIMATION DE LA DURÉE ==========
        for nav in navires_a_planifier:
            if self.quais:
                nav.duree_estimee = self.modele.calculer_temps_traitement(nav, self.quais[0])
            else:
                nav.duree_estimee = 24.0       

        # ========== TRI ==========
        def get_tri_datetime(navire):
            if navire.arrivee_datetime:
                return navire.arrivee_datetime.timestamp()
            base_now = date_reference.replace(hour=0, minute=0, second=0, microsecond=0)
            return (base_now + timedelta(hours=navire.arrivee)).timestamp()       

        navires_tries = sorted(
            navires_a_planifier,
            key=lambda n: (
                not getattr(n, 'est_en_rade', False),
                -n.priorite_calculee,
                get_tri_datetime(n),
                n.duree_estimee
            )
        )       

        affectations = []
        score_total = 0.0
        attente_totale = 0.0       

        # Dictionnaire pour compter les affectations par quai (anti-saturation)
        affectations_par_quai = {}
        # Dictionnaire pour suivre le dernier navire affecté par quai
        dernier_fin_par_quai = {}       

        print("\n" + "=" * 100)
        print("ORDRE DE TRAITEMENT (rade d'abord, priorité, ancienneté, durée)")
        print("=" * 100)
        for i, navire in enumerate(navires_tries, 1):
            priorite_text = self._get_priorite_text(navire)
            arrivee_str = navire.arrivee_datetime.strftime("%d/%m %H:%M") if navire.arrivee_datetime else f"{navire.arrivee:.1f}h"
            statut = "🔴 RADE" if getattr(navire, 'est_en_rade', False) else "⏳ ATTENDU"
            print(f"{i:2d}. {navire.nom} - {statut} - Priorite: {navire.priorite_calculee:.0f} - Arrivee: {arrivee_str} - Durée estimée: {navire.duree_estimee:.1f}h - {priorite_text}")       

        print("\n" + "=" * 100)
        print("PLANIFICATION EN COURS")
        if self.incertitude:
            print(f"Mode incertitude activé (amplitude: {self.amplitude * 100:.0f}%)")
        else:
            print("Mode déterministe")
        print(f"Buffers: {self.pourcentage_buffer * 100:.0f}% de la durée")
        if self.meteo_pluie:
            print("⚠️  Météo : Pluie en cours – ralentissement des opérations")
        if self.meteo_restrictions:
            print(f"⚠️  Restrictions météo : {', '.join(self.meteo_restrictions)}")
        print(f"📋 Scénario : {self.scenario}")
        if self.equipes:
            print(f"👥 Équipes disponibles : {', '.join(e.nom for e in self.equipes)}")
        print("=" * 100)       

        for navire in navires_tries:
            print(f"\nTraitement de {navire.nom}")
            print(f"   Priorites: {self._get_priorite_text(navire)}")
            print(f"   Arrivee: {navire.arrivee:.2f}h")
            print(f"   Type: {navire.type.value}")       

            # ========== IA : prédiction du quai recommandé ==========
            recommended_quai_id = None
            if hasattr(self, 'quai_choice_model') and self.quai_choice_model and self.quai_choice_model.model is not None:
                try:
                    approx_debut = max(navire.arrivee, heure_actuelle) if not getattr(navire, 'est_en_rade', False) else heure_actuelle
                    shift_label = self.get_shift_label(approx_debut)
                    recommended_quai_id = self.quai_choice_model.predire_quai(
                        navire.type.value,
                        navire.marchandise.volume,
                        navire.longueur,
                        navire.tirant,
                        navire.agent,
                        getattr(navire, 'entite', ''),
                        shift_label
                    )
                    if recommended_quai_id:
                        print(f"🤖 IA recommande le quai {recommended_quai_id} pour {navire.nom}")
                except Exception as e:
                    print(f"⚠️ Erreur prédiction quai: {e}")       

            # Trier les emplacements : mettre le quai recommandé en premier
            emplacements_tries = list(self.emplacements)
            if recommended_quai_id:
                for i, q in enumerate(emplacements_tries):
                    if q.id == recommended_quai_id:
                        emplacements_tries.insert(0, emplacements_tries.pop(i))
                        break       

            # ========== TRI DES QUAIS PAR PRIORITÉ ==========
            if navire.type == TypeNavire.GAZIER:
                emplacements_tries = sorted(
                    emplacements_tries,
                    key=lambda q: 0 if q.poste_numero in [24, 26] else 1
                )
                print(f"   🔥 Priorité aux postes gaziers (24/26) pour {navire.nom}")       

            elif navire.type == TypeNavire.CEREALIER:
                emplacements_tries = sorted(
                    emplacements_tries,
                    key=lambda q: (0 if q.poste_numero in [15, 16, 17, 21, 22, 23] else 1,
                                   0 if q.poste_numero in [15, 16, 17] else 1)
                )
                print(f"   🔥 Priorité aux postes céréaliers (15,16,17,21,22,23) pour {navire.nom}")       

            elif navire.type == TypeNavire.CONTENEUR:
                agent = getattr(navire, 'agent', '').upper()
                if 'MSC' in agent:
                    emplacements_tries = sorted(
                        emplacements_tries,
                        key=lambda q: 0 if q.poste_numero == 22 else 1
                    )
                    print(f"   🔥 Priorité au poste 22 pour MSC {navire.nom}")
                elif 'CMA' in agent or 'CGM' in agent:
                    emplacements_tries = sorted(
                        emplacements_tries,
                        key=lambda q: 0 if q.poste_numero == 24 else 1
                    )
                    print(f"   🔥 Priorité au poste 24 pour CMA {navire.nom}")
                else:
                    emplacements_tries = sorted(
                        emplacements_tries,
                        key=lambda q: 0 if q.poste_numero in [22, 24] else 1
                    )
                    print(f"   🔥 Priorité aux postes conteneurs (22/24) pour {navire.nom}")       

            elif navire.type in [TypeNavire.CARGO, TypeNavire.HUILIER]:
                emplacements_tries = sorted(
                    emplacements_tries,
                    key=lambda q: 0 if q.poste_numero in [11, 14, 18, 19] else 1
                )
                print(f"   🔥 Priorité aux postes généraux (11,14,18,19) pour {navire.nom}")       

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
                # ========== RÈGLES ANTI-SATURATION ==========
                nb_affectees = affectations_par_quai.get(quai.id, 0)       

                if navire.type == TypeNavire.CEREALIER and nb_affectees >= 3:
                    print(f"      ⚠️ Quai {quai.nom} déjà {nb_affectees} céréaliers, on passe au suivant")
                    continue       

                if navire.type == TypeNavire.CONTENEUR and nb_affectees >= 2:
                    print(f"      ⚠️ Quai {quai.nom} déjà {nb_affectees} conteneurs, on passe au suivant")
                    continue       

                if navire.type == TypeNavire.CARGO and nb_affectees >= 2:
                    print(f"      ⚠️ Quai {quai.nom} déjà {nb_affectees} cargos, on passe au suivant")
                    continue       

                if navire.type not in [TypeNavire.CEREALIER, TypeNavire.CONTENEUR, TypeNavire.CARGO] and nb_affectees >= 1:
                    print(f"      ⚠️ Quai {quai.nom} déjà occupé par un autre navire")
                    continue       

                compatible, raison = self.verifier_compatibilite(navire, quai)
                print(f"      Test quai {quai.nom} (spec: {quai.specialite}) : compatible={compatible} -> {raison}")
                if not compatible:
                    continue       

                # Calcul du début (prendre en compte la dernière fin de ce quai)
                dernier_fin = dernier_fin_par_quai.get(quai.id, 0)       

                if getattr(navire, 'est_en_rade', False):
                    debut = max(heure_actuelle, quai.libre, dernier_fin)
                else:
                    debut = max(navire.arrivee, quai.libre, dernier_fin)       

                # Vérification des shifts
                if not self.shift_autorise(navire, debut):
                    debut = self.prochain_shift_autorise(navire, debut)
                    traitement = self.modele.calculer_temps_traitement(navire, quai)
                    fin = debut + traitement
                    disponible, debut_ajuste, msg_equip, attente_equip = self.equipements_disponibles(navire, quai, debut, fin)
                    if not disponible:
                        print(f"         Équipements indisponibles après décalage shift: {msg_equip}")
                        continue
                    debut = debut_ajuste
                    fin = debut + traitement
                else:
                    traitement = self.modele.calculer_temps_traitement(navire, quai)
                    fin = debut + traitement       

                # Vérification initiale des équipements
                disponible, debut_ajuste, msg_equip, attente_equip = self.equipements_disponibles(navire, quai, debut, fin)
                if not disponible:
                    print(f"         Équipements indisponibles: {msg_equip}")
                    continue       

                debut = debut_ajuste
                traitement = self.modele.calculer_temps_traitement(navire, quai)
                fin = debut + traitement       

                # Ralentissements météo
                coeff_ralentissement = 1.0
                if self.meteo_pluie:
                    coeff_ralentissement *= 1.2
                if self.meteo_vent_force >= 8:
                    coeff_ralentissement *= 1.3
                traitement *= coeff_ralentissement
                fin = debut + traitement       

                buffer_debut = traitement * self.pourcentage_buffer
                buffer_fin = traitement * self.pourcentage_buffer       

                disponible, debut_ajuste2, msg_equip2, attente_equip2 = self.equipements_disponibles(navire, quai, debut, fin)
                if not disponible:
                    continue
                if debut_ajuste2 > debut:
                    debut = debut_ajuste2
                    fin = debut + traitement
                    attente_equip = attente_equip2       

                # Vérification conflit de poste
                debut_min = int(round(debut * 60))
                fin_min = int(round(fin * 60))
                conflit_poste = False
                for a in affectations:
                    if a.quai_id == quai.id:
                        a_debut_min = int(round(a.heure_accostage * 60))
                        a_fin_min = int(round(a.heure_fin * 60))
                        if not (fin_min <= a_debut_min or debut_min >= a_fin_min):
                            conflit_poste = True
                            print(f"         ⚠️ Conflit sur {quai.nom} avec {a.navire_nom} "
                                  f"([{debut:.2f},{fin:.2f}] vs [{a.heure_accostage:.2f},{a.heure_fin:.2f}])")
                            break       

                if conflit_poste:
                    debut_decale = debut + 0.1
                    fin_decale = debut_decale + traitement
                    print(f"         Tentative de résolution: décalage à {debut_decale:.2f}h")
                    disponible, debut_ajuste, msg_equip, attente_decale = self.equipements_disponibles(navire, quai, debut_decale, fin_decale)
                    if disponible:
                        conflit_decale = False
                        for a in affectations:
                            if a.quai_id == quai.id:
                                if not (fin_decale <= a.heure_accostage or debut_decale >= a.heure_fin):
                                    conflit_decale = True
                                    break
                        if not conflit_decale:
                            debut = debut_decale
                            fin = fin_decale
                            conflit_poste = False
                            attente_equip = attente_decale
                            print(f"         ✅ Conflit résolu en décalant le début à {debut:.2f}h")
                    if conflit_poste:
                        print(f"         ❌ Impossible de résoudre le conflit, ce quai est ignoré")
                        continue       

                # Vérification disponibilité équipe
                equipe_choisie = None
                if self.equipes:
                    debut_dt = base + timedelta(hours=debut)
                    fin_dt = base + timedelta(hours=fin)
                    shift_label = self.get_shift_label(debut)
                    print(f"         Recherche équipe pour shift {shift_label} (début {debut:.2f}h)")
                    for equipe in self.equipes:
                        try:
                            from port.views import equipe_disponible
                            dispo, msg = equipe_disponible(equipe, shift_label, debut_dt, fin_dt)
                            print(f"            {equipe.nom}: {dispo} -> {msg}")
                            if dispo:
                                equipe_choisie = equipe
                                break
                        except ImportError:
                            equipe_choisie = equipe
                            break
                    if not equipe_choisie:
                        print(f"         ⚠️ Aucune équipe disponible pour ce quai, on passe au suivant")
                        continue       

                contribution = self.calculer_score_contribution(navire, debut, traitement, buffer_debut, buffer_fin)       

                # ========== PRÉFÉRENCES DE QUAI ==========
                preference = 0       

                if navire.type == TypeNavire.GAZIER:
                    if quai.poste_numero == 26:
                        preference = -25
                    elif quai.poste_numero == 24:
                        preference = -15
                    else:
                        preference = 100       

                elif navire.type == TypeNavire.CEREALIER:
                    if quai.poste_numero in [15, 16, 17]:
                        preference = -25
                    elif quai.poste_numero in [21, 22, 23]:
                        preference = -15
                    else:
                        preference = 100       

                elif navire.type == TypeNavire.CONTENEUR:
                    agent = getattr(navire, 'agent', '').upper()
                    if 'MSC' in agent:
                        if quai.poste_numero == 22:
                            preference = -25
                        else:
                            preference = 100
                    elif 'CMA' in agent or 'CGM' in agent:
                        if quai.poste_numero == 24:
                            preference = -25
                        else:
                            preference = 100
                    else:
                        if quai.poste_numero in [22, 24]:
                            preference = -15
                        else:
                            preference = 50       

                elif navire.type in [TypeNavire.CARGO, TypeNavire.HUILIER]:
                    if quai.poste_numero in [11, 14, 18, 19]:
                        preference = -25
                    else:
                        preference = 100       

                contribution += preference
                contribution = max(0.1, contribution)       

                # ========== RÈGLE 3: Vérification conflit agent (conteneurs) ==========
                if navire.type == TypeNavire.CONTENEUR:
                    conflit_agent = False
                    for a in affectations:
                        if a.agent == navire.agent and a.type_navire == 'conteneur':
                            if not (fin <= a.heure_accostage or debut >= a.heure_fin):
                                conflit_agent = True
                                print(f"         ⚠️ Conflit avec fenêtre agent {navire.agent} (chevauchement avec {a.navire_nom})")
                                break
                    if conflit_agent:
                        continue       

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

            if meilleur_quai is not None:
                # Double vérification avant acceptation
                double_check = False
                for a in affectations:
                    if a.quai_id == meilleur_quai.id:
                        a_debut_min = int(round(a.heure_accostage * 60))
                        a_fin_min = int(round(a.heure_fin * 60))
                        if not (int(round(meilleur_fin * 60)) <= a_debut_min or int(round(meilleur_debut * 60)) >= a_fin_min):
                            double_check = True
                            print(f"   ⚠️ Double vérification : conflit avec {a.navire_nom} sur {meilleur_quai.nom}")
                            break
                if double_check:
                    print(f"   ❌ Affectation annulée pour cause de conflit résiduel")
                    continue       

                # Incrémenter les compteurs
                affectations_par_quai[meilleur_quai.id] = affectations_par_quai.get(meilleur_quai.id, 0) + 1
                dernier_fin_par_quai[meilleur_quai.id] = meilleur_fin       

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

                print(f"   ✅ Affecte au {meilleur_quai.nom} (specialite: {meilleur_quai.specialite})")
                print(f"      Debut: {meilleur_debut:.2f}h (buffer début: +{meilleur_buffer_debut:.1f}h)")
                print(f"      Fin: {meilleur_fin:.2f}h (buffer fin: +{meilleur_buffer_fin:.1f}h)")
                print(f"      Attente: {attente:.2f}h")
                print(f"      Duree traitement: {meilleur_traitement:.2f}h")
                print(f"      Temps manœuvre: {temps_manoeuvre:.2f}h")
                print(f"      Score: {meilleur_score:.2f}")
                if meilleur_equipe:
                    print(f"      Équipe: {meilleur_equipe.nom} (shift {self.get_shift_label(meilleur_debut)})")
            else:
                print(f"   ❌ Aucune affectation possible - {meilleur_message if meilleur_message else 'aucun quai compatible'}")       

        return affectations, score_total, attente_totale

    def afficher_resultats(self, affectations: List[AffectationResultat], score_total: float, attente_totale: float):
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
        if filename is None:
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
# =============================================================================
# INTERFACE EN LIGNE DE COMMANDE (pour tests hors Django)
# =============================================================================

def afficher_banniere():
    print("\n" + "="*80)
    print("""
    ======================================================================
    OPTIMISEUR EPB - SYSTEME INTELLIGENT DE GESTION DES ACCOSTAGES
    Entreprise Portuaire de Bejaia (EPB)
    ======================================================================
    """)
    print("="*80)
    print(f"\nVersion 7.4.0 - Avec toutes les regles EPB et gestion des equipements")
    print("-"*70)

def afficher_grille_priorites():
    print("\n" + "="*60)
    print("GRILLE DES PRIORITES EPB")
    print("="*60)
    print(f"{'Priorite':<30} {'Poids':<10} {'Regle'}")
    print("-"*70)
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
    print("="*70)

def afficher_quais(quais):
    print("\n" + "="*80)
    print("QUAIS DISPONIBLES")
    print("="*80)
    print(f"{'ID':<5} {'Nom':<12} {'Longueur':<10} {'Profondeur':<12} {'Specialite':<15} {'Etat'}")
    print("-"*80)
    for q in quais:
        etat = "Libre" if q.libre == 0 else f"Occupe jusqu'a {q.libre:.1f}h"
        print(f"{q.id:<5} {q.nom:<12} {q.longueur:<10.0f}m {q.profondeur:<12.1f}m {q.specialite:<15} {etat}")
    print("="*80)

def afficher_equipements(equipements):
    print("\n" + "="*80)
    print("EQUIPEMENTS DE MANUTENTION")
    print("="*80)
    print(f"{'ID':<3} {'Type':<25} {'Capacite':<12} {'Disponibles'}")
    print("-"*80)
    for e in equipements:
        print(f"{e.id:<3} {e.type:<25} {e.capacite:<6.1f}t       {e.dispo:<3}/{e.nombre:<3}")
    print("="*80)

def main():
    afficher_banniere()
    print("\nChargement des donnees du port...")
    occupations_exemple = {}
    quais = GestionnaireDonnees.charger_quais(occupations_exemple)
    equipements = GestionnaireDonnees.charger_equipements()
    print(f"{len(quais)} quais disponibles")
    print(f"{len(equipements)} types d'equipements")
    
    while True:
        print("\n" + "="*60)
        print("MENU PRINCIPAL")
        print("="*60)
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
            print(f"\nLancement de la planification (saison: {'HIVER' if mois in [11,12,1,2,3] else 'ETE'})...")
            
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
            print("\n" + "="*60)
            print("A PROPOS")
            print("="*60)
            print("Systeme d'optimisation des creneaux d'accostage")
            print("Entreprise Portuaire de Bejaia (EPB)")
            print("\nVersion: 7.4.0")
            print("Auteur: Votre Nom - Master Genie Logiciel")
            print("Date: Avril 2026")
            print("\nBase sur le memoire:")
            print("'Minimisation du Temps de Sejour des Navires dans un Port'")
            print("HADJI Mohammed & MEDJAHEDI Ilham, 2015/2016")
            print("="*60)
        elif choix == "6":
            print("\nAu revoir !")
            break
        else:
            print("Choix invalide")

if __name__ == "__main__":
    main()