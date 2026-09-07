# port/ml_model.py
import os
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import LabelEncoder
import joblib
from django.conf import settings

class DureeTraitementModel:
    def __init__(self):
        self.model = None
        self.encoders = {}
        self.model_path = os.path.join(settings.BASE_DIR, 'port', 'ml_duree.joblib')
        self.load()

    def entrainer(self, historique_queryset):
        data = []
        for op in historique_queryset:
            data.append({
                'navire_type': op.navire_type,
                'volume': op.volume,
                'duree_estimee': op.duree_estimee,
                'duree_reelle': op.duree_reelle,
            })
        df = pd.DataFrame(data)
        if len(df) < 30:
            print(f"⚠️ Données insuffisantes : {len(df)} enregistrements")
            return False

        le = LabelEncoder()
        df['type_enc'] = le.fit_transform(df['navire_type'])
        self.encoders['type'] = le

        X = df[['type_enc', 'volume', 'duree_estimee']]
        y = df['duree_reelle']
        self.model = RandomForestRegressor(n_estimators=100, random_state=42)
        self.model.fit(X, y)

        joblib.dump({'model': self.model, 'encoders': self.encoders}, self.model_path)
        print(f"✅ Modèle ML entraîné sur {len(df)} échantillons")
        return True

    def predire(self, navire, duree_estimee_classique):
        if self.model is None:
            return None
        try:
            # Compatible Django et dataclass
            navire_type = navire.type.value if hasattr(navire.type, 'value') else navire.type
            volume = getattr(navire, 'marchandise_volume', None) or \
                     (navire.marchandise.volume if hasattr(navire, 'marchandise') else 0)
            
            type_enc = self.encoders['type'].transform([navire_type])[0]
            X = [[type_enc, volume, duree_estimee_classique]]
            return max(0.5, self.model.predict(X)[0])
        except Exception:
            return None

    def load(self):
        if os.path.exists(self.model_path):
            obj = joblib.load(self.model_path)
            self.model = obj['model']
            self.encoders = obj['encoders']
            print("✅ Modèle ML chargé")
        else:
            print("ℹ️ Aucun modèle ML. Lancez 'python manage.py train_ml'")