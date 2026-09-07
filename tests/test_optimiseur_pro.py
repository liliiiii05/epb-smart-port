#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests unitaires pour l'optimiseur EPB
"""

import unittest
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from epb_smart.port.optimiseur_epb_pro import (
    GestionnaireDonnees, OptimiseurEPB, ModeleOptimisation,
    TypeNavire, Priorite, Saison
)

class TestGestionnaireDonnees(unittest.TestCase):
    """Tests du gestionnaire de données"""
    
    def test_chargement_quais(self):
        """Vérifie le chargement des quais"""
        quais = GestionnaireDonnees.charger_quais()
        self.assertEqual(len(quais), 16)
        self.assertTrue(any(q.id == 24 for q in quais))  # Quai gazier
    
    def test_chargement_equipements(self):
        """Vérifie le chargement des équipements"""
        equip = GestionnaireDonnees.charger_equipements()
        self.assertEqual(len(equip), 17)
        self.assertTrue(any(e.id == 14 for e in equip))  # Grue Gottwald
    
    def test_creation_navires(self):
        """Vérifie la création de navires de test"""
        navires = GestionnaireDonnees.creer_navires_test(5)
        self.assertEqual(len(navires), 5)
        for n in navires:
            self.assertIsNotNone(n.type)
            self.assertGreater(n.longueur, 0)

class TestModeleOptimisation(unittest.TestCase):
    """Tests du modèle mathématique"""
    
    def setUp(self):
        self.quais = GestionnaireDonnees.charger_quais()
        self.equip = GestionnaireDonnees.charger_equipements()
        self.navires = GestionnaireDonnees.creer_navires_test(3)
        self.modele = ModeleOptimisation(self.quais, self.navires, self.equip, mois=3)
    
    def test_est_hiver(self):
        """Vérifie la détection de l'hiver"""
        self.assertTrue(self.modele.est_hiver())
        modele_ete = ModeleOptimisation(self.quais, self.navires, self.equip, mois=7)
        self.assertFalse(modele_ete.est_hiver())
    
    def test_compatibilite_quai(self):
        """Vérifie la compatibilité navire-quai"""
        navire = self.navires[0]
        quai = self.quais[0]
        compatible, _ = self.modele.verifier_compatibilite_quai(navire, quai)
        self.assertIsInstance(compatible, bool)
    
    def test_calcul_temps_traitement(self):
        """Vérifie le calcul des temps de traitement"""
        navire = self.navires[0]
        quai = self.quais[0]
        temps = self.modele.calculer_temps_traitement(navire, quai, [])
        self.assertGreater(temps, 0)
        self.assertLess(temps, 100)

class TestOptimiseur(unittest.TestCase):
    """Tests de l'optimiseur principal"""
    
    def setUp(self):
        self.quais = GestionnaireDonnees.charger_quais()
        self.equip = GestionnaireDonnees.charger_equipements()
        self.navires = GestionnaireDonnees.creer_navires_test(3)
        self.opt = OptimiseurEPB(self.quais, self.navires, self.equip)
    
    def test_optimisation(self):
        """Vérifie que l'optimisation produit un résultat"""
        solution, score, stats = self.opt.optimiser()
        self.assertIsNotNone(solution)
        self.assertGreater(score, -10000)
        self.assertIn('temps_calcul', stats)
    
    def test_decodage_solution(self):
        """Vérifie le décodage des solutions"""
        solution = np.zeros(len(self.navires) * 4)
        affectations = self.opt.decoder_solution(solution)
        self.assertEqual(len(affectations), len(self.navires))
    
    def test_generation_rapport(self):
        """Vérifie la génération de rapport"""
        solution = np.zeros(len(self.navires) * 4)
        rapport = self.opt.generer_rapport(solution, 100.0, {'temps_calcul': 1.0})
        self.assertEqual(rapport.nb_navires, len(self.navires))
        self.assertEqual(rapport.score_total, 100.0)

if __name__ == '__main__':
    unittest.main()