#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script de test pour observer l'influence du buffer sur le choix du quai.
Utilise la même logique que l'optimiseur EPB mais avec un seul navire et plusieurs quais.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import random
from dataclasses import dataclass
from typing import List, Tuple
from datetime import datetime
from enum import Enum

# =============================================================================
# Définitions minimales (copiées depuis optimiseur_epb_pro.py)
# =============================================================================

class TypeNavire(Enum):
    CARGO = "cargo"
    # Ajoutez d'autres types si nécessaire

@dataclass
class Quai:
    id: int
    nom: str
    longueur: float
    profondeur: float
    specialite: str
    libre: float = 0.0
    performance: float = 1.0

@dataclass
class Marchandise:
    type: str
    volume: float
    dangereux: bool = False
    frigo: bool = False

@dataclass
class EquipementPropre:
    a_grue_bord: bool = False
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

@dataclass
class Equipement:
    id: int
    type: str
    capacite: float
    nombre: int
    dispo: int = 0
    en_panne: bool = False
    temps_reparation: float = 2.0

# =============================================================================
# Modèle de calcul simplifié (pour le test)
# =============================================================================
class ModeleCalcul:
    def __init__(self, incertitude=False, amplitude=0.0):
        self.incertitude = incertitude
        self.amplitude = amplitude

    def calculer_temps_traitement(self, navire: Navire, quai: Quai) -> float:
        volume = navire.marchandise.volume
        taux_base = 150  # tonnes/heure (pour cargo)
        coeff_quai = quai.performance
        taux_effectif = taux_base * coeff_quai
        if volume > 0:
            duree_estimee = volume / taux_effectif
        else:
            duree_estimee = 1.0
        if self.incertitude:
            var = self.amplitude
            variation = random.uniform(1 - var, 1 + var)
            duree_simulee = duree_estimee * variation
            duree_simulee = max(0.5, duree_simulee)
            return duree_simulee
        else:
            return duree_estimee

    def calculer_attente(self, navire: Navire, debut: float) -> float:
        return max(0, debut - navire.arrivee)

    def calculer_score_contribution(self, navire: Navire, debut: float, traitement: float, buffer_debut: float, buffer_fin: float, penalite_coeff=5.0, seuil_buffer=2.0) -> float:
        attente = self.calculer_attente(navire, debut)
        penalite = 0.0
        if buffer_debut < seuil_buffer:
            penalite += (seuil_buffer - buffer_debut) * penalite_coeff
        if buffer_fin < seuil_buffer:
            penalite += (seuil_buffer - buffer_fin) * penalite_coeff
        return traitement + attente + penalite

# =============================================================================
# Planificateur minimal pour le test
# =============================================================================
class TestPlanificateur:
    def __init__(self, quais: List[Quai], equipements: List[Equipement], incertitude=False, amplitude=0.0, pourcentage_buffer=0.15, penalite_coeff=5.0, seuil_buffer=2.0):
        self.quais = quais
        self.equipements = equipements
        self.modele = ModeleCalcul(incertitude, amplitude)
        self.pourcentage_buffer = pourcentage_buffer
        self.penalite_coeff = penalite_coeff
        self.seuil_buffer = seuil_buffer
        self.incertitude = incertitude
        self.amplitude = amplitude

    def planifier(self, navire: Navire) -> Tuple[Quai, float, float, float, float, float]:
        meilleur_quai = None
        meilleur_score = float('inf')
        meilleur_debut = None
        meilleur_fin = None
        meilleur_traitement = None
        meilleur_buffer_debut = None
        meilleur_buffer_fin = None

        for quai in self.quais:
            # Vérification simplifiée : le quai doit être compatible (longueur, tirant d'eau)
            if navire.longueur > quai.longueur or navire.tirant > quai.profondeur:
                continue
            debut = max(navire.arrivee, quai.libre)
            traitement = self.modele.calculer_temps_traitement(navire, quai)
            fin = debut + traitement
            buffer_debut = traitement * self.pourcentage_buffer
            buffer_fin = traitement * self.pourcentage_buffer
            score = self.modele.calculer_score_contribution(navire, debut, traitement, buffer_debut, buffer_fin,
                                                           self.penalite_coeff, self.seuil_buffer)
            if score < meilleur_score:
                meilleur_score = score
                meilleur_quai = quai
                meilleur_debut = debut
                meilleur_fin = fin
                meilleur_traitement = traitement
                meilleur_buffer_debut = buffer_debut
                meilleur_buffer_fin = buffer_fin

        return meilleur_quai, meilleur_debut, meilleur_fin, meilleur_traitement, meilleur_buffer_debut, meilleur_buffer_fin

# =============================================================================
# Fonction de test
# =============================================================================
def tester_buffer():
    print("="*80)
    print("TEST DE L'INFLUENCE DU BUFFER SUR LE CHOIX DU QUAI")
    print("="*80)

    # Créer un navire cargo simple
    navire = Navire(
        id=1,
        nom="NAVIRE_TEST",
        type=TypeNavire.CARGO,
        longueur=120,
        tirant=7,
        arrivee=0.0,  # arrive à 0h
        priorites=PrioritesNavire(),
        marchandise=Marchandise(type="Bois", volume=3000),  # 3000 tonnes
        equipement_propre=EquipementPropre(),
        priorite_calculee=0
    )

    # Créer plusieurs quais compatibles avec des performances différentes et des heures de libération différentes
    quais = [
        Quai(id=1, nom="Quai A", longueur=150, profondeur=8, specialite="general", libre=0.0, performance=1.0),
        Quai(id=2, nom="Quai B", longueur=150, profondeur=8, specialite="general", libre=0.0, performance=1.0),
        Quai(id=3, nom="Quai C", longueur=150, profondeur=8, specialite="general", libre=0.0, performance=1.0),
    ]
    # Donner des heures de libération différentes pour simuler des disponibilités décalées
    quais[0].libre = 0.0
    quais[1].libre = 5.0   # libre à 5h
    quais[2].libre = 10.0  # libre à 10h

    equipements = []  # pas d'équipements pour ce test

    print("\nNavire : arrivee à 0h, volume 3000t, taux manutention 150t/h -> durée estimée 20h")
    print("Quais : tous compatibles, mais libres à 0h, 5h et 10h respectivement.\n")

    # Tester différents pourcentages de buffer
    for buffer_pct in [0, 0.15, 0.30, 0.50]:
        print(f"\n--- Buffer = {buffer_pct*100:.0f}% ---")
        planif = TestPlanificateur(quais, equipements, incertitude=False, amplitude=0.0,
                                   pourcentage_buffer=buffer_pct, penalite_coeff=5.0, seuil_buffer=2.0)
        quai, debut, fin, traitement, buf_debut, buf_fin = planif.planifier(navire)
        if quai:
            print(f"  Quai choisi : {quai.nom} (libre à {quai.libre:.1f}h)")
            print(f"  Début : {debut:.1f}h, Fin : {fin:.1f}h, Traitement : {traitement:.1f}h")
            print(f"  Buffer début : {buf_debut:.1f}h, Buffer fin : {buf_fin:.1f}h")
            # Calcul du score manuellement pour voir la pénalité
            attente = debut - navire.arrivee
            penalite = 0
            seuil = 2.0
            if buf_debut < seuil:
                penalite += (seuil - buf_debut) * 5.0
            if buf_fin < seuil:
                penalite += (seuil - buf_fin) * 5.0
            score = traitement + attente + penalite
            print(f"  Score (avec pénalité) : {score:.2f} (traitement {traitement:.1f} + attente {attente:.1f} + penalite {penalite:.1f})")
        else:
            print("  Aucun quai compatible")

    print("\n" + "="*80)
    print("Si le quai choisi change avec le buffer, l'influence est visible.")
    print("Normalement, avec buffer=0%, le quai libre le plus tôt (0h) est choisi.")
    print("Avec buffer élevé, le quai offrant plus de marge (libre plus tard mais buffer plus grand) peut être préféré.")
    print("="*80)

if __name__ == "__main__":
    tester_buffer()