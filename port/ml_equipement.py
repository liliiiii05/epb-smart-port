import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
import joblib
from django.conf import settings
import os

class EquipementChoiceModel:
    def __init__(self):
        self.model = None
        self.encoders = {}
        self.model_path = os.path.join(settings.BASE_DIR, 'port', 'ml_equipement.joblib')
        self.load()

    def entrainer(self, utilisations_queryset):
        data = []
        for u in utilisations_queryset:
            data.append({
                'navire_type': u.navire.type,
                'equipement_type': u.equipement_type,
                'unite_index': u.unite_index,
                'quai_specialite': u.quai.specialite if u.quai else '',
                'heure_debut': u.debut.hour,
                'jour_semaine': u.debut.weekday(),
                'conflit': u.conflit,
                'attente': u.attente_navire,
            })
        df = pd.DataFrame(data)
        if len(df) < 30:
            print(f"⚠️ Données insuffisantes : {len(df)} enregistrements")
            return False

        # Encodage
        le_type = LabelEncoder()
        le_eq = LabelEncoder()
        le_quai = LabelEncoder()

        df['navire_type_enc'] = le_type.fit_transform(df['navire_type'])
        df['equipement_type_enc'] = le_eq.fit_transform(df['equipement_type'])
        df['quai_enc'] = le_quai.fit_transform(df['quai_specialite'])

        # Stocker les encodeurs
        self.encoders = {
            'type': le_type,
            'equipement': le_eq,
            'quai': le_quai
        }

        # Features et target
        X = df[['navire_type_enc', 'equipement_type_enc', 'quai_enc', 'heure_debut', 'jour_semaine']]
        y = df['unite_index']

        self.model = RandomForestClassifier(n_estimators=100, random_state=42)
        self.model.fit(X, y)

        joblib.dump({'model': self.model, 'encoders': self.encoders}, self.model_path)
        print(f"✅ Modèle de recommandation d'équipement entraîné sur {len(df)} échantillons")
        return True

    def predire_unite(self, navire_type, equipement_type, quai_specialite, heure_debut, jour_semaine):
        if self.model is None:
            return None
        try:
            type_enc = self.encoders['type'].transform([navire_type])[0]
            eq_enc = self.encoders['equipement'].transform([equipement_type])[0]
            quai_enc = self.encoders['quai'].transform([quai_specialite])[0]
            X = [[type_enc, eq_enc, quai_enc, heure_debut, jour_semaine]]
            return int(self.model.predict(X)[0])
        except Exception:
            return None

    def load(self):
        if os.path.exists(self.model_path):
            obj = joblib.load(self.model_path)
            self.model = obj['model']
            self.encoders = obj['encoders']
            print("✅ Modèle de recommandation chargé")
        else:
            print("ℹ️ Aucun modèle de recommandation. Lancez 'python manage.py train_equipement_choice'")
def predire_ordre_unites(self, navire_type, equipement_type, quai_specialite, heure_debut, jour_semaine):
    if self.model is None:
        return None
    try:
        type_enc = self.encoders['type'].transform([navire_type])[0]
        eq_enc = self.encoders['equipement'].transform([equipement_type])[0]
        quai_enc = self.encoders['quai'].transform([quai_specialite])[0]
        X = [[type_enc, eq_enc, quai_enc, heure_debut, jour_semaine]]
        probas = self.model.predict_proba(X)[0]  # probabilités pour chaque classe
        # Trier les indices par probabilité décroissante
        ordre = np.argsort(probas)[::-1]
        return ordre.tolist()
    except Exception:
        return None