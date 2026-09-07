# algo_epb_ameliore.py - Algorithme génétique amélioré avec pénalités d'attente renforcées

import pygad
import numpy as np
import random
import csv
from datetime import datetime

# ============================================
# DONNÉES DE L'EPB
# ============================================

# Mois actuel (pour règles saisonnières)
MOIS_ACTUEL = 3  # Mars (pour test)

def est_hiver():
    """Retourne True si on est en hiver (novembre à mars)"""
    return MOIS_ACTUEL in [11, 12, 1, 2, 3]

# Liste des quais (16 postes marchandises générales)
quais = [
    {"id": 8,  "nom": "Quai 8",  "longueur": 290, "profondeur": 8.0,  "specialite": "ferry", "postes_speciaux": [8]},
    {"id": 11, "nom": "Quai 11", "longueur": 273, "profondeur": 8.0,  "specialite": "general"},
    {"id": 12, "nom": "Quai 12", "longueur": 257, "profondeur": 8.0,  "specialite": "ferry", "postes_speciaux": [12]},
    {"id": 13, "nom": "Quai 13", "longueur": 273, "profondeur": 8.0,  "specialite": "ferry", "postes_speciaux": [13]},
    {"id": 14, "nom": "Quai 14", "longueur": 257, "profondeur": 8.0,  "specialite": "general"},
    {"id": 15, "nom": "Quai 15", "longueur": 146, "profondeur": 8.5,  "specialite": "general"},
    {"id": 16, "nom": "Quai 16", "longueur": 146, "profondeur": 8.5,  "specialite": "general"},
    {"id": 17, "nom": "Quai 17", "longueur": 230, "profondeur": 10.0, "specialite": "conteneurs"},
    {"id": 18, "nom": "Quai 18", "longueur": 230, "profondeur": 10.0, "specialite": "conteneurs"},
    {"id": 19, "nom": "Quai 19", "longueur": 230, "profondeur": 10.0, "specialite": "essence", "postes_speciaux": [19]},
    {"id": 21, "nom": "Quai 21", "longueur": 530, "profondeur": 10.0, "specialite": "grand"},
    {"id": 22, "nom": "Quai 22", "longueur": 530, "profondeur": 10.0, "specialite": "grand"},
    {"id": 23, "nom": "Quai 23", "longueur": 530, "profondeur": 10.0, "specialite": "grand"},
    {"id": 24, "nom": "Quai 24", "longueur": 530, "profondeur": 10.0, "specialite": "gazier", "postes_speciaux": [24]},
    {"id": 25, "nom": "Quai 25", "longueur": 78,  "profondeur": 12.0, "specialite": "huilier", "postes_speciaux": [23, 24]},
    {"id": 26, "nom": "Quai 26", "longueur": 750, "profondeur": 12.0, "specialite": "grand"},
]

# Liste des navires enrichie
navires = [
    # Navires standards
    {"id": 1, "nom": "CMA CGM",        "type": "conteneur",  "longueur": 390, "tirant": 8,  "arrivee": 8.0,  "priorite_base": 2, "categorie": "standard", "marchandise": "conteneurs"},
    {"id": 2, "nom": "Vraquier",       "type": "cerealier",  "longueur": 130, "tirant": 3,  "arrivee": 9.58, "priorite_base": 3, "categorie": "standard", "marchandise": "cereales"},
    {"id": 3, "nom": "Porte-conteneurs","type": "conteneur", "longueur": 310, "tirant": 10, "arrivee": 11.0, "priorite_base": 2, "categorie": "standard", "marchandise": "conteneurs"},
    
    # Ferry (ligne régulière) - priorité haute
    {"id": 4, "nom": "Ferry Tassili",  "type": "ferry",      "longueur": 250, "tirant": 7,  "arrivee": 10.25, "priorite_base": 5, "categorie": "ligne_reguliere", "ligne": "Marseille", "passagers": 500},
    
    # Gazier - règles spéciales hiver
    {"id": 5, "nom": "Gazier",         "type": "gazier",     "longueur": 180, "tirant": 9,  "arrivee": 14.0, "priorite_base": 4, "categorie": "gazier", "produit": "GPL"},
    
    # Navire avec denrées périssables
    {"id": 6, "nom": "Reefer",         "type": "frigorifique", "longueur": 160, "tirant": 7, "arrivee": 7.5, "priorite_base": 3, "categorie": "perissable", "marchandise": "bananes", "duree_limite": 24},
    
    # Navire animalier
    {"id": 7, "nom": "Animalier",      "type": "betail",    "longueur": 140, "tirant": 6,  "arrivee": 13.0, "priorite_base": 3, "categorie": "animalier", "animaux": "bovins"},
    
    # Caboteur d'essence - poste 19 obligatoire
    {"id": 8, "nom": "Essence",        "type": "essence",   "longueur": 110, "tirant": 5,  "arrivee": 9.0,  "priorite_base": 3, "categorie": "caboteur_essence", "produit": "essence"},
    
    # Huilier - postes 23/24 si libres
    {"id": 9, "nom": "Huilier",        "type": "huilier",   "longueur": 120, "tirant": 6,  "arrivee": 15.0, "priorite_base": 2, "categorie": "huilier", "produit": "huile"},
    
    # Produit stratégique (céréales pour l'État)
    {"id": 10, "nom": "Strategique",   "type": "cerealier", "longueur": 200, "tirant": 9,  "arrivee": 6.0, "priorite_base": 4, "categorie": "strategique", "marchandise": "ble_etat"},
]

# Matrice des temps de traitement C[i][j]
C = [
    [48, 30, 22, 35, 60, 25, 28, 20, 24, 30],  # Quai 8
    [29, 45, 36, 35, 40, 26, 30, 22, 26, 32],  # Quai 11
    [38, 62, 23, 55, 30, 24, 27, 21, 25, 28],  # Quai 12
    [25, 33, 41, 28, 37, 27, 29, 23, 27, 33],  # Quai 13
    [31, 44, 29, 42, 33, 28, 31, 24, 28, 34],  # Quai 14
    [20, 25, 18, 22, 24, 18, 20, 16, 18, 22],  # Quai 15
    [22, 28, 20, 25, 26, 19, 21, 17, 19, 23],  # Quai 16
    [15, 18, 16, 20, 19, 15, 17, 14, 15, 18],  # Quai 17 (conteneurs)
    [16, 19, 17, 21, 20, 16, 18, 15, 16, 19],  # Quai 18
    [14, 17, 15, 19, 18, 14, 16, 13, 14, 17],  # Quai 19
    [12, 15, 13, 17, 16, 13, 14, 12, 13, 15],  # Quai 21
    [13, 16, 14, 18, 17, 14, 15, 13, 14, 16],  # Quai 22
    [11, 14, 12, 16, 15, 12, 13, 11, 12, 14],  # Quai 23
    [10, 12, 11, 14, 13, 11, 12, 10, 11, 12],  # Quai 24
    [30, 35, 28, 32, 33, 29, 30, 28, 29, 31],  # Quai 25
    [8,  10,  9, 12, 11,  9, 10,  8,  9, 10],  # Quai 26 (grand)
]

print(f"✅ {len(quais)} quais chargés")
print(f"✅ {len(navires)} navires à optimiser")
print(f"✅ Matrice C: {len(C)} lignes x {len(C[0])} colonnes")

# ============================================
# FONCTION DE CALCUL DE PRIORITÉ AMÉLIORÉE
# ============================================

def calculer_priorite_reelle(navire, heure_proposee, solution_complete, idx_navire):
    """
    Calcule la priorité réelle d'un navire selon les règles du chapitre I
    Avec pénalités renforcées pour les longues attentes
    """
    attente = heure_proposee - navire["arrivee"]
    poids = navire["priorite_base"]
    
    # ========================================
    # PÉNALITÉ DE BASE POUR ATTENTE
    # ========================================
    # Moins 1 point par tranche de 4h d'attente (plus sévère)
    penalite_attente = attente / 4
    poids -= penalite_attente
    
    # ========================================
    # RÈGLES SPÉCIALES AVEC PÉNALITÉS RENFORCÉES
    # ========================================
    
    # 1. Gaziers en hiver - priorité MAX + pénalité énorme si attente longue
    if navire["type"] == "gazier" and est_hiver():
        poids += 10  # Priorité maximale
        if attente > 12:
            poids -= 30  # Pénalité très forte si plus de 12h
        elif attente > 6:
            poids -= 15
    
    # 2. Caboteurs d'essence
    if navire.get("categorie") == "caboteur_essence":
        poids += 6
        if attente > 12:
            poids -= 25
        elif attente > 6:
            poids -= 10
    
    # 3. Navires animaliers
    if navire.get("categorie") == "animalier":
        poids += 7
        if attente > 8:
            poids -= 30  # Bien-être animal critique
        elif attente > 4:
            poids -= 15
    
    # 4. Denrées périssables
    if navire.get("categorie") == "perissable":
        poids += 6
        duree_limite = navire.get("duree_limite", 24)
        if attente > duree_limite:
            poids -= 100  # Marchandise complètement perdue !
        elif attente > duree_limite / 2:
            poids -= 30
    
    # 5. Produits stratégiques
    if navire.get("categorie") == "strategique":
        poids += 7
        if attente > 12:
            poids -= 30
    
    # 6. Lignes régulières (ferries)
    if navire.get("categorie") == "ligne_reguliere":
        poids += 6
        if attente > 2:  # Ferry ne doit presque pas attendre
            poids -= 15
        if attente > 4:
            poids -= 30
    
    # 7. Huiliers
    if navire.get("categorie") == "huilier":
        poids += 3
        if attente > 24:
            poids -= 15
    
    # 8. Bonus pour placement optimal
    quai_idx = int(solution_complete[idx_navire*2])
    if navire.get("categorie") == "ligne_reguliere" and quais[quai_idx]["id"] in [8, 12, 13]:
        poids += 4
    if navire.get("categorie") == "huilier" and quais[quai_idx]["id"] in [23, 24]:
        poids += 3
    
    return max(1, poids)  # Priorité minimum 1

# ============================================
# FONCTION DE VÉRIFICATION DES CONTRAINTES SPÉCIALES
# ============================================

def verifier_contraintes_speciales(solution):
    """
    Vérifie toutes les contraintes spéciales du chapitre I
    """
    nb_navires = len(navires)
    
    for j in range(nb_navires):
        quai_idx = int(solution[j*2])
        navire = navires[j]
        quai = quais[quai_idx]
        
        # 1. Gaziers en hiver → poste 24 obligatoire
        if navire["type"] == "gazier" and est_hiver():
            if quai["id"] != 24:
                return False, f"❌ Gazier {navire['nom']} doit être au poste 24 en hiver"
        
        # 2. Caboteurs d'essence → poste 19 obligatoire
        if navire.get("categorie") == "caboteur_essence":
            if quai["id"] != 19:
                return False, f"❌ Caboteur essence {navire['nom']} doit être au poste 19"
    
    return True, "✅ Toutes les contraintes spéciales respectées"

# ============================================
# FONCTION FITNESS AMÉLIORÉE
# ============================================

def fitness_function(ga_instance, solution, solution_idx):
    """
    Évalue la qualité d'une solution avec toutes les priorités et contraintes
    """
    nb_navires = len(navires)
    PENALITE_INFINIE = -10**9
    MAX_ATTENTE_HEURES = 72  # 3 jours maximum d'attente
    
    # ========================================
    # 1. VÉRIFICATION DES CONTRAINTES DE BASE
    # ========================================
    for j in range(nb_navires):
        quai_idx = int(solution[j*2])
        heure = solution[j*2 + 1]
        
        # Quai existe
        if quai_idx < 0 or quai_idx >= len(quais):
            return PENALITE_INFINIE
        
        # Longueur
        if navires[j]["longueur"] > quais[quai_idx]["longueur"]:
            return PENALITE_INFINIE
        
        # Tirant d'eau
        if navires[j]["tirant"] > quais[quai_idx]["profondeur"]:
            return PENALITE_INFINIE
        
        # Heure d'arrivée
        if heure < navires[j]["arrivee"]:
            return PENALITE_INFINIE
        
        # Contrainte de temps maximum
        attente = heure - navires[j]["arrivee"]
        if attente > MAX_ATTENTE_HEURES:
            return PENALITE_INFINIE
    
    # ========================================
    # 2. VÉRIFICATION DES CHEVAUCHEMENTS
    # ========================================
    for i in range(nb_navires):
        for j in range(i+1, nb_navires):
            quai_i = int(solution[i*2])
            quai_j = int(solution[j*2])
            
            if quai_i == quai_j:
                heure_i = solution[i*2 + 1]
                heure_j = solution[j*2 + 1]
                duree_i = C[quai_i][i]
                duree_j = C[quai_j][j]
                
                fin_i = heure_i + duree_i
                fin_j = heure_j + duree_j
                
                if not (fin_i <= heure_j or fin_j <= heure_i):
                    return PENALITE_INFINIE
    
    # ========================================
    # 3. VÉRIFICATION DES CONTRAINTES SPÉCIALES
    # ========================================
    valide, _ = verifier_contraintes_speciales(solution)
    if not valide:
        return PENALITE_INFINIE
    
    # ========================================
    # 4. CALCUL DU SCORE AVEC PRIORITÉS RENFORCÉES
    # ========================================
    score_total = 0
    
    for j in range(nb_navires):
        quai_idx = int(solution[j*2])
        heure = solution[j*2 + 1]
        navire = navires[j]
        attente = heure - navire["arrivee"]
        
        # Calcul de la priorité réelle (avec pénalités d'attente)
        priorite = calculer_priorite_reelle(navire, heure, solution, j)
        
        # Temps de traitement
        traitement = C[quai_idx][j]
        
        # FACTEUR DE PRIORITÉ RENFORCÉ
        # priorite 10 → facteur 0.1, priorite 1 → facteur 1.0
        facteur = 1.0 / priorite
        
        # PÉNALITÉ DIRECTE SUR L'ATTENTE POUR LES TRÈS PRIORITAIRES
        penalite_attente_directe = 0
        if priorite > 8:  # Très haute priorité (gazier, animalier, etc.)
            penalite_attente_directe = attente * 3  # Triple pénalité
        elif priorite > 5:  # Haute priorité
            penalite_attente_directe = attente * 2  # Double pénalité
        elif priorite > 3:  # Priorité moyenne
            penalite_attente_directe = attente * 1.5
        
        score_total += (attente + traitement) * facteur + penalite_attente_directe
        
        # Bonus/Malus spécifiques
        if navire.get("categorie") == "ligne_reguliere" and quais[quai_idx]["id"] in [8, 12, 13]:
            score_total -= 15  # Bonus ferry bien placé
        
        if navire.get("categorie") == "huilier" and quais[quai_idx]["id"] in [23, 24]:
            score_total -= 8  # Bonus huilier bien placé
    
    # Bonus pour dispersion (utiliser plusieurs quais)
    quais_utilises = set([int(solution[i*2]) for i in range(nb_navires)])
    score_total -= len(quais_utilises) * 5
    
    # On veut MINIMISER score_total, donc fitness = -score_total
    return -score_total

# ============================================
# CONFIGURATION DE L'ALGORITHME GÉNÉTIQUE
# ============================================

def creer_espace_recherche():
    """Définit les espaces de recherche pour chaque gène"""
    espace = []
    for j in range(len(navires)):
        # Quai (0 à 15)
        espace.append(list(range(len(quais))))
        
        # Heure (entre arrivee et arrivee + 72h max)
        min_h = navires[j]["arrivee"]
        max_h = min_h + 72
        espace.append({'low': min_h, 'high': max_h})
    
    return espace

# Création de l'instance PyGAD
ga_instance = pygad.GA(
    num_generations=300,              # Plus de générations
    num_parents_mating=40,
    fitness_func=fitness_function,
    sol_per_pop=200,                   # Population plus grande
    num_genes=len(navires) * 2,
    gene_type=[int, float] * len(navires),
    gene_space=creer_espace_recherche(),
    mutation_percent_genes=20,          # Plus de mutation pour explorer
    crossover_type="single_point",
    mutation_type="random",
    save_best_solutions=True,
    suppress_warnings=True
)

print("\n⚙️ Configuration de l'algorithme génétique amélioré :")
print(f"   - {len(navires)} navires, {len(quais)} quais")
print(f"   - {ga_instance.num_genes} gènes par solution")
print(f"   - Population: {ga_instance.sol_per_pop} solutions")
print(f"   - {ga_instance.num_generations} générations")
print(f"   - Mutation: {ga_instance.mutation_percent_genes}%")

# ============================================
# FONCTION DE SAUVEGARDE DES RÉSULTATS
# ============================================

def sauvegarder_planning(solution, fitness):
    """Sauvegarde le planning dans un fichier CSV"""
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"planning_epb_{timestamp}.csv"
    
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Navire', 'Type', 'Quai', 'Heure', 'Attente', 'Traitement', 'Priorite_Calculee', 'Categorie'])
        
        total_attente = 0
        total_traitement = 0
        
        for j in range(len(navires)):
            quai_idx = int(solution[j*2])
            heure = solution[j*2 + 1]
            navire = navires[j]
            attente = heure - navire["arrivee"]
            traitement = C[quai_idx][j]
            priorite = calculer_priorite_reelle(navire, heure, solution, j)
            
            total_attente += attente
            total_traitement += traitement
            
            writer.writerow([
                navire["nom"],
                navire["type"],
                quais[quai_idx]["nom"],
                f"{heure:.2f}",
                f"{attente:.2f}",
                f"{traitement:.2f}",
                f"{priorite:.1f}",
                navire.get("categorie", "standard")
            ])
        
        # Ligne des totaux
        writer.writerow([])
        writer.writerow(['TOTAL', '', '', '', f"{total_attente:.2f}", f"{total_traitement:.2f}", f"{-fitness:.2f}", ''])
    
    print(f"\n💾 Planning sauvegardé dans : {filename}")
    return filename

# ============================================
# LANCEMENT DE L'OPTIMISATION
# ============================================

print("\n🔍 Lancement de l'optimisation améliorée...")
print("⏳ Cela peut prendre 2-3 minutes...\n")

ga_instance.run()

# ============================================
# AFFICHAGE DES RÉSULTATS
# ============================================

print("\n" + "="*80)
print("🏆 OPTIMISATION TERMINÉE - RÉSULTATS FINAUX AMÉLIORÉS")
print("="*80)

# Meilleure solution
solution, fitness, idx = ga_instance.best_solution()
print(f"\n📊 Meilleur score trouvé : {-fitness:.2f} heures")
print(f"📈 Trouvé à la génération : {ga_instance.best_solution_generation}")

# Détail par navire
print("\n📋 PLANNING OPTIMAL AVEC PRIORITÉS :")
print("-"*80)
print(f"{'Navire':<18} {'Type':<12} {'Quai':<8} {'Heure':<8} {'Attente':<8} {'Trait.':<8} {'Priorité':<8} {'Statut'}")
print("-"*80)

total_attente = 0
total_traitement = 0

for j in range(len(navires)):
    quai_idx = int(solution[j*2])
    heure = solution[j*2 + 1]
    navire = navires[j]
    
    attente = heure - navire["arrivee"]
    traitement = C[quai_idx][j]
    priorite_reelle = calculer_priorite_reelle(navire, heure, solution, j)
    
    quai_nom = quais[quai_idx]["nom"]
    
    total_attente += attente
    total_traitement += traitement
    
    # Indicateur de statut
    statut = ""
    if attente < 6:
        statut = "✅ Excellent"
    elif attente < 12:
        statut = "👍 Bon"
    elif attente < 24:
        statut = "⚠️ Acceptable"
    else:
        statut = "❌ Trop long"
    
    # Indicateur spécial
    special = ""
    if navire["type"] == "gazier" and est_hiver():
        special = "❄️"
    elif navire.get("categorie") == "animalier":
        special = "🐮"
    elif navire.get("categorie") == "perissable":
        special = "🍌"
    elif navire.get("categorie") == "ligne_reguliere":
        special = "⛴️"
    
    print(f"{navire['nom']:<18} {navire['type']:<12} {quai_nom:<8} {heure:6.2f}h  {attente:6.2f}h  {traitement:6.2f}h  {priorite_reelle:6.1f}  {special} {statut}")

print("-"*80)
print(f"{'TOTAUX':<18} {'':<12} {'':<8} {'':<8} {total_attente:6.2f}h  {total_traitement:6.2f}h")
print("="*80)

# Statistiques d'attente
attentes = [solution[j*2 + 1] - navires[j]["arrivee"] for j in range(len(navires))]
print(f"\n📊 STATISTIQUES D'ATTENTE :")
print(f"   - Attente moyenne : {np.mean(attentes):.2f} heures")
print(f"   - Attente maximale : {np.max(attentes):.2f} heures")
print(f"   - Attente minimale : {np.min(attentes):.2f} heures")
print(f"   - Navires avec attente < 12h : {sum(1 for a in attentes if a < 12)} / {len(navires)}")

# Vérification finale
print("\n🔍 VÉRIFICATION FINALE DES CONTRAINTES SPÉCIALES :")
valide, msg = verifier_contraintes_speciales(solution)
print(msg)

# Analyse des priorités appliquées
print("\n📊 ANALYSE DES PRIORITÉS APPLIQUÉES :")
if est_hiver():
    print("❄️ Règle hivernale active (gaziers → poste 24)")
for j in range(len(navires)):
    if navires[j]["type"] == "gazier" and est_hiver():
        print(f"   • Gazier {navires[j]['nom']} au poste 24 (règle hiver)")
    if navires[j].get("categorie") == "caboteur_essence":
        print(f"   • Caboteur essence {navires[j]['nom']} au poste 19")
    if navires[j].get("categorie") == "ligne_reguliere":
        print(f"   • Ferry {navires[j]['nom']} prioritaire")

# Sauvegarde des résultats
fichier = sauvegarder_planning(solution, fitness)

# Graphique de convergence
try:
    import matplotlib.pyplot as plt
    ga_instance.plot_fitness()
    plt.title("Convergence de l'algorithme génétique amélioré")
    plt.xlabel("Générations")
    plt.ylabel("Fitness (meilleur score)")
    plt.grid(True)
    plt.savefig("convergence_epb_ameliore.png")
    print("\n📊 Graphique de convergence sauvegardé : convergence_epb_ameliore.png")
    plt.show()
except Exception as e:
    print(f"\n📊 Graphique non disponible: {e}")

print("\n🎉 FÉLICITATIONS ! L'algorithme amélioré est prêt !")
print(f"📁 Les résultats sont dans : {fichier}")