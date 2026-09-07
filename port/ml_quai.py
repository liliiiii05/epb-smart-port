import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
import joblib
import os
from django.conf import settings

class QuaiChoiceModel:
    def __init__(self):
        self.model = None
        self.encoders = {}
        self.model_path = os.path.join(settings.BASE_DIR, 'port', 'ml_quai.joblib')
        self.load()

    def entrainer(self, historique_queryset):
        data = []
        for a in historique_queryset:
            data.append({
                'type_navire': a.type_navire,
                'volume': a.volume,
                'longueur': a.longueur,
                'tirant': a.tirant,
                'agent': a.agent,
                'entite': a.entite,
                'shift': a.shift_debut,
                'quai_id': a.quai.id,
            })
        df = pd.DataFrame(data)
        if len(df) < 30:
            print(f"⚠️ Données insuffisantes : {len(df)} enregistrements")
            return False

        le_type = LabelEncoder()
        le_agent = LabelEncoder()
        le_entite = LabelEncoder()
        le_shift = LabelEncoder()
        le_quai = LabelEncoder()

        df['type_enc'] = le_type.fit_transform(df['type_navire'])
        df['agent_enc'] = le_agent.fit_transform(df['agent'])
        df['entite_enc'] = le_entite.fit_transform(df['entite'])
        df['shift_enc'] = le_shift.fit_transform(df['shift'])
        df['quai_enc'] = le_quai.fit_transform(df['quai_id'])

        self.encoders = {
            'type': le_type, 'agent': le_agent, 'entite': le_entite,
            'shift': le_shift, 'quai': le_quai
        }

        X = df[['type_enc', 'volume', 'longueur', 'tirant', 'agent_enc', 'entite_enc', 'shift_enc']]
        y = df['quai_enc']
        self.model = RandomForestClassifier(n_estimators=100, random_state=42)
        self.model.fit(X, y)
        joblib.dump({'model': self.model, 'encoders': self.encoders}, self.model_path)
        print(f"✅ Modèle de choix de quai entraîné sur {len(df)} échantillons")
        return True

    def predire_quai(self, type_navire, volume, longueur, tirant, agent, entite, shift):
        if self.model is None:
            return None
        try:
            type_enc = self.encoders['type'].transform([type_navire])[0]
            agent_enc = self.encoders['agent'].transform([agent])[0]
            entite_enc = self.encoders['entite'].transform([entite])[0]
            shift_enc = self.encoders['shift'].transform([shift])[0]
            X = [[type_enc, volume, longueur, tirant, agent_enc, entite_enc, shift_enc]]
            quai_enc = self.model.predict(X)[0]
            # Retrouver l'ID du quai à partir de l'encodeur
            quai_id = self.encoders['quai'].inverse_transform([quai_enc])[0]
            return quai_id
        except Exception:
            return None

    def load(self):
        if os.path.exists(self.model_path):
            obj = joblib.load(self.model_path)
            self.model = obj['model']
            self.encoders = obj['encoders']
            print("✅ Modèle de choix de quai chargé")
        else:
            print("ℹ️ Aucun modèle de choix de quai. Lancez 'python manage.py train_quai'")