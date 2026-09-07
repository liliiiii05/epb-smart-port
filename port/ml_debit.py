import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import LabelEncoder
import joblib
import os
from django.conf import settings

class DebitModel:
    def __init__(self):
        self.model = None
        self.encoders = {}
        self.model_path = os.path.join(settings.BASE_DIR, 'port', 'ml_debit.joblib')
        self.load()

    def entrainer(self, historique_queryset):
        data = []
        for op in historique_queryset:
            if op.debit_reel <= 0:
                continue
            data.append({
                'navire_type': op.navire_type,
                'volume': op.volume,
                'nb_equipes': op.nb_equipes,
                'shift': op.shift or 'inconnu',
                'debit_reel': op.debit_reel,
            })
        df = pd.DataFrame(data)
        if len(df) < 30:
            print(f"⚠️ Données insuffisantes : {len(df)} enregistrements")
            return False

        le_type = LabelEncoder()
        le_shift = LabelEncoder()
        df['type_enc'] = le_type.fit_transform(df['navire_type'])
        df['shift_enc'] = le_shift.fit_transform(df['shift'])
        self.encoders['type'] = le_type
        self.encoders['shift'] = le_shift

        X = df[['type_enc', 'volume', 'nb_equipes', 'shift_enc']]
        y = df['debit_reel']
        self.model = RandomForestRegressor(n_estimators=100, random_state=42)
        self.model.fit(X, y)
        joblib.dump({'model': self.model, 'encoders': self.encoders}, self.model_path)
        print(f"✅ Modèle de débit entraîné sur {len(df)} échantillons")
        return True

    def predire_debit(self, navire_type, volume, nb_equipes=1, shift='matin'):
        if self.model is None:
            return None
        try:
            type_enc = self.encoders['type'].transform([navire_type])[0]
            shift_enc = self.encoders['shift'].transform([shift])[0]
            X = [[type_enc, volume, nb_equipes, shift_enc]]
            return max(0.1, self.model.predict(X)[0])
        except Exception:
            return None

    def load(self):
        if os.path.exists(self.model_path):
            obj = joblib.load(self.model_path)
            self.model = obj['model']
            self.encoders = obj['encoders']
            print("✅ Modèle de débit chargé")
        else:
            print("ℹ️ Aucun modèle de débit. Lancez 'python manage.py train_debit'")