# optimiseur_integre.py
# Module d'intégration entre l'optimiseur et Django
# Version corrigée pour votre projet

import os
import django
from datetime import datetime
import threading

# Configuration Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'epb_smart.settings')
django.setup()

from port.models import Navire, Quai, Affectation, SessionOptimisation
from epb_smart.port.optimiseur_epb_pro import PlanificateurEPB, GestionnaireDonnees
from epb_smart.port.optimiseur_epb_pro import Navire as NavireData, TypeNavire, PrioritesNavire, Marchandise, EquipementPropre
from epb_smart.port.optimiseur_epb_pro import POIDS_PRIORITES, Priorite

# Verrou pour éviter les optimisations simultanées
optimisation_lock = threading.Lock()
optimisation_en_cours = False

def charger_navires_depuis_django():
    """
    Charge les navires depuis Django vers le format de l'optimiseur
    
    Returns:
        list: Liste de navires au format optimiseur
    """
    navires_django = Navire.objects.filter(etat='attente').order_by('arrivee')
    
    if not navires_django.exists():
        print("⚠️ Aucun navire en attente dans Django")
        return []
    
    # Mapping des types Django -> TypeNavire
    type_map = {
        'conteneur': TypeNavire.CONTENEUR,
        'cerealier': TypeNavire.CEREALIER,
        'ferry': TypeNavire.FERRY,
        'gazier': TypeNavire.GAZIER,
        'frigorifique': TypeNavire.FRIGORIFIQUE,
        'betail': TypeNavire.BETAIL,
        'essence': TypeNavire.ESSENCE,
        'huilier': TypeNavire.HUILIER,
        'petrolier': TypeNavire.PETROLIER,
        'cargo': TypeNavire.CARGO,
    }
    
    navires_optimiseur = []
    
    for n in navires_django:
        # Créer les priorités
        priorites = PrioritesNavire(
            sortant=n.sortant,
            passage=n.passage,
            gazier=n.gazier,
            essence=n.essence,
            animalier=n.animalier,
            perissable=n.perissable,
            strategique=n.strategique,
            ligne_reguliere=n.ligne_reguliere,
            convention=n.convention,
            huilier=n.huilier
        )
        
        # Créer la marchandise
        marchandise = Marchandise(
            type=n.marchandise_type or n.type,
            volume=float(n.marchandise_volume or 1000),
            dangereux=n.marchandise_dangereuse,
            frigo=n.marchandise_frigo,
        )
        
        # Créer l'équipement propre
        equip_propre = EquipementPropre(
            a_grue_bord=n.a_grue_bord,
            capacite=float(n.grue_capacite or 0)
        )
        
        # Calculer le score de priorité
        score = 1.0
        if n.sortant:
            score += POIDS_PRIORITES[Priorite.SORTANT]
        if n.passage:
            score += POIDS_PRIORITES[Priorite.PASSAGE]
        if n.gazier:
            score += POIDS_PRIORITES[Priorite.GAZIER_HIVER]
        if n.essence:
            score += POIDS_PRIORITES[Priorite.ESSENCE]
        if n.animalier:
            score += POIDS_PRIORITES[Priorite.ANIMALIER]
        if n.perissable:
            score += POIDS_PRIORITES[Priorite.PERISSABLE]
        if n.strategique:
            score += POIDS_PRIORITES[Priorite.STRATEGIQUE]
        if n.ligne_reguliere:
            score += POIDS_PRIORITES[Priorite.LIGNE_REGULIERE]
        if n.convention:
            score += POIDS_PRIORITES[Priorite.CONVENTION]
        if n.huilier:
            score += POIDS_PRIORITES[Priorite.HUILIER]
        
        # Créer le navire
        navire_data = NavireData(
            id=n.id,
            nom=n.nom,
            type=type_map.get(n.type, TypeNavire.CARGO),
            longueur=float(n.longueur),
            tirant=float(n.tirant),
            arrivee=float(n.arrivee),
            priorites=priorites,
            marchandise=marchandise,
            equipement_propre=equip_propre,
            priorite_calculee=score
        )
        
        navires_optimiseur.append(navire_data)
    
    print(f"✅ {len(navires_optimiseur)} navires chargés depuis Django")
    return navires_optimiseur

def lancer_optimisation_django(mois=3):
    """
    Lance l'optimisation et sauvegarde dans la base Django
    
    Args:
        mois: Mois pour la saison (3=hiver, 7=été)
    
    Returns:
        SessionOptimisation: instance de la session créée ou None
    """
    global optimisation_en_cours
    
    # Éviter les optimisations simultanées
    if optimisation_en_cours:
        print("⚠️ Une optimisation est déjà en cours")
        return None
    
    optimisation_en_cours = True
    
    try:
        # 1. Charger les navires depuis Django
        navires = charger_navires_depuis_django()
        
        if not navires:
            print("❌ Aucun navire à optimiser")
            return None
        
        # 2. Charger les quais et équipements
        quais = GestionnaireDonnees.charger_quais()
        equipements = GestionnaireDonnees.charger_equipements()
        
        # 3. Lancer l'optimisation
        print("\n🚀 Lancement de l'optimisation...")
        planificateur = PlanificateurEPB(quais, equipements, mois=mois)
        affectations, score_total, attente_totale = planificateur.planifier(navires)
        
        if not affectations:
            print("❌ Aucune affectation trouvée")
            return None
        
        print(f"\n✅ Optimisation terminée!")
        print(f"📊 Score total: {score_total:.2f}")
        print(f"⏱️ Attente totale: {attente_totale:.2f}h")
        print(f"🚢 Navires planifiés: {len(affectations)}")
        
        # 4. Sauvegarder dans Django
        session = SessionOptimisation.objects.create(
            nom=f"Optimisation {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            nb_navires=len(affectations),
            nb_quais=len(quais),
            score_total=score_total,
            attente_totale=attente_totale,
            attente_moyenne=attente_totale / len(affectations),
            taux_occupation=(len(set(a.quai_id for a in affectations)) / len(quais)) * 100,
            saison='hiver' if mois in [11,12,1,2,3] else 'ete'
        )
        
        # Sauvegarder les affectations
        for a in affectations:
            navire = Navire.objects.get(id=a.navire_id)
            quai = Quai.objects.get(id=a.quai_id)
            
            Affectation.objects.create(
                navire=navire,
                quai=quai,
                heure_debut=a.heure_accostage,
                heure_fin=a.heure_fin,
                attente=a.attente,
                traitement=a.traitement,
                score_contribution=a.score_contribution,
                priorites_texte=a.priorites_speciale,
                utilise_grues_bord=a.utilise_grues_bord,
            )
            
            # Mettre à jour le navire
            navire.etat = 'quai'
            navire.quai_attribue = quai
            navire.heure_debut = a.heure_accostage
            navire.heure_fin = a.heure_fin
            navire.save()
            
            # Mettre à jour le quai
            quai.disponible = False
            quai.occupation_jusqua = a.heure_fin
            quai.save()
        
        print(f"✅ {len(affectations)} affectations sauvegardées dans la session #{session.id}")
        
        return session
    
    except Exception as e:
        print(f"❌ Erreur lors de l'optimisation: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    finally:
        optimisation_en_cours = False

def reset_navires_django():
    """Réinitialise tous les navires en attente"""
    from port.models import Affectation, SessionOptimisation, Navire, Quai
    
    print("🔄 Réinitialisation des navires Django...")
    
    nb_affectations = Affectation.objects.count()
    nb_sessions = SessionOptimisation.objects.count()
    
    Affectation.objects.all().delete()
    SessionOptimisation.objects.all().delete()
    
    nb_navires = Navire.objects.exclude(etat='attente').update(etat='attente')
    nb_quais = Quai.objects.update(disponible=True, occupation_jusqua=0.0)
    
    print(f"✅ {nb_affectations} affectations supprimées")
    print(f"✅ {nb_sessions} sessions supprimées")
    print(f"✅ {nb_navires} navires remis en attente")
    print(f"✅ {nb_quais} quais remis disponibles")
    
    return nb_navires

def afficher_statistiques():
    """Affiche les statistiques de la base"""
    from port.models import Navire, Quai, Affectation, SessionOptimisation
    
    print("\n" + "="*60)
    print("📊 STATISTIQUES DE LA BASE")
    print("="*60)
    
    # Navires
    total = Navire.objects.count()
    attente = Navire.objects.filter(etat='attente').count()
    rade = Navire.objects.filter(etat='rade').count()
    quai = Navire.objects.filter(etat='quai').count()
    termine = Navire.objects.filter(etat='termine').count()
    
    print(f"\n🚢 NAVIRES: {total}")
    print(f"   ⏳ En attente: {attente}")
    print(f"   ⚓ En rade: {rade}")
    print(f"   🚢 À quai: {quai}")
    print(f"   ✅ Terminés: {termine}")
    
    # Quais
    quais_total = Quai.objects.count()
    quais_dispos = Quai.objects.filter(disponible=True).count()
    print(f"\n🏗️ QUAIS: {quais_total} (disponibles: {quais_dispos})")
    
    # Sessions
    sessions = SessionOptimisation.objects.count()
    affectations = Affectation.objects.count()
    print(f"\n📋 SESSIONS: {sessions}")
    print(f"📊 AFFECTATIONS: {affectations}")
    
    if sessions > 0:
        derniere = SessionOptimisation.objects.last()
        print(f"\n🆕 Dernière session: #{derniere.id}")
        print(f"   Score: {derniere.score_total:.2f}")
        print(f"   Navires: {derniere.nb_navires}")
        print(f"   Attente moyenne: {derniere.attente_moyenne:.2f}h")

if __name__ == "__main__":
    """Test du module d'intégration"""
    print("="*60)
    print("🚢 MODULE D'INTÉGRATION DJANGO")
    print("="*60)
    
    while True:
        print("\n📋 MENU:")
        print("   1. Lancer l'optimisation")
        print("   2. Réinitialiser les navires")
        print("   3. Afficher les statistiques")
        print("   4. Quitter")
        
        choix = input("\n👉 Votre choix (1-4): ").strip()
        
        if choix == "1":
            print("\n🌍 Saison:")
            print("   1. Hiver (défaut)")
            print("   2. Été")
            saison = input("👉 Choix (1-2): ").strip()
            mois = 3 if saison == "2" else 3
            
            session = lancer_optimisation_django(mois=mois)
            if session:
                print(f"\n✅ Optimisation sauvegardée (ID: {session.id})")
                print(f"👉 http://127.0.0.1:8000/resultats/{session.id}/")
        
        elif choix == "2":
            confirm = input("⚠️ Confirmer la réinitialisation? (oui/non): ").strip().lower()
            if confirm == "oui":
                reset_navires_django()
        
        elif choix == "3":
            afficher_statistiques()
        
        elif choix == "4":
            print("\n👋 Au revoir !")
            break
        
        else:
            print("❌ Choix invalide")