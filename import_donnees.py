# import_donnees.py
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'epb_smart.settings')
django.setup()

from port.models import Quai, Navire, TempsTraitement

print("🚢 Importation des données de test...")

# ============================================
# 1. IMPORTER LES QUAIS
# ============================================
quais_data = [
    {"id": 8,  "nom": "Quai 8",  "longueur": 290, "profondeur": 8.0,  "specialite": "ferry"},
    {"id": 11, "nom": "Quai 11", "longueur": 273, "profondeur": 8.0,  "specialite": "general"},
    {"id": 12, "nom": "Quai 12", "longueur": 257, "profondeur": 8.0,  "specialite": "ferry"},
    {"id": 13, "nom": "Quai 13", "longueur": 273, "profondeur": 8.0,  "specialite": "ferry"},
    {"id": 14, "nom": "Quai 14", "longueur": 257, "profondeur": 8.0,  "specialite": "general"},
    {"id": 15, "nom": "Quai 15", "longueur": 146, "profondeur": 8.5,  "specialite": "general"},
    {"id": 16, "nom": "Quai 16", "longueur": 146, "profondeur": 8.5,  "specialite": "general"},
    {"id": 17, "nom": "Quai 17", "longueur": 230, "profondeur": 10.0, "specialite": "conteneurs"},
    {"id": 18, "nom": "Quai 18", "longueur": 230, "profondeur": 10.0, "specialite": "conteneurs"},
    {"id": 19, "nom": "Quai 19", "longueur": 230, "profondeur": 10.0, "specialite": "essence"},
    {"id": 21, "nom": "Quai 21", "longueur": 530, "profondeur": 10.0, "specialite": "grand"},
    {"id": 22, "nom": "Quai 22", "longueur": 530, "profondeur": 10.0, "specialite": "grand"},
    {"id": 23, "nom": "Quai 23", "longueur": 530, "profondeur": 10.0, "specialite": "grand"},
    {"id": 24, "nom": "Quai 24", "longueur": 530, "profondeur": 10.0, "specialite": "gazier"},
    {"id": 25, "nom": "Quai 25", "longueur": 78,  "profondeur": 12.0, "specialite": "huilier"},
    {"id": 26, "nom": "Quai 26", "longueur": 750, "profondeur": 12.0, "specialite": "grand"},
]

for q in quais_data:
    Quai.objects.update_or_create(id=q['id'], defaults=q)
print(f"✅ {len(quais_data)} quais importés")

# ============================================
# 2. IMPORTER LES NAVIRES (AVEC TOUTES LES PRIORITÉS)
# ============================================
navires_data = [
    # Navires standards
    {"nom": "CMA CGM", "type": "conteneur", "categorie": "standard", 
     "priorite_base": 2, "longueur": 390, "tirant": 8, "arrivee": 8.0,
     "marchandise": "conteneurs", "duree_traitement": 15, "etat": "attente",
     "est_sortant": False, "est_passage": False, 
     "strategique": False, "convention_speciale": False},
    
    {"nom": "Vraquier", "type": "cerealier", "categorie": "standard", 
     "priorite_base": 3, "longueur": 130, "tirant": 3, "arrivee": 9.58,
     "marchandise": "cereales", "duree_traitement": 25, "etat": "attente",
     "est_sortant": False, "est_passage": False, 
     "strategique": False, "convention_speciale": False},
    
    {"nom": "Porte-conteneurs", "type": "conteneur", "categorie": "standard", 
     "priorite_base": 2, "longueur": 310, "tirant": 10, "arrivee": 11.0,
     "marchandise": "conteneurs", "duree_traitement": 15, "etat": "attente",
     "est_sortant": False, "est_passage": False, 
     "strategique": False, "convention_speciale": False},
    
    # Ferry (ligne régulière) - avec est_sortant = True (prioritaire)
    {"nom": "Ferry Tassili", "type": "ferry", "categorie": "ligne_reguliere",
     "priorite_base": 5, "longueur": 250, "tirant": 7, "arrivee": 10.25,
     "marchandise": "passagers", "duree_traitement": 8, "etat": "attente",
     "est_sortant": True, "est_passage": False, 
     "strategique": False, "convention_speciale": False},
    
    # Gazier - règles spéciales hiver
    {"nom": "Gazier", "type": "gazier", "categorie": "gazier", 
     "priorite_base": 4, "longueur": 180, "tirant": 9, "arrivee": 14.0,
     "marchandise": "GPL", "duree_traitement": 20, "etat": "attente",
     "est_sortant": False, "est_passage": False, 
     "strategique": False, "convention_speciale": False},
    
    # Navire avec denrées périssables
    {"nom": "Reefer", "type": "frigorifique", "categorie": "perissable", 
     "priorite_base": 3, "longueur": 160, "tirant": 7, "arrivee": 7.5,
     "marchandise": "bananes", "duree_limite": 24, "duree_traitement": 12, "etat": "attente",
     "est_sortant": False, "est_passage": False, 
     "strategique": False, "convention_speciale": False},
    
    # Navire animalier
    {"nom": "Animalier", "type": "betail", "categorie": "animalier", 
     "priorite_base": 3, "longueur": 140, "tirant": 6, "arrivee": 13.0,
     "marchandise": "bovins", "duree_traitement": 10, "etat": "attente",
     "est_sortant": False, "est_passage": False, 
     "strategique": False, "convention_speciale": False},
    
    # Caboteur d'essence - poste 19 obligatoire
    {"nom": "Essence", "type": "essence", "categorie": "caboteur_essence", 
     "priorite_base": 3, "longueur": 110, "tirant": 5, "arrivee": 9.0,
     "marchandise": "essence", "duree_traitement": 8, "etat": "attente",
     "est_sortant": False, "est_passage": False, 
     "strategique": False, "convention_speciale": False},
    
    # Huilier - postes 23/24 si libres
    {"nom": "Huilier", "type": "huilier", "categorie": "huilier", 
     "priorite_base": 2, "longueur": 120, "tirant": 6, "arrivee": 15.0,
     "marchandise": "huile", "duree_traitement": 12, "etat": "attente",
     "est_sortant": False, "est_passage": False, 
     "strategique": False, "convention_speciale": False},
    
    # Produit stratégique (céréales pour l'État) - strategique = True
    {"nom": "Strategique", "type": "cerealier", "categorie": "strategique", 
     "priorite_base": 4, "longueur": 200, "tirant": 9, "arrivee": 6.0,
     "marchandise": "ble_etat", "duree_traitement": 25, "etat": "attente",
     "est_sortant": False, "est_passage": False, 
     "strategique": True, "convention_speciale": False},
    
    # Navire de passage - est_passage = True
    {"nom": "Navire Passage", "type": "cargo", "categorie": "standard", 
     "priorite_base": 2, "longueur": 150, "tirant": 6, "arrivee": 12.0,
     "marchandise": "divers", "duree_traitement": 10, "etat": "attente",
     "est_sortant": False, "est_passage": True, 
     "strategique": False, "convention_speciale": False},
    
    # Convention spéciale - convention_speciale = True
    {"nom": "Convention Speciale", "type": "cargo", "categorie": "standard", 
     "priorite_base": 3, "longueur": 170, "tirant": 7, "arrivee": 14.0,
     "marchandise": "special", "duree_traitement": 18, "etat": "attente",
     "est_sortant": False, "est_passage": False, 
     "strategique": False, "convention_speciale": True},
]

for n in navires_data:
    Navire.objects.get_or_create(nom=n['nom'], defaults=n)
print(f"✅ {len(navires_data)} navires importés")

# ============================================
# 3. IMPORTER LES TEMPS DE TRAITEMENT
# ============================================
C = [
    [48, 30, 22, 35, 60, 25, 28, 20, 24, 30, 22, 18, 20],  # Quai 8
    [29, 45, 36, 35, 40, 26, 30, 22, 26, 32, 24, 20, 22],  # Quai 11
    [38, 62, 23, 55, 30, 24, 27, 21, 25, 28, 26, 22, 24],  # Quai 12
    [25, 33, 41, 28, 37, 27, 29, 23, 27, 33, 28, 24, 26],  # Quai 13
    [31, 44, 29, 42, 33, 28, 31, 24, 28, 34, 30, 26, 28],  # Quai 14
    [20, 25, 18, 22, 24, 18, 20, 16, 18, 22, 20, 16, 18],  # Quai 15
    [22, 28, 20, 25, 26, 19, 21, 17, 19, 23, 21, 17, 19],  # Quai 16
    [15, 18, 16, 20, 19, 15, 17, 14, 15, 18, 16, 14, 15],  # Quai 17
    [16, 19, 17, 21, 20, 16, 18, 15, 16, 19, 17, 15, 16],  # Quai 18
    [14, 17, 15, 19, 18, 14, 16, 13, 14, 17, 15, 13, 14],  # Quai 19
    [12, 15, 13, 17, 16, 13, 14, 12, 13, 15, 14, 12, 13],  # Quai 21
    [13, 16, 14, 18, 17, 14, 15, 13, 14, 16, 15, 13, 14],  # Quai 22
    [11, 14, 12, 16, 15, 12, 13, 11, 12, 14, 13, 11, 12],  # Quai 23
    [10, 12, 11, 14, 13, 11, 12, 10, 11, 12, 12, 10, 11],  # Quai 24
    [30, 35, 28, 32, 33, 29, 30, 28, 29, 31, 28, 26, 27],  # Quai 25
    [8,  10,  9, 12, 11,  9, 10,  8,  9, 10,  9,  8,  9],  # Quai 26
]

quais_ids = {q.nom: q.id for q in Quai.objects.all()}
navires_ids = {n.nom: n.id for n in Navire.objects.all()}

compteur = 0
quai_noms = ["Quai 8", "Quai 11", "Quai 12", "Quai 13", "Quai 14", 
             "Quai 15", "Quai 16", "Quai 17", "Quai 18", "Quai 19",
             "Quai 21", "Quai 22", "Quai 23", "Quai 24", "Quai 25", "Quai 26"]
navire_noms = [n["nom"] for n in navires_data]

for i, quai_nom in enumerate(quai_noms):
    for j, navire_nom in enumerate(navire_noms):
        TempsTraitement.objects.update_or_create(
            quai_id=quais_ids[quai_nom],
            navire_id=navires_ids[navire_nom],
            defaults={'duree': C[i][j]}
        )
        compteur += 1

print(f"✅ {compteur} temps de traitement importés")
print("\n🎉 IMPORTATION TERMINÉE AVEC SUCCÈS !")