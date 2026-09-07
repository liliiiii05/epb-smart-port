import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import LabelEncoder
import joblib
import os
from django.conf import settings

class DebitShiftModel:
    def __init__(self):
        self.model = None
        self.encoders = {}
        self.model_path = os.path.join(settings.BASE_DIR, 'port', 'ml_debit_shift.joblib')
        self.load()

    def entrainer(self, historique_queryset):
        data = []
        for op in historique_queryset:
            if op.debit_shift <= 0:
                continue
            data.append({
                'navire_type': op.navire_type,
                'shift': op.shift,
                'nb_equipements': op.nb_equipements_utilises,
                'attente': op.attente_shift,
                'debit_shift': op.debit_shift,
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

        X = df[['type_enc', 'shift_enc', 'nb_equipements', 'attente']]
        y = df['debit_shift']
        self.model = RandomForestRegressor(n_estimators=100, random_state=42)
        self.model.fit(X, y)
        joblib.dump({'model': self.model, 'encoders': self.encoders}, self.model_path)
        print(f"✅ Modèle de débit par shift entraîné sur {len(df)} échantillons")
        return True

    def predire_debit_shift(self, navire_type, shift, nb_equipements, attente):
        if self.model is None:
            return None
        try:
            type_enc = self.encoders['type'].transform([navire_type])[0]
            shift_enc = self.encoders['shift'].transform([shift])[0]
            X = [[type_enc, shift_enc, nb_equipements, attente]]
            return max(0.1, self.model.predict(X)[0])
        except Exception:
            return None

    def load(self):
        if os.path.exists(self.model_path):
            obj = joblib.load(self.model_path)
            self.model = obj['model']
            self.encoders = obj['encoders']
            print("✅ Modèle de débit par shift chargé")
        else:
            print("ℹ️ Aucun modèle de débit par shift. Lancez 'python manage.py train_debit_shift'")