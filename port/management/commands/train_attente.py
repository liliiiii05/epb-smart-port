from django.core.management.base import BaseCommand
from django.conf import settings
import os
import joblib
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error
from port.models import Affectation, Meteo

class Command(BaseCommand):
    help = 'Entraîne le modèle de prédiction d\'attente'

    def handle(self, *args, **options):
        self.stdout.write("📊 Entraînement du modèle de prédiction d'attente...")
        
        # Récupérer l'historique des affectations
        affectations = Affectation.objects.select_related('navire', 'quai').all()
        
        data = []
        for a in affectations:
            # Ne garder que les affectations avec attente réelle
            if a.attente is None or a.attente <= 0:
                continue
            
            # Récupérer la météo du jour
            meteo = Meteo.objects.filter(date=a.date_creation.date()).first()
            
            data.append({
                'type_navire': a.navire.type,
                'volume': a.navire.marchandise_volume or 0,
                'longueur': a.navire.longueur,
                'tirant': a.navire.tirant,
                'agent': a.navire.agent or '',
                'quai_specialite': a.quai.specialite,
                'meteo_pluie': 1 if meteo and meteo.pluie else 0,
                'meteo_vent': meteo.vent_force if meteo else 0,
                'attente_reelle': a.attente
            })
        
        if len(data) < 30:
            self.stdout.write(self.style.WARNING(f"⚠️ Données insuffisantes : {len(data)} enregistrements (min 50 requis)"))
            return
        
        df = pd.DataFrame(data)
        
        # Encodage des variables catégorielles
        df['type_enc'] = df['type_navire'].astype('category').cat.codes
        df['agent_enc'] = df['agent'].astype('category').cat.codes
        df['quai_spec_enc'] = df['quai_specialite'].astype('category').cat.codes
        
        # Features
        features = ['type_enc', 'volume', 'longueur', 'tirant', 'agent_enc', 
                    'quai_spec_enc', 'meteo_pluie', 'meteo_vent']
        X = df[features]
        y = df['attente_reelle']
        
        # Split
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        
        # Entraînement
        model = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
        model.fit(X_train, y_train)
        
        # Évaluation
        y_pred = model.predict(X_test)
        mae = mean_absolute_error(y_test, y_pred)
        r2 = model.score(X_test, y_test)
        
        self.stdout.write(self.style.SUCCESS(f"✅ Modèle entraîné sur {len(data)} échantillons"))
        self.stdout.write(f"   - MAE (erreur moyenne) : {mae:.2f} heures")
        self.stdout.write(f"   - R² : {r2:.3f}")
        
        # Feature importance
        importance = pd.DataFrame({
            'feature': features,
            'importance': model.feature_importances_
        }).sort_values('importance', ascending=False)
        self.stdout.write("\n📊 Importance des features :")
        for _, row in importance.head(5).iterrows():
            self.stdout.write(f"   - {row['feature']}: {row['importance']:.3f}")
        
        # Sauvegarde
        models_dir = os.path.join(settings.BASE_DIR, 'models')
        os.makedirs(models_dir, exist_ok=True)
        model_path = os.path.join(models_dir, 'attente_model.pkl')
        joblib.dump(model, model_path)
        self.stdout.write(self.style.SUCCESS(f"\n✅ Modèle sauvegardé dans {model_path}"))