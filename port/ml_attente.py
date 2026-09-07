#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Modèle de prédiction du temps d'attente des navires en rade.
Basé sur l'historique des affectations et les conditions météo.
"""

import joblib
import numpy as np
import os
from datetime import datetime
from django.conf import settings

class AttentePredictor:
    def __init__(self):
        self.model = None
        # Chemin absolu avec settings
        model_path = os.path.join(settings.BASE_DIR, 'models', 'attente_model.pkl')
        try:
            if os.path.exists(model_path):
                self.model = joblib.load(model_path)
                print("✅ Modèle d'attente chargé")
            else:
                print(f"ℹ️ Modèle d'attente non trouvé à {model_path}")
        except Exception as e:
            print(f"⚠️ Erreur chargement modèle: {e}")
    
    def predire_attente(self, navire, quai=None, meteo=None):
        """
        Prédit le temps d'attente en heures pour un navire.
        
        Args:
            navire: objet Navire (Django ou dataclass)
            quai: objet Quai (optionnel)
            meteo: objet Meteo (optionnel)
        
        Returns:
            float: temps d'attente en heures
        """
        # 1. Essayer le modèle ML si disponible
        if self.model is not None:
            try:
                # Préparer les features
                features = self._preparer_features(navire, quai, meteo)
                attente = self.model.predict([features])[0]
                return max(0, round(attente, 1))  # Jamais négatif
            except Exception as e:
                print(f"⚠️ Erreur prédiction ML: {e}")
        
        # 2. Fallback : règles métier
        return self._predire_par_regle(navire, quai, meteo)
    
    def _preparer_features(self, navire, quai, meteo):
        """
        Prépare les features pour le modèle ML.
        À adapter selon vos colonnes d'entraînement.
        """
        # Récupération des attributs (compatible Django et dataclass)
        type_navire = self._get_type_navire(navire)
        volume = self._get_volume(navire)
        longueur = self._get_longueur(navire)
        tirant = self._get_tirant(navire)
        agent = self._get_agent(navire)
        specialite = quai.specialite if quai else 'general'
        
        return [
            self._encoder_type(type_navire),
            volume,
            longueur,
            tirant,
            self._encoder_agent(agent),
            self._encoder_specialite(specialite),
            datetime.now().hour + datetime.now().minute / 60.0,
            1 if meteo and getattr(meteo, 'pluie', False) else 0,
            getattr(meteo, 'vent_force', 0) if meteo else 0,
            datetime.now().weekday()
        ]
    
    def _get_type_navire(self, navire):
        if hasattr(navire, 'type'):
            if hasattr(navire.type, 'value'):
                return navire.type.value
            return navire.type
        return getattr(navire, 'type', 'cargo')
    
    def _get_volume(self, navire):
        if hasattr(navire, 'marchandise_volume'):
            return navire.marchandise_volume
        elif hasattr(navire, 'marchandise') and hasattr(navire.marchandise, 'volume'):
            return navire.marchandise.volume
        return 0
    
    def _get_longueur(self, navire):
        return getattr(navire, 'longueur', 100)
    
    def _get_tirant(self, navire):
        return getattr(navire, 'tirant', 8)
    
    def _get_agent(self, navire):
        return getattr(navire, 'agent', 'Inconnu')
    
    def _encoder_type(self, type_navire):
        """Encoder simple pour le type de navire"""
        mapping = {
            'cerealier': 0, 'cargo': 1, 'conteneur': 2, 'gazier': 3,
            'petrolier': 4, 'ferry': 5, 'essence': 6, 'huilier': 7,
            'betail': 8, 'frigorifique': 9, 'roulier': 10, 'chimiquier': 11
        }
        return mapping.get(type_navire, 1)
    
    def _encoder_agent(self, agent):
        """Encoder simple pour l'agent"""
        mapping = {
            'MSC': 0, 'CMA CGM': 1, 'MAERSK': 2, 'Inconnu': 3
        }
        for key, val in mapping.items():
            if key in agent.upper():
                return val
        return 3
    
    def _encoder_specialite(self, specialite):
        """Encoder simple pour la spécialité du quai"""
        mapping = {
            'cerealier': 0, 'general': 1, 'grand': 2, 'conteneurs': 3,
            'gazier': 4, 'petrolier': 5, 'ferry': 6, 'huilier': 7
        }
        return mapping.get(specialite, 1)
    
    def _predire_par_regle(self, navire, quai=None, meteo=None):
        """
        Règles métier (fallback) quand le modèle ML n'est pas disponible.
        """
        type_navire = self._get_type_navire(navire)
        volume = self._get_volume(navire)
        agent = self._get_agent(navire)
        
        # Règles selon type de navire
        if type_navire == 'cerealier':
            if volume > 50000:
                return 24.0  # 24h d'attente pour gros céréalier
            return 12.0
        elif type_navire == 'gazier':
            return 8.0
        elif type_navire == 'conteneur':
            if 'MSC' in agent.upper() or 'CMA' in agent.upper():
                return 6.0  # Contrats prioritaires
            return 12.0
        elif type_navire == 'cargo':
            return 12.0
        elif type_navire == 'ferry':
            return 2.0  # Ferries prioritaires
        elif type_navire == 'petrolier':
            return 8.0
        elif type_navire == 'essence':
            return 6.0
        elif type_navire == 'huilier':
            return 10.0
        else:
            return 6.0  # Valeur par défaut