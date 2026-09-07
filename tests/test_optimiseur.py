# tests/test_optimiseur.py
import unittest
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from epb_smart.port.optimiseur_epb_pro import OptimiseurEPB_Complet

class TestOptimiseurEPB(unittest.TestCase):
    
    def setUp(self):
        """Initialisation avant chaque test"""
        self.opt = OptimiseurEPB_Complet(mois_actuel=3)  # Mars (hiver)
    
    def test_chargement_donnees(self):
        """Vérifie que les données sont chargées correctement"""
        self.assertGreater(len(self.opt.quais), 0)
        self.assertGreater(len(self.opt.navires), 0)
        self.assertGreater(len(self.opt.equipements), 0)
    
    def test_est_hiver(self):
        """Vérifie la détection de l'hiver"""
        self.assertTrue(self.opt.est_hiver())
        self.opt.mois_actuel = 7  # Juillet
        self.assertFalse(self.opt.est_hiver())
    
    def test_calcul_temps_traitement(self):
        """Vérifie que les temps de traitement sont positifs"""
        navire = self.opt.navires[0]
        quai = self.opt.quais[0]
        temps = self.opt.calculer_temps_traitement(navire, quai, [])
        self.assertGreater(temps, 0)
        
        # Avec équipement
        temps_equip = self.opt.calculer_temps_traitement(navire, quai, [14])  # grue
        self.assertLess(temps_equip, temps)  # Plus rapide avec grue
    
    def test_calcul_priorite_gazier_hiver(self):
        """Vérifie la priorité des gaziers en hiver"""
        # Trouver un gazier
        gazier = None
        for n in self.opt.navires:
            if n["priorites"]["gazier"]:
                gazier = n
                break
        self.assertIsNotNone(gazier)
        
        score = self.opt.calculer_score_priorite(gazier, 5)  # 5h d'attente
        self.assertGreater(score, 100)  # Priorité élevée
        
        # Pénalité si trop d'attente
        score_long = self.opt.calculer_score_priorite(gazier, 20)
        self.assertLess(score_long, score)
    
    def test_verifier_contraintes(self):
        """Vérifie la validation des contraintes"""
        # Solution valide (à adapter)
        solution_valide = [0, 8.0, 0, 0] * len(self.opt.navires)
        # On ne peut pas tester directement car dépend des navires
        # Ce test est à compléter avec des cas concrets
    
    def test_verifier_dispo_equipements(self):
        """Vérifie la disponibilité des équipements"""
        nb_navires = len(self.opt.navires)
        # Solution avec trop d'équipements
        solution_trop = []
        for i in range(nb_navires):
            solution_trop.extend([0, 8.0, 14, 14])  # Même grue utilisée partout
        
        # Doit échouer car la grue 14 n'a qu'un seul exemplaire
        self.assertFalse(self.opt.verifier_dispo_equipements(solution_trop))

if __name__ == '__main__':
    unittest.main()