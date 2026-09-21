# port/ml_attente.py
"""
Modèle de prédiction du temps d'attente des navires.

Utilise un Random Forest entraîné sur l'historique des escales archivées.
Fallback par règles métier si le modèle n'est pas encore entraîné.
"""
import os
import joblib
import logging
from datetime import datetime
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

# Chemin du modèle
MODEL_DIR = Path(settings.BASE_DIR) / 'port' / 'ml_models'
MODEL_DIR.mkdir(parents=True, exist_ok=True)
MODEL_PATH = MODEL_DIR / 'attente_predictor.joblib'


class AttentePredictor:
    """
    Prédicteur de durée d'attente basé sur Random Forest.
    
    Utilise l'historique des escales archivées (archive=True) pour :
    - Entraîner un modèle Random Forest
    - Prédire la durée d'attente des nouvelles escales
    """
    
    def __init__(self):
        self.model = None
        self.encoders = {}
        self.feature_names = [
            'type_navire_encoded',
            'volume',
            'longueur',
            'tirant',
            'agent_encoded',
            'entite_encoded',
            'shift_encoded',
            'meteo_pluie',
            'meteo_vent_force',
            'mois',
            'jour_semaine',
            'heure_arrivee',
            'quai_id',
            'duree_escale',
        ]
        self.charger()
    
    # =========================================================================
    # CHARGEMENT ET SAUVEGARDE
    # =========================================================================
    
    def charger(self):
        """Charge le modèle s'il existe."""
        if MODEL_PATH.exists():
            try:
                data = joblib.load(MODEL_PATH)
                self.model = data.get('model')
                self.encoders = data.get('encoders', {})
                logger.info(f"Modele charge depuis {MODEL_PATH}")
                print(f"Modele d'attente charge ({MODEL_PATH.name})")
            except Exception as e:
                logger.error(f"Erreur chargement modele : {e}")
                print(f"Erreur chargement modele : {e}")
                self.model = None
        else:
            logger.info("Aucun modele entraine (a creer avec entrainer())")
            print("Aucun modele entraine (utilise regles metier)")
    
    def sauvegarder(self):
        """Sauvegarde le modèle et les encodeurs."""
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            'model': self.model,
            'encoders': self.encoders,
            'feature_names': self.feature_names,
        }, MODEL_PATH)
        logger.info(f"Modele sauvegarde : {MODEL_PATH}")
        print(f"Modele sauvegarde : {MODEL_PATH}")
    
    # =========================================================================
    # ENTRAINEMENT
    # =========================================================================
    
    def entrainer(self, df=None, test_size=0.2):
        """
        Entraîne le modèle Random Forest sur les escales archivées.
        
        Args:
            df: DataFrame (si None, utilise construire_dataset_attentes())
            test_size: Proportion du test set
        
        Returns:
            dict: métriques d'évaluation
        """
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import LabelEncoder
        from sklearn.metrics import mean_absolute_error, r2_score
        
        # 1. Construire le dataset si nécessaire
        if df is None:
            from port.utils_escales import construire_dataset_attentes
            df = construire_dataset_attentes()
        
        if df is None or df.empty:
            msg = "Dataset vide - aucun entrainement possible"
            logger.warning(msg)
            print(msg)
            return {'error': 'dataset_vide', 'size': 0}
        
        if len(df) < 5:
            msg = f"Dataset trop petit ({len(df)} exemples) - entrainement annule"
            logger.warning(msg)
            print(msg)
            return {'error': 'dataset_trop_petit', 'size': len(df)}
        
        print(f"Entrainement sur {len(df)} escales...")
        
        # 2. Encodage des variables catégorielles
        df_encoded = df.copy()
        cat_cols = ['type_navire', 'agent', 'entite', 'shift']
        
        for col in cat_cols:
            if col not in df_encoded.columns:
                continue
            le = LabelEncoder()
            df_encoded[col + '_encoded'] = le.fit_transform(
                df_encoded[col].astype(str)
            )
            self.encoders[col] = le
        
        # 3. Sélection des features
        feature_cols = [
            'type_navire_encoded', 'volume', 'longueur', 'tirant',
            'agent_encoded', 'entite_encoded', 'shift_encoded',
            'meteo_pluie', 'meteo_vent_force', 'mois',
            'jour_semaine', 'heure_arrivee', 'quai_id', 'duree_escale',
        ]
        feature_cols = [c for c in feature_cols if c in df_encoded.columns]
        
        X = df_encoded[feature_cols]
        y = df_encoded['duree_attente']
        
        # 4. Split train/test
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42
        )
        
        # 5. Entraînement Random Forest
        self.model = RandomForestRegressor(
            n_estimators=100,
            max_depth=15,
            min_samples_split=5,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1
        )
        self.model.fit(X_train, y_train)
        
        # 6. Évaluation
        y_pred = self.model.predict(X_test)
        mae = mean_absolute_error(y_test, y_pred)
        r2 = r2_score(y_test, y_pred)
        
        # 7. Sauvegarde
        self.sauvegarder()
        
        metrics = {
            'nb_exemples': len(df),
            'nb_train': len(X_train),
            'nb_test': len(X_test),
            'mae': round(mae, 2),
            'r2': round(r2, 3),
        }
        
        print(f"Entrainement termine : MAE={mae:.2f}h, R2={r2:.3f}")
        return metrics
    
    # =========================================================================
    # PREDICTION
    # =========================================================================
    
    def predire_attente(self, navire, quai=None, meteo=None):
        """
        Prédit la durée d'attente pour un navire.
        
        Args:
            navire: objet Navire (Django)
            quai: objet Quai (optionnel)
            meteo: objet Meteo (optionnel)
        
        Returns:
            float: durée d'attente en heures
        """
        # 1. Essayer le modèle ML
        if self.model is not None:
            try:
                X = self._preparer_features(navire, quai, meteo)
                prediction = self.model.predict(X)[0]
                attente = max(0.0, float(prediction))
                logger.info(f"Prediction IA pour {navire.nom} : {attente:.1f}h")
                return round(attente, 1)
            except Exception as e:
                logger.error(f"Erreur prediction IA : {e}")
        
        # 2. Fallback : règles métier
        return self._predire_par_regles(navire, quai, meteo)
    
    def _preparer_features(self, navire, quai=None, meteo=None):
        """Prépare les features pour le modèle."""
        import pandas as pd
        from django.utils import timezone
        
        # Récupérer l'escale active
        escale = getattr(navire, 'escale_active', None)
        
        now = timezone.now()
        
        # Features de base
        features_dict = {
            'type_navire': self._get_type_navire(navire),
            'volume': self._get_volume(navire),
            'longueur': getattr(navire, 'longueur', 0) or 0,
            'tirant': getattr(navire, 'tirant', 0) or 0,
            'agent': getattr(navire, 'agent', '') or '',
            'entite': getattr(navire, 'entite', '') or '',
            'shift': self._get_shift_actuel(now),
            'meteo_pluie': 1 if (meteo and getattr(meteo, 'pluie', False)) else 0,
            'meteo_vent_force': getattr(meteo, 'vent_force', 0) if meteo else 0,
            'mois': now.month,
            'jour_semaine': now.weekday(),
            'heure_arrivee': now.hour,
            'quai_id': quai.id if quai else 0,
            'duree_escale': escale.duree_reelle if escale else 0,
        }
        
        # Encoder les variables catégorielles
        row = {}
        for col in ['type_navire', 'agent', 'entite', 'shift']:
            encoded_col = col + '_encoded'
            if col in self.encoders:
                le = self.encoders[col]
                val = str(features_dict.get(col, ''))
                try:
                    row[encoded_col] = le.transform([val])[0]
                except ValueError:
                    # Valeur inconnue : prendre la première classe
                    row[encoded_col] = 0
            else:
                row[encoded_col] = 0
        
        # Ajouter les features numériques
        for col in ['volume', 'longueur', 'tirant', 'meteo_pluie',
                    'meteo_vent_force', 'mois', 'jour_semaine',
                    'heure_arrivee', 'quai_id', 'duree_escale']:
            row[col] = features_dict.get(col, 0)
        
        # Créer le DataFrame avec les bonnes colonnes
        X = pd.DataFrame([row])
        
        # S'assurer que toutes les features attendues sont présentes
        for col in self.feature_names:
            if col not in X.columns:
                X[col] = 0
        
        return X[self.feature_names]
    
    # =========================================================================
    # UTILITAIRES
    # =========================================================================
    
    def _get_type_navire(self, navire):
        """Retourne le type du navire (string)."""
        if hasattr(navire, 'type'):
            if hasattr(navire.type, 'value'):
                return navire.type.value
            return navire.type
        return 'cargo'
    
    def _get_volume(self, navire):
        """Retourne le volume de marchandise."""
        if hasattr(navire, 'marchandise_volume'):
            return navire.marchandise_volume or 0
        elif hasattr(navire, 'marchandise') and hasattr(navire.marchandise, 'volume'):
            return navire.marchandise.volume or 0
        return 0
    
    def _get_shift_actuel(self, dt):
        """Retourne le shift actuel."""
        h = dt.hour + dt.minute / 60.0
        if 7 <= h < 13:
            return 'matin'
        elif 13 <= h < 19:
            return 'soir'
        elif 19 <= h < 24:
            return 'nuit'
        else:
            return 'double_nuit'
    
    # =========================================================================
    # FALLBACK : REGLES METIER
    # =========================================================================
    
    def _predire_par_regles(self, navire, quai=None, meteo=None):
        """
        Règles métier quand le modèle ML n'est pas disponible.
        """
        type_navire = self._get_type_navire(navire)
        volume = self._get_volume(navire)
        agent = getattr(navire, 'agent', '') or ''
        
        # Règles selon type
        if type_navire == 'cerealier':
            base = 24.0 if volume > 50000 else 12.0
        elif type_navire == 'gazier':
            base = 8.0
        elif type_navire == 'conteneur':
            if 'MSC' in agent.upper() or 'CMA' in agent.upper():
                base = 6.0
            else:
                base = 12.0
        elif type_navire == 'cargo':
            base = 12.0
        elif type_navire == 'ferry':
            base = 2.0
        elif type_navire == 'petrolier':
            base = 8.0
        elif type_navire == 'essence':
            base = 6.0
        elif type_navire == 'huilier':
            base = 10.0
        else:
            base = 6.0
        
        # Ajustements météo
        if meteo:
            if getattr(meteo, 'pluie', False):
                base *= 1.3
            vent = getattr(meteo, 'vent_force', 0)
            if vent >= 8:
                base *= 1.2
        
        return round(base, 1)
    
    # =========================================================================
    # STATISTIQUES
    # =========================================================================
    
    def est_entraine(self):
        """Retourne True si le modèle est chargé."""
        return self.model is not None
    
    def info_modele(self):
        """Retourne des infos sur le modèle."""
        if self.model is None:
            return {
                'entraine': False,
                'message': 'Modele non entraine (utilise regles metier)',
            }
        
        return {
            'entraine': True,
            'chemin': str(MODEL_PATH),
            'n_estimators': getattr(self.model, 'n_estimators', 'N/A'),
            'features': self.feature_names,
        }