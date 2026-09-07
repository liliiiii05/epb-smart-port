# port/regles_meteo.py
# Dictionnaire des règles météo intelligentes
# Format: (type_marchandise, condition) -> action

REGLE_METEO = {
    # Règle pour les céréales
    ("cerealier", "pluie"): {
        "interdit": True,
        "message": "🌧️ Déchargement de céréales interdit par temps de pluie (risque de détérioration et d'humidité)"
    },
    ("cerealier", "vent_fort"): {
        "ralentissement": 1.5,
        "message": "💨 Vent fort – opérations sur céréales ralenties (+50% de durée, risque de perte de produit)"
    },
    
    # Règle pour le bois
    ("bois", "pluie"): {
        "ralentissement": 1.3,
        "message": "🌧️ Pluie – manutention du bois ralentie (glissance, gonflement du bois)"
    },
    ("bois", "vent_fort"): {
        "ralentissement": 1.2,
        "message": "💨 Vent fort – manutention du bois dangereuse (+20% de durée)"
    },
    
    # Règle pour les produits dangereux
    ("dangereux", "pluie"): {
        "interdit": True,
        "message": "⚠️ Produits dangereux – opérations interdites par temps de pluie (risque de réaction chimique)"
    },
    ("dangereux", "vent_fort"): {
        "interdit": True,
        "message": "⚠️ Produits dangereux – opérations interdites par vent fort (risque de dispersion)"
    },
    
    # Règle pour les conteneurs
    ("conteneur", "vent_fort"): {
        "ralentissement": 1.2,
        "message": "💨 Vent fort – manutention de conteneurs ralentie (+20%, risque de balancement)"
    },
    
    # Règle pour les produits frigorifiques
    ("frigorifique", "vent_fort"): {
        "ralentissement": 1.1,
        "message": "💨 Vent fort – opérations frigorifiques légèrement ralenties (+10%)"
    },
    
    # Règle pour les produits périssables
    ("perissable", "chaleur"): {
        "ralentissement": 1.2,
        "message": "🌡️ Température élevée – accélération nécessaire pour les produits périssables"
    },
}