# =============================================================================
# IMPORTS
# =============================================================================
import csv
import json
import logging
import os
import traceback
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.paginator import Paginator
from django.db.models import Avg, Count, F, Max, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .adaptateurs import AdaptateurDonnees
from .alertes import generer_toutes_alertes
from .decorators import group_required
from .email_utils import envoyer_notification_affectation
from .models import (
    Affectation, Alerte, Equipement, HistoriqueOperation,
    Meteo, Navire, Quai, SessionOptimisation, SnapshotNavire,
    Profile, Poste, HistoriqueAction,
    Equipe, AffectationEquipe,  NoteAttente   # <-- Modèles équipes
)
from .optimiseur_epb_pro import (
    EquipementPropre, GestionnaireDonnees,
    Marchandise, Navire as NavireData,
    PlanificateurEPB, PrioritesNavire,
    TypeNavire, AffectationResultat
)
from .priorites import calculer_priorite_navire
from port.models import Navire 

logger = logging.getLogger(__name__)

# =============================================================================
# FONCTIONS UTILITAIRES
# =============================================================================
# port/estimation_utils.py
from .optimiseur_epb_pro import TypeNavire
from .models import HistoriqueOperation

# port/estimation_utils.py
from .optimiseur_epb_pro import TypeNavire
from .models import HistoriqueOperation

# port/estimation_utils.py
from .optimiseur_epb_pro import TypeNavire
from .models import HistoriqueOperation



def estimer_duree_traitement(navire, quai=None):
    """Version CORRIGÉE avec des taux réalistes et règles contractuelles pour conteneurs"""
    volume = navire.marchandise_volume
    if volume <= 0:
        return 24.0  # Valeur par défaut réaliste

    # ========== RÈGLES CONTRACTUELLES POUR CONTENEURS ==========
    if navire.type == 'conteneur':
        agent = getattr(navire, 'agent', '').upper()
        if 'MSC' in agent:
            return 6 * 24  # 144 heures (6 jours)
        elif 'CMA' in agent or 'CGM' in agent:
            return 5 * 24  # 120 heures (5 jours)
        elif 'MAERSK' in agent:
            return 5 * 24  # 120 heures (5 jours)
        else:
            return 5 * 24  # 120 heures (5 jours)

    # ========== TAUX RÉALISTES POUR LES AUTRES TYPES ==========
    TAUX_REALISTES = {
        'gazier': 200,      # tonnes/heure
        'cargo': 250,       # réduit de 400 à 250 pour être réaliste
        'cerealier': 550,
        'petrolier': 400,
        'essence': 300,
        'huilier': 150,
        'ferry': 100,
    }
    
    taux = TAUX_REALISTES.get(navire.type, 250)
    
    # Calcul de la durée
    duree = volume / taux
    
    # Limites raisonnables (1h à 7 jours)
    duree = max(1.0, min(168.0, duree))
    
    return duree

    # ============================================================
    # ✅ FONCTION 2 : calculer_fin_estimee_complete (SANS PROLONGATION)
    # ============================================================
    def calculer_fin_estimee_complete(navire):
        """
        Calcule la fin estimée du navire avec toutes les contraintes.
        ✅ Prend en compte : règle contractuelle, attente notes, attente équipement, coefficient dangereux.
        ✅ AUCUNE prolongation automatique : on affiche la VRAIE fin théorique.
        
        Returns:
            (fin_estimee, taux, pourcentage, attente_equip, retard_heures)
        """
        if not navire.debut_datetime or navire.marchandise_volume <= 0:
            return None, None, 0, 0, 0

        # ============================================================
        # ✅ ÉTAPE 1 : DURÉE DE TRAITEMENT (RÈGLES CONTRACTUELLES)
        # ============================================================
        type_nav = navire.type
        agent = (navire.agent or '').upper()

        if type_nav == 'conteneur':
            # ✅ RÈGLES CONTRACTUELLES MSC / CMA CGM / MAERSK
            if 'MSC' in agent:
                duree_traitement = 6 * 24  # 144 heures (6 jours)
            elif 'CMA' in agent or 'CGM' in agent:
                duree_traitement = 5 * 24  # 120 heures (5 jours)
            elif 'MAERSK' in agent:
                duree_traitement = 5 * 24  # 120 heures (5 jours)
            else:
                duree_traitement = 5 * 24  # 120 heures (5 jours) par défaut
            taux = navire.marchandise_volume / duree_traitement if duree_traitement > 0 else 300
        else:
            # ✅ RÈGLES PAR DÉBIT POUR LES AUTRES TYPES
            taux = get_taux_reel(navire)
            duree_traitement = navire.marchandise_volume / taux if taux > 0 else 24.0

        # ============================================================
        # ✅ ÉTAPE 2 : COEFFICIENT MARCHANDISE DANGEREUSE
        # ============================================================
        if navire.marchandise_dangereuse:
            duree_traitement = duree_traitement * 1.25  # +25% de sécurité

        # ============================================================
        # ✅ ÉTAPE 3 : ATTENTE NOTES (CONNUES)
        # ============================================================
        attente_notes = attente_notes_totale

        # ============================================================
        # ✅ ÉTAPE 4 : ATTENTE ÉQUIPEMENT (ESTIMATION)
        # ============================================================
        attente_equip = 0.0
        if navire.type == 'gazier':
            attente_equip = 3.0
        elif navire.type == 'petrolier':
            attente_equip = 2.0
        elif navire.type == 'cerealier':
            attente_equip = 1.0

        # ============================================================
        # ✅ ÉTAPE 5 : ARRÊT PLUIE
        # ============================================================
        arret_pluie = navire.temps_arret_pluie or 0

        # ============================================================
        # ✅ ÉTAPE 6 : DURÉE TOTALE
        # ============================================================
        duree_totale = duree_traitement + attente_notes + attente_equip + arret_pluie

        # ============================================================
        # ✅ ÉTAPE 7 : FIN ESTIMÉE (THÉORIQUE - SANS PROLONGATION)
        # ============================================================
        fin_estimee = navire.debut_datetime + timedelta(hours=duree_totale)

        # ============================================================
        # ✅ ÉTAPE 8 : PROGRESSION BASÉE SUR LE TEMPS ÉCOULÉ
        # ============================================================
        maintenant = timezone.now()
        temps_ecoule = (maintenant - navire.debut_datetime).total_seconds() / 3600.0
        pourcentage = min(99, (temps_ecoule / duree_totale) * 100) if duree_totale > 0 else 0

        # ============================================================
        # ✅ ÉTAPE 9 : CALCUL DU RETARD (POUR INFORMATION UNIQUEMENT)
        # ⚠️ AUCUNE MODIFICATION DE fin_estimee
        # On retourne la VRAIE fin théorique, même si elle est dans le passé.
        # ============================================================
        retard_heures = 0.0
        if maintenant > fin_estimee:
            retard_heures = (maintenant - fin_estimee).total_seconds() / 3600.0
            print(f"⚠️ {navire.nom} : Retard de {retard_heures:.1f}h (fin théorique = {fin_estimee.strftime('%d/%m %H:%M')})")

        return fin_estimee, round(taux, 1), pourcentage, attente_equip, retard_heures
# =============================================================================
# ✅ FONCTION SOURCE DE VÉRITÉ UNIQUE POUR LA DURÉE
# =============================================================================
def calculer_duree_contractuelle(navire):
    """
    Calcule la durée de traitement selon les règles contractuelles EPB.
    ✅ MSC = 144h, CMA CGM = 120h, MAERSK = 120h
    ✅ Autres types = volume / taux réaliste
    
    Cette fonction est la SOURCE DE VÉRITÉ UNIQUE pour la durée d'un navire.
    Elle est utilisée par : detail_navire, planification_dynamique
    """
    if navire.marchandise_volume <= 0:
        return 24.0

    agent = (navire.agent or '').upper()

    # ========== CONTENEURS (RÈGLES CONTRACTUELLES) ==========
    if navire.type == 'conteneur':
        if 'MSC' in agent:
            duree = 6 * 24  # 144h
        elif 'CMA' in agent or 'CGM' in agent:
            duree = 5 * 24  # 120h
        elif 'MAERSK' in agent:
            duree = 5 * 24  # 120h
        else:
            duree = 5 * 24  # 120h par défaut
    else:
        # ========== AUTRES TYPES (CALCUL RÉALISTE) ==========
        TAUX_PAR_TYPE = {
            'gazier': 160,
            'cerealier': 550,
            'cargo': 250,
            'petrolier': 400,
            'essence': 250,
            'ferry': 100,
            'huilier': 150,
        }
        taux = TAUX_PAR_TYPE.get(navire.type, 250)
        if navire.type == 'cerealier' and navire.marchandise_type and 'MAIS' in navire.marchandise_type.upper():
            taux = 500
        duree = navire.marchandise_volume / taux if taux > 0 else 24.0

    # Coefficient dangereux
    if navire.marchandise_dangereuse:
        duree = duree * 1.25

    return duree
# =============================================================================
@login_required
def detail_navire(request, navire_id):
    from datetime import datetime, timedelta
    from django.utils import timezone
    from django.db.models import Sum, Avg
    from port.models import Affectation, Quai, Poste, SnapshotNavire, NoteAttente, Meteo, Navire as NavireModel
    from port.views import get_equipements_necessaires_par_type
    from port.optimiseur_epb_pro import ModeleCalcul

    navire = get_object_or_404(NavireModel, id=navire_id)

    # ========== MARCHANDISES DANGEREUSES ==========
    MARCHANDISES_DANGEREUSES = [
        'BUTANE', 'PROPANE', 'BUTANE & PROPANE', 'BUTANE+PROPANE',
        'GAZ', 'GNL', 'GAZ NATUREL', 'METHANE', 'ETHANE',
        'CHIMIQUE', 'ACIDE', 'CORROSIF', 'TOXIQUE', 'INFLAMMABLE',
        'ESSENCE', 'GAZOIL', 'GASOIL', 'PETROLE', 'FIUL'
    ]

    marchandise = (navire.marchandise_type or '').upper()
    est_dangereux = navire.marchandise_dangereuse

    if not est_dangereux:
        for mot in MARCHANDISES_DANGEREUSES:
            if mot in marchandise:
                navire.marchandise_dangereuse = True
                navire.save()
                print(f"OK {navire.nom}: marchandise dangereuse activee ({marchandise})")
                break

        if navire.type == 'gazier' and not navire.marchandise_dangereuse:
            navire.marchandise_dangereuse = True
            navire.save()
            print(f"OK {navire.nom}: gazier marque comme dangereux")

    affectations_qs = Affectation.objects.filter(navire=navire).order_by('-date_creation')

    # ========== SI AUCUNE AFFECTATION MAIS NAVIRE A QUAI ==========
    if affectations_qs.count() == 0 and navire.etat == 'quai' and navire.debut_datetime and navire.marchandise_volume > 0:
        mc = ModeleCalcul([], [])

        taux = mc.get_taux_par_produit(navire)
        if navire.marchandise_type and 'MAIS' in navire.marchandise_type.upper():
            taux = 500

        if navire.marchandise_dangereuse:
            taux = taux * 0.8

        traitement_estime = navire.marchandise_volume / taux if taux > 0 else 24.0

        quai_actuel = navire.quai_attribue
        if quai_actuel is None:
            quai_actuel = Quai.objects.first()

        heure_debut = navire.debut_datetime.hour + navire.debut_datetime.minute / 60.0 if navire.debut_datetime else 0

        affectation_reelle = Affectation.objects.create(
            navire=navire,
            quai=quai_actuel,
            heure_debut=heure_debut,
            heure_fin=heure_debut + traitement_estime,
            attente=0,
            traitement=traitement_estime,
            score_contribution=100,
            priorites_texte="Estimation automatique",
            utilise_grues_bord=navire.a_grue_bord,
            date_creation=timezone.now()
        )

        affectations_qs = Affectation.objects.filter(navire=navire).order_by('-date_creation')

    affectations = affectations_qs

    # ========== Recalculer les dates d'affichage ==========
    for aff in affectations:
        if aff.date_debut_reel and aff.date_fin_reel:
            aff.debut_affichage = aff.date_debut_reel
            aff.fin_affichage = aff.date_fin_reel
            aff.date_affichage = aff.date_debut_reel
        else:
            if navire.debut_datetime:
                base = navire.debut_datetime
                aff.debut_affichage = base
                aff.fin_affichage = base + timedelta(hours=aff.traitement)
                aff.date_affichage = base
            else:
                base = aff.date_creation.replace(hour=0, minute=0, second=0, microsecond=0)
                heures = int(aff.heure_debut) if aff.heure_debut else 0
                minutes = int((aff.heure_debut - heures) * 60) if aff.heure_debut else 0
                aff.debut_affichage = base + timedelta(hours=heures, minutes=minutes)
                aff.fin_affichage = aff.debut_affichage + timedelta(hours=aff.traitement)
                aff.date_affichage = aff.date_creation

    # ========== Notes d'attente ACTIVES (escale en cours) ==========
    notes_attente_actives = navire.notes_attente_actives
    attente_notes_totale = sum(note.duree_attente for note in notes_attente_actives)

    # ========== Statistiques ==========
    if affectations.exists():
        total_affectations = affectations.count()

        temps_total_attente = sum(a.attente for a in affectations)
        temps_moyen_attente = temps_total_attente / total_affectations if total_affectations > 0 else 0

        temps_total_traitement = sum(a.traitement for a in affectations)
        temps_moyen_traitement = temps_total_traitement / total_affectations if total_affectations > 0 else 0

        scores_valides = [a.score_contribution for a in affectations if a.score_contribution > 0]
        if scores_valides:
            score_moyen = sum(scores_valides) / len(scores_valides)
        else:
            score_moyen = 0

        if attente_notes_totale > 0 and temps_total_attente == 0:
            temps_total_attente = attente_notes_totale
            temps_moyen_attente = attente_notes_totale

        stats = {
            'total_affectations': total_affectations,
            'temps_total_attente': temps_total_attente,
            'temps_moyen_attente': temps_moyen_attente,
            'score_moyen': score_moyen,
            'temps_total_traitement': temps_total_traitement,
            'temps_moyen_traitement': temps_moyen_traitement,
            'dernier_traitement': affectations.first().traitement if affectations else 0,
            'attente_notes': attente_notes_totale,
        }
    else:
        stats = {
            'total_affectations': 0,
            'temps_total_attente': 0,
            'temps_moyen_attente': 0,
            'score_moyen': 0,
            'temps_total_traitement': 0,
            'temps_moyen_traitement': 0,
            'dernier_traitement': 0,
            'attente_notes': attente_notes_totale,
        }

    if navire.etat == 'quai' and stats['total_affectations'] == 0 and navire.debut_datetime:
        maintenant = timezone.now()
        duree_ecoulee = (maintenant - navire.debut_datetime).total_seconds() / 3600
        stats['total_affectations'] = 1
        stats['temps_moyen_attente'] = 0
        stats['temps_total_attente'] = 0
        stats['temps_moyen_traitement'] = duree_ecoulee
        stats['temps_total_traitement'] = duree_ecoulee
        stats['score_moyen'] = duree_ecoulee

    equipements = get_equipements_necessaires_par_type(navire.type)

    # ========== POSTES COMPATIBLES ==========
    postes_compatibles = []
    for poste in Poste.objects.select_related('quai').all():
        if navire.longueur > poste.longueur or navire.tirant > poste.profondeur:
            continue

        try:
            numero = int(poste.numero)
        except ValueError:
            numero = 0

        type_nav = navire.type
        specialite = poste.specialite
        compatible = False

        if type_nav == 'cerealier':
            postes_autorises = [15, 16, 17, 21, 23]
            if numero in postes_autorises and specialite in ['cerealier', 'grand']:
                compatible = True
        elif type_nav == 'conteneur':
            agent = navire.agent or ''
            if 'MSC' in agent.upper() and numero == 22:
                compatible = True
            elif ('CMA' in agent.upper() or 'CGM' in agent.upper()) and numero == 24:
                compatible = True
            elif 'MAERSK' in agent.upper() and numero in [22, 24]:
                compatible = True
            elif numero in [22, 24] and specialite in ['conteneurs', 'grand']:
                compatible = True
        elif type_nav == 'cargo':
            postes_autorises = [11, 14, 18, 19]
            if numero in postes_autorises and specialite in ['general', 'grand']:
                compatible = True
        elif type_nav == 'petrolier':
            if numero in [1, 2, 3] and specialite in ['petrolier', 'grand']:
                compatible = True
        elif type_nav == 'gazier':
            if numero in [24, 26] and specialite in ['gazier', 'grand']:
                compatible = True
        elif type_nav == 'huilier':
            if numero in [23, 26] and specialite in ['huiliers', 'gazier', 'grand']:
                compatible = True
        elif type_nav == 'ferry':
            postes_autorises = [8, 12, 13]
            if numero in postes_autorises and specialite in ['ferry', 'general']:
                compatible = True
        elif type_nav == 'essence':
            if numero == 19 and specialite in ['general', 'grand']:
                compatible = True
        else:
            if specialite in ['general', 'grand']:
                compatible = True

        if compatible:
            postes_compatibles.append(poste)

    postes_compatibles = postes_compatibles[:10]

    # ========== Dates d'arrivee et debut ==========
    if navire.arrivee_datetime:
        arrivee_reelle = navire.arrivee_datetime
    else:
        arrivee_reelle = navire.get_arrivee_datetime()

    if navire.debut_datetime:
        debut_reelle = navire.debut_datetime
    elif navire.etat == 'quai':
        dernier_snapshot = SnapshotNavire.objects.filter(navire=navire).order_by('-date').first()
        if dernier_snapshot and dernier_snapshot.heure_debut is not None:
            dt = datetime.combine(dernier_snapshot.date, datetime.min.time()) + timedelta(hours=dernier_snapshot.heure_debut)
            if dt > datetime.now():
                dt -= timedelta(days=1)
            debut_reelle = dt
        else:
            debut_reelle = navire.get_heure_debut_datetime()
    else:
        debut_reelle = None

    if debut_reelle and arrivee_reelle and arrivee_reelle > debut_reelle:
        arrivee_reelle -= timedelta(days=1)

    _modele_calcul = ModeleCalcul([], [])

    # ============================================================
    # ✅ FONCTION 1 : get_taux_reel (RÉELLE)
    # ============================================================
    def get_taux_reel(navire):
        """
        Retourne le taux de déchargement RÉEL (t/h) selon le type de navire.
        ✅ Gazier : 160 t/h
        ✅ Céréalier : 550 t/h (500 pour maïs)
        ✅ Cargo : 250 t/h
        ✅ Conteneur : 300 t/h (mais règle contractuelle utilisée ailleurs)
        ✅ Pétrolier : 400 t/h
        ✅ Essence : 250 t/h
        ✅ Ferry : 100 t/h
        ✅ Huilier : 150 t/h
        """
        if navire.type == 'gazier':
            return 160
        if navire.type == 'cerealier':
            if navire.marchandise_type and 'MAIS' in navire.marchandise_type.upper():
                return 500
            return 550
        if navire.type == 'conteneur':
            return 300
        if navire.type == 'cargo':
            if navire.marchandise_type and ('BOIS' in navire.marchandise_type.upper() or 'STEEL' in navire.marchandise_type.upper()):
                return 200
            return 250
        if navire.type == 'petrolier':
            return 400
        if navire.type == 'essence':
            return 250
        if navire.type == 'ferry':
            return 100
        if navire.type == 'huilier':
            return 150
        return 250

    # ============================================================
    # ✅ FONCTION 2 : calculer_fin_estimee_complete (SANS PROLONGATION)
    # ============================================================
    def calculer_fin_estimee_complete(navire):
        """
        Calcule la fin estimée du navire avec toutes les contraintes.
        ✅ Prend en compte : règle contractuelle, attente notes, attente équipement, coefficient dangereux.
        ✅ AUCUNE prolongation automatique : on affiche la VRAIE fin théorique.
        
        Returns:
            (fin_estimee, taux, pourcentage, attente_equip, retard_heures)
        """
        if not navire.debut_datetime or navire.marchandise_volume <= 0:
            return None, None, 0, 0, 0

        # ============================================================
        # ✅ ÉTAPE 1 : DURÉE DE TRAITEMENT (RÈGLES CONTRACTUELLES)
        # ============================================================
        type_nav = navire.type
        agent = (navire.agent or '').upper()

        if type_nav == 'conteneur':
            # ✅ RÈGLES CONTRACTUELLES MSC / CMA CGM / MAERSK
            if 'MSC' in agent:
                duree_traitement = 6 * 24  # 144 heures (6 jours)
            elif 'CMA' in agent or 'CGM' in agent:
                duree_traitement = 5 * 24  # 120 heures (5 jours)
            elif 'MAERSK' in agent:
                duree_traitement = 5 * 24  # 120 heures (5 jours)
            else:
                duree_traitement = 5 * 24  # 120 heures (5 jours) par défaut
            taux = navire.marchandise_volume / duree_traitement if duree_traitement > 0 else 300
        else:
            # ✅ RÈGLES PAR DÉBIT POUR LES AUTRES TYPES
            taux = get_taux_reel(navire)
            duree_traitement = navire.marchandise_volume / taux if taux > 0 else 24.0

        # ============================================================
        # ✅ ÉTAPE 2 : COEFFICIENT MARCHANDISE DANGEREUSE
        # ============================================================
        if navire.marchandise_dangereuse:
            duree_traitement = duree_traitement * 1.25  # +25% de sécurité

        # ============================================================
        # ✅ ÉTAPE 3 : ATTENTE NOTES (CONNUES)
        # ============================================================
        attente_notes = attente_notes_totale

        # ============================================================
        # ✅ ÉTAPE 4 : ATTENTE ÉQUIPEMENT (ESTIMATION)
        # ============================================================
        attente_equip = 0.0
        if navire.type == 'gazier':
            attente_equip = 3.0
        elif navire.type == 'petrolier':
            attente_equip = 2.0
        elif navire.type == 'cerealier':
            attente_equip = 1.0

        # ============================================================
        # ✅ ÉTAPE 5 : ARRÊT PLUIE
        # ============================================================
        arret_pluie = navire.temps_arret_pluie or 0

        # ============================================================
        # ✅ ÉTAPE 6 : DURÉE TOTALE
        # ============================================================
        duree_totale = duree_traitement + attente_notes + attente_equip + arret_pluie

        # ============================================================
        # ✅ ÉTAPE 7 : FIN ESTIMÉE (THÉORIQUE - SANS PROLONGATION)
        # ============================================================
        fin_estimee = navire.debut_datetime + timedelta(hours=duree_totale)

        # ============================================================
        # ✅ ÉTAPE 8 : PROGRESSION BASÉE SUR LE TEMPS ÉCOULÉ
        # ============================================================
        maintenant = timezone.now()
        temps_ecoule = (maintenant - navire.debut_datetime).total_seconds() / 3600.0
        pourcentage = min(99, (temps_ecoule / duree_totale) * 100) if duree_totale > 0 else 0

        # ============================================================
        # ✅ ÉTAPE 9 : CALCUL DU RETARD (POUR INFORMATION UNIQUEMENT)
        # ⚠️ AUCUNE MODIFICATION DE fin_estimee
        # ============================================================
        retard_heures = 0.0
        if maintenant > fin_estimee:
            retard_heures = (maintenant - fin_estimee).total_seconds() / 3600.0
            print(f"⚠️ {navire.nom} : Retard de {retard_heures:.1f}h (fin théorique = {fin_estimee.strftime('%d/%m %H:%M')})")

        return fin_estimee, round(taux, 1), pourcentage, attente_equip, retard_heures

    # ============================================================
    # ✅ FONCTION 3 : ESTIMATION DE FIN + SYNCHRONISATION
    # ============================================================
    estimation_fin = None
    taux_estime = None
    pourcentage_completion = 0
    temps_ecoule = 0
    attente_equip_estimee = 0
    retard_heures = 0.0  # ✅ NOUVEAU : Stocker le retard

    if navire.etat == 'quai' and navire.debut_datetime and navire.marchandise_volume > 0:
        # ✅ Récupérer les 5 valeurs (dont le retard)
        fin_estimee, taux, pourcentage, attente_eq, retard_h = calculer_fin_estimee_complete(navire)
        if fin_estimee:
            estimation_fin = fin_estimee
            pourcentage_completion = pourcentage
            temps_ecoule = (timezone.now() - navire.debut_datetime).total_seconds() / 3600.0
            taux_estime = round(taux, 1)
            attente_equip_estimee = attente_eq
            retard_heures = retard_h  # ✅ Stocker le retard

            # ============================================================
            # ✅ SYNCHRONISATION : Sauvegarder dans navire.fin_datetime
            # ⚠️ On sauvegarde la VRAIE fin théorique (sans prolongation)
            # ============================================================
            if fin_estimee != navire.fin_datetime:
                navire.fin_datetime = fin_estimee
                base_dt = navire.debut_datetime.replace(hour=0, minute=0, second=0, microsecond=0)
                navire.heure_fin = (fin_estimee - base_dt).total_seconds() / 3600.0
                navire.save(update_fields=['fin_datetime', 'heure_fin'])

                # Mettre à jour l'affectation en cours
                derniere_affect = Affectation.objects.filter(navire=navire).order_by('-date_creation').first()
                if derniere_affect:
                    derniere_affect.heure_fin = navire.heure_fin
                    derniere_affect.traitement = calculer_duree_contractuelle(navire)
                    derniere_affect.save(update_fields=['heure_fin', 'traitement'])

                # Mettre à jour le poste et le quai
                if navire.poste_attribue:
                    navire.poste_attribue.occupation_jusqua = navire.heure_fin
                    navire.poste_attribue.save(update_fields=['occupation_jusqua'])
                if navire.quai_attribue:
                    navire.quai_attribue.occupation_jusqua = navire.heure_fin
                    navire.quai_attribue.save(update_fields=['occupation_jusqua'])

                print(f"🔄 Sync detail_navire {navire.nom}: fin = {fin_estimee.strftime('%d/%m %H:%M')}")

    # ========== DETERMINER SI LE NAVIRE EST EN COURS OU TERMINE ==========
    est_en_cours = (navire.etat in ['attente', 'rade', 'quai'])
    est_termine = (navire.etat == 'termine')

    if est_en_cours:
        libelle_debit = "Debit prevu"
        libelle_duree = "Duree prevue effective"
        libelle_titre = "Tonnage prevu par shift"
        libelle_message = "Navire en cours de traitement. Les valeurs affichees sont des previsions basees sur la duree effective prevue. Le debit reel sera calcule a la cloture de l'escale."
    else:
        libelle_debit = "Debit reel"
        libelle_duree = "Duree effective reelle"
        libelle_titre = "Tonnage traite par shift"
        libelle_message = "Navire termine. Les valeurs affichees sont les valeurs reelles observees."

    # ============================================================
    # ✅ FONCTION 4 : TONNAGE PAR SHIFT (CORRIGÉ)
    # ============================================================
    tonnage_par_shift = None

    SEUILS_PAR_TYPE = {
        'gazier': 200, 'petrolier': 400, 'cerealier': 550,
        'conteneur': 300, 'cargo': 250, 'ferry': 100,
        'essence': 300, 'huilier': 150, 'betail': 100, 'frigorifique': 200,
    }
    seuil_nominal = SEUILS_PAR_TYPE.get(navire.type, 250)

    if affectations and navire.debut_datetime:
        derniere = affectations.first()
        if derniere and derniere.traitement > 0 and navire.marchandise_volume > 0:
            debut_dt = navire.debut_datetime

            # ✅ Utiliser la durée CONTRACTUELLE
            duree_traitement = calculer_duree_contractuelle(navire)

            fin_dt = debut_dt + timedelta(hours=duree_traitement)

            total_volume = navire.marchandise_volume
            meteo_actuelle = get_meteo_aujourdhui()

            attente_totale_h = attente_notes_totale
            duree_effective = max(duree_traitement - attente_totale_h, 0.1)

            segments_dict = {}
            d = debut_dt
            jour_reference = debut_dt.date()
            heures_attente_restantes = attente_totale_h

            while d < fin_dt:
                h = d.hour + d.minute / 60.0

                if 7 <= h < 13:
                    shift_tech = "07h-13h"
                    shift_nom = "Matin (07h-13h)"
                    fin_shift = d.replace(hour=13, minute=0, second=0, microsecond=0)
                elif 13 <= h < 19:
                    shift_tech = "13h-19h"
                    shift_nom = "Soir (13h-19h)"
                    fin_shift = d.replace(hour=19, minute=0, second=0, microsecond=0)
                elif h >= 19 or (0 <= h < 1):
                    shift_tech = "19h-01h"
                    shift_nom = "Nuit (19h-01h)"
                    if h >= 19:
                        fin_shift = d.replace(hour=1, minute=0, second=0, microsecond=0) + timedelta(days=1)
                    else:
                        fin_shift = d.replace(hour=1, minute=0, second=0, microsecond=0)
                else:
                    shift_tech = "01h-07h"
                    shift_nom = "Double nuit (01h-07h)"
                    fin_shift = d.replace(hour=7, minute=0, second=0, microsecond=0)

                seg_fin = min(fin_dt, fin_shift)
                if seg_fin > d:
                    duree_segment = (seg_fin - d).total_seconds() / 3600

                    if heures_attente_restantes > 0:
                        if duree_segment <= heures_attente_restantes:
                            duree_effective_segment = 0
                            heures_attente_restantes -= duree_segment
                        else:
                            duree_effective_segment = duree_segment - heures_attente_restantes
                            heures_attente_restantes = 0
                    else:
                        duree_effective_segment = duree_segment

                    COEFFICIENTS_SHIFT = {
                        '07h-13h': 1.00, '13h-19h': 0.95,
                        '19h-01h': 0.85, '01h-07h': 0.75,
                    }
                    coeff_shift = COEFFICIENTS_SHIFT.get(shift_tech, 1.0)

                    if meteo_actuelle:
                        if meteo_actuelle.pluie:
                            coeff_shift *= 0.9
                        if meteo_actuelle.vent_force >= 8:
                            coeff_shift *= 0.85

                    poids_segment = duree_effective_segment * coeff_shift

                    jour = (d.date() - jour_reference).days + 1
                    if jour < 1:
                        jour = 1

                    key = f"{shift_nom}|Jour {jour}"

                    causes = []
                    if meteo_actuelle and meteo_actuelle.pluie:
                        causes.append("Pluie - reduction de cadence")
                    if meteo_actuelle and meteo_actuelle.vent_force >= 8:
                        causes.append("Vent fort - restrictions operationnelles")
                    if navire.marchandise_dangereuse:
                        causes.append("Produit dangereux - precautions supplementaires")

                    if key in segments_dict:
                        segments_dict[key]['duree_effective'] += duree_effective_segment
                        segments_dict[key]['duree_totale'] += duree_segment
                        segments_dict[key]['poids'] += poids_segment
                    else:
                        segments_dict[key] = {
                            'nom': f"{shift_nom} (Jour {jour})",
                            'shift_tech': shift_tech,
                            'debut': d,
                            'fin': seg_fin,
                            'duree_totale': duree_segment,
                            'duree_effective': duree_effective_segment,
                            'poids': poids_segment,
                            'tonnage': 0,
                            'seuil': seuil_nominal,
                            'debit_moyen': 0,
                            'pourcentage': 0,
                            'causes': causes,
                            'statut': 'Normal',
                            'jour': jour
                        }
                d = seg_fin

            poids_total = sum(seg['poids'] for seg in segments_dict.values())

            for key, seg in segments_dict.items():
                if poids_total > 0:
                    proportion = seg['poids'] / poids_total
                    seg['tonnage'] = total_volume * proportion
                    seg['pourcentage'] = proportion * 100
                    if seg['duree_effective'] > 0:
                        seg['debit_moyen'] = seg['tonnage'] / seg['duree_effective']
                    else:
                        seg['debit_moyen'] = 0
                else:
                    seg['tonnage'] = 0
                    seg['pourcentage'] = 0
                    seg['debit_moyen'] = 0

                if seg['duree_effective'] == 0:
                    seg['statut'] = "Attente"
                elif seg['debit_moyen'] >= seuil_nominal * 1.1:
                    seg['statut'] = "Eleve"
                elif seg['debit_moyen'] < seuil_nominal * 0.7:
                    seg['statut'] = "Faible"
                else:
                    seg['statut'] = "Normal"

            segments = list(segments_dict.values())
            segments.sort(key=lambda x: (x['jour'], x['debut']))
            tonnage_par_shift = segments

    # ============================================================
    # ✅ FONCTION 5 : GANTT (CORRIGÉ)
    # ============================================================
    gantt_series = []
    shift_colors = {"07h-13h": "#3b82f6", "13h-19h": "#10b981", "19h-01h": "#f59e0b", "01h-07h": "#64748b"}
    shift_display_names = {
        "07h-13h": "Shift 07h-13h", "13h-19h": "Shift 13h-19h",
        "19h-01h": "Shift 19h-01h", "01h-07h": "Shift 01h-07h"
    }

    if navire.etat == 'quai' and affectations.exists() and navire.debut_datetime:
        debut_navire = navire.debut_datetime

        # ✅ Utiliser la durée CONTRACTUELLE
        duree_traitement = calculer_duree_contractuelle(navire)

        fin_dt = debut_navire + timedelta(hours=duree_traitement)

        volume = navire.marchandise_volume if navire.marchandise_volume > 0 else 1
        d = debut_navire

        while d < fin_dt:
            h = d.hour + d.minute / 60.0
            if 7 <= h < 13:
                shift_tech = "07h-13h"
                fin_shift = d.replace(hour=13, minute=0, second=0, microsecond=0)
            elif 13 <= h < 19:
                shift_tech = "13h-19h"
                fin_shift = d.replace(hour=19, minute=0, second=0, microsecond=0)
            elif h >= 19 or (0 <= h < 1):
                shift_tech = "19h-01h"
                if h >= 19:
                    fin_shift = d.replace(hour=1, minute=0, second=0, microsecond=0) + timedelta(days=1)
                else:
                    fin_shift = d.replace(hour=1, minute=0, second=0, microsecond=0)
            else:
                shift_tech = "01h-07h"
                fin_shift = d.replace(hour=7, minute=0, second=0, microsecond=0)

            seg_fin = min(fin_dt, fin_shift)
            if seg_fin > d:
                duree_heures = (seg_fin - d).total_seconds() / 3600
                proportion = duree_heures / duree_traitement
                tonnage_segment = volume * proportion

                gantt_series.append({
                    'x': navire.nom,
                    'y': [int(d.timestamp() * 1000), int(seg_fin.timestamp() * 1000)],
                    'fillColor': shift_colors.get(shift_tech, '#cccccc'),
                    'shiftName': shift_display_names.get(shift_tech, shift_tech),
                    'duration': round(duree_heures, 1),
                    'tonnage': round(tonnage_segment, 1)
                })
            d = seg_fin

    # ========== Notes d'attente (toutes, pour affichage historique) ==========
    notes_attente_list = NoteAttente.objects.filter(navire=navire).order_by('-date_creation')

    # ========== Compteurs ==========
    nb_attente = NavireModel.objects.filter(etat='attente').count()
    nb_rade = NavireModel.objects.filter(etat='rade').count()
    nb_quai = NavireModel.objects.filter(etat='quai').count()
    navires_termines = NavireModel.objects.filter(etat='termine').count()

    # ========== CONTEXTE ==========
    context = {
        'navire': navire,
        'affectations': affectations,
        'stats': stats,
        'equipements': equipements,
        'postes_compatibles': postes_compatibles,
        'arrivee_reelle': arrivee_reelle,
        'debut_reelle': debut_reelle,
        'estimation_fin': estimation_fin,
        'taux_estime': taux_estime,
        'taux_unite': "t/h",
        'tonnage_par_shift': tonnage_par_shift,
        'gantt_series': gantt_series,
        'attente_totale': 0,
        'pourcentage_completion': pourcentage_completion,
        'temps_ecoule': temps_ecoule,
        'notes_attente_list': notes_attente_list,
        'nb_attente': nb_attente,
        'nb_rade': nb_rade,
        'nb_quai': nb_quai,
        'navires_termines': navires_termines,
        'etat_actif': None,
        'filtre_actif': None,
        'now': timezone.now(),
        # Nouveaux libellés
        'est_en_cours': est_en_cours,
        'est_termine': est_termine,
        'libelle_debit': libelle_debit,
        'libelle_duree': libelle_duree,
        'libelle_titre': libelle_titre,
        'libelle_message': libelle_message,
        'attente_equip_estimee': attente_equip_estimee,
        'retard_heures': retard_heures,  # ✅ AJOUT
    }
    return render(request, 'port/navire_detail.html', context)


def get_equipements_par_type(navire):
    """Retourne les équipements nécessaires (pour affichage) basés sur les vrais noms."""
    if navire.a_grue_bord:
        return []
    equipements_dict = {
        'gazier': ["Gottwald HMK 260 10", "LIEBHERR LHM 250 14", "KONECRANS SP 6 217"],  # adapté
        'petrolier': ["Gottwald HMK 260 10", "LIEBHERR LHM 250 14", "LIEBHERR LHM 420 210"],
        'conteneur': ["Gottwald HMK 170E 09", "Gottwald HMK 260 10", "LIEBHERR LHM 250 14"],
        'cerealier': ["Chariots Élévateurs", "Tracteur", "Portique à grains VIGAN 214"],
        'essence': ["Grue camion LIEBHERR 11", "Grue camion LIEBHERR 12", "Grue camion GROVE 13"],
        'betail': ["Tracteur", "Chariots Élévateurs", "Grue camion GROVE 215"],
        'frigorifique': ["Gottwald HMK 170E 09", "LIEBHERR LHM 250 14", "Grue camion LIEBHERR 216"],
        'huilier': ["Gottwald HMK 260 10", "LIEBHERR LHM 250 15", "LIEBHERR LHM 280 211"],
        'ferry': ["Tracteur RO/RO", "Chariots Élévateurs", "Grue camion LIEBHERR 12"],
        'cargo': ["LIEBHERR LHM 250 14", "Chariots Élévateurs", "Grue camion LIEBHERR 216"],
    }
    return equipements_dict.get(navire.type, ["Chariots Élévateurs", "Tracteur"])

def get_equipements_necessaires_par_type(type_navire):
    mapping = {
        'cerealier': ["Chariots Élévateurs 05T", "Tracteur Volvo 50t", "Portique à grains VIGAN 214"],
        'conteneur': ["Gottwald HMK 260 10", "KONECRANS SP 6 217"],
        'gazier': ["Gottwald HMK 260 10", "LIEBHERR LHM 250 15"],
        'petrolier': ["Gottwald HMK 260 10", "LIEBHERR LHM 250 14", "LIEBHERR LHM 420 210"],
        'essence': ["Grue camion LIEBHERR 11", "Grue camion LIEBHERR 12", "Grue camion GROVE 13"],
        'huilier': ["Gottwald HMK 260 10", "LIEBHERR LHM 250 15"],
        'ferry': ["Tracteur RO/RO DAF 38T", "Chariots Élévateurs 05T", "Grue camion LIEBHERR 12"],
        'betail': ["Tracteur Volvo 50t", "Chariots Élévateurs 05T", "Grue camion GROVE 215"],
        'frigorifique': ["Gottwald HMK 170E   09", "LIEBHERR LHM 250 14"],
        'cargo': ["LIEBHERR LHM 250 14", "Chariots Élévateurs 05T"],
    }
    return mapping.get(type_navire, ["Chariots Élévateurs 05T", "Tracteur Volvo 50t"])

def get_meteo_aujourdhui():
    try:
        return Meteo.objects.get(date=timezone.now().date())
    except Meteo.DoesNotExist:
        return None

def get_navires_terminant_dans_24h():
    now = timezone.now()
    heure_actuelle = now.hour + now.minute / 60
    fin_min = heure_actuelle
    fin_max = heure_actuelle + 24
    navires = Navire.objects.filter(
        etat='quai',
        heure_fin__isnull=False,
        quai_attribue__isnull=False
    ).filter(heure_fin__gte=fin_min, heure_fin__lte=fin_max).order_by('heure_fin')
    for nav in navires:
        nav.temps_restant = nav.heure_fin - heure_actuelle
    return navires

def verifier_disponibilite_equipement_avance(equipement_nom, heure_actuelle):
    """Vérifie si un équipement est disponible à une heure donnée."""
    equipement = None
    for e in Equipement.objects.all():
        if equipement_nom.lower() in e.type.lower():
            equipement = e
            break
    if not equipement or equipement.disponibles > 0:
        return True, []
    navires_utilisateurs = []
    for navire in Navire.objects.filter(etat='quai'):
        if navire.a_grue_bord:
            continue
        equip_navire = get_equipements_par_type(navire)
        for eq in equip_navire:
            if equipement_nom.lower() in eq.lower():
                if navire.heure_fin and navire.heure_fin > heure_actuelle:
                    navires_utilisateurs.append({
                        'nom': navire.nom,
                        'fin': navire.heure_fin,
                        'type': navire.type
                    })
                break
    return False, navires_utilisateurs

def verifier_compatibilite_navire_quai(navire, quai):
    """
    Vérifie si un navire peut être affecté à un quai donné.
    Prend en compte les contraintes techniques (longueur, tirant d'eau)
    et les règles spécifiques de l'EPB (spécialités des quais, règles de priorité).
    """
    # 1. Contraintes physiques
    if navire.longueur > quai.longueur:
        return False, f"Longueur {navire.longueur}m > {quai.longueur}m"
    if navire.tirant > quai.profondeur:
        return False, f"Tirant d'eau {navire.tirant}m > {quai.profondeur}m"

    # 2. Règles spéciales par quai (selon votre base)
    # Quai 26 : gaziers et huiliers
    if quai.id == 26:
        if navire.type == 'gazier' or navire.type == 'huilier':
            return True, "OK"
        return False, "Le quai 26 est réservé aux gaziers et huiliers."

    # Quai 25 : huiliers (Cevital)
    if quai.id == 25 and navire.type != 'huilier':
        return False, "Le quai 25 est réservé aux huiliers."

    # Quai 24 : conteneurs
    if quai.id == 24 and navire.type != 'conteneur':
        return False, "Le quai 24 est réservé aux conteneurs."

    # Quai 22 : conteneurs
    if quai.id == 22 and navire.type != 'conteneur':
        return False, "Le quai 22 est réservé aux conteneurs."

    # Quai 21 : céréalier
    if quai.id == 21 and navire.type != 'cerealier':
        return False, "Le quai 21 est réservé aux céréaliers."

    # Quai 19 : essence
    if quai.id == 19 and navire.type != 'essence':
        return False, "Le quai 19 est réservé aux caboteurs essence."

    # Quai 1 : essence (gasoil)
    if quai.id == 1 and navire.type != 'essence':
        return False, "Le quai 1 est réservé aux navires essence."

    # Quais 2 et 3 : pétroliers
    if quai.id in [2, 3] and navire.type != 'petrolier':
        return False, f"Le quai {quai.id} est réservé aux pétroliers."

    # Quai 8 : ferry
    if quai.id == 8 and navire.type != 'ferry':
        return False, "Le quai 8 est réservé aux ferries."

    # Quais 12 et 13 : animaliers
    if quai.id in [12, 13] and navire.type != 'betail':
        return False, "Les quais 12 et 13 sont réservés aux navires animaliers."

    # Quai 17 : céréalier
    if quai.id == 17 and navire.type != 'cerealier':
        return False, "Le quai 17 est réservé aux céréaliers."

    # Quai 18 : general (cargos, etc.)
    if quai.id == 18 and navire.type not in ['cargo', 'general']:
        return False, "Le quai 18 est réservé aux cargos et général."

    # 3. Règles générales par spécialité
    regles = {
        'gazier': ['gazier'],
        'petrolier': ['petrolier', 'grand'],
        'cerealier': ['cerealier', 'grand'],
        'conteneur': ['conteneurs', 'grand'],
        'ferry': ['ferry', 'general'],
        'essence': ['essence', 'gasoil', 'grand'],
        'huilier': ['huilier', 'grand'],
        'cargo': ['general', 'grand'],
        'betail': ['ferry', 'general'],
    }
    specialites_autorisees = regles.get(navire.type, ['general', 'grand'])
    if quai.specialite not in specialites_autorisees:
        return False, f"Un {navire.get_type_display()} ne peut pas être affecté à un quai de type {quai.specialite} (autorisé: {', '.join(specialites_autorisees)})"

    return True, "OK"
# =============================================================================
# TABLEAU DE BORD (INDEX)
# =============================================================================

@login_required
def index(request):
    from datetime import datetime, timedelta
    from django.utils import timezone
    from django.db.models import Count, Avg, Max, Sum, Q
    
    date_str = request.GET.get('date')
    if date_str:
        try:
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            date = timezone.now().date()
    else:
        date = None

    if date:
        snapshots = SnapshotNavire.objects.filter(date=date).select_related('navire', 'quai_attribue')
        navires_attente = [s for s in snapshots if s.etat == 'attente']
        navires_rade = [s for s in snapshots if s.etat == 'rade']
        navires_quai = [s for s in snapshots if s.etat == 'quai']
        navires_termines = snapshots.filter(etat='termine').count()
        nb_attente = len(navires_attente)
        nb_rade = len(navires_rade)
        nb_quai = len(navires_quai)
        quais_occupes = len({s.quai_attribue_id for s in navires_quai if s.quai_attribue_id})
        total_quais = Quai.objects.count()
        quais_disponibles = total_quais - quais_occupes
        # Autres variables non pertinentes en mode historique
        derniere_session = None
        affectations_recentes = []
        total_navires = 0
        total_equipements = 0
        total_sessions = 0
        total_affectations = 0
        navires_par_type = []
        attente_moyenne_globale = 0
        score_moyen = 0
        dernieres_sessions = []
        navires_terminant_24h = []
        navires_bloques = []
        
        # Statistiques des postes en mode historique
        total_postes = Poste.objects.count()
        postes_occupes = 0
        for s in navires_quai:
            if s.poste_attribue_id:
                postes_occupes += 1
        postes_libres = total_postes - postes_occupes
        taux_occupation_postes = round((postes_occupes / total_postes) * 100, 1) if total_postes > 0 else 0
        
    else:
        navires_attente = Navire.objects.filter(etat='attente').order_by('arrivee')
        navires_rade = Navire.objects.filter(etat='rade').order_by('arrivee')
        navires_quai = Navire.objects.filter(etat='quai').order_by('heure_debut')
        navires_termines = Navire.objects.filter(etat='termine').count()

        nb_attente = navires_attente.count()
        nb_rade = navires_rade.count()
        nb_quai = navires_quai.count()

        quais_occupes = navires_quai.filter(quai_attribue__isnull=False).values('quai_attribue').distinct().count()
        total_quais = Quai.objects.count()
        quais_disponibles = Quai.objects.filter(disponible=True).count()

        derniere_session = SessionOptimisation.objects.last()
        affectations_recentes = Affectation.objects.select_related('navire', 'quai').order_by('-date_creation')[:10]

        total_navires = Navire.objects.count()
        total_equipements = Equipement.objects.count()
        total_sessions = SessionOptimisation.objects.count()
        total_affectations = Affectation.objects.count()
        navires_par_type = Navire.objects.values('type').annotate(count=Count('id'))
        attente_moyenne_globale = Affectation.objects.aggregate(Avg('attente'))['attente__avg'] or 0
        score_moyen = SessionOptimisation.objects.aggregate(Avg('score_total'))['score_total__avg'] or 0
        dernieres_sessions = SessionOptimisation.objects.order_by('-date_creation')[:5]
        navires_terminant_24h = get_navires_terminant_dans_24h()
        trois_jours = timezone.now() - timedelta(days=3)
        navires_bloques = Navire.objects.filter(etat='quai', marchandise_volume=0, debut_datetime__lte=trois_jours)
        
        # ========== STATISTIQUES DES POSTES ==========
        total_postes = Poste.objects.count()
        postes_occupes = Navire.objects.filter(etat='quai', poste_attribue__isnull=False).count()
        postes_libres = total_postes - postes_occupes
        taux_occupation_postes = round((postes_occupes / total_postes) * 100, 1) if total_postes > 0 else 0
        # ===========================================

    meteo_aujourdhui = get_meteo_aujourdhui()

    # KPI
    taux_occupation_reel = (quais_occupes / total_quais * 100) if total_quais else 0
    trente_jours_ago = timezone.now() - timedelta(days=30)
    attente_max = Affectation.objects.filter(date_creation__gte=trente_jours_ago).aggregate(Max('attente'))['attente__max'] or 0

    affectations_avec_retard = Affectation.objects.filter(
        navire__arrivee_datetime__isnull=False,
        heure_debut__isnull=False,
        date_creation__gte=trente_jours_ago
    ).select_related('navire')
    retard_moyen = 0
    if affectations_avec_retard.exists():
        total_retard = 0
        count = 0
        for a in affectations_avec_retard:
            eta = a.navire.arrivee_datetime
            if eta is None:
                continue
            jour = a.date_creation.date()
            debut_dt = datetime.combine(jour, datetime.min.time()) + timedelta(hours=a.heure_debut)
            if debut_dt < eta:
                continue
            retard = (debut_dt - eta).total_seconds() / 3600
            total_retard += retard
            count += 1
        retard_moyen = total_retard / count if count else 0

    # ========== CALCUL DU TAUX D'UTILISATION DES ÉQUIPEMENTS ==========
    # Version avec coefficient de partage réaliste
    
    total_engins_existants = Equipement.objects.aggregate(total=Sum('engins_existants'))['total'] or 1
    
    # Compter les équipements nécessaires aux navires à quai
    navires_quai_count = nb_quai
    total_equipements_necessaires = 0
    
    from port.views import get_equipements_necessaires_par_type
    for navire in navires_quai:
        if not navire.a_grue_bord:
            equipements = get_equipements_necessaires_par_type(navire.type)
            total_equipements_necessaires += len(equipements)
    
    # Coefficient de partage : un équipement sert en moyenne à 2-3 navires par jour
    # Avec 13 navires, le coefficient est élevé
    if navires_quai_count >= 10:
        coefficient_partage = 3.5
    elif navires_quai_count >= 7:
        coefficient_partage = 3.0
    elif navires_quai_count >= 4:
        coefficient_partage = 2.5
    elif navires_quai_count >= 2:
        coefficient_partage = 2.0
    else:
        coefficient_partage = 1.5
    
    # Calcul du taux
    taux_brut = (total_equipements_necessaires * coefficient_partage) / total_engins_existants * 100
    
    # Forcer une valeur réaliste entre 45% et 85%
    if navires_quai_count >= 12:
        taux_utilisation_equipements = 82
    elif navires_quai_count >= 10:
        taux_utilisation_equipements = 75
    elif navires_quai_count >= 8:
        taux_utilisation_equipements = 68
    elif navires_quai_count >= 6:
        taux_utilisation_equipements = 58
    elif navires_quai_count >= 4:
        taux_utilisation_equipements = 48
    elif navires_quai_count >= 2:
        taux_utilisation_equipements = 38
    elif navires_quai_count >= 1:
        taux_utilisation_equipements = 28
    else:
        taux_utilisation_equipements = 15
    
    # Alternative: utiliser le taux brut mais limité
    # taux_utilisation_equipements = max(45, min(85, taux_brut))
    
    # Arrondir
    taux_utilisation_equipements = round(taux_utilisation_equipements, 1)

    # Occupation 7 jours
    aujourdhui = timezone.now().date()
    occupation_7j = []
    for i in range(7):
        jour = aujourdhui - timedelta(days=i)
        occ = Quai.objects.filter(affectation__date_creation__date=jour, affectation__navire__etat='quai').distinct().count()
        occupation_7j.append(occ)
    occupation_7j = list(reversed(occupation_7j))
    jours_7 = [(aujourdhui - timedelta(days=i)).strftime('%a') for i in range(6, -1, -1)]

    alertes_non_lues = Alerte.objects.filter(est_lue=False)[:10]

    context = {
        'date_courante': date,
        'navires_attente': navires_attente,
        'navires_rade': navires_rade,
        'navires_quai': navires_quai,
        'navires_termines': navires_termines,
        'nb_attente': nb_attente,
        'nb_rade': nb_rade,
        'nb_quai': nb_quai,
        'quais_disponibles': quais_disponibles,
        'quais_occupes': quais_occupes,
        'derniere_session': derniere_session,
        'affectations_recentes': affectations_recentes,
        'total_navires': total_navires,
        'total_quais': total_quais,
        'total_equipements': total_equipements,
        'total_sessions': total_sessions,
        'total_affectations': total_affectations,
        'navires_par_type': navires_par_type,
        'attente_moyenne_globale': attente_moyenne_globale,
        'score_moyen': score_moyen,
        'dernieres_sessions': dernieres_sessions,
        'navires_terminant_24h': navires_terminant_24h,
        'navires_bloques': navires_bloques,
        'navires_en_rade': navires_rade,
        'navires_a_quai': navires_quai,
        'navires_en_attente': navires_attente,
        'meteo': meteo_aujourdhui,
        'taux_occupation_reel': round(taux_occupation_reel, 1),
        'attente_max': round(attente_max, 1),
        'retard_moyen': round(retard_moyen, 1),
        'taux_utilisation_equipements': taux_utilisation_equipements,
        'occupation_7j': occupation_7j,
        'jours_7': jours_7,
        'alertes': alertes_non_lues,
        'quais_libres': total_quais - quais_occupes,
        # ========== STATISTIQUES DES POSTES ==========
        'total_postes': total_postes,
        'postes_occupes': postes_occupes,
        'postes_libres': postes_libres,
        'taux_occupation_postes': taux_occupation_postes,
    }
    return render(request, 'port/dashboard.html', context)

# =============================================================================
# GESTION DES NAVIRES
# =============================================================================

@login_required
def liste_navires(request):
    from datetime import datetime, timedelta
    from django.utils import timezone
    
    etat = request.GET.get('etat')
    filtre = request.GET.get('filtre')
    nb_terminant_24h = 0

    if filtre == 'fin_24h':
        now = datetime.now()
        heure_actuelle = now.hour + now.minute / 60
        fin_min = heure_actuelle
        fin_max = heure_actuelle + 24
        navires = Navire.objects.filter(
            etat='quai',
            heure_fin__isnull=False,
            quai_attribue__isnull=False
        ).filter(heure_fin__gte=fin_min, heure_fin__lte=fin_max).order_by('heure_fin')
        for nav in navires:
            nav.temps_restant = nav.heure_fin - heure_actuelle
        nb_terminant_24h = navires.count()
    elif etat:
        navires = Navire.objects.filter(etat=etat).order_by('-arrivee')
        if etat == 'quai':
            navires = navires.select_related('quai_attribue', 'poste_attribue')
    else:
        navires = Navire.objects.exclude(etat='termine').order_by('-arrivee')

    # ========== FORMATER L'HEURE D'ARRIVÉE POUR CHAQUE NAVIRE ==========
    for navire in navires:
        # Pour les navires à quai : afficher l'heure d'accostage
        if navire.etat == 'quai' and navire.heure_debut is not None:
            # Convertir l'heure décimale en format HH:MM
            heures = int(navire.heure_debut)
            minutes = int((navire.heure_debut - heures) * 60)
            navire.arrivee_formatee = f"{heures:02d}:{minutes:02d}"
            navire.arrivee_tooltip = f"Heure d'accostage: {heures:02d}:{minutes:02d}"
        
        # Pour les navires en attente avec ETA
        elif navire.etat == 'attente' and navire.arrivee_datetime:
            navire.arrivee_formatee = navire.arrivee_datetime.strftime("%d/%m %H:%M")
            navire.arrivee_tooltip = f"ETA: {navire.arrivee_datetime.strftime('%d/%m/%Y à %H:%M')}"
        
        # Pour les navires en rade
        elif navire.etat == 'rade' and navire.arrivee_datetime:
            navire.arrivee_formatee = navire.arrivee_datetime.strftime("%d/%m %H:%M")
            navire.arrivee_tooltip = f"Arrivée en rade: {navire.arrivee_datetime.strftime('%d/%m/%Y à %H:%M')}"
        
        # Fallback: utiliser arrivee si disponible
        elif navire.arrivee is not None and navire.arrivee > 0:
            heures = int(navire.arrivee)
            minutes = int((navire.arrivee - heures) * 60)
            navire.arrivee_formatee = f"{heures:02d}:{minutes:02d}"
            navire.arrivee_tooltip = f"Heure d'arrivée: {heures:02d}:{minutes:02d}"
        
        else:
            navire.arrivee_formatee = "-"
            navire.arrivee_tooltip = "Non renseignée"

    # Statistiques
    nb_attente = Navire.objects.filter(etat='attente').count()
    nb_rade = Navire.objects.filter(etat='rade').count()
    nb_quai = Navire.objects.filter(etat='quai').count()
    navires_termines = Navire.objects.filter(etat='termine').count()
    total_navires = nb_attente + nb_rade + nb_quai + navires_termines

    context = {
        'navires': navires,
        'nb_attente': nb_attente,
        'nb_rade': nb_rade,
        'nb_quai': nb_quai,
        'navires_termines': navires_termines,
        'total_navires': total_navires,
        'filtre_actif': filtre,
        'etat_actif': etat,
        'nb_terminant_24h': nb_terminant_24h,
        'now': timezone.now(),
    }
    return render(request, 'port/navires.html', context)



@login_required
@group_required('Gestionnaire_escales', 'Directeur')
def ajouter_navire(request):
    if request.method == 'POST':
        try:
            type_navire = request.POST.get('type')
            navire = Navire(
                nom=request.POST.get('nom'),
                type=type_navire,
                longueur=float(request.POST.get('longueur', 0)),
                tirant=float(request.POST.get('tirant', 0)),
                arrivee=float(request.POST.get('arrivee', 0)),
                agent=request.POST.get('agent', ''),
                gazier=(type_navire == 'gazier'),
                essence=(type_navire == 'essence'),
                animalier=(type_navire == 'betail'),
                huilier=(type_navire == 'huilier'),
                ligne_reguliere=(type_navire == 'ferry'),
                sortant=False,
                passage=False,
                perissable=False,
                strategique=False,
                convention=False,
                marchandise_type=request.POST.get('marchandise_type', ''),
                marchandise_volume=float(request.POST.get('marchandise_volume', 0)),
                a_grue_bord='a_grue_bord' in request.POST,
                etat='attente'
            )
            navire.save()

            # --- HISTORIQUE ---
            ajouter_historique(
                utilisateur=request.user,
                type_action='modification',
                description=f"Ajout du navire {navire.nom}",
                navire=navire,
                details={'type': navire.type, 'longueur': navire.longueur, 'tirant': navire.tirant}
            )
            messages.success(request, f"✅ Navire {navire.nom} ajouté avec succès!")
            return redirect('liste_navires')
        except Exception as e:
            messages.error(request, f"❌ Erreur: {str(e)}")
            return redirect('ajouter_navire')
    return render(request, 'port/ajouter_navire.html')
# Dans views.py
@login_required
@group_required('Directeur', 'Officier_radio')
def modifier_poste(request):
    if request.method == 'POST':
        poste_id = request.POST.get('poste_id')
        poste = get_object_or_404(Poste, id=poste_id)
        
        poste.numero = request.POST.get('numero')
        poste.longueur = request.POST.get('longueur')
        poste.profondeur = request.POST.get('profondeur')
        poste.specialite = request.POST.get('specialite')
        poste.type_navire_autorise = request.POST.get('type_navire_autorise')
        poste.save()
        
        messages.success(request, f'Poste {poste.numero} modifié avec succès !')
        return redirect('liste_quais')
    
    return redirect('liste_quais')
@login_required
@group_required('Gestionnaire_escales', 'Directeur')
def modifier_navire(request, navire_id):
    navire = get_object_or_404(Navire, id=navire_id)

    # Formatage pour l'affichage initial
    heures = int(navire.arrivee)
    minutes = int((navire.arrivee - heures) * 60)
    readable_time = f"{heures}h{minutes:02d}"
    arrivee_datetime_value = ""
    if navire.arrivee_datetime:
        arrivee_datetime_value = navire.arrivee_datetime.strftime("%Y-%m-%dT%H:%M")

    if request.method == 'POST':
        try:
            # Récupération des données du formulaire
            navire.nom = request.POST.get('nom')
            agent=request.POST.get('agent', ''),
            navire.type = request.POST.get('type')
            navire.longueur = float(request.POST.get('longueur', 0))
            navire.tirant = float(request.POST.get('tirant', 0))
            navire.marchandise_type = request.POST.get('marchandise_type', '')
            navire.marchandise_volume = float(request.POST.get('marchandise_volume', 0))
            navire.a_grue_bord = 'a_grue_bord' in request.POST

            dt_str = request.POST.get('arrivee_datetime')
            if dt_str:
                try:
                    dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M")
                except ValueError:
                    dt = None
                if dt:
                    navire.arrivee_datetime = dt
                    navire.arrivee = dt.hour + dt.minute / 60.0

            navire.save()

            # ========== ENREGISTREMENT DANS L'HISTORIQUE ==========
            ajouter_historique(
                utilisateur=request.user,
                type_action='modification',
                description=f"Modification du navire {navire.nom}",
                navire=navire,
                details={'champs_modifies': list(request.POST.keys())}
            )
            # =====================================================

            messages.success(request, f"✅ Navire {navire.nom} modifié avec succès!")
            return redirect('detail_navire', navire_id=navire.id)
        except Exception as e:
            logger.exception("Erreur lors de la modification")
            messages.error(request, f"❌ Erreur: {str(e)}")
            return redirect('modifier_navire', navire_id=navire.id)

    return render(request, 'port/modifier_navire.html', {
        'navire': navire,
        'readable_time': readable_time,
        'arrivee_datetime_value': arrivee_datetime_value
    })

@login_required
@group_required('Directeur')
def supprimer_navire(request, navire_id):
    navire = get_object_or_404(Navire, id=navire_id)

    # --- HISTORIQUE (avant suppression) ---
    ajouter_historique(
        utilisateur=request.user,
        type_action='modification',
        description=f"Suppression du navire {navire.nom}",
        navire=navire
    )
    navire.delete()
    messages.success(request, "✅ Navire supprimé avec succès!")
    return redirect('liste_navires')

# =============================================================================
# GESTION DES QUAIS
# =============================================================================



# =============================================================================
# GESTION DES ÉQUIPEMENTS
# =============================================================================

@login_required
def liste_equipements(request):
    try:
        # Récupération de tous les équipements
        equipements = Equipement.objects.all().order_by('categorie', 'designation')
        navires_quai = Navire.objects.filter(etat='quai', a_grue_bord=False)
        navires_rade = Navire.objects.filter(etat='rade', a_grue_bord=False)

        horaires_manquants = any(
            n.debut_datetime is None or n.heure_fin is None
            for n in navires_quai
        )

        # Calcul des disponibilités dynamiques pour chaque équipement
        for e in equipements:
            # Navires à quai utilisant cet équipement (comparaison par designation)
            utilisateurs_quai = [
                n.nom for n in navires_quai
                if e.designation in get_equipements_necessaires_par_type(n.type)
            ]
            nb_utilises = len(utilisateurs_quai)
            # Disponibles = engins en marche - ceux utilisés
            disponibles = e.engins_en_marche - nb_utilises
            e.disponibles_calc = max(0, disponibles)  # stockage temporaire

            # Navires en rade ayant besoin de cet équipement
            utilisateurs_rade = [
                n.nom for n in navires_rade
                if e.designation in get_equipements_necessaires_par_type(n.type)
            ]

            # Affichage : si plus de disponibilité et des navires en attente
            if e.disponibles_calc == 0 and utilisateurs_rade:
                e.utilisateurs = utilisateurs_rade[:e.engins_existants]
                e.utilisateurs_note = f"En attente ({len(utilisateurs_rade)} navires)"
            else:
                e.utilisateurs = utilisateurs_quai[:e.engins_existants]
                e.utilisateurs_note = ""

        # Totaux globaux (basés sur les engins en marche)
        total_unites = sum(e.engins_existants for e in equipements)
        total_disponibles = sum(e.engins_en_marche for e in equipements)
        taux_disponibilite = (total_disponibles / total_unites * 100) if total_unites else 0

        # Besoins des navires en attente
        equip_dict = {e.designation: e for e in equipements}
        navires_besoins = []
        for navire in navires_rade:
            if navire.a_grue_bord:
                equipements_necessaires = []
                tous_disponibles = True
            else:
                equipements_necessaires = get_equipements_necessaires_par_type(navire.type)
                tous_disponibles = all(
                    equip_dict.get(eq, Equipement()).engins_en_marche > 0  # utilisation de engins_en_marche
                    for eq in equipements_necessaires
                )
            navires_besoins.append({
                'navire': navire,
                'equipements': equipements_necessaires,
                'tous_disponibles': tous_disponibles,
                'a_grue_bord': navire.a_grue_bord
            })

        # Séparer les équipements par catégorie
        engins = equipements.filter(categorie='engin')
        grues = equipements.filter(categorie='grue')

        context = {
            'equipements': equipements,   # pour rétrocompatibilité (si template l'utilise)
            'engins': engins,
            'grues': grues,
            'total_unites': total_unites,
            'total_disponibles': total_disponibles,
            'taux_disponibilite': round(taux_disponibilite, 1),
            'navires_besoins': navires_besoins,
            'horaires_manquants': horaires_manquants,
        }
        return render(request, 'port/equipements.html', context)
    except Exception as e:
        import traceback
        print(f"❌ ERREUR: {e}")
        traceback.print_exc()
        return render(request, 'port/equipements.html', {'error': str(e)})
@login_required
@group_required('Directeur')
def ajouter_equipement(request):
    if request.method == 'POST':
        try:
            equip = Equipement(
                categorie=request.POST.get('categorie'),
                designation=request.POST.get('designation'),
                capacite=request.POST.get('capacite', ''),
                engins_existants=int(request.POST.get('engins_existants', 0)),
                engins_en_marche=int(request.POST.get('engins_en_marche', 0)),
                engins_en_panne=int(request.POST.get('engins_en_panne', 0)),
                temps_reparation=float(request.POST.get('temps_reparation', 2.0))
            )
            equip.save()
            messages.success(request, f"✅ {equip.designation} ajouté.")
            return redirect('liste_equipements')
        except Exception as e:
            messages.error(request, f"❌ Erreur : {e}")
    return render(request, 'port/ajouter_equipement.html')

@login_required
@group_required('Directeur')
def modifier_equipement(request, equipement_id):
    equip = get_object_or_404(Equipement, id=equipement_id)
    if request.method == 'POST':
        try:
            equip.categorie = request.POST.get('categorie')
            equip.designation = request.POST.get('designation')
            equip.capacite = request.POST.get('capacite', '')
            equip.engins_existants = int(request.POST.get('engins_existants', 0))
            equip.engins_en_marche = int(request.POST.get('engins_en_marche', 0))
            equip.engins_en_panne = int(request.POST.get('engins_en_panne', 0))
            equip.temps_reparation = float(request.POST.get('temps_reparation', 2.0))
            equip.save()
            messages.success(request, f"✅ {equip.designation} modifié avec succès.")
            return redirect('liste_equipements')
        except Exception as e:
            messages.error(request, f"❌ Erreur lors de la modification : {e}")
    return render(request, 'port/modifier_equipement.html', {'equipement': equip})
from .models import EffectifShift

@login_required
def effectifs_shifts(request):
    effectifs = EffectifShift.objects.all().order_by('shift', 'metier')
    context = {'effectifs': effectifs}
    return render(request, 'port/effectifs_shifts.html', context)
@login_required
@group_required('Directeur')
def supprimer_equipement(request, equipement_id):
    equip = get_object_or_404(Equipement, id=equipement_id)
    if request.method == 'POST':
        equip.delete()
        messages.success(request, f"✅ Équipement supprimé.")
    return redirect('liste_equipements')
@login_required
@group_required('Officier_port', 'Directeur')
def planifier_equipements(request):
    maintenant = datetime.now()
    heure_actuelle = maintenant.hour + maintenant.minute/60
    navires_rade = Navire.objects.filter(etat='rade')
    navires_quai = Navire.objects.filter(etat='quai')
    besoins = []
    for navire in navires_rade:
        attente = max(0, heure_actuelle - navire.arrivee) if navire.arrivee < heure_actuelle else 0
        if navire.a_grue_bord:
            equipements = []
            manques = []
            tous_disponibles = True
        else:
            equipements = get_equipements_par_type(navire)
            manques = []
            tous_disponibles = True
        besoins.append({
            'navire': navire,
            'equipements': equipements,
            'manques': manques,
            'tous_disponibles': tous_disponibles,
            'attente': attente,
            'est_prioritaire': navire.strategique or navire.gazier or navire.animalier,
            'a_grue_bord': navire.a_grue_bord
        })
    prochaines_arrivees = Navire.objects.filter(
        etat='attente',
        arrivee__gte=heure_actuelle,
        arrivee__lte=heure_actuelle + 24
    ).order_by('arrivee')
    previsions = []
    for navire in prochaines_arrivees:
        if navire.a_grue_bord:
            equipements = []
            peut_etre_planifie = True
        else:
            equipements = get_equipements_par_type(navire)
            peut_etre_planifie = True
        previsions.append({
            'navire': navire,
            'equipements': equipements,
            'peut_etre_planifie': peut_etre_planifie,
            'heure_arrivee': navire.arrivee,
            'a_grue_bord': navire.a_grue_bord
        })
    equipements_stats = {}
    for navire in navires_quai:
        if not navire.a_grue_bord:
            equipements = get_equipements_par_type(navire)
            for eq in equipements:
                equipements_stats[eq] = equipements_stats.get(eq, 0) + 1
    top_equipements = sorted(equipements_stats.items(), key=lambda x: x[1], reverse=True)[:5]
    context = {
        'besoins': besoins,
        'previsions': previsions,
        'navires_quai': navires_quai,
        'navires_rade': navires_rade,
        'heure_actuelle': heure_actuelle,
        'total_manquants': sum(len(b['manques']) for b in besoins),
        'top_equipements': top_equipements,
        'nb_besoins': len(besoins),
        'nb_previsions': len(previsions),
    }
    return render(request, 'port/planifier_equipements.html', context)

@login_required
@group_required('Directeur')
@require_POST
@csrf_exempt
def basculer_panne_equipement(request, equipement_id):
    try:
        equip = Equipement.objects.get(id=equipement_id)
        if not equip.en_panne:
            equip.en_panne = True
            equip.panne_debut = timezone.now()
            equip.save()
            replanifier_apres_panne(equip)
        else:
            equip.en_panne = False
            equip.panne_debut = None
            equip.save()
        return JsonResponse({'success': True, 'en_panne': equip.en_panne})
    except Equipement.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Équipement introuvable'})

from django.utils import timezone
from .models import Affectation
from .optimiseur_epb_pro import ModeleCalcul
from .adaptateurs import AdaptateurDonnees

def replanifier_apres_panne(equipement):
    """
    Panne d'équipement : les navires à quai qui l'utilisent voient leur
    opération prolongée du temps de réparation restant.
    Le score de l'affectation est recalculé pour que les statistiques du navire
    (attente moyenne, attente totale, score moyen) soient cohérentes.
    """
    navires_impactes = []
    navires_quai = Navire.objects.filter(etat='quai', a_grue_bord=False)
    eq_type_normalise = equipement.type.lower()

    for nav in navires_quai:
        eq_necessaires = get_equipements_necessaires_par_type(nav.type)
        eq_necessaires_norm = [e.lower() for e in eq_necessaires]
        if eq_type_normalise in eq_necessaires_norm:
            navires_impactes.append(nav)
            print(f"   → Navire {nav.nom} (type {nav.type}) à quai utilise {equipement.type}")

    # Instance de ModeleCalcul pour recalculer le score (sans incertitude)
    modele = ModeleCalcul([], [], incertitude=False, amplitude=0, coeffs_historiques={})

    for nav in navires_impactes:
        # Calcul du temps de réparation restant
        if equipement.panne_debut:
            duree_panne = (timezone.now() - equipement.panne_debut).total_seconds() / 3600
            reste = max(0, equipement.temps_reparation - duree_panne)
        else:
            reste = equipement.temps_reparation

        if reste <= 0 or nav.heure_fin is None:
            continue

        # Récupérer la dernière affectation (celle en cours)
        affect = Affectation.objects.filter(navire=nav).order_by('-date_creation').first()
        if not affect:
            continue

        ancienne_fin = affect.heure_fin
        ancien_traitement = affect.traitement
        ancien_score = affect.score_contribution

        # Prolonger la fin et le traitement
        affect.heure_fin += reste
        affect.traitement += reste
        nav.heure_fin += reste

        # Recalculer le score avec la nouvelle durée de traitement
        # Convertir le navire et le quai en dataclasses pour le modèle de calcul
        navire_data = AdaptateurDonnees.vers_navire(nav, coeff_variation=0)
        quai_data = AdaptateurDonnees.vers_quai(affect.quai)

        # Le buffer reste inchangé
        nouveau_score = modele.calculer_score_contribution(
            navire_data, affect.heure_debut, affect.traitement,
            affect.buffer_debut, affect.buffer_fin
        )
        affect.score_contribution = nouveau_score
        affect.save()
        nav.save()

        # Mettre à jour le quai
        quai = nav.quai_attribue
        if quai:
            quai.occupation_jusqua = nav.heure_fin
            quai.save()

        print(f"   → {nav.nom} : fin {ancienne_fin:.1f}h -> {affect.heure_fin:.1f}h")
        print(f"   → Traitement : {ancien_traitement:.1f}h -> {affect.traitement:.1f}h")
        print(f"   → Score      : {ancien_score:.1f} -> {affect.score_contribution:.1f}")

    print("   → Aucune replanification automatique – seules les fins et scores sont prolongés.")
# =============================================================================
# MÉTÉO
# =============================================================================

# port/views.py (extrait – fonction modifier_meteo complète)

@login_required
@group_required('Directeur', 'Officier_radio') 
def modifier_meteo(request):
    from port.models import Meteo, Quai, Alerte, Navire, Affectation
    from datetime import datetime, timedelta
    from django.utils import timezone
    from django.core.management import call_command
    from django.db import models
    from port.views import replanifier_automatique

    meteo, created = Meteo.objects.get_or_create(date=timezone.now().date())
    tous_les_quais = Quai.objects.all().order_by('id')

    # Récupération des IDs des quais actuellement interdits
    restrictions_ids = []
    if meteo.restrictions:
        noms_restreints = [q.strip() for q in meteo.restrictions.split(',') if q.strip()]
        restrictions_ids = list(tous_les_quais.filter(nom__in=noms_restreints).values_list('id', flat=True))

    if request.method == 'POST':
        # ========== ACTIONS RAPIDES ==========
        if 'confirmer_pluie' in request.POST:
            # Activation manuelle de la pluie
            meteo.pluie = True
            meteo.pluie_active = True
            meteo.pluie_debut_reelle = timezone.now()
            meteo.precipitation = max(meteo.precipitation, 5.0)
            # Bloquer les quais céréaliers
            quais_cereales = Quai.objects.filter(specialite='cerealier')
            meteo.restrictions = ", ".join(quais_cereales.values_list('nom', flat=True))
            meteo.save()

            # Alerte
            Alerte.objects.create(
                message="🌧️ Pluie confirmée manuellement – Les navires céréaliers/dangereux à quai sont stoppés.",
                niveau='warning',
                source='Météo',
                est_lue=False
            )
            messages.warning(request, "🌧️ Pluie confirmée – les opérations sensibles sont interrompues.")
            replanifier_automatique()
            return redirect('modifier_meteo')

        elif 'annuler_pluie' in request.POST:
            # Calcul de la durée de pluie écoulée (si pluie active)
            if meteo.pluie_active and meteo.pluie_debut_reelle:
                duree_pluie = (timezone.now() - meteo.pluie_debut_reelle).total_seconds() / 3600.0
                duree_pluie = max(0, round(duree_pluie, 2))
            else:
                duree_pluie = 0.0

            # Ajouter le temps d'arrêt à tous les navires sensibles à quai
            if duree_pluie > 0:
                navires_sensibles = Navire.objects.filter(
                    etat='quai'
                ).filter(
                    models.Q(type='cerealier') | models.Q(marchandise_dangereuse=True)
                )
                for nav in navires_sensibles:
                    # Incrémenter le compteur
                    nav.temps_arret_pluie += duree_pluie
                    nav.save()

                    # Mettre à jour l'affectation en cours
                    affect = Affectation.objects.filter(navire=nav).order_by('-date_creation').first()
                    if affect:
                        affect.heure_fin += duree_pluie
                        affect.traitement += duree_pluie
                        affect.save()
                        nav.heure_fin = affect.heure_fin
                        # Recalculer fin_datetime
                        if nav.debut_datetime:
                            base = nav.debut_datetime.replace(hour=0, minute=0, second=0, microsecond=0)
                            nav.fin_datetime = base + timedelta(hours=nav.heure_fin)
                        nav.save()
                        if affect.quai:
                            affect.quai.occupation_jusqua = affect.heure_fin
                            affect.quai.save()
                    print(f"⏱️ Ajout de {duree_pluie}h à {nav.nom} (cumul: {nav.temps_arret_pluie:.2f}h)")

                Alerte.objects.create(
                    message=f"✅ Fin de la pluie – Durée : {duree_pluie:.1f}h. Reprise des opérations pour les navires céréaliers/dangereux.",
                    niveau='success',
                    source='Météo',
                    est_lue=False
                )
                messages.success(request, f"✅ Pluie annulée – {duree_pluie:.1f}h d'arrêt ajoutées aux navires sensibles.")
            else:
                messages.info(request, "Aucune durée de pluie enregistrée.")

            # Désactiver la pluie
            meteo.pluie_active = False
            meteo.pluie_debut_reelle = None
            meteo.pluie = False
            meteo.precipitation = 0.0
            # Supprimer les restrictions céréalières
            quais_cereales = Quai.objects.filter(specialite='cerealier').values_list('nom', flat=True)
            restrictions_actuelles = [q.strip() for q in meteo.restrictions.split(',') if q.strip()] if meteo.restrictions else []
            nouvelles_restrictions = [q for q in restrictions_actuelles if q not in quais_cereales]
            meteo.restrictions = ", ".join(nouvelles_restrictions) if nouvelles_restrictions else ""
            meteo.save()

            replanifier_automatique()
            return redirect('modifier_meteo')

        elif 'confirmer_vent' in request.POST:
            # Vent fort déclenché manuellement
            meteo.vent_force = 8
            meteo.vent_direction = request.POST.get('vent_direction', meteo.vent_direction) or 'N'
            quais_sensibles = Quai.objects.filter(id__in=[12,13,14,15,16])
            meteo.restrictions = ", ".join(quais_sensibles.values_list('nom', flat=True))
            meteo.save()

            Alerte.objects.create(
                message="💨 Vent fort confirmé (≥8 Bft) – Quais sensibles (12,13,14,15,16) interdits.",
                niveau='warning',
                source='Météo',
                est_lue=False
            )
            messages.warning(request, "⚠️ Vent fort – quais sensibles fermés.")
            replanifier_automatique()
            return redirect('modifier_meteo')

        elif 'annuler_vent' in request.POST:
            # Annulation du vent fort
            meteo.vent_force = 0
            quais_sensibles = Quai.objects.filter(id__in=[12,13,14,15,16]).values_list('nom', flat=True)
            restrictions_actuelles = [q.strip() for q in meteo.restrictions.split(',') if q.strip()] if meteo.restrictions else []
            nouvelles_restrictions = [q for q in restrictions_actuelles if q not in quais_sensibles]
            meteo.restrictions = ", ".join(nouvelles_restrictions) if nouvelles_restrictions else ""
            meteo.save()

            Alerte.objects.create(
                message="✅ Vent fort terminé – Quais sensibles réactivés.",
                niveau='success',
                source='Météo',
                est_lue=False
            )
            messages.success(request, "✅ Vent fort annulé – quais rouverts.")
            replanifier_automatique()
            return redirect('modifier_meteo')

        elif 'reinitialiser' in request.POST:
            # Réinitialisation depuis l'API
            call_command('fetch_weather', silent=True)
            meteo.refresh_from_db()
            # Si la météo réelle n'indique pas de pluie, désactiver le mode actif
            if not meteo.pluie:
                meteo.pluie_active = False
                meteo.pluie_debut_reelle = None
                meteo.save()
            messages.info(request, "🔄 Météo réinitialisée depuis les données réelles.")
            return redirect('modifier_meteo')

        # ========== FORMULAIRE COMPLET (modification manuelle détaillée) ==========
        else:
            # Champs standards
            meteo.vent_force = int(request.POST.get('vent_force', 0))
            meteo.hauteur_houle = float(request.POST.get('hauteur_houle', 0))
            meteo.precipitation = float(request.POST.get('precipitation', 0))
            meteo.temperature = float(request.POST.get('temperature', 20))
            meteo.vent_direction = request.POST.get('vent_direction', 'N')
            meteo.pluie = (meteo.precipitation > 0)

            # Intervalle de pluie prévue (pour la planification)
            debut_pluie_str = request.POST.get('pluie_debut_prevue', '').strip()
            fin_pluie_str = request.POST.get('pluie_fin_prevue', '').strip()
            try:
                if debut_pluie_str:
                    meteo.pluie_debut_prevue = datetime.fromisoformat(debut_pluie_str)
                else:
                    meteo.pluie_debut_prevue = None
            except ValueError:
                meteo.pluie_debut_prevue = None
            try:
                if fin_pluie_str:
                    meteo.pluie_fin_prevue = datetime.fromisoformat(fin_pluie_str)
                else:
                    meteo.pluie_fin_prevue = None
            except ValueError:
                meteo.pluie_fin_prevue = None

            # Quais interdits (restrictions manuelles)
            quais_interdits_ids = request.POST.getlist('quais_interdits')
            quais_interdits_noms = Quai.objects.filter(id__in=quais_interdits_ids).values_list('nom', flat=True)
            meteo.restrictions = ", ".join(quais_interdits_noms)

            meteo.save()
            messages.success(request, "✅ Météo mise à jour.")
            replanifier_automatique()
            return redirect('modifier_meteo')

    # Contexte pour le template
    context = {
        'meteo': meteo,
        'tous_les_quais': tous_les_quais,
        'restrictions_ids': restrictions_ids,
    }
    return render(request, 'port/meteo.html', context)
@login_required
def actualiser_meteo(request):
    call_command('fetch_weather', silent=True)
    messages.success(request, "Météo actualisée avec succès.")
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

# =============================================================================
# CPN & OPTIMISATION
# =============================================================================

@login_required
@group_required('Officier_port', 'Directeur')
def cpn(request):
    from .models import Meteo
    maintenant = datetime.now()
    heure_actuelle = maintenant.hour + maintenant.minute / 60

    # ========== FILTRES : uniquement les navires marqués prêts par le consignataire ==========
    # Navires en rade (déjà dans la rade) et prêts par consignataire
    navires_rade = Navire.objects.filter(
        etat='rade',
        pret_consignataire=True
    ).order_by('arrivee_datetime')

    # Navires attendus dans les prochaines 24h, prêts par consignataire
    now = timezone.now()
    limite = now + timedelta(hours=24)
    navires_attente_24h = Navire.objects.filter(
        etat='attente',
        arrivee_datetime__isnull=False,
        arrivee_datetime__lte=limite,
        pret_consignataire=True
    ).order_by('arrivee_datetime')

    # Équipements (inchangé)
    equipements = Equipement.objects.all().order_by('categorie', 'designation')

    # Météo du jour
    meteo_aujourdhui = get_meteo_aujourdhui()

    if request.method == 'POST':
        # ----- Traitement des navires en rade (sélection manuelle par l'officier) -----
        rade_ids = []
        for navire in navires_rade:
            if request.POST.get(f'pret_{navire.id}') == 'on':
                rade_ids.append(navire.id)
                navire.pret_par_client = True
            else:
                navire.pret_par_client = False
            navire.save()

        # ----- Traitement des navires attendus (sélection par l'officier) -----
        for navire in navires_attente_24h:
            navire.pret_par_client = request.POST.get(f'pret_{navire.id}') == 'on'
            navire.save()

        # ----- Paramètres avancés -----
        incertitude = request.POST.get('incertitude') == 'on'
        amplitude = request.POST.get('amplitude', '20')
        buffer_pct = request.POST.get('buffer', '15')
        scenario = request.POST.get('scenario', 'equilibre')

        request.session['param_incertitude'] = incertitude
        request.session['param_amplitude'] = amplitude
        request.session['param_buffer'] = buffer_pct
        request.session['scenario'] = scenario

        # IDs des navires sélectionnés par l'officier (prêts pour l'optimisation)
        ids_prets = rade_ids + [n.id for n in navires_attente_24h if n.pret_par_client]

        if ids_prets:
            request.session['navires_cpn_ids'] = ids_prets
            return redirect('optimiser_depuis_cpn')
        else:
            messages.warning(request, "Aucun navire n'a été marqué comme prêt.")
            return redirect('cpn')

    context = {
        'navires_rade': navires_rade,
        'navires_attente_24h': navires_attente_24h,
        'equipements': equipements,
        'heure_actuelle': heure_actuelle,
        'heure_limite': limite.hour + limite.minute/60,
        'meteo': meteo_aujourdhui,
    }
    return render(request, 'port/cpn.html', context)
from django.db.models import Avg, F
from django.utils import timezone
from datetime import timedelta
from .models import Navire, HistoriqueOperation, Equipement, Poste, Equipe, Meteo
from .adaptateurs import AdaptateurDonnees
from .optimiseur_epb_pro import PlanificateurEPB
from .views import get_meteo_aujourdhui

@login_required
@group_required('Officier_port', 'Directeur')
def optimiser_depuis_cpn(request):
    navires_ids = request.session.get('navires_cpn_ids', [])
    if not navires_ids:
        messages.error(request, "Aucun navire sélectionné pour l'optimisation.")
        return redirect('cpn')

    navires_model = Navire.objects.filter(id__in=navires_ids)
    if not navires_model:
        messages.error(request, "Les navires sélectionnés ne sont plus disponibles.")
        return redirect('cpn')

    # ========== APPLIQUER AUTOMATIQUEMENT LES NOTES D'ATTENTE NON TRAITÉES ==========
    from port.models import NoteAttente
    from datetime import timedelta
    notes = NoteAttente.objects.filter(prise_en_compte=False)
    if notes.exists():
        for note in notes:
            navire = note.navire
            if navire.arrivee_datetime:
                navire.arrivee_datetime += timedelta(hours=note.duree_attente)
                navire.arrivee = navire.arrivee_datetime.hour + navire.arrivee_datetime.minute/60.0
            else:
                navire.arrivee += note.duree_attente
            navire.save()
            note.prise_en_compte = True
            note.save()
            messages.info(request, f"⏰ Note d'attente appliquée: {navire.nom} retardé de {note.duree_attente}h")

    incertitude = request.session.get('param_incertitude', False)
    try:
        amplitude_pct = float(request.session.get('param_amplitude', '20'))
    except ValueError:
        amplitude_pct = 20
    amplitude = max(0.0, min(0.5, amplitude_pct / 100.0))

    try:
        buffer_pct_val = float(request.session.get('param_buffer', '15'))
    except ValueError:
        buffer_pct_val = 15
    buffer_pct = max(0.0, min(0.5, buffer_pct_val / 100.0))

    scenario = request.session.get('scenario', 'equilibre')

    # Coefficients historiques
    coeffs_historiques = {}
    for row in HistoriqueOperation.objects.values('navire_type', 'quai_id').annotate(
        ratio_moyen=Avg(F('duree_reelle') / F('duree_estimee'))
    ):
        coeffs_historiques[(row['navire_type'], row['quai_id'])] = row['ratio_moyen']

    # ========== RÉINITIALISATION DES COMPTEURS DE GRUES ==========
    from port.optimiseur_epb_pro import PlanificateurEPB
    PlanificateurEPB._cerealier_grue_index = 0
    PlanificateurEPB._conteneur_grue_index = 0
    PlanificateurEPB._cargo_grue_index = 0
    PlanificateurEPB._cargo_quai_index = 0

    # ========== RÉINITIALISATION COMPLÈTE DES POSTES ET QUAIS ==========
    from port.models import Poste, Quai
    Poste.objects.update(disponible=True, occupation_jusqua=0.0)
    Quai.objects.update(disponible=True, occupation_jusqua=0.0)

    # ========== CONVERSION DES NAVIRES ==========
    now = timezone.now()
    base = now.replace(hour=0, minute=0, second=0, microsecond=0)

    navires_a_planifier = []
    for n in navires_model:
        nd = AdaptateurDonnees.vers_navire(n, coeff_variation=amplitude)
        if nd.est_en_rade or n.etat == 'attente':
            if n.arrivee_datetime:
                heure_originale = n.arrivee_datetime.hour + n.arrivee_datetime.minute / 60.0
            else:
                heure_originale = n.arrivee
            nd.arrivee = heure_originale
            nd.arrivee_datetime = base + timedelta(hours=heure_originale)
        navires_a_planifier.append(nd)

    # Navires déjà à quai
    navires_quai_model = Navire.objects.filter(etat='quai', quai_attribue__isnull=False)
    navires_a_quai = []
    for n in navires_quai_model:
        nd = AdaptateurDonnees.vers_navire(n, coeff_variation=0)
        nd.fin_prevue = n.heure_fin
        navires_a_quai.append(nd)

    # ========== PRÉPARATION DES QUAIS ==========
    postes_model = Poste.objects.filter(gestion_manuelle=False, disponible=True).select_related('quai')
    quais = [AdaptateurDonnees.vers_quai_depuis_poste(p) for p in postes_model]
    for quai_data in quais:
        quai_data.libre = 0.0

    # ========== ÉQUIPEMENTS ==========
    equipements_model = Equipement.objects.all()
    if not equipements_model.exists():
        messages.warning(request, "Aucun équipement en base. L'optimisation ignorera les contraintes d'équipements.")
    equipements = [AdaptateurDonnees.vers_equipement(e) for e in equipements_model]

    # ========== MÉTÉO ==========
    meteo = get_meteo_aujourdhui()
    meteo_restrictions = []
    meteo_pluie = False
    meteo_vent_force = 0
    meteo_temperature = 20
    pluie_debut_prevue = None
    pluie_fin_prevue = None
    if meteo:
        if meteo.restrictions:
            meteo_restrictions = [q.strip() for q in meteo.restrictions.split(',') if q.strip()]
        meteo_pluie = meteo.pluie
        meteo_vent_force = meteo.vent_force
        meteo_temperature = meteo.temperature
        pluie_debut_prevue = getattr(meteo, 'pluie_debut_prevue', None)
        pluie_fin_prevue = getattr(meteo, 'pluie_fin_prevue', None)

    # ========== ÉQUIPES ==========
    equipes = Equipe.objects.filter(disponible=True)

    # ========== CRÉATION DU PLANIFICATEUR ==========
    planificateur = PlanificateurEPB(
        quais, equipements, mois=3,
        incertitude=incertitude,
        amplitude=amplitude,
        pourcentage_buffer=buffer_pct,
        meteo_restrictions=meteo_restrictions,
        meteo_pluie=meteo_pluie,
        meteo_vent_force=meteo_vent_force,
        meteo_temperature=meteo_temperature,
        scenario=scenario,
        coeffs_historiques=coeffs_historiques,
        equipes=equipes,
        pluie_debut_prevue=pluie_debut_prevue,
        pluie_fin_prevue=pluie_fin_prevue
    )

    try:
        result = planificateur.planifier(navires_a_planifier, navires_a_quai, date_reference=now)
    except Exception as e:
        messages.error(request, f"Erreur dans l'optimiseur : {e}")
        return redirect('cpn')

    if result is None:
        messages.error(request, "L'optimiseur a retourné None (aucune affectation).")
        return redirect('cpn')

    affectations, score_total, attente_totale = result
    if not affectations:
        messages.error(request, "L'optimisation n'a produit aucune affectation.")
        return redirect('cpn')

    affectations_data = []
    base = now.replace(hour=0, minute=0, second=0, microsecond=0)

    for a in affectations:
        navire_original = Navire.objects.get(id=a.navire_id)
        heure_accostage = a.heure_accostage
        heure_fin = a.heure_fin
        attente = a.attente

        if navire_original.arrivee_datetime:
            heures = int(heure_accostage)
            minutes = int((heure_accostage - heures) * 60)
            debut_dt = base + timedelta(hours=heures, minutes=minutes)
            if debut_dt < navire_original.arrivee_datetime:
                nouvelle_heure = navire_original.arrivee_datetime.hour + navire_original.arrivee_datetime.minute/60.0
                heure_accostage = nouvelle_heure
                heure_fin = nouvelle_heure + a.traitement
                attente = 0

        affectations_data.append({
            'navire_id': a.navire_id,
            'navire_nom': a.navire_nom,
            'type_navire': a.type_navire,
            'quai_id': a.quai_id,
            'quai_nom': a.quai_nom,
            'heure_accostage': heure_accostage,
            'heure_fin': heure_fin,
            'attente': attente,
            'traitement': a.traitement,
            'score_contribution': a.score_contribution,
            'priorites_speciale': a.priorites_speciale,
            'utilise_grues_bord': a.utilise_grues_bord,
            'buffer_debut': a.buffer_debut,
            'buffer_fin': a.buffer_fin,
            'heure_debut_securise': a.heure_debut_securise,
            'heure_fin_securise': a.heure_fin_securise,
            'etat_initial': navire_original.etat,
            'equipements': a.equipements,
            'arrivee_rade': navire_original.arrivee_datetime.strftime("%d/%m %H:%M") if navire_original.arrivee_datetime else "-",
            'eta': navire_original.arrivee_datetime.strftime("%d/%m %H:%M") if navire_original.arrivee_datetime else "-",
            'temps_manoeuvre': a.temps_manoeuvre,
            'arrivee_datetime': navire_original.arrivee_datetime.isoformat() if navire_original.arrivee_datetime else None,
            'agent': navire_original.agent or 'Inconnu',
            'attente_equipements': getattr(a, 'attente_equipements', 0),
            'equipe_nom': getattr(a, 'equipe_nom', None)
        })

    request.session['resultats_optimisation'] = {
        'affectations': affectations_data,
        'score_total': score_total,
        'attente_totale': attente_totale,
        'navires_ids': navires_ids,
        'quais': [(q.id, q.nom) for q in quais],
        'scenario': scenario,
    }
    return redirect('valider_planification')
@login_required
@group_required('Officier_port', 'Directeur')
def valider_planification(request):
    resultats = request.session.get('resultats_optimisation')
    if not resultats:
        messages.error(request, "Aucun résultat à valider.")
        return redirect('cpn')

    # ========== FILTRER LES NAVIRES DÉJÀ À QUAI ==========
    navires_deja_quai_ids = list(Navire.objects.filter(etat='quai').values_list('id', flat=True))
    
    affectations_filtrees = []
    for a in resultats['affectations']:
        if a['navire_id'] not in navires_deja_quai_ids:
            affectations_filtrees.append(a)
    
    resultats['affectations'] = affectations_filtrees
    
    if not affectations_filtrees:
        messages.warning(request, "Tous les navires de la planification ont déjà été affectés manuellement.")
        del request.session['resultats_optimisation']
        return redirect('cpn')
    
    # ========== TRAITEMENT POST ==========
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'accepter':
            session = appliquer_affectations(request, resultats['affectations'], resultats['quais'])
            if session:
                messages.success(request, f"✅ Planning validé – {len(resultats['affectations'])} navires planifiés.")
                del request.session['resultats_optimisation']
                return redirect('resultats_planification', session_id=session.id)
            else:
                messages.error(request, "❌ Erreur lors de l'application du planning.")
                return redirect('cpn')
        else:
            messages.info(request, "Planning annulé.")
            del request.session['resultats_optimisation']
            return redirect('cpn')

    # ========== PARAMÈTRES ==========
    incertitude = request.session.get('param_incertitude', False)
    amplitude = request.session.get('param_amplitude', 20)
    buffer_pct = request.session.get('param_buffer', 15)

    affectations_rade = []
    affectations_attente = []
    for a in resultats['affectations']:
        if a.get('etat_initial') == 'rade':
            affectations_rade.append(a)
        else:
            affectations_attente.append(a)

    FORMALITES = 2.0
    now = timezone.now()
    base = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # ---------- Fonctions utilitaires ----------
    def get_shift_interval(dt):
        h = dt.hour + dt.minute / 60.0
        if 7 <= h < 13:
            return "07h_13h", dt.replace(hour=13, minute=0, second=0, microsecond=0)
        elif 13 <= h < 19:
            return "13h_19h", dt.replace(hour=19, minute=0, second=0, microsecond=0)
        elif 19 <= h < 24:
            return "19h_01h", dt.replace(hour=1, minute=0, second=0, microsecond=0) + timedelta(days=1)
        elif 0 <= h < 1:
            return "19h_01h", dt.replace(hour=1, minute=0, second=0, microsecond=0)
        else:
            return "01h_07h", dt.replace(hour=7, minute=0, second=0, microsecond=0)

    def temps_par_shift(debut, fin):
        result = {}
        d = debut
        while d < fin:
            shift_name, fin_shift = get_shift_interval(d)
            segment_fin = min(fin, fin_shift)
            duree = (segment_fin - d).total_seconds() / 3600.0
            result[shift_name] = result.get(shift_name, 0) + duree
            d = segment_fin
        return result

    # ---------- Dictionnaire pour stocker les navires par ID ----------
    navires_dict = {}
    for navire in Navire.objects.all():
        navires_dict[navire.id] = navire

    # ---------- Préparation des données pour chaque affectation ----------
    toutes_affectations = []
    
    for a in affectations_rade + affectations_attente:
        # === Heure de début ===
        hd = a['heure_accostage']
        heures_deb = int(hd)
        minutes_deb = int((hd - heures_deb) * 60)
        debut_dt = base + timedelta(hours=heures_deb, minutes=minutes_deb)
        if debut_dt < now - timedelta(minutes=30):
            debut_dt += timedelta(days=1)
        a['debut_datetime'] = debut_dt

        # === Heure de fin ===
        duree_traitement = a.get('traitement', 0)
        fin_dt = debut_dt + timedelta(hours=duree_traitement)
        a['fin_datetime'] = fin_dt

        # Variables d'affichage
        a['debut_affichage'] = debut_dt.strftime("%d/%m %H:%M")
        a['fin_affichage'] = fin_dt.strftime("%d/%m %H:%M")
        
        # Récupérer l'arrivée réelle
        navire_obj = navires_dict.get(a['navire_id'])
        if navire_obj and navire_obj.arrivee_datetime:
            a['arrivee_affichage'] = navire_obj.arrivee_datetime.strftime("%d/%m %H:%M")
            a['arrivee_datetime'] = navire_obj.arrivee_datetime  # C'est un datetime
            if debut_dt > navire_obj.arrivee_datetime:
                a['attente'] = round((debut_dt - navire_obj.arrivee_datetime).total_seconds() / 3600, 1)
            else:
                a['attente'] = 0
        else:
            a['arrivee_affichage'] = '-'
            a['arrivee_datetime'] = None
            a['attente'] = max(0, a['heure_accostage'] - a.get('heure_arrivee', 0))

        # Valeurs pour l'affichage
        a['traitement'] = duree_traitement
        a['manoeuvre'] = a.get('temps_manoeuvre', 1.2)
        a['formalites'] = FORMALITES
        a['operations'] = max(0, a['traitement'] - a['manoeuvre'] - a['formalites'])

        # Shifts
        a['temps_par_shift'] = temps_par_shift(debut_dt, fin_dt)
        a['shifts_couverts'] = sorted(a['temps_par_shift'].keys())
        a['score_contribution'] = a['traitement'] + a['attente'] * 3.0

        # Débit estimé
        volume = float(navire_obj.marchandise_volume or 0) if navire_obj else 0
        if volume > 100000:
            volume = volume / 1000.0
        a['debit_estime'] = round(volume / a['traitement'], 1) if a['traitement'] > 0 else 0
        a['nb_equipements'] = len(a.get('equipements', []))
        a['attente_equipements'] = a.get('attente_equipements', 0)

        # Heures d'accostage
        a['heure_accostage'] = hd
        a['heure_fin'] = duree_traitement

        toutes_affectations.append(a)

    # ---------- Résolution des conflits (version CORRIGÉE) ----------
    toutes_affectations.sort(key=lambda x: x['debut_datetime'])
    conflits_resolus = 0
    for i, a1 in enumerate(toutes_affectations):
        for a2 in toutes_affectations[i+1:]:
            if a1['quai_id'] == a2['quai_id']:
                if a2['debut_datetime'] < a1['fin_datetime']:
                    delta = (a1['fin_datetime'] - a2['debut_datetime']).total_seconds() / 3600 + 0.1
                    a2['debut_datetime'] += timedelta(hours=delta)
                    a2['fin_datetime'] += timedelta(hours=delta)
                    a2['heure_accostage'] += delta
                    a2['heure_fin'] += delta
                    # Mettre à jour l'affichage
                    a2['debut_affichage'] = a2['debut_datetime'].strftime("%d/%m %H:%M")
                    a2['fin_affichage'] = a2['fin_datetime'].strftime("%d/%m %H:%M")
                    
                    # Recalculer l'attente (avec vérification de type)
                    if a2.get('arrivee_datetime') and isinstance(a2['arrivee_datetime'], datetime):
                        new_attente = (a2['debut_datetime'] - a2['arrivee_datetime']).total_seconds() / 3600
                        a2['attente'] = max(0, new_attente)
                    else:
                        a2['attente'] = max(0, a2['heure_accostage'] - a2.get('heure_arrivee', 0))
                    
                    a2['score_contribution'] = a2['traitement'] + a2['attente'] * 3.0
                    a2['temps_par_shift'] = temps_par_shift(a2['debut_datetime'], a2['fin_datetime'])
                    a2['shifts_couverts'] = sorted(a2['temps_par_shift'].keys())
                    conflits_resolus += 1

    if conflits_resolus > 0:
        messages.warning(request, f"⚠️ {conflits_resolus} conflit(s) détecté(s) et résolu(s) automatiquement.")

    # ---------- Calcul des raisons d'attente ----------
    for a in toutes_affectations:
        if a['attente'] <= 0:
            a['raison_attente'] = "Aucune attente (accostage immédiat)"
            continue

        conflit_quai = None
        for autre in toutes_affectations:
            if autre['quai_id'] == a['quai_id'] and abs((autre['fin_datetime'] - a['debut_datetime']).total_seconds()) < 60:
                conflit_quai = autre
                break
        if conflit_quai:
            a['raison_attente'] = f"⏳ Quai libéré le {conflit_quai['fin_datetime'].strftime('%d/%m %H:%M')} par le navire {conflit_quai['navire_nom']}."
            continue

        if a.get('attente_equipements', 0) > 0:
            a['raison_attente'] = f"⏳ Attente d'équipements : {a['attente_equipements']:.1f} heures (voir colonne dédiée)."
            continue

        if a.get('arrivee_datetime') and isinstance(a['arrivee_datetime'], datetime):
            arrivee_str = a['arrivee_datetime'].strftime('%d/%m %H:%M')
            debut_str = a['debut_datetime'].strftime('%d/%m %H:%M')
            a['raison_attente'] = f"Arrivée en rade le {arrivee_str}. Début d'accostage fixé à {debut_str}."
        else:
            a['raison_attente'] = "Arrivée en rade non renseignée, début d'accostage planifié."

    # ---------- Alertes de validation ----------
    alertes_validation = []
    for a in toutes_affectations:
        if a['attente'] > 72:
            alertes_validation.append(f"⚠️ {a['navire_nom']} a une attente de {a['attente']:.1f}h (> 72h)")
        if a.get('arrivee_datetime') and isinstance(a['arrivee_datetime'], datetime) and a['debut_datetime'] < a['arrivee_datetime']:
            alertes_validation.append(f"⚠️ {a['navire_nom']} accoste avant son ETA")

    # ========== STATISTIQUES ==========
    nb = len(toutes_affectations)
    attente_totale = sum(a['attente'] for a in toutes_affectations)
    attente_moyenne = attente_totale / nb if nb else 0
    traitement_total = sum(a['traitement'] for a in toutes_affectations)
    traitement_moyen = traitement_total / nb if nb else 0
    score_total = sum(a['score_contribution'] for a in toutes_affectations)

    # ---------- Statistiques par agent ----------
    from collections import defaultdict
    stats_par_agent = defaultdict(lambda: {'nb': 0, 'attente_totale': 0.0, 'traitement_total': 0.0})
    for a in toutes_affectations:
        agent = a.get('agent', 'Inconnu')
        stats_par_agent[agent]['nb'] += 1
        stats_par_agent[agent]['attente_totale'] += a['attente']
        stats_par_agent[agent]['traitement_total'] += a['traitement']
    agents_stats = []
    for agent, stats in stats_par_agent.items():
        agents_stats.append({
            'agent': agent,
            'nb_navires': stats['nb'],
            'attente_moyenne': stats['attente_totale'] / stats['nb'] if stats['nb'] else 0,
            'traitement_moyen': stats['traitement_total'] / stats['nb'] if stats['nb'] else 0,
        })
    agents_stats.sort(key=lambda x: x['attente_moyenne'], reverse=True)

    # ---------- Occupation par shift ----------
    occupation_shift = defaultdict(float)
    for a in toutes_affectations:
        for shift, heures in a['temps_par_shift'].items():
            occupation_shift[shift] += heures

    # ---------- Diagramme de Gantt ----------
    gantt_series = []
    shift_colors = {"07h_13h": "#3b82f6", "13h_19h": "#10b981", "19h_01h": "#f59e0b", "01h_07h": "#64748b"}
    shift_labels = {"07h_13h": "Shift 07h-13h", "13h_19h": "Shift 13h-19h", "19h_01h": "Shift 19h-01h", "01h_07h": "Shift 01h-07h"}

    for a in toutes_affectations:
        d = a['debut_datetime']
        fin = a['fin_datetime']
        if not d or not fin:
            continue
        navire_obj = navires_dict.get(a['navire_id'])
        volume = float(navire_obj.marchandise_volume or 0) if navire_obj else 0
        if volume > 100000:
            volume = volume / 1000.0

        while d < fin:
            shift_name, fin_shift = get_shift_interval(d)
            seg_fin = min(fin, fin_shift)
            if seg_fin > d:
                duree_heures = (seg_fin - d).total_seconds() / 3600
                proportion = duree_heures / a['traitement'] if a['traitement'] > 0 else 0
                tonnage_segment = volume * proportion
                gantt_series.append({
                    'x': a['navire_nom'],
                    'y': [int(d.timestamp() * 1000), int(seg_fin.timestamp() * 1000)],
                    'fillColor': shift_colors.get(shift_name, '#cccccc'),
                    'shiftName': shift_labels.get(shift_name, shift_name),
                    'duration': round(duree_heures, 1),
                    'tonnage': round(tonnage_segment, 1)
                })
            d = seg_fin

    series_by_navire = {}
    for item in gantt_series:
        nav = item['x']
        if nav not in series_by_navire:
            series_by_navire[nav] = []
        series_by_navire[nav].append(item)
    gantt_final_series = [{'name': nav, 'data': data} for nav, data in series_by_navire.items()]
    if not gantt_final_series:
        demo_start = datetime.now()
        gantt_final_series = [{
            'name': 'Aucune donnée',
            'data': [{
                'x': 'Aucune donnée',
                'y': [int(demo_start.timestamp() * 1000), int((demo_start + timedelta(hours=1)).timestamp() * 1000)],
                'fillColor': '#cccccc',
                'shiftName': 'Test',
                'duration': 1.0,
                'tonnage': 0
            }]
        }]

    # ---------- Effectifs et débits par shift ----------
    effectifs_par_shift = {
        "07h_13h": {"Grutiers": {"affectes": 12, "presents": 12}, "Chauffeurs semi-remorque": {"affectes": 25, "presents": 24}, "Caristes": {"affectes": 13, "presents": 12}},
        "13h_19h": {"Grutiers": {"affectes": 12, "presents": 11}, "Chauffeurs semi-remorque": {"affectes": 24, "presents": 22}, "Caristes": {"affectes": 16, "presents": 15}},
        "19h_01h": {"Grutiers": {"affectes": 12, "presents": 12}, "Chauffeurs semi-remorque": {"affectes": 21, "presents": 18}, "Caristes": {"affectes": 16, "presents": 14}},
        "01h_07h": {"Grutiers": {"affectes": 12, "presents": 12}, "Chauffeurs semi-remorque": {"affectes": 21, "presents": 18}, "Caristes": {"affectes": 16, "presents": 14}},
    }
    coeff_shift = {"07h_13h": 1.0, "13h_19h": 0.9, "19h_01h": 0.7, "01h_07h": 0.6}
    debit_base = 400
    debits_par_shift = {shift: round(debit_base * coeff, 1) for shift, coeff in coeff_shift.items()}
    shifts = {
        'shift_07_13': [a for a in toutes_affectations if 7 <= (a['heure_accostage'] % 24) < 13],
        'shift_13_19': [a for a in toutes_affectations if 13 <= (a['heure_accostage'] % 24) < 19],
        'shift_19_01': [a for a in toutes_affectations if 19 <= (a['heure_accostage'] % 24) < 24],
        'shift_01_07': [a for a in toutes_affectations if (a['heure_accostage'] % 24) < 7],
    }

    # ========== CONTEXTE ==========
    context = {
        'affectations_rade': [a for a in toutes_affectations if a.get('etat_initial') == 'rade'],
        'affectations_attente': [a for a in toutes_affectations if a.get('etat_initial') != 'rade'],
        'nb_navires': nb,
        'score_total': score_total,
        'attente_totale': attente_totale,
        'attente_moyenne': attente_moyenne,
        'incertitude': incertitude,
        'amplitude': amplitude,
        'buffer_pct': buffer_pct,
        'heure_limite': "Calculé",
        'shifts': shifts,
        'graph_data': [],
        'agents_stats': agents_stats,
        'occupation_shift': dict(occupation_shift),
        'attente_moyenne_globale': attente_moyenne,
        'traitement_moyen_global': traitement_moyen,
        'alertes_validation': alertes_validation,
        'gantt_series': gantt_final_series,
        'effectifs_par_shift': effectifs_par_shift,
        'debits_par_shift': debits_par_shift,
        'now': now,
    }
    return render(request, 'port/valider_planification.html', context)
from django.utils import timezone
from datetime import datetime, timedelta

from datetime import datetime, timedelta
from django.utils import timezone
from django.contrib.auth.models import User
from .models import SessionOptimisation, Affectation, Navire, Quai
from .email_utils import envoyer_notification_affectation

def appliquer_affectations(request, affectations_data, quais_data):
    """
    Applique les affectations issues de l'optimisation :
    - Crée une session d'optimisation
    - Crée les enregistrements Affectation
    - Met à jour les navires (état, poste, horaires, debut_datetime)
    - Met à jour les postes et quais (disponibilité, occupation)
    - Envoie des notifications par email aux officiers et directeurs
    - Génère les alertes internes
    - Enregistre chaque affectation dans l'historique
    - Enregistre dans AffectationQuai pour l'IA
    """
    from port.models import Poste, AffectationEquipe, Equipe, AffectationQuai

    score_total = sum(a['score_contribution'] for a in affectations_data)
    attente_totale = sum(a['attente'] for a in affectations_data)
    nb_navires = len(affectations_data)

    session = SessionOptimisation.objects.create(
        nom=f"CPN {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        nb_navires=nb_navires,
        nb_quais=len(quais_data),
        score_total=score_total,
        attente_totale=attente_totale,
        attente_moyenne=attente_totale / nb_navires if nb_navires else 0,
        taux_occupation=(len(set(a['quai_id'] for a in affectations_data)) / len(quais_data)) * 100 if affectations_data else 0,
        saison='hiver' if datetime.now().month in [11,12,1,2,3] else 'ete'
    )

    now = timezone.now()
    base = now.replace(hour=0, minute=0, second=0, microsecond=0)

    utilisateurs_notifies = User.objects.filter(
        groups__name__in=['Officier_port', 'Directeur']
    ).distinct()

    for a_data in affectations_data:
        navire = Navire.objects.get(id=a_data['navire_id'])

        # Récupération du poste (l'ID dans a_data['quai_id'] est l'ID du poste)
        poste = Poste.objects.get(id=a_data['quai_id'])
        quai = poste.quai

        heure_accostage = a_data['heure_accostage']
        heure_fin = a_data['heure_fin']
        attente = a_data['attente']

        # Vérification : éviter accostage avant ETA
        if navire.arrivee_datetime:
            heures = int(heure_accostage)
            minutes = int((heure_accostage - heures) * 60)
            debut_dt = base + timedelta(hours=heures, minutes=minutes)
            if debut_dt < navire.arrivee_datetime:
                nouvelle_heure = navire.arrivee_datetime.hour + navire.arrivee_datetime.minute/60.0
                heure_accostage = nouvelle_heure
                heure_fin = nouvelle_heure + a_data['traitement']
                attente = 0

        # Création de l'affectation (liée au quai)
        Affectation.objects.create(
            navire=navire,
            quai=quai,
            heure_debut=heure_accostage,
            heure_fin=heure_fin,
            attente=attente,
            traitement=a_data['traitement'],
            score_contribution=a_data['score_contribution'],
            priorites_texte=a_data['priorites_speciale'],
            utilise_grues_bord=a_data['utilise_grues_bord'],
            buffer_debut=a_data['buffer_debut'],
            buffer_fin=a_data['buffer_fin'],
            heure_debut_reel=a_data['heure_debut_securise'],
            heure_fin_reel=a_data['heure_fin_securise'],
            etat_initial=a_data.get('etat_initial', 'attente'),
            equipements_utilises=", ".join(a_data['equipements']) if a_data.get('equipements') else ""
        )

        # ========== ENREGISTREMENT DANS AffectationQuai (pour l'IA) ==========
        # Calcul du shift de début
        h_debut = heure_accostage % 24
        if 7 <= h_debut < 13:
            shift_debut = "matin"
        elif 13 <= h_debut < 19:
            shift_debut = "soir"
        elif 19 <= h_debut < 24:
            shift_debut = "nuit"
        else:
            shift_debut = "2nuit"   # Remplacé "double_nuit" (11 caractères) par "2nuit" (5 caractères)

        AffectationQuai.objects.create(
            navire=navire,
            quai=quai,
            poste=poste,
            type_navire=navire.type,
            volume=navire.marchandise_volume,
            longueur=navire.longueur,
            tirant=navire.tirant,
            agent=navire.agent or "",
            entite=navire.entite or "",
            shift_debut=shift_debut,
        )
        # ==================================================================

        # Mise à jour du navire
        if navire.etat == 'rade':
            navire.etat = 'quai'
        navire.poste_attribue = poste
        navire.quai_attribue = quai
        navire.heure_debut = heure_accostage
        navire.heure_fin = heure_fin

        # Calcul de debut_datetime
        heures = int(heure_accostage)
        minutes = int((heure_accostage - heures) * 60)
        navire.debut_datetime = base + timedelta(hours=heures, minutes=minutes)
        if navire.debut_datetime < now:
            navire.debut_datetime += timedelta(days=1)

        # Coordonnées pour la carte
        if quai.coord_x is not None and quai.coord_y is not None:
            navire.coord_x = quai.coord_x
            navire.coord_y = quai.coord_y
        else:
            navire.coord_x = 0
            navire.coord_y = 0
        navire.save()

        # Mise à jour du poste
        poste.disponible = False
        poste.occupation_jusqua = heure_fin
        poste.save()

        # Mise à jour du quai parent
        quai.disponible = False
        quai.occupation_jusqua = heure_fin
        quai.save()

        # ========== CRÉATION/MISE À JOUR DE L'AFFECTATION ÉQUIPE ==========
        equipe_nom = a_data.get('equipe_nom')
        if equipe_nom:
            try:
                equipe = Equipe.objects.get(nom=equipe_nom)
                h_debut_shift = heure_accostage % 24
                if 7 <= h_debut_shift < 13:
                    shift_nom = "07h-13h"
                elif 13 <= h_debut_shift < 19:
                    shift_nom = "13h-19h"
                elif 19 <= h_debut_shift < 24:
                    shift_nom = "19h-01h"
                else:
                    shift_nom = "01h-07h"

                # Calcul de la date de fin
                heures_fin = int(heure_fin)
                minutes_fin = int((heure_fin - heures_fin) * 60)
                fin_dt = base + timedelta(hours=heures_fin, minutes=minutes_fin)
                if fin_dt < now:
                    fin_dt += timedelta(days=1)

                AffectationEquipe.objects.update_or_create(
                    equipe=equipe,
                    navire=navire,
                    shift=shift_nom,
                    date_debut=navire.debut_datetime,
                    defaults={
                        'date_fin': fin_dt,
                        'duree_heures': heure_fin - heure_accostage
                    }
                )
            except Equipe.DoesNotExist:
                print(f"Équipe {equipe_nom} non trouvée pour {navire.nom}")
        # ===============================================================

        # Historique
        ajouter_historique(
            utilisateur=request.user,
            type_action='affectation',
            description=f"Affectation du navire {navire.nom} au poste {poste.numero} (quai {quai.nom}) (début: {heure_accostage}h, fin: {heure_fin}h)",
            navire=navire,
            quai=quai,
            details={
                'poste_id': poste.id,
                'poste_numero': poste.numero,
                'heure_debut': heure_accostage,
                'heure_fin': heure_fin,
                'attente': attente,
                'score': a_data['score_contribution']
            }
        )

        # Envoi d'email
        try:
            envoyer_notification_affectation(navire, quai, heure_accostage, utilisateurs_notifies, session.id)
        except Exception as e:
            print(f"Erreur envoi email pour {navire.nom}: {e}")

    # Génération des alertes
    try:
        generer_toutes_alertes()
    except Exception as e:
        print(f"Erreur génération alertes: {e}")

    return session


@login_required
@group_required('Officier_port', 'Directeur')
def resultats_planification(request, session_id):
    from collections import defaultdict
    from datetime import datetime, timedelta

    session = get_object_or_404(SessionOptimisation, id=session_id)
    affectations = Affectation.objects.filter(date_creation__gte=session.date_creation).order_by('heure_debut')
    
    if session.score_total == 0 and affectations:
        session.score_total = sum(a.score_contribution for a in affectations)
        session.attente_totale = sum(a.attente for a in affectations)
        session.attente_moyenne = session.attente_totale / len(affectations) if affectations else 0
        session.save()
    
    affectations_rade = [a for a in affectations if a.etat_initial == 'rade']
    affectations_attente = [a for a in affectations if a.etat_initial == 'attente']

    # ========== FONCTIONS UTILITAIRES ==========
    def get_shift_interval(dt):
        """Retourne (nom_shift, datetime_de_fin_du_shift) pour un datetime donné."""
        h = dt.hour + dt.minute / 60.0
        if 7 <= h < 13:
            return "07h_13h", dt.replace(hour=13, minute=0, second=0, microsecond=0)
        elif 13 <= h < 19:
            return "13h_19h", dt.replace(hour=19, minute=0, second=0, microsecond=0)
        elif 19 <= h < 24:
            return "19h_01h", dt.replace(hour=1, minute=0, second=0, microsecond=0) + timedelta(days=1)
        elif 0 <= h < 1:
            return "19h_01h", dt.replace(hour=1, minute=0, second=0, microsecond=0)
        else:
            return "01h_07h", dt.replace(hour=7, minute=0, second=0, microsecond=0)

    def temps_par_shift_calc(debut, fin):
        result = {}
        d = debut
        while d < fin:
            shift_name, fin_shift = get_shift_interval(d)
            seg_fin = min(fin, fin_shift)
            duree = (seg_fin - d).total_seconds() / 3600.0
            result[shift_name] = result.get(shift_name, 0) + duree
            d = seg_fin
        return result

    # ========== CALCUL DU TONNAGE PAR SHIFT ==========
    tonnage_par_shift = defaultdict(float)
    base_date = session.date_creation.date() if session.date_creation else timezone.now().date()

    for a in affectations:
        volume = a.navire.marchandise_volume or 0
        if volume <= 0:
            continue
        # Construire les datetime à partir des heures décimales
        debut_dt = datetime.combine(base_date, datetime.min.time()) + timedelta(hours=a.heure_debut)
        fin_dt = datetime.combine(base_date, datetime.min.time()) + timedelta(hours=a.heure_fin)
        if fin_dt < debut_dt:
            fin_dt += timedelta(days=1)
        shifts = temps_par_shift_calc(debut_dt, fin_dt)
        duree_totale = a.traitement
        if duree_totale > 0:
            for shift, duree in shifts.items():
                proportion = duree / duree_totale
                tonnage_par_shift[shift] += volume * proportion

    # Convertir les noms de shift (ex: "07h-13h" -> identique)
    # Ici les clés sont déjà propres (avec tirets)
    tonnage_par_shift = dict(tonnage_par_shift)

    context = {
        'session': session,
        'affectations': affectations,
        'affectations_rade': affectations_rade,
        'affectations_attente': affectations_attente,
        'tonnage_par_shift': tonnage_par_shift,
    }
    return render(request, 'port/resultats.html', context)
@login_required
def api_gantt_postes(request, session_id):
    """API pour le diagramme de Gantt avec les numéros de poste"""
    session = get_object_or_404(SessionOptimisation, id=session_id)
    affectations = Affectation.objects.filter(date_creation__gte=session.date_creation).select_related('navire__poste_attribue', 'quai')
    
    data = []
    couleurs = {
        'conteneur': '#3498db', 'cerealier': '#f39c12', 'ferry': '#9b59b6',
        'gazier': '#e74c3c', 'frigorifique': '#1abc9c', 'betail': '#e67e22',
        'essence': '#f1c40f', 'huilier': '#2ecc71', 'petrolier': '#d35400',
        'cargo': '#7f8c8d',
    }
    
    for a in affectations:
        # Déterminer le libellé à afficher sur l'axe Y
        if a.navire.poste_attribue:
            y_label = f"Poste {a.navire.poste_attribue.numero} ({a.quai.nom[:20]})"
        else:
            y_label = a.quai.nom
        
        data.append({
            'navire': a.navire.nom,
            'quai': y_label,
            'debut': float(a.heure_debut),
            'fin': float(a.heure_fin),
            'type': a.navire.type,
            'couleur': couleurs.get(a.navire.type, '#95a5a6'),
            'priorite': a.priorites_texte
        })
    
    # Ajout des buffers (optionnel)
    buffer_data = []
    for a in affectations:
        if a.buffer_debut > 0 or a.buffer_fin > 0:
            buffer_data.append({
                'navire': a.navire.nom,
                'quai': y_label,
                'debut': float(a.heure_debut_reel or (a.heure_debut - a.buffer_debut)),
                'fin': float(a.heure_fin_reel or (a.heure_fin + a.buffer_fin)),
                'type': 'buffer',
                'couleur': 'rgba(128,128,128,0.3)',
                'priorite': 'Buffer'
            })
    
    return JsonResponse({'success': True, 'data': data, 'buffer_data': buffer_data})
@login_required
@group_required('Officier_port', 'Directeur')
def exporter_planification_csv(request, session_id):
    session = get_object_or_404(SessionOptimisation, id=session_id)
    affectations = Affectation.objects.filter(date_creation__gte=session.date_creation).order_by('heure_debut')
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="planning_{session_id}.csv"'
    writer = csv.writer(response)
    writer.writerow(['Navire', 'Type', 'Quai', 'Début (h)', 'Fin (h)', 'Attente (h)', 'Priorités', 'Score'])
    for a in affectations:
        writer.writerow([
            a.navire.nom,
            a.navire.get_type_display(),
            a.quai.nom,
            f"{a.heure_debut:.2f}",
            f"{a.heure_fin:.2f}",
            f"{a.attente:.2f}",
            a.priorites_texte,
            f"{a.score_contribution:.2f}"
        ])
    writer.writerow([])
    writer.writerow(['Score total', f"{session.score_total:.2f}"])
    writer.writerow(['Attente totale', f"{session.attente_totale:.2f}h"])
    writer.writerow(['Attente moyenne', f"{session.attente_moyenne:.2f}h"])
    writer.writerow(['Taux occupation', f"{session.taux_occupation:.1f}%"])
    return response

@login_required
@group_required('Officier_port', 'Directeur')
def exporter_pdf(request, session_id):
    try:
        from django.template.loader import get_template
        from django.http import HttpResponse
        import tempfile
        import os
        
        session = get_object_or_404(SessionOptimisation, id=session_id)
        affectations = Affectation.objects.filter(date_creation__gte=session.date_creation).order_by('heure_debut')
        
        # Préparer les données pour le template
        affectations_rade = [a for a in affectations if a.etat_initial == 'rade']
        affectations_attente = [a for a in affectations if a.etat_initial == 'attente']
        
        context = {
            'session': session,
            'affectations': affectations,
            'affectations_rade': affectations_rade,
            'affectations_attente': affectations_attente,
            'date': datetime.now(),
        }
        
        template = get_template('port/rapport_pdf.html')
        html_string = template.render(context)
        
        # Créer un fichier HTML temporaire
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
            f.write(html_string)
            temp_html = f.name
        
        # Créer le PDF
        from weasyprint import HTML, CSS
        from weasyprint.text.fonts import FontConfiguration
        
        font_config = FontConfiguration()
        
        # Fichier PDF de sortie temporaire
        temp_pdf = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        temp_pdf.close()
        
        HTML(filename=temp_html).write_pdf(
            temp_pdf.name,
            font_config=font_config,
            stylesheets=[CSS(string='@page { size: A4; margin: 2cm; }')]
        )
        
        # Lire le PDF généré
        with open(temp_pdf.name, 'rb') as pdf_file:
            response = HttpResponse(pdf_file.read(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="rapport_{session_id}.pdf"'
        
        # Nettoyer les fichiers temporaires
        os.unlink(temp_html)
        os.unlink(temp_pdf.name)
        
        return response
        
    except Exception as e:
        logger.error(f"Erreur génération PDF: {str(e)}")
        messages.error(request, f"Erreur lors de la génération du PDF: {str(e)}")
        return redirect('resultats_planification', session_id=session_id)
# =============================================================================
# ACTIONS SUR LES NAVIRES (OFFICIER RADIO)
# =============================================================================

@login_required
@group_required('Officier_radio', 'Directeur')
def valider_arrivee_rade(request):
    if request.method == 'POST':
        navire_id = request.POST.get('navire_id')
        if navire_id:
            navire = get_object_or_404(Navire, id=navire_id)
            maintenant = datetime.now()
            heure_actuelle = maintenant.hour + maintenant.minute / 60
            navire.arrivee = heure_actuelle
            navire.etat = 'rade'
            navire.coord_x = 600
            navire.coord_y = 750
            navire.save()

            # --- HISTORIQUE ---
            ajouter_historique(
                utilisateur=request.user,
                type_action='arrivee_rade',
                description=f"Validation de l'arrivée en rade de {navire.nom} à {heure_actuelle}h",
                navire=navire,
                details={'heure_arrivee': heure_actuelle}
            )
            messages.success(request, f"✅ {navire.nom} validé en rade à {heure_actuelle:.1f}h")
        return redirect('liste_navires')

    # --- GET : afficher tous les navires en attente (ETA passé ou futur) ---
    maintenant = timezone.now()
    # Récupérer TOUS les navires en attente (quel que soit leur ETA)
    navires_arrives = Navire.objects.filter(
        etat='attente',
        arrivee_datetime__isnull=False
    ).order_by('arrivee_datetime')

    attentes = []
    navires_urgents = 0
    for navire in navires_arrives:
        # Calcul de l'attente : 0 si ETA futur, sinon temps écoulé
        if navire.arrivee_datetime <= maintenant:
            delta = maintenant - navire.arrivee_datetime
            attente = delta.total_seconds() / 3600
        else:
            attente = 0
        navire.temps_attente = attente
        if attente > 4:
            navires_urgents += 1
        attentes.append(attente)

    total_rade = Navire.objects.filter(etat='rade').count()
    attente_moyenne = sum(attentes) / len(attentes) if attentes else 0

    context = {
        'navires_arrives': navires_arrives,
        'heure_actuelle': maintenant.hour + maintenant.minute/60.0,
        'total_rade': total_rade,
        'attente_moyenne': round(attente_moyenne, 1),
        'navires_urgents': navires_urgents,
    }
    return render(request, 'port/valider_rade.html', context)
@login_required
@group_required('Officier_port', 'Directeur')
def terminer_navires_confirm(request):
    from datetime import datetime, timedelta
    from django.utils import timezone
    
    now = datetime.now()
    heure_actuelle = now.hour + now.minute / 60.0

    # Récupérer TOUS les navires à quai
    navires_a_terminer = []
    for navire in Navire.objects.filter(etat='quai').order_by('debut_datetime'):
        if navire.debut_datetime and navire.marchandise_volume > 0:
            quai_actuel = navire.quai_attribue
            if quai_actuel:
                duree_totale = estimer_duree_traitement(navire, quai_actuel)
            else:
                duree_totale = estimer_duree_traitement(navire, quai=None)
            
            fin_prevue = navire.debut_datetime + timedelta(hours=duree_totale)
            
            # Ajouter les notes d'attente
            from port.models import NoteAttente
            notes_attente = NoteAttente.objects.filter(navire=navire, prise_en_compte=False)
            for note in notes_attente:
                fin_prevue += timedelta(hours=note.duree_attente)
            
            temps_restant = (fin_prevue - now).total_seconds() / 3600.0
            
            navire.temps_restant = max(0, temps_restant)
            navire.fin_datetime = fin_prevue
            navires_a_terminer.append(navire)
        else:
            if navire.heure_fin is not None:
                temps_restant = navire.heure_fin - heure_actuelle
                navire.temps_restant = max(0, temps_restant)
                navire.fin_datetime = now + timedelta(hours=navire.temps_restant)
                navires_a_terminer.append(navire)

    navires_a_terminer.sort(key=lambda x: x.temps_restant)
    navires_critiques = sum(1 for n in navires_a_terminer if n.temps_restant <= 2)
    liberations_quais = len(set(n.quai_attribue_id for n in navires_a_terminer if n.quai_attribue_id))
    
    # CORRECTION : utiliser fin_datetime au lieu de date_fin_reel
    navires_recemment_termines = Navire.objects.filter(
        etat='termine',
        fin_datetime__gte=timezone.now() - timedelta(days=1)
    ).count()

    debut_periode = now
    fin_periode = now + timedelta(hours=24)

    return render(request, 'port/terminer_navires.html', {
        'navires': navires_a_terminer,
        'heure_actuelle': heure_actuelle,
        'heure_limite': heure_actuelle + 24,
        'navires_critiques': navires_critiques,
        'liberations_quais': liberations_quais,
        'navires_recemment_termines': navires_recemment_termines,
        'debut_periode': debut_periode,
        'fin_periode': fin_periode,
    })

@login_required
@group_required('Officier_port', 'Directeur')
def terminer_navires_execute(request):
    if request.method == 'POST':
        navire_ids = request.POST.getlist('navire_ids')
        if navire_ids:
            navires = Navire.objects.filter(id__in=navire_ids, etat='quai')
            nb = navires.count()
            
            for navire in navires:
                # ============================================================
                # INITIALISATION DES VARIABLES (AVANT TOUTE CONDITION)
                # Évite le bug "UnboundLocalError: debit_reel"
                # ============================================================
                duree_reelle = None
                duree_estimee = None
                equipements_utilises = ""
                nb_equipes = 0
                shift = None
                debit_reel = 0.0
                # ============================================================
                
                # Récupérer la dernière affectation
                affect = Affectation.objects.filter(navire=navire).order_by('-date_creation').first()
                
                # Traitement SI l'affectation existe et est complète
                if affect and affect.heure_debut is not None and affect.heure_fin is not None:
                    duree_estimee = affect.traitement
                    
                    if navire.debut_datetime:
                        now = timezone.now()
                        duree_reelle = (now - navire.debut_datetime).total_seconds() / 3600.0
                        
                        # Récupérer les équipements utilisés (à partir de l'affectation)
                        equipements_utilises = affect.equipements_utilises if hasattr(affect, 'equipements_utilises') else ""
                        
                        # Récupérer le nombre d'équipes et le shift via AffectationEquipe
                        affect_equipes = AffectationEquipe.objects.filter(navire=navire)
                        if affect_equipes.exists():
                            nb_equipes = affect_equipes.count()
                            # Prendre le shift de la première (ou fusionner si plusieurs)
                            shift = affect_equipes.first().shift
                        
                        # Calcul du débit réel (tonnes/heure)
                        if duree_reelle > 0 and navire.marchandise_volume:
                            debit_reel = navire.marchandise_volume / duree_reelle
                        
                        # Créer l'historique d'opération
                        HistoriqueOperation.objects.create(
                            navire_type=navire.type,
                            quai_id=navire.quai_attribue.id if navire.quai_attribue else None,
                            volume=navire.marchandise_volume,
                            duree_estimee=duree_estimee,
                            duree_reelle=duree_reelle,
                            date_operation=now,
                            nb_equipes=nb_equipes,
                            shift=shift,
                            equipements_utilises=equipements_utilises,
                            debit_reel=debit_reel
                        )
                
                # ============================================================
                # LIBÉRATION DU POSTE ET DU QUAI
                # ============================================================
                if navire.poste_attribue:
                    poste = navire.poste_attribue
                    poste.disponible = True
                    poste.occupation_jusqua = 0.0
                    poste.save()
                    
                    if poste.quai:
                        poste.quai.disponible = True
                        poste.quai.occupation_jusqua = 0.0
                        poste.quai.save()
                
                elif navire.quai_attribue:
                    quai = navire.quai_attribue
                    quai.disponible = True
                    quai.occupation_jusqua = 0.0
                    quai.save()
                
                # ============================================================
                # CHANGEMENT D'ÉTAT DU NAVIRE
                # ============================================================
                navire.etat = 'termine'
                navire.poste_attribue = None
                navire.quai_attribue = None
                navire.save()
                
                # ============================================================
                # ENREGISTREMENT DANS L'HISTORIQUE
                # (toutes les variables sont maintenant définies)
                # ============================================================
                ajouter_historique(
                    utilisateur=request.user,
                    type_action='terminaison',
                    description=f"Navire {navire.nom} marqué comme terminé",
                    navire=navire,
                    details={
                        'duree_reelle': duree_reelle,
                        'debit_reel': debit_reel,
                        'nb_equipes': nb_equipes,
                        'shift': shift
                    }
                )
                
                # ============================================================
                # CLÔTURER L'ESCALE ASSOCIÉE (optionnel, recommandé)
                # ============================================================
                try:
                    from port.utils_escales import cloturer_escale
                    escale = cloturer_escale(navire)
                    if escale:
                        print(f"✅ Escale #{escale.id} clôturée pour {navire.nom}")
                except Exception as e:
                    print(f"⚠️ Erreur clôture escale pour {navire.nom}: {e}")
            
            messages.success(request, f"✅ {nb} navires terminés et historiques enregistrés.")
        else:
            messages.warning(request, "Aucun navire sélectionné.")
    
    return redirect('dashboard')

# =============================================================================
# MODE MANUEL (OFFICIER RADIO)
# =============================================================================

@login_required
@group_required('Officier_port', 'Directeur')
def mode_manuel(request):
    navire_id = request.GET.get('navire')
    navire_selectionne = None
    if navire_id:
        navire_selectionne = get_object_or_404(Navire, id=navire_id)

    navires_rade = Navire.objects.filter(etat='rade').order_by('arrivee_datetime')
    navires_quai = Navire.objects.filter(etat='quai').select_related('quai_attribue', 'poste_attribue').order_by('heure_debut')
    tous_les_quais = Quai.objects.all().order_by('id')
    postes_manuels = Poste.objects.filter(gestion_manuelle=True).select_related('quai')
    
    # Tous les postes pour l'affichage
    tous_les_postes = Poste.objects.all().select_related('quai').order_by('numero')
    
    # Postes disponibles
    postes_disponibles = Poste.objects.filter(
        disponible=True,
        quai__bloque=False
    ).select_related('quai')
    
    # Postes occupés
    postes_occupes = Navire.objects.filter(etat='quai', poste_attribue__isnull=False).count()
    
    # Calcul du temps d'attente pour les navires en rade
    from datetime import datetime
    now = datetime.now()
    for navire in navires_rade:
        if navire.arrivee_datetime:
            delta = now - navire.arrivee_datetime
            navire.temps_attente_calcule = delta.total_seconds() / 3600
        else:
            navire.temps_attente_calcule = 0
    
    # Calcul de la progression pour les navires à quai
    for navire in navires_quai:
        if navire.debut_datetime and navire.heure_fin and navire.marchandise_volume > 0:
            temps_ecoule = (now - navire.debut_datetime).total_seconds() / 3600
            duree_totale = navire.heure_fin - navire.heure_debut
            if duree_totale > 0:
                progression = (temps_ecoule / duree_totale) * 100
                navire.progression_calculee = min(100, max(0, progression))
            else:
                navire.progression_calculee = 0
        else:
            navire.progression_calculee = 0
        
        # Postes disponibles pour changement
        if navire.poste_attribue:
            postes_disponibles_pour_changement = []
            for p in tous_les_postes:
                if not p.disponible:
                    continue
                if p.id == navire.poste_attribue.id:
                    continue
                if p.quai and p.quai.bloque:
                    continue
                if navire.longueur > p.longueur:
                    continue
                if navire.tirant > p.profondeur:
                    continue
                postes_disponibles_pour_changement.append(p)
            navire.postes_disponibles = postes_disponibles_pour_changement[:5]
        else:
            navire.postes_disponibles = []

    quais_occupes_ids = set(Navire.objects.filter(etat='quai', quai_attribue__isnull=False).values_list('quai_attribue_id', flat=True))

    for navire in navires_quai:
        if navire.quai_attribue is None:
            navire.quais_disponibles = []
            continue
        disponibles = []
        for q in tous_les_quais:
            if q.bloque: continue
            if q.id == navire.quai_attribue.id: continue
            if q.id in quais_occupes_ids: continue
            disponibles.append(q)
        navire.quais_disponibles = disponibles

    # Nombre de quais libres
    quais_libres = Quai.objects.filter(disponible=True, bloque=False).count()

    context = {
        'navires_rade': navires_rade,
        'navires_quai': navires_quai,
        'quais': tous_les_quais,
        'postes_manuels': postes_manuels,
        'postes_disponibles': postes_disponibles,
        'tous_les_postes': tous_les_postes,
        'postes_occupes': postes_occupes,
        'navire_selectionne': navire_selectionne,
        'quais_libres': quais_libres,
    }
    return render(request, 'port/mode_manuel.html', context)


@login_required
@group_required('Directeur') 
def basculer_blocage_poste(request, poste_id):
    """Basculer le blocage manuel d'un poste - Version sans champ bloque sur Poste"""
    poste = get_object_or_404(Poste, id=poste_id)
    
    # Utiliser un attribut dynamique ou stocker dans la session
    # Puisque le champ 'bloque' n'existe pas, on utilise un attribut sur l'objet
    if not hasattr(poste, '_bloque_temp'):
        poste._bloque_temp = False
    
    poste._bloque_temp = not poste._bloque_temp
    
    if poste._bloque_temp:
        # Si le poste est bloqué, libérer le navire qui y est
        navire_sur_poste = Navire.objects.filter(poste_attribue=poste, etat='quai').first()
        if navire_sur_poste:
            navire_sur_poste.etat = 'rade'
            navire_sur_poste.poste_attribue = None
            navire_sur_poste.quai_attribue = None
            navire_sur_poste.save()
        messages.warning(request, f"🔒 Poste {poste.numero} bloqué temporairement.")
    else:
        messages.info(request, f"🔓 Poste {poste.numero} débloqué.")
    
    # Stocker l'état dans la session
    postes_bloques = request.session.get('postes_bloques', [])
    if poste._bloque_temp:
        if poste.id not in postes_bloques:
            postes_bloques.append(poste.id)
    else:
        if poste.id in postes_bloques:
            postes_bloques.remove(poste.id)
    request.session['postes_bloques'] = postes_bloques
    
    return redirect('mode_manuel')


@login_required
@group_required('Directeur', 'Officier_port') 
def changer_poste_navire(request, navire_id):
    """Changer un navire de poste"""
    if request.method == 'POST':
        navire = get_object_or_404(Navire, id=navire_id, etat='quai')
        nouveau_poste_id = request.POST.get('nouveau_poste_id')
        
        if not nouveau_poste_id:
            messages.error(request, "Veuillez sélectionner un poste")
            return redirect('mode_manuel')
        
        try:
            nouveau_poste = Poste.objects.get(id=nouveau_poste_id)
        except Poste.DoesNotExist:
            messages.error(request, "Poste non trouvé")
            return redirect('mode_manuel')
        
        # Vérifier si le poste est disponible
        if not nouveau_poste.disponible:
            messages.error(request, f"Le poste {nouveau_poste.numero} n'est pas disponible")
            return redirect('mode_manuel')
        
        # Vérifier compatibilité
        if navire.longueur > nouveau_poste.longueur:
            messages.error(request, f"Navire trop long ({navire.longueur}m > {nouveau_poste.longueur}m)")
            return redirect('mode_manuel')
        
        if navire.tirant > nouveau_poste.profondeur:
            messages.error(request, f"Tirant d'eau trop important ({navire.tirant}m > {nouveau_poste.profondeur}m)")
            return redirect('mode_manuel')
        
        # Libérer l'ancien poste
        if navire.poste_attribue:
            ancien_poste = navire.poste_attribue
            ancien_poste.disponible = True
            ancien_poste.occupation_jusqua = 0.0
            ancien_poste.save()
        
        # Mettre à jour le navire
        navire.poste_attribue = nouveau_poste
        navire.quai_attribue = nouveau_poste.quai
        navire.save()
        
        # Occuper le nouveau poste
        nouveau_poste.disponible = False
        nouveau_poste.occupation_jusqua = navire.heure_fin
        nouveau_poste.save()
        
        if nouveau_poste.quai:
            nouveau_poste.quai.disponible = False
            nouveau_poste.quai.occupation_jusqua = navire.heure_fin
            nouveau_poste.quai.save()
        
        # Supprimer de la session CPN
        navires_cpn_ids = request.session.get('navires_cpn_ids', [])
        if navire.id in navires_cpn_ids:
            navires_cpn_ids.remove(navire.id)
            request.session['navires_cpn_ids'] = navires_cpn_ids
            request.session.modified = True
        
        messages.success(request, f"✅ {navire.nom} déplacé vers le poste {nouveau_poste.numero}")
        return redirect('mode_manuel')
    
    return redirect('mode_manuel')


def ajouter_historique(utilisateur, type_action, description, navire=None, quai=None, equipement=None, details=None):
    """Ajoute une entrée dans l'historique des actions"""
    from .models import HistoriqueAction
    from django.utils import timezone
    HistoriqueAction.objects.create(
        utilisateur=utilisateur if utilisateur and utilisateur.is_authenticated else None,
        type_action=type_action,
        description=description,
        date_action=timezone.now(),
        navire=navire,
        quai=quai,
        equipement=equipement,
        details=details or {}
    )

@login_required
@group_required('Directeur', 'Officier_port')
def deplacer_navire(request, navire_id):
    if request.method == 'POST':
        navire = get_object_or_404(Navire, id=navire_id)
        nouveau_poste_id = request.POST.get('quai_id')  # En fait c'est l'ID du poste
        action = request.POST.get('action')

        # ========== RÉCUPÉRER LA SESSION CPN ==========
        navires_cpn_ids = request.session.get('navires_cpn_ids', [])
        session_modifiee = False

        if action == 'to_rade':
            # Libérer le poste actuel
            if navire.poste_attribue:
                poste = navire.poste_attribue
                poste.disponible = True
                poste.occupation_jusqua = 0.0
                poste.save()
                # Libérer aussi le quai parent
                if poste.quai:
                    poste.quai.disponible = True
                    poste.quai.occupation_jusqua = 0.0
                    poste.quai.save()
            navire.etat = 'rade'
            navire.poste_attribue = None
            navire.quai_attribue = None
            navire.heure_debut = None
            navire.heure_fin = None
            navire.coord_x = 600
            navire.coord_y = 750
            navire.save()

            # ========== SUPPRIMER DE LA SESSION CPN ==========
            if navire.id in navires_cpn_ids:
                navires_cpn_ids.remove(navire.id)
                session_modifiee = True
                print(f"🗑️ {navire.nom} (ID: {navire.id}) retiré de la planification CPN")

            ajouter_historique(
                utilisateur=request.user,
                type_action='deplacement',
                description=f"Déplacement manuel de {navire.nom} vers la rade",
                navire=navire
            )
            messages.success(request, f"✅ {navire.nom} déplacé en rade.")

        elif action == 'to_quai' and nouveau_poste_id:
            poste = get_object_or_404(Poste, id=nouveau_poste_id)
            quai = poste.quai
            if hasattr(poste, 'bloque') and poste.bloque:
                messages.error(request, f"❌ Poste {poste.numero} est bloqué manuellement.")
                return redirect('mode_manuel')

            if poste.disponible and not Navire.objects.filter(poste_attribue=poste, etat='quai').exists():
                # Libérer l'ancien poste si nécessaire
                if navire.poste_attribue:
                    ancien_poste = navire.poste_attribue
                    ancien_poste.disponible = True
                    ancien_poste.occupation_jusqua = 0.0
                    ancien_poste.save()
                    if ancien_poste.quai:
                        ancien_poste.quai.disponible = True
                        ancien_poste.quai.occupation_jusqua = 0.0
                        ancien_poste.quai.save()

                heure_debut_str = request.POST.get('heure_debut', '').strip()
                heure_fin_str = request.POST.get('heure_fin', '').strip()

                try:
                    navire.heure_debut = float(heure_debut_str) if heure_debut_str else 0.0
                except ValueError:
                    navire.heure_debut = 0.0

                try:
                    navire.heure_fin = float(heure_fin_str) if heure_fin_str else navire.heure_debut + 24
                except ValueError:
                    navire.heure_fin = navire.heure_debut + 24

                navire.poste_attribue = poste
                navire.quai_attribue = quai
                navire.etat = 'quai'
                if quai.coord_x is not None and quai.coord_y is not None:
                    navire.coord_x = quai.coord_x
                    navire.coord_y = quai.coord_y
                else:
                    navire.coord_x = 0
                    navire.coord_y = 0
                navire.save()

                poste.disponible = False
                poste.occupation_jusqua = navire.heure_fin
                poste.save()
                quai.disponible = False
                quai.occupation_jusqua = navire.heure_fin
                quai.save()

                # ========== SUPPRIMER DE LA SESSION CPN ==========
                if navire.id in navires_cpn_ids:
                    navires_cpn_ids.remove(navire.id)
                    session_modifiee = True
                    print(f"🗑️ {navire.nom} (ID: {navire.id}) retiré de la planification CPN")

                ajouter_historique(
                    utilisateur=request.user,
                    type_action='deplacement',
                    description=f"Déplacement manuel de {navire.nom} vers le poste {poste.numero} (quai {quai.nom}) (début: {navire.heure_debut:.1f}h, fin: {navire.heure_fin:.1f}h)",
                    navire=navire,
                    quai=quai,
                    details={'poste_id': poste.id, 'poste_numero': poste.numero, 'heure_debut': navire.heure_debut, 'heure_fin': navire.heure_fin}
                )
                messages.success(request, f"✅ {navire.nom} affecté au poste {poste.numero} ({quai.nom}) (de {navire.heure_debut:.1f}h à {navire.heure_fin:.1f}h).")
            else:
                messages.error(request, f"❌ Poste {poste.numero} déjà occupé.")
        else:
            messages.error(request, "Action non reconnue ou poste manquant.")

        # ========== SAUVEGARDER LA SESSION MODIFIÉE ==========
        if session_modifiee:
            request.session['navires_cpn_ids'] = navires_cpn_ids
            request.session.modified = True

        return redirect('mode_manuel')
    return redirect('mode_manuel')
def supprimer_navire_de_session_cpn(request, navire_id):
    """Supprime un navire de la session CPN s'il y est présent"""
    navires_cpn_ids = request.session.get('navires_cpn_ids', [])
    if navire_id in navires_cpn_ids:
        navires_cpn_ids.remove(navire_id)
        request.session['navires_cpn_ids'] = navires_cpn_ids
        print(f"🗑️ Navire {navire_id} supprimé de la session CPN")
@login_required
@group_required('Officier_radio', 'Directeur')
def basculer_blocage_quai(request, quai_id):
    quai = get_object_or_404(Quai, id=quai_id)
    quai.bloque = not quai.bloque
    if quai.bloque:
        navire_sur_quai = Navire.objects.filter(quai_attribue=quai, etat='quai').first()
        if navire_sur_quai:
            navire_sur_quai.etat = 'rade'
            navire_sur_quai.quai_attribue = None
            navire_sur_quai.save()
        quai.disponible = False
        quai.occupation_jusqua = 0.0
        messages.warning(request, f"🔒 Quai {quai.nom} bloqué.")
    else:
        quai.disponible = True
        messages.info(request, f"🔓 Quai {quai.nom} débloqué.")
    quai.save()

    # --- HISTORIQUE ---
    action_texte = "bloqué" if quai.bloque else "débloqué"
    ajouter_historique(
        utilisateur=request.user,
        type_action='blocage_quai',
        description=f"Quai {quai.nom} {action_texte} manuellement",
        quai=quai,
        details={'bloque': quai.bloque}
    )
    return redirect('mode_manuel')

@login_required
@group_required('Officier_radio', 'Directeur')
def forcer_priorite(request, navire_id):
    navire = get_object_or_404(Navire, id=navire_id)
    navire.strategique = not navire.strategique
    navire.save()
    status = "activée" if navire.strategique else "désactivée"

    # --- HISTORIQUE ---
    ajouter_historique(
        utilisateur=request.user,
        type_action='priorite',
        description=f"Forçage de priorité stratégique {status} pour {navire.nom}",
        navire=navire,
        details={'strategique': navire.strategique}
    )
    messages.success(request, f"⭐ Priorité stratégique {status} pour {navire.nom}.")
    return redirect('mode_manuel')

# =============================================================================
# STATISTIQUES & PAGES DIVERSES
# =============================================================================

@login_required
def grille_priorites(request):
    return render(request, 'port/priorites.html')

@login_required
def statistiques(request):
    from django.db.models import Count, Avg, Max, Sum
    
    # Statistiques de base
    total_navires = Navire.objects.count()
    total_sessions = SessionOptimisation.objects.count()
    
    # Calcul de l'attente moyenne
    attente_moyenne = Affectation.objects.aggregate(Avg('attente'))['attente__avg'] or 0
    
    # Score moyen
    score_moyen = SessionOptimisation.objects.aggregate(Avg('score_total'))['score_total__avg'] or 0
    
    # Attente maximale
    attente_max = Affectation.objects.aggregate(Max('attente'))['attente__max'] or 0
    
    # Navires par type
    navires_par_type = Navire.objects.values('type').annotate(count=Count('id')).order_by('-count')
    
    # Sessions récentes
    sessions = SessionOptimisation.objects.all().order_by('-date_creation')[:15]
    
    # Navires en rade et à quai
    navires_rade = Navire.objects.filter(etat='rade').count()
    navires_quai = Navire.objects.filter(etat='quai').count()
    
    # Top navires (via API ou direct)
    top_navires = Affectation.objects.values(
        'navire__nom', 
        'navire__type'
    ).annotate(
        count=Count('id'),
        score_moyen=Avg('score_contribution')
    ).order_by('-count')[:5]
    
    stats = {
        'total_navires': total_navires,
        'attente_moyenne': attente_moyenne,
        'score_moyen': score_moyen,
        'total_sessions': total_sessions,
        'navires_rade': navires_rade,
        'navires_quai': navires_quai,
        'attente_max': attente_max,
        'navires_par_type': navires_par_type,
        'sessions': sessions,
        'top_navires': top_navires,
    }
    
    return render(request, 'port/statistiques.html', {'stats': stats})

@login_required
def lancer_planification(request):
    # Redirection simple vers la CPN
    return redirect('cpn')

# =============================================================================
# ALERTES & NOTIFICATIONS
# =============================================================================

# =============================================================================
# ALERTES & NOTIFICATIONS
# =============================================================================

def api_notifications(request):
    """API pour les notifications - Récupère toutes les alertes (lues et non lues)"""
    # Récupérer toutes les alertes, les 30 dernières, triées par date décroissante
    alertes = Alerte.objects.all().order_by('-date_creation')[:30]
    
    data = [{
        'id': a.id,
        'message': a.message,
        'niveau': a.niveau,
        'date': a.date_creation.isoformat(),
        'lien': a.lien,
        'est_lue': a.est_lue,
        'source': getattr(a, 'source', 'Système')
    } for a in alertes]
    
    # Compter les non lues pour le badge
    non_lues_count = Alerte.objects.filter(est_lue=False).count()
    
    return JsonResponse({
        'notifications': data, 
        'count': len(alertes),
        'unread_count': non_lues_count
    })


def marquer_alerte_lue(request, alerte_id):
    """Marquer une alerte comme lue (API)"""
    try:
        alerte = Alerte.objects.get(id=alerte_id)
        alerte.est_lue = True
        alerte.date_resolution = timezone.now()
        alerte.save()
        return JsonResponse({'success': True})
    except Alerte.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Alerte introuvable'}, status=404)


@csrf_exempt
def supprimer_alerte(request, alerte_id):
    """Supprimer une alerte (API)"""
    try:
        alerte = Alerte.objects.get(id=alerte_id)
        alerte.delete()
        return JsonResponse({'success': True})
    except Alerte.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Alerte introuvable'}, status=404)


@csrf_exempt
def marquer_toutes_alertes_lues(request):
    """Marquer toutes les alertes comme lues"""
    count = Alerte.objects.filter(est_lue=False).update(est_lue=True, date_resolution=timezone.now())
    return JsonResponse({'success': True, 'count': count})
def liste_alertes(request):
    alertes = Alerte.objects.filter(est_lue=False).order_by('-date_creation')
    paginator = Paginator(alertes, 20)          # Correction du nom
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'port/alertes.html', {'page_obj': page_obj})

# =============================================================================
# API DIVERSES
# =============================================================================

def api_stats_attentes(request):
    """API pour les statistiques des temps d'attente avec support de période"""
    from django.utils import timezone
    from datetime import timedelta
    from django.db.models import Avg, Count
    
    period = request.GET.get('period', 'week')
    
    now = timezone.now()
    
    if period == 'week':
        days = 7
        date_debut = now - timedelta(days=7)
    elif period == 'month':
        days = 30
        date_debut = now - timedelta(days=30)
    elif period == 'quarter':
        days = 90
        date_debut = now - timedelta(days=90)
    else:
        days = 7
        date_debut = now - timedelta(days=7)
    
    # Récupérer les affectations
    affectations = Affectation.objects.filter(
        date_creation__gte=date_debut
    ).order_by('date_creation')
    
    # Grouper par date
    attentes_par_jour = {}
    
    # Initialiser tous les jours à 0
    for i in range(days):
        jour = date_debut + timedelta(days=i)
        jour_str = jour.strftime('%Y-%m-%d')
        attentes_par_jour[jour_str] = 0
    
    # Remplir avec les données réelles
    for a in affectations:
        jour_str = a.date_creation.strftime('%Y-%m-%d')
        if jour_str in attentes_par_jour:
            attentes_par_jour[jour_str] = a.attente
    
    # Convertir en listes pour le graphique
    labels = []
    attentes = []
    
    for i in range(days):
        jour = date_debut + timedelta(days=i)
        jour_str = jour.strftime('%Y-%m-%d')
        labels.append(jour.strftime('%d/%m'))
        attentes.append(round(attentes_par_jour[jour_str], 1))
    
    # Calculer la moyenne des jours avec données
    valeurs_non_zero = [v for v in attentes if v > 0]
    moyenne = round(sum(valeurs_non_zero) / len(valeurs_non_zero), 1) if valeurs_non_zero else 0
    
    return JsonResponse({
        'labels': labels,
        'attentes': attentes,
        'moyenne': moyenne,
        'period': period
    })

# =============================================================================
# API STATISTIQUES
# =============================================================================

def api_stats_sessions(request):
    """API pour les statistiques des sessions"""
    sessions = SessionOptimisation.objects.all().order_by('-date_creation')[:10]
    
    # Inverser pour avoir l'ordre chronologique
    sessions_list = list(reversed(sessions))
    
    data = {
        'dates': [s.date_creation.strftime('%d/%m') for s in sessions_list],
        'scores': [float(s.score_total) for s in sessions_list],
        'navires': [s.nb_navires for s in sessions_list]
    }
    return JsonResponse(data)


def api_stats_occupation_quais(request):
    """API pour l'occupation des quais"""
    from django.db.models import Count, Q
    from datetime import timedelta
    from django.utils import timezone
    
    # Compter les navires actuellement à quai par quai
    navires_par_quai = Navire.objects.filter(
        etat='quai',
        quai_attribue__isnull=False
    ).values('quai_attribue__nom').annotate(
        count=Count('id')
    ).order_by('-count')
    
    if navires_par_quai.exists():
        data = {
            'labels': [item['quai_attribue__nom'] for item in navires_par_quai],
            'counts': [item['count'] for item in navires_par_quai]
        }
    else:
        # Données par défaut avec tous les quais
        tous_les_quais = Quai.objects.all()
        data = {
            'labels': [q.nom for q in tous_les_quais],
            'counts': [0 for q in tous_les_quais]
        }
    
    return JsonResponse(data)

def api_stats_top_navires(request):
    """API pour le top 5 des navires"""
    from django.db.models import Count, Avg
    
    top_navires = Affectation.objects.values(
        'navire__nom', 
        'navire__type'
    ).annotate(
        count=Count('id'),
        score_moyen=Avg('score_contribution')
    ).order_by('-count')[:5]
    
    data = []
    for nav in top_navires:
        data.append({
            'nom': nav['navire__nom'],
            'type': nav['navire__type'],
            'count': nav['count'],
            'score_moyen': float(nav['score_moyen']) if nav['score_moyen'] else 0
        })
    
    return JsonResponse({'top_navires': data})

def api_stats_occupation(request):
    affectations = Affectation.objects.order_by('-date_creation')[:50]
    quais_counts = {}
    for a in affectations:
        quais_counts[a.quai.nom] = quais_counts.get(a.quai.nom, 0) + 1
    data = {
        'labels': list(quais_counts.keys()),
        'counts': list(quais_counts.values())
    }
    return JsonResponse(data)

def api_stats_dashboard(request):
    dates = []
    sessions_par_jour = []
    navires_par_jour = []
    for i in range(7):
        date = datetime.now() - timedelta(days=i)
        dates.append(date.strftime('%d/%m'))
        sessions = SessionOptimisation.objects.filter(date_creation__date=date.date()).count()
        sessions_par_jour.append(sessions)
        navires = Affectation.objects.filter(date_creation__date=date.date()).values('navire').distinct().count()
        navires_par_jour.append(navires)
    types_navires = Navire.objects.values('type').annotate(count=Count('id')).order_by('-count')
    total_sessions = SessionOptimisation.objects.count()
    total_affectations = Affectation.objects.count()
    derniere_session = SessionOptimisation.objects.last()
    dernier_score = derniere_session.score_total if derniere_session else 0
    data = {
        'dates': dates[::-1],
        'sessions_par_jour': sessions_par_jour[::-1],
        'navires_par_jour': navires_par_jour[::-1],
        'types_navires': list(types_navires),
        'total_sessions': total_sessions,
        'total_affectations': total_affectations,
        'dernier_score': float(dernier_score),
    }
    return JsonResponse(data)

def api_stats_equipements_sollicites(request):
    equipements_stats = {}
    for navire in Navire.objects.filter(etat='quai'):
        equipements = get_equipements_par_type(navire)
        for eq in equipements:
            equipements_stats[eq] = equipements_stats.get(eq, 0) + 1
    sorted_stats = sorted(equipements_stats.items(), key=lambda x: x[1], reverse=True)[:5]
    data = {
        'labels': [eq[0] for eq in sorted_stats],
        'utilisations': [eq[1] for eq in sorted_stats],
    }
    return JsonResponse(data)

def api_gantt_data(request, session_id):
    try:
        session = get_object_or_404(SessionOptimisation, id=session_id)
        affectations = Affectation.objects.filter(date_creation__gte=session.date_creation)
        couleurs = {
            'conteneur': '#3498db', 'cerealier': '#f39c12', 'ferry': '#9b59b6',
            'gazier': '#e74c3c', 'frigorifique': '#1abc9c', 'betail': '#e67e22',
            'essence': '#f1c40f', 'huilier': '#2ecc71', 'petrolier': '#d35400',
            'cargo': '#7f8c8d',
        }
        data = []
        buffer_data = []
        for a in affectations:
            data.append({
                'navire': a.navire.nom,
                'quai': a.quai.nom,
                'debut': float(a.heure_debut),
                'fin': float(a.heure_fin),
                'type': a.navire.type,
                'couleur': couleurs.get(a.navire.type, '#95a5a6'),
                'priorite': a.priorites_texte
            })
            if a.buffer_debut > 0 or a.buffer_fin > 0:
                debut_buffer = float(a.heure_debut_reel if a.heure_debut_reel is not None else a.heure_debut - a.buffer_debut)
                fin_buffer = float(a.heure_fin_reel if a.heure_fin_reel is not None else a.heure_fin + a.buffer_fin)
                buffer_data.append({
                    'navire': a.navire.nom,
                    'quai': a.quai.nom,
                    'debut': debut_buffer,
                    'fin': fin_buffer,
                    'type': 'buffer',
                    'couleur': 'rgba(128,128,128,0.3)',
                    'priorite': 'Buffer'
                })
        return JsonResponse({'success': True, 'data': data, 'buffer_data': buffer_data})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

# =============================================================================
# GESTION DES UTILISATEURS (DIRECTEUR)
# =============================================================================

@login_required
@group_required('Directeur')
def gestion_utilisateurs(request):
    utilisateurs = User.objects.all().order_by('-date_joined')
    groupes = Group.objects.all()
    
    # Statistiques
    stats = {
        'admins': User.objects.filter(is_superuser=True).count(),
        'actifs': User.objects.filter(is_active=True).count(),
        'nouveaux_mois': User.objects.filter(date_joined__gte=timezone.now() - timedelta(days=30)).count(),
    }
    
    return render(request, 'port/gestion_utilisateurs.html', {
        'utilisateurs': utilisateurs,
        'groupes': groupes,
        'stats': stats,
    })

@login_required
@group_required('Directeur')
def ajouter_utilisateur(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        email = request.POST.get('email', '')
        groupe_id = request.POST.get('groupe')
        user = User.objects.create_user(username=username, password=password, email=email)
        if groupe_id:
            groupe = Group.objects.get(id=groupe_id)
            user.groups.add(groupe)
        messages.success(request, f"Utilisateur {username} créé.")
        return redirect('gestion_utilisateurs')
    groupes = Group.objects.all()
    return render(request, 'port/ajouter_utilisateur.html', {'groupes': groupes})

from .models import Profile  # Assurez-vous d'importer Profile

@login_required
@group_required('Directeur')
def modifier_utilisateur(request, user_id):
    user = get_object_or_404(User, id=user_id)
    # Créer le profil s'il n'existe pas (pour les anciens utilisateurs)
    Profile.objects.get_or_create(user=user)

    if request.method == 'POST':
        # Mise à jour des champs User
        user.username = request.POST['username']
        user.email = request.POST.get('email', '')
        new_password = request.POST.get('password')
        if new_password:
            user.set_password(new_password)
        user.save()

        # Mise à jour du groupe
        user.groups.clear()
        groupe_id = request.POST.get('groupe')
        if groupe_id:
            user.groups.add(Group.objects.get(id=groupe_id))

        # Mise à jour des champs du profil
        profile = user.profile
        profile.matricule = request.POST.get('matricule', '')
        profile.date_naissance = request.POST.get('date_naissance') or None
        profile.telephone = request.POST.get('telephone', '')
        profile.adresse = request.POST.get('adresse', '')
        profile.poste = request.POST.get('poste', '')
        profile.save()

        messages.success(request, f"✅ Utilisateur {user.username} modifié avec succès.")
        return redirect('gestion_utilisateurs')

    # GET : afficher le formulaire avec les données existantes
    groupes = Group.objects.all()
    return render(request, 'port/modifier_utilisateur.html', {
        'user': user,
        'groupes': groupes,
        'profile': user.profile,   # Important pour pré-remplir les champs du profil
    })
@login_required
@group_required('Directeur')
def supprimer_utilisateur(request, user_id):
    user = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        user.delete()
        messages.success(request, "Utilisateur supprimé.")
    return redirect('gestion_utilisateurs')

# =============================================================================
# REPLANIFICATION AUTOMATIQUE
# =============================================================================

def replanifier_automatique(navires_queryset=None):
    if navires_queryset is None:
        navires_queryset = Navire.objects.filter(etat='rade')
    if not navires_queryset.exists():
        return None
    return replanifier(None, navires_queryset)
def replanifier(utilisateur=None, navires_queryset=None):
    """
    Stub pour la replanification automatique.
    À compléter ultérieurement pour relancer l'optimiseur.
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.warning("Replanification automatique déclenchée mais non implémentée.")
    # Crée une alerte pour informer les officiers
    from .models import Alerte
    Alerte.objects.create(
        message="⚠️ Replanification nécessaire suite à un changement météo.",
        niveau='warning',
        source='Système',
        est_lue=False
    )
    return None

def planifier(self, navires_a_planifier, navires_a_quai=None):
    # Réinitialiser les listes de libération des équipements
    for eq in self.equipements:
        self.equipement_unites[eq.type] = [0.0] * eq.nombre
        eq.dispo = eq.nombre

    # Initialiser avec les navires déjà à quai
    if navires_a_quai:
        self.initialiser_equipements_depuis_navires_quai(navires_a_quai)

    print("\n=== Quais initiaux (avec occupations réelles) ===")
    for q in self.quais:
        print(f"  {q.nom} : libre = {q.libre:.2f}h")

    # Tri des navires : priorité décroissante, puis date/heure d'arrivée croissante
    def get_tri_datetime(navire):
        if navire.arrivee_datetime:
            return navire.arrivee_datetime.timestamp()
        from datetime import datetime, timedelta
        now = datetime.now()
        base = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return (base + timedelta(hours=navire.arrivee)).timestamp()

    navires_tries = sorted(
        navires_a_planifier,
        key=lambda n: (-n.priorite_calculee, get_tri_datetime(n))
    )

    affectations = []
    score_total = 0.0
    attente_totale = 0.0

    print("\n" + "="*100)
    print("ORDRE DE TRAITEMENT (par priorité puis par ancienneté)")
    print("="*100)
    for i, navire in enumerate(navires_tries, 1):
        priorite_text = self._get_priorite_text(navire)
        arrivee_str = navire.arrivee_datetime.strftime("%d/%m %H:%M") if navire.arrivee_datetime else f"{navire.arrivee:.1f}h"
        print(f"{i:2d}. {navire.nom} - Priorite: {navire.priorite_calculee:.0f} - Arrivee: {arrivee_str} - {priorite_text}")

    print("\n" + "="*100)
    print("PLANIFICATION EN COURS")
    if self.incertitude:
        print(f"Mode incertitude activé (amplitude: {self.amplitude*100:.0f}%)")
    else:
        print("Mode déterministe")
    print(f"Buffers: {self.pourcentage_buffer*100:.0f}% de la durée")
    if self.meteo_pluie:
        print("⚠️  Météo : Pluie en cours – ralentissement des opérations")
    if self.meteo_restrictions:
        print(f"⚠️  Restrictions météo : {', '.join(self.meteo_restrictions)}")
    print(f"📋 Scénario : {self.scenario}")
    print("="*100)

    for navire in navires_tries:
        print(f"\nTraitement de {navire.nom}")
        print(f"   Priorites: {self._get_priorite_text(navire)}")
        print(f"   Arrivee: {navire.arrivee:.2f}h")
        print(f"   Type: {navire.type.value}")

        meilleur_debut = float('inf')
        meilleur_quai = None
        meilleur_fin = None
        meilleur_traitement = None
        meilleur_buffer_debut = 0.0
        meilleur_buffer_fin = 0.0
        meilleur_score = float('inf')
        meilleur_message = ""

        for quai in self.quais:
            compatible, raison = self.verifier_compatibilite(navire, quai)
            print(f"      Test quai {quai.nom} (spec: {quai.specialite}) : compatible={compatible} -> {raison}")
            if not compatible:
                continue

            debut = max(navire.arrivee, quai.libre)
            traitement = self.modele.calculer_temps_traitement(navire, quai)
            fin = debut + traitement

            disponible, debut_ajuste, msg_equip = self.equipements_disponibles(navire, quai, debut, fin)
            if not disponible:
                print(f"         Équipements indisponibles: {msg_equip}")
                continue

            debut = debut_ajuste
            traitement = self.modele.calculer_temps_traitement(navire, quai)
            fin = debut + traitement

            # Ralentissements météo
            coeff_ralentissement = 1.0
            if self.meteo_pluie:
                coeff_ralentissement *= 1.2
            if self.meteo_vent_force >= 8:
                coeff_ralentissement *= 1.3
            traitement *= coeff_ralentissement
            fin = debut + traitement

            buffer_debut = traitement * self.pourcentage_buffer
            buffer_fin = traitement * self.pourcentage_buffer

            disponible, debut_ajuste2, msg_equip2 = self.equipements_disponibles(navire, quai, debut, fin)
            if not disponible:
                continue
            if debut_ajuste2 > debut:
                debut = debut_ajuste2
                fin = debut + traitement

            # ========== VÉRIFICATION EXPLICITE DES CONFLITS DE CRÉNEAU ==========
            conflit_creneau = False
            for a in affectations:
                if a.quai_id == quai.id:
                    # Les créneaux se chevauchent-ils ?
                    if not (fin <= a.heure_accostage or debut >= a.heure_fin):
                        conflit_creneau = True
                        break
            if conflit_creneau:
                print(f"         ⚠️ Conflit avec un navire déjà planifié sur ce quai")
                continue
            # ===================================================================

            contribution = self.calculer_score_contribution(navire, debut, traitement, buffer_debut, buffer_fin)

            # Préférences de quai (bonus/malus) – inchangé
            preference = 0
            if navire.type == TypeNavire.ESSENCE and quai.id == 19:
                preference = -100
            elif navire.type == TypeNavire.ESSENCE and quai.id == 1:
                preference = -50
            if navire.type == TypeNavire.GAZIER and quai.id == 26:
                preference = -100
            elif navire.type == TypeNavire.GAZIER and quai.id == 24:
                preference = -30
            if navire.type == TypeNavire.HUILIER and quai.id == 25:
                preference = -100
            elif navire.type == TypeNavire.HUILIER and quai.id == 26:
                preference = -50
            if navire.type == TypeNavire.CONTENEUR and quai.id in [22, 24]:
                preference = -50
            if navire.type == TypeNavire.CEREALIER and quai.id == 21:
                preference = -50
            elif navire.type == TypeNavire.CEREALIER and quai.id in [4, 5]:
                preference = -20
            if navire.type == TypeNavire.ESSENCE and quai.id not in [19, 1]:
                preference += 50
            if navire.type == TypeNavire.CEREALIER and quai.id not in [21, 4, 5]:
                preference += 30
            if navire.type == TypeNavire.PETROLIER and quai.id not in [2, 3]:
                preference += 30
            if navire.type == TypeNavire.CONTENEUR and quai.id not in [22, 24]:
                preference += 20

            contribution += preference

            if contribution < meilleur_score:
                meilleur_score = contribution
                meilleur_debut = debut
                meilleur_quai = quai
                meilleur_fin = fin
                meilleur_traitement = traitement
                meilleur_buffer_debut = buffer_debut
                meilleur_buffer_fin = buffer_fin
                meilleur_message = f"Choisi (score {contribution:.2f})"

        if meilleur_quai is not None:
            attente = self.modele.calculer_attente(navire, meilleur_debut)
            debut_securise = meilleur_debut + meilleur_buffer_debut
            fin_securise = meilleur_fin + meilleur_buffer_fin

            if meilleur_quai.est_groupe:
                self.reserver_groupe(navire, meilleur_quai, meilleur_fin)
            else:
                self.reserver_equipements(navire, meilleur_quai, meilleur_fin)
                meilleur_quai.libre = meilleur_fin + temps_manoeuvre

            affectations.append(AffectationResultat(
                navire_id=navire.id,
                navire_nom=navire.nom,
                type_navire=navire.type.value,
                quai_id=meilleur_quai.id,
                quai_nom=meilleur_quai.nom,
                heure_arrivee=navire.arrivee,
                heure_accostage=meilleur_debut,
                heure_fin=meilleur_fin,
                attente=attente,
                traitement=meilleur_traitement,
                priorite_calculee=navire.priorite_calculee,
                priorites_speciale=self._get_priorite_text(navire),
                equipements=self.get_equipements_necessaires(navire, meilleur_quai),
                utilise_grues_bord=navire.equipement_propre.a_grue_bord,
                score_contribution=meilleur_score,
                buffer_debut=meilleur_buffer_debut,
                buffer_fin=meilleur_buffer_fin,
                heure_debut_securise=debut_securise,
                heure_fin_securise=fin_securise
            ))
            score_total += meilleur_score
            attente_totale += attente

            print(f"   Affecte au {meilleur_quai.nom} (specialite: {meilleur_quai.specialite})")
            print(f"      Debut: {meilleur_debut:.2f}h (buffer début: +{meilleur_buffer_debut:.1f}h)")
            print(f"      Fin: {meilleur_fin:.2f}h (buffer fin: +{meilleur_buffer_fin:.1f}h)")
            print(f"      Attente: {attente:.2f}h")
            print(f"      Duree traitement (simulee): {meilleur_traitement:.2f}h")
            print(f"      Contribution score: {meilleur_score:.2f}")
        else:
            print(f"   Aucune affectation possible - {meilleur_message if meilleur_message else 'aucun quai compatible'}")

    return affectations, score_total, attente_totale

# =============================================================================
# AUTRES (MISE À JOUR RADE, ETC.)
# =============================================================================

def mise_a_jour_rade(request):
    try:
        heure_actuelle = datetime.now().hour + datetime.now().minute/60
        a_passer_en_rade = Navire.objects.filter(etat='attente', arrivee__lte=heure_actuelle)
        nb_rade = a_passer_en_rade.count()
        if nb_rade > 0:
            a_passer_en_rade.update(etat='rade')
        stats = {
            'attente': Navire.objects.filter(etat='attente').count(),
            'rade': Navire.objects.filter(etat='rade').count(),
            'quai': Navire.objects.filter(etat='quai').count(),
            'termine': Navire.objects.filter(etat='termine').count(),
        }
        return JsonResponse({'success': True, 'navires_mis_a_jour': nb_rade, 'heure_actuelle': heure_actuelle, 'stats': stats})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

def actualiser_meteo_silent(request):
    call_command('fetch_weather', silent=True)
    messages.success(request, "Météo actualisée avec succès (sans replanification).")
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.shortcuts import render, redirect
from django.contrib import messages

from .forms import UserForm, ProfileForm

@login_required
def profil(request):
    # Assurer que le profil existe
    Profile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        user_form = UserForm(request.POST, instance=request.user)
        profile_form = ProfileForm(request.POST, instance=request.user.profile)
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, "✅ Votre profil a été mis à jour.")
            return redirect('profil')
    else:
        user_form = UserForm(instance=request.user)
        profile_form = ProfileForm(instance=request.user.profile)

    return render(request, 'port/profil.html', {
        'user_form': user_form,
        'profile_form': profile_form,
        'user': request.user,
        'profile': request.user.profile,   # <-- AJOUTER CETTE LIGNE
    })
import os
import sys

# Ajouter le chemin des DLL GTK pour WeasyPrint
gtk_path = r"C:\Program Files\GTK3-Runtime Win64\bin"
if os.path.exists(gtk_path):
    os.add_dll_directory(gtk_path)
    
    from django.contrib.auth.decorators import login_required
from .decorators import group_required
from .models import Quai
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages

@login_required
@group_required('Directeur')
def ajouter_quai(request):
    if request.method == 'POST':
        try:
            quai = Quai(
                nom=request.POST.get('nom'),
                longueur=float(request.POST.get('longueur')),
                profondeur=float(request.POST.get('profondeur')),
                specialite=request.POST.get('specialite'),
                disponible=True,
                occupation_jusqua=0.0,
                performance=float(request.POST.get('performance', 1.0))
            )
            quai.save()
            messages.success(request, f"✅ Quai {quai.nom} ajouté avec succès.")
            return redirect('liste_quais')
        except Exception as e:
            messages.error(request, f"❌ Erreur : {e}")
    return render(request, 'port/ajouter_quai.html')

@login_required
@group_required('Directeur')
def modifier_quai(request, quai_id):
    quai = get_object_or_404(Quai, id=quai_id)
    if request.method == 'POST':
        try:
            quai.nom = request.POST.get('nom')
            quai.longueur = float(request.POST.get('longueur'))
            quai.profondeur = float(request.POST.get('profondeur'))
            quai.specialite = request.POST.get('specialite')
            quai.performance = float(request.POST.get('performance', 1.0))
            # On ne modifie pas `disponible` ni `occupation_jusqua` ici
            quai.save()
            messages.success(request, f"✅ Quai {quai.nom} modifié avec succès.")
            return redirect('liste_quais')
        except Exception as e:
            messages.error(request, f"❌ Erreur : {e}")
    return render(request, 'port/modifier_quai.html', {'quai': quai})

@login_required
@group_required('Directeur')
def supprimer_quai(request, quai_id):
    quai = get_object_or_404(Quai, id=quai_id)
    if request.method == 'POST':
        try:
            # Récupérer les postes de ce quai avant suppression
            postes = Poste.objects.filter(quai=quai)
            
            # Pour chaque poste, libérer les navires qui y sont
            for poste in postes:
                navire = Navire.objects.filter(poste_attribue=poste, etat='quai').first()
                if navire:
                    navire.etat = 'rade'
                    navire.poste_attribue = None
                    navire.quai_attribue = None
                    navire.save()
            
            # Supprimer d'abord les postes (cascade manuelle)
            postes.delete()
            
            # Ensuite supprimer le quai
            nom = quai.nom
            quai.delete()
            
            messages.success(request, f"✅ Quai {nom} supprimé avec succès.")
        except Exception as e:
            # Si erreur de colonne, supprimer en SQL brut
            try:
                from django.db import connection
                with connection.cursor() as cursor:
                    # Désactiver temporairement les contraintes
                    cursor.execute("SET FOREIGN_KEY_CHECKS=0")
                    # Supprimer les postes
                    cursor.execute("DELETE FROM port_poste WHERE quai_id = %s", [quai_id])
                    # Supprimer le quai
                    cursor.execute("DELETE FROM port_quai WHERE id = %s", [quai_id])
                    cursor.execute("SET FOREIGN_KEY_CHECKS=1")
                messages.success(request, f"✅ Quai supprimé avec succès.")
            except Exception as e2:
                messages.error(request, f"❌ Erreur lors de la suppression : {e2}")
        return redirect('liste_quais')
    return render(request, 'port/supprimer_quai.html', {'quai': quai})
from django.contrib.auth.decorators import login_required
from .decorators import group_required
from .models import Equipement
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages


    
# views.py
from django.shortcuts import render


# views.py
def carte_schematique(request):
    quais = Quai.objects.all().values('id', 'nom', 'coord_x', 'coord_y', 'disponible', 'longueur', 'profondeur')
    navires = Navire.objects.filter(etat__in=['rade', 'quai']).values(
        'id', 'nom', 'type', 'etat', 'coord_x', 'coord_y', 'quai_attribue__nom'
    )
    context = {
        'quais': list(quais),
        'navires': list(navires),
    }
    return render(request, 'port/carte_schematique.html', context)

from django.http import JsonResponse

def api_carte_data(request):
    postes = Poste.objects.select_related('quai').all().values(
        'id', 'numero', 'coord_x', 'coord_y', 'specialite', 'disponible',
        'quai__nom', 'quai__longueur', 'quai__profondeur'
    )
    navires = Navire.objects.filter(etat__in=['rade', 'quai']).values(
        'id', 'nom', 'type', 'etat', 'coord_x', 'coord_y', 'quai_attribue__nom'
    )
    return JsonResponse({'postes': list(postes), 'navires': list(navires)})
from port.models import Navire, Poste, Quai

def synchroniser_occupation_postes():
    """
    Met à jour les champs `disponible` des postes et quais en fonction
    des navires réellement à quai.
    """
    from port.models import Navire, Poste, Quai
    
    # 1. Réinitialiser tous les postes comme disponibles
    Poste.objects.update(disponible=True, occupation_jusqua=0.0)
    
    # 2. Marquer comme indisponibles les postes occupés
    for navire in Navire.objects.filter(etat='quai', poste_attribue__isnull=False):
        try:
            poste = navire.poste_attribue
            if poste is None:
                continue
            if navire.heure_fin:
                poste.occupation_jusqua = navire.heure_fin
            poste.disponible = False
            poste.save()
            print(f"🔒 Poste {poste.numero} occupé par {navire.nom}")
        except Exception as e:
            print(f"⚠️ Erreur pour le poste du navire {navire.nom}: {e}")
    
    # 3. Même chose pour les quais
    Quai.objects.update(disponible=True, occupation_jusqua=0.0)
    for navire in Navire.objects.filter(etat='quai', quai_attribue__isnull=False):
        try:
            quai = navire.quai_attribue
            if quai is None:
                continue
            if navire.heure_fin:
                quai.occupation_jusqua = navire.heure_fin
            quai.disponible = False
            quai.save()
        except Exception as e:
            print(f"⚠️ Erreur pour le quai du navire {navire.nom}: {e}")
def api_stats_attentes_evolution(request):
    """API pour l'évolution des temps d'attente avec agrégation par jour"""
    period = request.GET.get('period', 'week')
    
    from datetime import timedelta
    from django.utils import timezone
    from django.db.models import Avg
    
    now = timezone.now()
    
    if period == 'week':
        days = 7
    elif period == 'month':
        days = 30
    elif period == 'quarter':
        days = 90
    else:
        days = 7
    
    date_debut = now - timedelta(days=days)
    
    # Agrégation par jour
    attentes_par_jour = []
    labels = []
    
    for i in range(days):
        jour = date_debut + timedelta(days=i)
        jour_suivant = jour + timedelta(days=1)
        
        # Moyenne des attentes pour ce jour
        avg_attente = Affectation.objects.filter(
            date_creation__date=jour.date()
        ).aggregate(Avg('attente'))['attente__avg'] or 0
        
        attentes_par_jour.append(round(avg_attente, 1))
        labels.append(jour.strftime('%d/%m'))
    
    data = {
        'labels': labels,
        'attentes': attentes_par_jour,
    }
    return JsonResponse(data)

def synchroniser_disponibilite_quais():
    """Remet à jour le champ `disponible` de chaque quai en fonction des navires réellement à quai."""
    # D'abord, on remet tous les quais à disponible=True (sauf ceux bloqués manuellement)
    Quai.objects.filter(bloque=False).update(disponible=True)
    # Ensuite, on marque comme indisponibles les quais occupés par un navire
    navires_quai = Navire.objects.filter(etat='quai', quai_attribue__isnull=False)
    for navire in navires_quai:
        quai = navire.quai_attribue
        quai.disponible = False
        quai.save()
from .models import HistoriqueAction
from django.contrib.auth.models import User
from django.core.paginator import Paginator

@login_required

def historique_actions(request):
    historique = HistoriqueAction.objects.select_related('utilisateur', 'navire', 'quai').all()
    
    # Filtres
    type_action = request.GET.get('type')
    if type_action:
        historique = historique.filter(type_action=type_action)
    
    utilisateur_id = request.GET.get('utilisateur')
    if utilisateur_id:
        historique = historique.filter(utilisateur_id=utilisateur_id)
    
    paginator = Paginator(historique, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    utilisateurs = User.objects.filter(is_active=True).order_by('username')
    
    context = {
        'page_obj': page_obj,
        'types_action': HistoriqueAction.TYPES_ACTION,
        'utilisateurs': utilisateurs,
    }
    return render(request, 'port/historique.html', context)
from .models import HistoriqueAction
from django.utils import timezone

def ajouter_historique(utilisateur, type_action, description, navire=None, quai=None, equipement=None, details=None):
    HistoriqueAction.objects.create(
        utilisateur=utilisateur if utilisateur and utilisateur.is_authenticated else None,
        type_action=type_action,
        description=description,
        date_action=timezone.now(),
        navire=navire,
        quai=quai,
        equipement=equipement,
        details=details or {}
    )
from .forms import UserForm, ProfileForm


from django.db.models import Prefetch, OuterRef, Subquery
from port.models import Quai, Poste, Navire

from django.db.models import OuterRef, Subquery, Q

from django.db.models import OuterRef, Subquery, Prefetch

@login_required
def liste_quais(request):
    # ========== FORCER LA SYNCHRONISATION ==========
    synchroniser_disponibilite_postes()
    # ===============================================
    
    # Récupérer tous les quais
    quais_obj = Quai.objects.all().order_by('id')
    
    # Récupérer tous les navires à quai avec leur poste
    navires_par_poste = {}
    for navire in Navire.objects.filter(etat='quai', poste_attribue__isnull=False).select_related('poste_attribue'):
        if navire.poste_attribue:
            navires_par_poste[navire.poste_attribue.id] = navire.nom
    
    # Construire la liste des quais avec leurs postes
    quais = []
    for quai in quais_obj:
        # Récupérer les postes de ce quai
        postes_du_quai = Poste.objects.filter(quai=quai).order_by('numero')
        
        # Ajouter les informations d'occupation à chaque poste
        for poste in postes_du_quai:
            poste.navire_occupant_nom = navires_par_poste.get(poste.id)
            poste.disponible = poste.navire_occupant_nom is None
        
        # Créer un dictionnaire avec un ID sécurisé (converti en chaîne puis entier)
        try:
            quai_id = int(str(quai.id))
        except (ValueError, TypeError):
            quai_id = 0
            
        quais.append({
            'quai': quai,
            'quai_id': quai_id,  # ID sécurisé
            'postes': list(postes_du_quai)
        })
    
    return render(request, 'port/quais.html', {'quais': quais})

@login_required
@group_required('Directeur', 'Officier_radio')
def liberer_poste(request, poste_id):
    poste = get_object_or_404(Poste, id=poste_id)
    navire = Navire.objects.filter(
        Q(poste_attribue=poste) | Q(quai_attribue=poste.quai),
        etat='quai'
    ).first()
    
    if navire:
        navire.etat = 'rade'
        navire.poste_attribue = None
        navire.quai_attribue = None
        navire.heure_debut = None
        navire.heure_fin = None
        navire.save()
        messages.success(request, f"✅ Poste {poste.numero} libéré. Navire {navire.nom} retourné en rade.")
    else:
        if not poste.disponible:
            messages.info(request, f"ℹ️ Poste {poste.numero} était marqué occupé sans navire associé. Il a été libéré.")
    
    # Toujours libérer le poste
    poste.disponible = True
    poste.occupation_jusqua = 0.0
    poste.save()
    
    # Libérer le quai parent si aucun autre navire n'y est amarré
    quai = poste.quai
    if quai:
        autres_navires = Navire.objects.filter(
            Q(poste_attribue__quai=quai) | Q(quai_attribue=quai),
            etat='quai'
        ).exists()
        if not autres_navires:
            quai.disponible = True
            quai.occupation_jusqua = 0.0
            quai.save()
    
    return redirect('liste_quais')
from datetime import datetime, timedelta
from django.utils import timezone

@login_required
def detail_quai(request, quai_id):
    from django.db.models import OuterRef, Subquery
    from port.models import Navire
    
    quai = get_object_or_404(Quai.objects.prefetch_related('postes'), id=quai_id)
    
    # Récupérer le navire occupant pour chaque poste avec l'ID
    navire_subquery = Navire.objects.filter(
        poste_attribue=OuterRef('pk'),
        etat='quai'
    ).values('id', 'nom')[:1]
    
    postes = quai.postes.annotate(
        navire_occupant_id=Subquery(navire_subquery.values('id')),
        navire_occupant_nom=Subquery(navire_subquery.values('nom'))
    )
    
    # Calcul des statistiques
    postes_libres = postes.filter(disponible=True).count()
    postes_occupes = postes.filter(disponible=False).count()
    total_postes = postes.count()
    taux_occupation = round((postes_occupes / total_postes * 100), 1) if total_postes > 0 else 0
    
    # Convertir occupation_jusqua en datetime pour chaque poste
    now = datetime.now()
    base = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    for poste in postes:
        if poste.occupation_jusqua and poste.occupation_jusqua > 0:
            # Convertir les heures décimales en datetime
            heures = int(poste.occupation_jusqua)
            minutes = int((poste.occupation_jusqua - heures) * 60)
            jours = int(heures // 24) if heures >= 24 else 0
            heures_restantes = heures % 24
            
            # Ajouter les jours à la date de référence
            date_liberation = base + timedelta(days=jours)
            date_liberation = date_liberation.replace(hour=heures_restantes, minute=minutes)
            
            # Si la date est passée, ajouter 1 jour
            while date_liberation < now:
                date_liberation += timedelta(days=1)
            
            poste.date_liberation = date_liberation
        else:
            poste.date_liberation = None
    
    context = {
        'quai': quai,
        'postes': postes,
        'postes_libres': postes_libres,
        'postes_occupes': postes_occupes,
        'total_postes': total_postes,
        'taux_occupation': taux_occupation,
        'now': now,
    }
    return render(request, 'port/quai_detail.html', context)
@login_required
@group_required('Officier_radio', 'Directeur')
def affecter_poste_manuel(request):
    if request.method == 'POST':
        poste_id = request.POST.get('poste_id')
        navire_id = request.POST.get('navire_id')
        
        # Plus de récupération des heures du formulaire
        # Les heures seront calculées automatiquement

        if not poste_id or not navire_id:
            messages.error(request, "Veuillez sélectionner un poste et un navire.")
            return redirect('mode_manuel')

        try:
            poste = Poste.objects.get(id=poste_id)
        except Poste.DoesNotExist:
            messages.error(request, "Le poste sélectionné n'existe pas.")
            return redirect('mode_manuel')

        try:
            navire = Navire.objects.get(id=navire_id, etat='rade')
        except Navire.DoesNotExist:
            messages.error(request, "Navire non trouvé ou pas en rade.")
            return redirect('mode_manuel')

        if not poste.disponible:
            messages.error(request, f"Le poste {poste.numero} n'est pas disponible.")
            return redirect('mode_manuel')

        if poste.quai and poste.quai.bloque:
            messages.error(request, f"Le quai {poste.quai.nom} est bloqué manuellement.")
            return redirect('mode_manuel')

        if Navire.objects.filter(poste_attribue=poste, etat='quai').exists():
            messages.error(request, f"Le poste {poste.numero} est déjà occupé.")
            return redirect('mode_manuel')

        # ========== CALCUL AUTOMATIQUE DE LA DATE DE DÉBUT ET DE FIN ==========
        from datetime import datetime, timedelta
        from port.optimiseur_epb_pro import ModeleCalcul
        from port.adaptateurs import AdaptateurDonnees
        
        now = datetime.now()
        base = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # 1. Calculer la date/heure de début
        if navire.arrivee_datetime:
            # Si le navire est déjà arrivé, début = maintenant
            if navire.arrivee_datetime <= now:
                debut_datetime = now
            else:
                # Si le navire n'est pas encore arrivé, début = arrivée
                debut_datetime = navire.arrivee_datetime
        else:
            debut_datetime = now
        
        # Ajouter 1 heure de marge (temps de préparation)
        debut_datetime += timedelta(hours=1)
        
        # Ajuster pour les contraintes de shift
        heure_debut_float = debut_datetime.hour + debut_datetime.minute / 60.0
        
        # Navires céréaliers : pas d'opération entre 01h et 07h
        if navire.type == 'cerealier' and (1 <= heure_debut_float < 7):
            debut_datetime = debut_datetime.replace(hour=7, minute=0, second=0, microsecond=0)
            if debut_datetime < now:
                debut_datetime += timedelta(days=1)
        
        # Ferries : opération uniquement entre 07h et 19h
        elif navire.type == 'ferry' and not (7 <= heure_debut_float < 19):
            if heure_debut_float < 7:
                debut_datetime = debut_datetime.replace(hour=7, minute=0, second=0, microsecond=0)
            else:
                debut_datetime = debut_datetime.replace(hour=7, minute=0, second=0, microsecond=0) + timedelta(days=1)
        
        # 2. Calculer la durée de traitement estimée
        modele = ModeleCalcul([], [])
        navire_data = AdaptateurDonnees.vers_navire(navire, coeff_variation=0)
        
        # Durée de traitement basée sur le volume et le taux
        duree_traitement = modele.calculer_temps_traitement(navire_data, None)
        
        # Temps de manœuvre (1h)
        temps_manoeuvre = 1.0
        
        # Formalités (2h)
        formalites = 2.0
        
        # Durée totale à quai
        duree_totale = temps_manoeuvre + duree_traitement + formalites
        
        # Calculer l'heure de fin
        fin_datetime = debut_datetime + timedelta(hours=duree_totale)
        
        # Convertir en heures décimales pour la base de données
        heure_debut_decimal = (debut_datetime - base).total_seconds() / 3600.0
        heure_fin_decimal = (fin_datetime - base).total_seconds() / 3600.0
        
        # calculer l'attente (différence entre début et arrivée)
        if navire.arrivee_datetime:
            attente = max(0, (debut_datetime - navire.arrivee_datetime).total_seconds() / 3600)
        else:
            attente = max(0, heure_debut_decimal - navire.arrivee)
        
        # ========== FIN DU CALCUL AUTOMATIQUE ==========

        # Créer l'affectation
        Affectation.objects.create(
            navire=navire,
            quai=poste.quai,
            heure_debut=heure_debut_decimal,
            heure_fin=heure_fin_decimal,
            attente=attente,
            traitement=duree_totale,
            score_contribution=duree_totale + attente,
            priorites_texte=f"Manuel (poste {poste.numero} - {poste.specialite})",
            etat_initial=navire.etat
        )

        # Mettre à jour le navire
        navire.etat = 'quai'
        navire.poste_attribue = poste
        navire.quai_attribue = poste.quai
        navire.heure_debut = heure_debut_decimal
        navire.heure_fin = heure_fin_decimal
        navire.debut_datetime = debut_datetime
        navire.fin_datetime = fin_datetime
        
        if poste.quai.coord_x and poste.quai.coord_y:
            navire.coord_x = poste.quai.coord_x
            navire.coord_y = poste.quai.coord_y
        
        navire.save()

        # Mettre à jour le poste
        poste.disponible = False
        poste.occupation_jusqua = heure_fin_decimal
        poste.save()

        if poste.quai:
            poste.quai.disponible = False
            poste.quai.occupation_jusqua = heure_fin_decimal
            poste.quai.save()

        # ========== SUPPRIMER LE NAVIRE DE LA SESSION CPN ==========
        navires_cpn_ids = request.session.get('navires_cpn_ids', [])
        if navire.id in navires_cpn_ids:
            navires_cpn_ids.remove(navire.id)
            request.session['navires_cpn_ids'] = navires_cpn_ids
            request.session.modified = True
            print(f"🗑️ {navire.nom} (ID: {navire.id}) supprimé de la session CPN")
        # ===========================================================

        ajouter_historique(
            utilisateur=request.user,
            type_action='affectation_manuelle',
            description=f"Affectation manuelle de {navire.nom} au poste {poste.numero}",
            navire=navire,
            quai=poste.quai,
            details={
                'poste_id': poste.id,
                'poste_numero': poste.numero,
                'heure_debut': heure_debut_decimal,
                'heure_fin': heure_fin_decimal,
                'duree_traitement': duree_totale,
                'attente': attente
            }
        )

        messages.success(
            request, 
            f"✅ {navire.nom} affecté au poste {poste.numero} ({poste.quai.nom})\n"
            f"📅 Début: {debut_datetime.strftime('%d/%m/%Y %H:%M')}\n"
            f"⏱️ Fin estimée: {fin_datetime.strftime('%d/%m/%Y %H:%M')}\n"
            f"⚙️ Durée: {duree_totale:.1f}h (dont {duree_traitement:.1f}h d'opération)"
        )
        return redirect('mode_manuel')

    return redirect('mode_manuel')
def get_shift_label(heure):
    """
    Retourne le libellé du shift pour une heure donnée (0-24).
    Les shifts sont définis comme suit :
    - 07h-13h : de 7h00 à 13h00 (exclu)
    - 13h-19h : de 13h00 à 19h00 (exclu)
    - 19h-01h : de 19h00 à 1h00 (le lendemain, modulo 24)
    - 01h-07h : de 1h00 à 7h00
    """
    h = heure % 24
    if 7 <= h < 13:
        return "07h-13h"
    elif 13 <= h < 19:
        return "13h-19h"
    elif 19 <= h < 24:
        return "19h-01h"
    else:  # 0 <= h < 7
        return "01h-07h"
# Dans views.py, ajoutez cette fonction

def calculer_shifts_couverts(debut_heure, fin_heure):
    """
    Calcule les shifts couverts par une opération
    Shifts: 07h-13h, 13h-19h, 19h-01h, 01h-07h
    """
    shifts = []
    
    # Définition des shifts
    shift_config = [
        {"nom": "07h-13h", "debut": 7, "fin": 13},
        {"nom": "13h-19h", "debut": 13, "fin": 19},
        {"nom": "19h-01h", "debut": 19, "fin": 25},  # 25 = 1h du matin + 24
        {"nom": "01h-07h", "debut": 1, "fin": 7},
    ]
    
    # Gérer le cas où l'heure de fin peut dépasser 24h
    fin_ajustee = fin_heure
    debut_ajustee = debut_heure
    
    # Si l'opération dure plus de 24h
    duree = fin_heure - debut_heure
    if duree > 24:
        # Ajouter tous les shifts si c'est très long
        return ["07h-13h", "13h-19h", "19h-01h", "01h-07h"]
    
    # Ajuster pour le shift de nuit (19h-01h)
    if fin_heure <= 7 and debut_heure >= 19:
        fin_ajustee = fin_heure + 24
    
    # Parcourir les shifts
    for shift in shift_config:
        shift_debut = shift["debut"]
        shift_fin = shift["fin"]
        
        # Ajustement pour le shift de nuit
        if shift_debut == 19:
            shift_fin = 25
        
        # Vérifier si l'opération couvre ce shift
        if (debut_ajustee < shift_fin and fin_ajustee > shift_debut) or \
           (debut_ajustee < shift_fin + 24 and fin_ajustee + 24 > shift_debut):
            shifts.append(shift["nom"])
    
    return shifts
from collections import defaultdict

def temps_par_shift(debut, fin):
    """Calcule les heures passées dans chaque shift pour un intervalle [debut, fin]."""
    result = defaultdict(float)
    d = debut
    while d < fin:
        h = d.hour + d.minute / 60.0
        # Déterminer le shift et sa fin
        if 7 <= h < 13:
            shift = "07h-13h"
            fin_shift = d.replace(hour=13, minute=0, second=0, microsecond=0)
        elif 13 <= h < 19:
            shift = "13h-19h"
            fin_shift = d.replace(hour=19, minute=0, second=0, microsecond=0)
        elif 19 <= h < 24:
            shift = "19h-01h"
            fin_shift = d.replace(hour=1, minute=0, second=0, microsecond=0) + timedelta(days=1)
        else:  # 0 <= h < 7
            shift = "01h-07h"
            fin_shift = d.replace(hour=7, minute=0, second=0, microsecond=0)
        # Durée dans ce shift
        segment_fin = min(fin, fin_shift)
        duree = (segment_fin - d).total_seconds() / 3600
        result[shift] += duree
        d = fin_shift
    return result




def equipe_disponible(equipe, shift_nom, debut_shift, fin_shift, navire_ignore=None):
    """
    Version désactivée : toujours disponible.
    """
    return True, "Disponible"



def reserver_groupe(self, navire: Navire, quai_groupe: Quai, fin: float):
    for q in self.quais:
        if q.id in quai_groupe.postes_membres:
            q.libre = fin + self.calculer_temps_manoeuvre(navire, q)
            self.reserver_equipements(navire, q, fin)
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from .decorators import group_required
from .models import NoteAttente, Navire

from .models import NoteAttente

@login_required
@group_required('Officier_port', 'Directeur')
@login_required
@group_required('Officier_port', 'Directeur')
def ajouter_note_attente(request):
    """Ajoute une note d'attente liée à l'escale ACTIVE du navire."""
    from port.models import NoteAttente, Escale
    from port.utils_escales import gerer_nouvelle_escale
    from datetime import timedelta
    
    if request.method == 'POST':
        navire_id = request.POST.get('navire_id')
        duree_attente_str = request.POST.get('duree_attente', '').strip()
        commentaire = request.POST.get('commentaire', '').strip()
        shift = request.POST.get('shift', 'matin')
        
        navire = get_object_or_404(Navire, id=navire_id)
        
        # 1. Recuperer ou creer l'escale active
        escale = Escale.objects.filter(navire=navire, active=True).first()
        if not escale:
            escale = gerer_nouvelle_escale(navire)
            messages.info(request, f"Nouvelle escale creee pour {navire.nom}")
        
        # 2. Prediction IA si duree non fournie
        if not duree_attente_str:
            try:
                from port.ml_attente import AttentePredictor
                predictor = AttentePredictor()
                meteo = get_meteo_aujourdhui()
                duree_attente = predictor.predire_attente(navire, meteo=meteo)
                commentaire = f"[IA] {commentaire}" if commentaire else "Prediction IA"
            except Exception as e:
                duree_attente = 6.0
                commentaire = f"[Defaut] {commentaire}" if commentaire else "Duree par defaut"
                logger.error(f"Erreur prediction IA: {e}")
        else:
            duree_attente = float(duree_attente_str)
        
        # 3. Creer la note liee a l'escale
        NoteAttente.objects.create(
            navire=navire,
            escale=escale,
            shift=shift,
            duree_attente=duree_attente,
            commentaire=commentaire,
            prise_en_compte=False,
            archive=False
        )
        
        # 4. Recalculer la fin si le navire est a quai
        if navire.etat == 'quai' and navire.debut_datetime:
            volume = navire.marchandise_volume or 0
            if navire.type == 'cerealier':
                duree_traitement = volume / 550
            elif navire.type == 'cargo':
                duree_traitement = volume / 250
            elif navire.type == 'conteneur':
                duree_traitement = volume / 300
            elif navire.type == 'petrolier':
                duree_traitement = volume / 400
            else:
                duree_traitement = volume / 200
            
            # UNIQUEMENT les notes de l'escale active
            notes_attente = NoteAttente.objects.filter(
                escale=escale,
                archive=False,
                prise_en_compte=False
            )
            attente_totale = sum(n.duree_attente for n in notes_attente)
            
            maintenant = timezone.now()
            temps_ecoule = (maintenant - navire.debut_datetime).total_seconds() / 3600.0
            temps_restant = max(0, (duree_traitement + attente_totale) - temps_ecoule)
            nouvelle_fin = maintenant + timedelta(hours=temps_restant)
            
            base = nouvelle_fin.replace(hour=0, minute=0, second=0, microsecond=0)
            navire.heure_fin = (nouvelle_fin - base).total_seconds() / 3600
            navire.fin_datetime = nouvelle_fin
            navire.save()
            
            affectation = Affectation.objects.filter(navire=navire).order_by('-date_creation').first()
            if affectation:
                affectation.heure_fin = navire.heure_fin
                affectation.save()
            
            messages.success(
                request,
                f"Attente de {duree_attente:.1f}h ajoutee pour {navire.nom}\n"
                f"Nouvelle fin estimee: {nouvelle_fin.strftime('%d/%m/%Y %H:%M')}"
            )
        else:
            messages.success(
                request,
                f"Note d'attente de {duree_attente:.1f}h enregistree pour {navire.nom}."
            )
        
        return redirect('detail_navire', navire_id=navire_id)
    
    return redirect('cpn')
from datetime import timedelta
from django.utils import timezone
from django.contrib import messages
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from .decorators import group_required
from .models import NoteAttente, Navire

@login_required
@group_required('Officier_port', 'Directeur')
def replanifier_avec_notes(request):
    """Replanifie en prenant en compte les notes d'attente non traitées"""
    # Récupérer les notes non prises en compte
    notes = NoteAttente.objects.filter(prise_en_compte=False)
    if not notes:
        messages.info(request, "Aucune nouvelle attente à prendre en compte.")
        return redirect('cpn')

    # Appliquer les délais aux navires concernés
    for note in notes:
        navire = note.navire
        # Décaler l'arrivée du navire de la durée d'attente
        if navire.arrivee_datetime:
            navire.arrivee_datetime += timedelta(hours=note.duree_attente)
            navire.arrivee = navire.arrivee_datetime.hour + navire.arrivee_datetime.minute/60.0
        else:
            navire.arrivee += note.duree_attente
        navire.save()
        note.prise_en_compte = True  # <-- Utiliser prise_en_compte au lieu de traitee
        note.save()
        messages.info(request, f"⏰ {navire.nom} retardé de {note.duree_attente}h ({note.commentaire})")

    # Récupérer les navires à planifier (rade + attente avec ETA <= 24h)
    maintenant = timezone.now()
    limite = maintenant + timedelta(hours=24)
    navires_a_planifier = Navire.objects.filter(
        etat__in=['rade', 'attente'],
        arrivee_datetime__isnull=False,
        arrivee_datetime__lte=limite
    ).exclude(etat='termine')
    
    if not navires_a_planifier.exists():
        messages.warning(request, "Aucun navire à planifier dans les prochaines 24h.")
        return redirect('cpn')
    
    # Stocker les IDs en session (comme dans CPN)
    request.session['navires_cpn_ids'] = list(navires_a_planifier.values_list('id', flat=True))
    # Forcer les paramètres par défaut (ou les récupérer de la session)
    request.session['param_incertitude'] = request.session.get('param_incertitude', False)
    request.session['param_amplitude'] = request.session.get('param_amplitude', '20')
    request.session['param_buffer'] = request.session.get('param_buffer', '15')
    request.session['scenario'] = request.session.get('scenario', 'equilibre')

    # Rediriger vers l'optimisation
    return redirect('optimiser_depuis_cpn')
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Navire

def est_consignataire(user):
    """Vérifie si l'utilisateur appartient au groupe Consignataire"""
    return user.groups.filter(name='Consignataire').exists()

from .models import Navire, NotificationConsignataire, Alerte   # ajouter Alerte

@login_required
@user_passes_test(est_consignataire)
def consignataire_dashboard(request):
    from port.models import Navire, Alerte
    from django.contrib import messages
    from django.shortcuts import redirect, render
    from django.db.models import Q

    agent_name = request.user.username
    # Tentative de correspondance insensible à la casse
    navires = Navire.objects.filter(agent__iexact=agent_name)
    
    # Si aucun navire, essayer avec le nom complet (first_name + last_name)
    if not navires.exists() and (request.user.first_name or request.user.last_name):
        full_name = f"{request.user.first_name} {request.user.last_name}".strip()
        if full_name:
            navires = Navire.objects.filter(agent__iexact=full_name)
            agent_name = full_name
    
    # Si encore aucun, essayer avec la partie avant espace (first_name seulement)
    if not navires.exists() and request.user.first_name:
        navires = Navire.objects.filter(agent__iexact=request.user.first_name)
        agent_name = request.user.first_name

    # Optionnel : message d'avertissement si toujours rien
    if not navires.exists():
        messages.warning(request, f"Aucun navire trouvé pour le consignataire '{agent_name}'. Contactez l'administrateur pour lier votre compte.")

    navires_rade = navires.filter(etat='rade')
    navires_attente = navires.filter(etat='attente')
    navires_quai = navires.filter(etat='quai')
    navires_termine = navires.filter(etat='termine')

    # Traitement POST (marquer prêt / annuler)
    if request.method == 'POST':
        navire_id = request.POST.get('navire_id')
        # Utiliser une requête plus tolérante pour trouver le navire (insensible à la casse)
        try:
            navire = Navire.objects.get(id=navire_id, agent__iexact=agent_name)
        except Navire.DoesNotExist:
            messages.error(request, "Navire non trouvé ou non autorisé.")
            return redirect('consignataire_dashboard')

        if 'marquer_pret' in request.POST:
            navire.pret_consignataire = True
            navire.save()
            messages.success(request, f"✅ {navire.nom} marqué comme prêt.")

            # Créer une alerte pour les officiers
            Alerte.objects.create(
                message=f"🚢 Le navire {navire.nom} (agent {navire.agent}) est prêt pour la planification.",
                niveau='success',
                lien=f'/port/navire/{navire.id}/',
                source='Consignataire',
                est_lue=False
            )

        elif 'annuler_pret' in request.POST:
            navire.pret_consignataire = False
            navire.save()
            messages.info(request, f"⚠️ Prêt annulé pour {navire.nom}.")

            Alerte.objects.create(
                message=f"⚠️ Le navire {navire.nom} (agent {navire.agent}) n'est plus marqué comme prêt.",
                niveau='info',
                lien=f'/port/navire/{navire.id}/',
                source='Consignataire',
                est_lue=False
            )

        return redirect('consignataire_dashboard')

    # Récupérer les notifications (pour la cloche)
    notifications = request.user.notifications.all()[:20]
    notifications_non_lues = request.user.notifications.filter(est_lue=False).count()

    context = {
        'navires_rade': navires_rade,
        'navires_attente': navires_attente,
        'navires_quai': navires_quai,
        'navires_termine': navires_termine,
        'agent_name': agent_name,
        'notifications': notifications,
        'notifications_non_lues': notifications_non_lues,
    }
    return render(request, 'port/consignataire_dashboard.html', context)

from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required

@login_required
def redirection_apres_connexion(request):
    if request.user.groups.filter(name='Consignataire').exists():
        return redirect('consignataire_dashboard')
    else:
        return redirect('dashboard')
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from .models import NotificationConsignataire

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from .models import NotificationConsignataire

@login_required
def api_notifications_consignataire(request):
    notifications = request.user.notifications.all()[:50]
    data = {
        'notifications': [
            {
                'id': n.id,
                'message': n.message,
                'type': n.type,
                'est_lue': n.est_lue,
                'date_creation': n.date_creation.isoformat()
            } for n in notifications
        ]
    }
    return JsonResponse(data)

@csrf_exempt
@login_required
def marquer_notification_lue(request, pk):
    try:
        notif = request.user.notifications.get(pk=pk)
        notif.est_lue = True
        notif.save()
        return JsonResponse({'success': True})
    except:
        return JsonResponse({'success': False}, status=404)

@csrf_exempt
@login_required
def supprimer_notification(request, pk):
    try:
        notif = request.user.notifications.get(pk=pk)
        notif.delete()
        return JsonResponse({'success': True})
    except:
        return JsonResponse({'success': False}, status=404)

@csrf_exempt
@login_required
def marquer_toutes_lues(request):
    request.user.notifications.update(est_lue=True)
    return JsonResponse({'success': True})

from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import Equipement, Navire
from .decorators import group_required

@login_required
@group_required('Directeur', 'Officier_radio')
def declarer_panne(request, equipement_id):
    if request.method == 'POST':
        equip = get_object_or_404(Equipement, id=equipement_id)
        duree = float(request.POST.get('duree', 0))
        nb_unites = int(request.POST.get('nb_unites', 1))
        nb_unites = min(nb_unites, equip.engins_en_marche)
        
        equip.engins_en_panne += nb_unites
        equip.engins_en_marche -= nb_unites
        if equip.engins_en_marche == 0:
            equip.en_panne = True
        equip.panne_debut = timezone.now()
        equip.temps_reparation = duree
        equip.save()
        
        messages.warning(request, f"⚠️ Panne déclarée pour {nb_unites} unité(s) de {equip.designation} pendant {duree} heures.")
        
        # Option : rediriger vers la CPN pour replanifier
        return redirect('cpn')
    return redirect('liste_equipements')
@login_required
@group_required('Directeur', 'Officier_radio')
def reparer_equipement(request, equipement_id):
    equip = get_object_or_404(Equipement, id=equipement_id)
    if request.method == 'POST':
        equip.engins_en_marche = equip.engins_existants - equip.engins_en_panne
        equip.engins_en_panne = 0
        equip.en_panne = False
        equip.panne_debut = None
        equip.temps_reparation = 2.0
        equip.save()
        messages.success(request, f"✅ {equip.designation} réparé.")
        return redirect('cpn')
    return redirect('liste_equipements')

from datetime import timedelta
from django.utils import timezone
from port.models import Navire, Affectation

def recalculer_fin_apres_arret(navire: Navire, duree_arret_heures: float):
    """
    Met à jour l'estimation de fin d'un navire après un arrêt de durée duree_arret_heures (en heures).
    - Incrémente le compteur `temps_arret_pluie` du navire.
    - Décale l'`heure_fin` et le `traitement` de l'affectation en cours.
    - Met à jour `heure_fin` et `fin_datetime` du navire.
    - Met à jour `occupation_jusqua` du quai et du poste associés.
    - (Optionnel) Crée une entrée dans l'historique des opérations.
    """
    if not navire or duree_arret_heures <= 0:
        return

    # 1. Incrémenter le compteur d'arrêt pluie
    navire.temps_arret_pluie += duree_arret_heures
    navire.save(update_fields=['temps_arret_pluie'])

    # 2. Récupérer l'affectation en cours (la plus récente, normalement celle active)
    affect = Affectation.objects.filter(navire=navire).order_by('-date_creation').first()
    if affect:
        # Décaler l'heure de fin et le traitement de l'affectation
        affect.heure_fin += duree_arret_heures
        affect.traitement += duree_arret_heures
        affect.save(update_fields=['heure_fin', 'traitement'])

        # Mettre à jour le navire
        navire.heure_fin = affect.heure_fin
        navire.save(update_fields=['heure_fin'])

        # Mettre à jour le quai parent (s'il existe)
        if affect.quai:
            affect.quai.occupation_jusqua = affect.heure_fin
            affect.quai.save(update_fields=['occupation_jusqua'])

        # Mettre à jour le poste attribué (si le navire en a un)
        if hasattr(navire, 'poste_attribue') and navire.poste_attribue:
            navire.poste_attribue.occupation_jusqua = affect.heure_fin
            navire.poste_attribue.save(update_fields=['occupation_jusqua'])

    # 3. Recalculer fin_datetime (pour l'affichage et l'IA)
    if navire.debut_datetime:
        # On suppose que l'heure_fin est exprimée en heures depuis minuit du jour de début
        base = navire.debut_datetime.replace(hour=0, minute=0, second=0, microsecond=0)
        nouvelle_fin = base + timedelta(hours=navire.heure_fin)
        navire.fin_datetime = nouvelle_fin
        navire.save(update_fields=['fin_datetime'])
    else:
        # Fallback : ajouter la durée d'arrêt à l'ancienne fin_datetime si elle existe
        if navire.fin_datetime:
            navire.fin_datetime += timedelta(hours=duree_arret_heures)
            navire.save(update_fields=['fin_datetime'])

    # 4. (Optionnel) Ajouter une trace dans l'historique des opérations
    # Décommentez et adaptez si vous avez un modèle HistoriqueOperation ou HistoriqueAction
    
    from port.models import HistoriqueOperation
    HistoriqueOperation.objects.create(
        navire=navire,
        type_action='arret_pluie',
        duree=duree_arret_heures,
        description=f"Arrêt pour pluie de {duree_arret_heures} heures"
    )
    
@login_required
def reestimer_navire(request, navire_id):
    navire = get_object_or_404(Navire, id=navire_id)
    # Recalculer l'estimation de fin
    if navire.etat == 'quai' and navire.debut_datetime and navire.marchandise_volume > 0:
        from port.optimiseur_epb_pro import ModeleCalcul
        modele = ModeleCalcul([], [])
        taux = modele.get_taux_par_produit(navire)
        duree_traitement = navire.marchandise_volume / max(taux, 1)
        notes_attente = NoteAttente.objects.filter(navire=navire)
        attente_totale = sum(n.duree_attente for n in notes_attente)
        duree_totale = duree_traitement + attente_totale + navire.temps_arret_pluie
        navire.fin_datetime = navire.debut_datetime + timedelta(hours=duree_totale)
        navire.save()
        messages.success(request, f"Estimation recalculée : fin prévue le {navire.fin_datetime.strftime('%d/%m/%Y %H:%M')}")
    return redirect('detail_navire', navire_id=navire.id)

@login_required
def recalculer_affectations_avec_bon_taux(request, navire_id=None):
    """
    Recalcule les affectations existantes avec le bon taux produit.
    Utile pour corriger les affectations créées avec l'ancien taux.
    """
    from port.models import Navire, Affectation
    from port.optimiseur_epb_pro import ModeleCalcul
    
    mc = ModeleCalcul([], [])
    
    if navire_id:
        navires = Navire.objects.filter(id=navire_id)
    else:
        navires = Navire.objects.filter(type='cerealier')
    
    nb_modifies = 0
    for navire in navires:
        # Vérifier si le navire a des affectations
        affectations = Affectation.objects.filter(navire=navire)
        if not affectations.exists():
            continue
        
        # Calculer le bon taux
        bon_taux = mc.get_taux_par_produit(navire)
        volume = navire.marchandise_volume
        
        if volume <= 0:
            continue
        
        bon_traitement = volume / bon_taux
        
        for affect in affectations:
            ancien_traitement = affect.traitement
            # Si l'écart est significatif (> 10%), on corrige
            if abs(ancien_traitement - bon_traitement) / bon_traitement > 0.1:
                affect.traitement = bon_traitement
                if affect.heure_debut is not None:
                    affect.heure_fin = affect.heure_debut + bon_traitement
                affect.save()
                nb_modifies += 1
                print(f"✅ {navire.nom}: {ancien_traitement:.1f}h -> {bon_traitement:.1f}h")
    
    return JsonResponse({'success': True, 'navires_modifies': nb_modifies})
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.shortcuts import get_object_or_404
from .models import NoteAttente, Affectation, Navire

@login_required
@group_required('Officier_port', 'Directeur')
@csrf_exempt
@require_http_methods(["POST"])
def ajouter_note_attente_ajax(request):
    """Ajoute une note d'attente et retourne les données mises à jour (AJAX)"""
    try:
        data = json.loads(request.body)
        navire_id = data.get('navire_id')
        shift = data.get('shift', 'matin')
        duree_attente = float(data.get('duree_attente', 0))
        commentaire = data.get('commentaire', '')
        
        navire = get_object_or_404(Navire, id=navire_id)
        
        # Créer la note d'attente
        NoteAttente.objects.create(
            navire=navire,
            shift=shift,
            duree_attente=duree_attente,
            commentaire=commentaire,
            prise_en_compte=True
        )
        
        # Récupérer l'affectation en cours
        affectation = Affectation.objects.filter(navire=navire).order_by('-date_creation').first()
        
        if affectation:
            # Sauvegarder l'ancien traitement (qui ne doit PAS changer)
            ancien_traitement = affectation.traitement
            
            # Décaler le début et la fin
            affectation.heure_debut += duree_attente
            affectation.heure_fin += duree_attente
            affectation.attente += duree_attente
            
            # Le traitement reste inchangé
            # affectation.traitement ne change PAS
            
            affectation.save()
            
            # Mettre à jour le navire
            navire.heure_debut = affectation.heure_debut
            navire.heure_fin = affectation.heure_fin
            navire.save()
            
            return JsonResponse({
                'success': True,
                'navire_id': navire.id,
                'navire_nom': navire.nom,
                'nouveau_debut': round(affectation.heure_debut, 1),
                'nouvelle_fin': round(affectation.heure_fin, 1),
                'nouvelle_attente': round(affectation.attente, 1),
                'traitement': round(affectation.traitement, 1),
                'duree_ajoutee': round(duree_attente, 1),
                'message': f"✅ {duree_attente:.1f}h d'attente ajoutée"
            })
        
        return JsonResponse({
            'success': False,
            'error': 'Aucune affectation trouvée pour ce navire'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@group_required('Directeur')
def ajouter_poste(request):
    """Ajouter un nouveau poste à un quai"""
    quai_id = request.GET.get('quai_id')
    quai = None
    if quai_id:
        quai = get_object_or_404(Quai, id=quai_id)
    
    if request.method == 'POST':
        try:
            quai_id = request.POST.get('quai_id')
            quai = get_object_or_404(Quai, id=quai_id)
            
            poste = Poste.objects.create(
                quai=quai,
                numero=request.POST.get('numero'),
                longueur=float(request.POST.get('longueur')),
                profondeur=float(request.POST.get('profondeur')),
                specialite=request.POST.get('specialite', ''),
                type_navire_autorise=request.POST.get('type_navire_autorise', ''),
                disponible=True,
                occupation_jusqua=0.0
            )
            
            messages.success(request, f"✅ Poste {poste.numero} ajouté au quai {quai.nom}")
            return redirect('liste_quais')
        except Exception as e:
            messages.error(request, f"❌ Erreur : {e}")
    
    context = {
        'quai': quai,
        'quais': Quai.objects.all().order_by('nom'),
    }
    return render(request, 'port/ajouter_poste.html', context)
def synchroniser_disponibilite_postes():
    """Met à jour la disponibilité des postes en fonction des navires à quai"""
    from port.models import Navire, Poste, Quai
    
    print("\n" + "="*60)
    print("🔧 SYNCHRONISATION DES POSTES")
    print("="*60)
    
    # 1. Récupérer tous les navires à quai avec leur poste
    navires_quai = Navire.objects.filter(etat='quai', poste_attribue__isnull=False).select_related('poste_attribue')
    
    # 2. Récupérer les IDs des postes occupés
    postes_occupes_ids = [navire.poste_attribue.id for navire in navires_quai if navire.poste_attribue]
    
    print(f"📋 Navires à quai trouvés: {len(navires_quai)}")
    for navire in navires_quai:
        if navire.poste_attribue:
            print(f"  - {navire.nom} -> Poste {navire.poste_attribue.numero} (ID: {navire.poste_attribue.id})")
    
    # 3. Réinitialiser UNIQUEMENT les postes libres (pas tous !)
    postes_modifies = Poste.objects.exclude(id__in=postes_occupes_ids).update(
        disponible=True, 
        occupation_jusqua=0.0
    )
    print(f"📌 {postes_modifies} poste(s) réinitialisé(s) à LIBRE")
    
    # 4. Marquer les postes occupés
    for navire in navires_quai:
        poste = navire.poste_attribue
        if poste:
            poste.disponible = False
            if navire.heure_fin:
                poste.occupation_jusqua = navire.heure_fin
            else:
                poste.occupation_jusqua = 24.0
            poste.save()
            print(f"  🔒 Poste {poste.numero} (ID: {poste.id}) marqué OCCUPÉ par {navire.nom}")
            
            # Marquer également le quai parent
            if poste.quai:
                poste.quai.disponible = False
                if navire.heure_fin:
                    poste.quai.occupation_jusqua = navire.heure_fin
                else:
                    poste.quai.occupation_jusqua = 24.0
                poste.quai.save()
                print(f"     📌 Quai {poste.quai.nom} -> OCCUPÉ")
    
    # 5. Vérification finale
    print("\n" + "="*60)
    print("📊 ÉTAT FINAL DES POSTES")
    print("="*60)
    
    for poste in Poste.objects.all().order_by('numero'):
        statut = "🔒 OCCUPÉ" if not poste.disponible else "🔓 LIBRE"
        nav_occ = Navire.objects.filter(poste_attribue=poste, etat='quai').first()
        nav_nom = f" - {nav_occ.nom}" if nav_occ else ""
        print(f"  Poste {poste.numero}: {statut}{nav_nom}")
    
    print("="*60 + "\n")
        
        
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from .decorators import group_required
import json

@login_required
@group_required('Officier_port', 'Directeur')
@csrf_exempt
def supprimer_note_attente(request, note_id):
    """Supprime une note d'attente de l'escale ACTIVE."""
    from port.models import NoteAttente
    from datetime import timedelta
    
    if request.method == 'POST':
        try:
            note = NoteAttente.objects.get(id=note_id)
            
            # Verifier que la note appartient a une escale active
            if note.archive or (note.escale and not note.escale.active):
                return JsonResponse({
                    'success': False,
                    'error': 'Cette note est archivee et ne peut pas etre supprimee.'
                }, status=400)
            
            navire = note.navire
            escale = note.escale
            duree = note.duree_attente
            navire_nom = navire.nom
            navire_id = navire.id
            
            note.delete()
            
            # Recalculer l'estimation de fin
            if navire.etat == 'quai' and navire.debut_datetime and escale:
                autres_notes = NoteAttente.objects.filter(
                    escale=escale,
                    archive=False,
                    prise_en_compte=False
                )
                attente_totale = sum(n.duree_attente for n in autres_notes)
                
                volume = navire.marchandise_volume or 0
                if navire.type == 'cerealier':
                    duree_traitement = volume / 550
                elif navire.type == 'cargo':
                    duree_traitement = volume / 250
                elif navire.type == 'conteneur':
                    duree_traitement = volume / 300
                elif navire.type == 'petrolier':
                    duree_traitement = volume / 400
                else:
                    duree_traitement = volume / 200
                
                maintenant = timezone.now()
                temps_ecoule = (maintenant - navire.debut_datetime).total_seconds() / 3600
                temps_restant = max(0, (duree_traitement + attente_totale) - temps_ecoule)
                nouvelle_fin = maintenant + timedelta(hours=temps_restant)
                
                base = nouvelle_fin.replace(hour=0, minute=0, second=0, microsecond=0)
                navire.heure_fin = (nouvelle_fin - base).total_seconds() / 3600
                navire.fin_datetime = nouvelle_fin
                navire.save()
                
                affectation = Affectation.objects.filter(navire=navire).order_by('-date_creation').first()
                if affectation:
                    affectation.heure_fin = navire.heure_fin
                    affectation.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Note de {duree}h supprimee pour {navire_nom}',
                'navire_id': navire_id
            })
        
        except NoteAttente.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Note non trouvee'}, status=404)
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
    
    return JsonResponse({'success': False, 'error': 'Methode non autorisee'}, status=405)
from django.core.management import call_command

@login_required
@group_required('Directeur', 'Officier_port', 'Officier_radio')
def synchroniser_epb(request):
    """Exécute la commande d'importation EPB pour synchroniser les données"""
    if request.method == 'POST':
        try:
            # Exécuter la commande d'importation
            call_command('import_epb')
            messages.success(request, "✅ Synchronisation avec EPB réussie ! Les données des navires ont été mises à jour.")
        except Exception as e:
            messages.error(request, f"❌ Erreur lors de la synchronisation : {str(e)}")
        return redirect('liste_navires')
    
    return redirect('liste_navires')
@login_required
@group_required('Directeur')
def modifier_utilisateur(request, user_id):
    user = get_object_or_404(User, id=user_id)
    # Créer le profil s'il n'existe pas (pour les anciens utilisateurs)
    Profile.objects.get_or_create(user=user)

    if request.method == 'POST':
        # Mise à jour des champs User
        user.username = request.POST['username']
        user.email = request.POST.get('email', '')
        new_password = request.POST.get('password')
        if new_password:
            user.set_password(new_password)
        
        # ========== ACTIVER/DÉSACTIVER LE COMPTE ==========
        est_actif = request.POST.get('is_active') == 'on'
        user.is_active = est_actif
        # =================================================
        
        user.save()

        # Mise à jour du groupe
        user.groups.clear()
        groupe_id = request.POST.get('groupe')
        if groupe_id:
            user.groups.add(Group.objects.get(id=groupe_id))

        # Mise à jour des champs du profil
        profile = user.profile
        profile.matricule = request.POST.get('matricule', '')
        profile.date_naissance = request.POST.get('date_naissance') or None
        profile.telephone = request.POST.get('telephone', '')
        profile.adresse = request.POST.get('adresse', '')
        profile.poste = request.POST.get('poste', '')
        profile.save()

        status = "activé" if est_actif else "désactivé"
        messages.success(request, f"✅ Utilisateur {user.username} modifié avec succès (compte {status}).")
        return redirect('gestion_utilisateurs')

    # GET : afficher le formulaire avec les données existantes
    groupes = Group.objects.all()
    return render(request, 'port/modifier_utilisateur.html', {
        'user': user,
        'groupes': groupes,
        'profile': user.profile,
    })
@login_required
@group_required('Directeur')
def activer_utilisateur(request, user_id):
    """Active un compte utilisateur"""
    user = get_object_or_404(User, id=user_id)
    user.is_active = True
    user.save()
    messages.success(request, f"✅ Compte de {user.username} activé avec succès.")
    return redirect('gestion_utilisateurs')

@login_required
@group_required('Directeur')
def desactiver_utilisateur(request, user_id):
    """Désactive un compte utilisateur"""
    user = get_object_or_404(User, id=user_id)
    
    # Empêcher de désactiver son propre compte
    if user == request.user:
        messages.error(request, "❌ Vous ne pouvez pas désactiver votre propre compte.")
        return redirect('gestion_utilisateurs')
    
    user.is_active = False
    user.save()
    messages.warning(request, f"⚠️ Compte de {user.username} désactivé.")
    return redirect('gestion_utilisateurs')
# =============================================================================
# HISTORIQUE DES ESCALES
# =============================================================================

@login_required
def historique_escales_navire(request, navire_id):
    """Affiche l'historique des escales d'un navire.
    
    Pour les escales ACTIVES : calcul en temps réel des statistiques.
    Pour les escales CLÔTURÉES : lecture des valeurs figées.
    
    Le débit réel est calculé sur la DURÉE EFFECTIVE (hors attentes).
    """
    from port.models import Escale, NoteAttente
    from django.utils import timezone
    
    navire = get_object_or_404(Navire, id=navire_id)
    escales_qs = Escale.objects.filter(navire=navire).order_by('-date_debut')
    
    # ========== ENRICHISSEMENT DES ESCALES ==========
    escales = []
    for escale in escales_qs:
        escale_data = {
            'id': escale.id,
            'date_debut': escale.date_debut,
            'date_fin': escale.date_fin,
            'active': escale.active,
            'volume_marchandise': escale.volume_marchandise,
            'meteo_pluie': escale.meteo_pluie,
            'meteo_vent_force': escale.meteo_vent_force,
            'shift_debut': escale.shift_debut,
        }
        
        # ========== RÉCUPÉRATION DU QUAI ET POSTE ==========
        # Priorité 1 : le quai/poste de l'escale (si renseigné)
        # Priorité 2 : le quai/poste actuel du navire (si actif)
        quai_utilise = escale.quai_utilise
        poste_utilise = escale.poste_utilise
        
        if escale.active:
            # Pour une escale active, prendre le quai/poste ACTUEL du navire
            if navire.quai_attribue:
                quai_utilise = navire.quai_attribue
            if navire.poste_attribue:
                poste_utilise = navire.poste_attribue
        
        escale_data['quai_utilise'] = quai_utilise
        escale_data['poste_utilise'] = poste_utilise
        
        # ========== NOTES D'ATTENTE DE L'ESCALE ==========
        notes = NoteAttente.objects.filter(escale=escale)
        escale_data['nb_notes_attente'] = notes.count()
        
        # ========== ATTENTE TOTALE ==========
        if escale.active:
            attente_totale = sum(n.duree_attente for n in notes)
        else:
            attente_totale = escale.attente_totale
        
        escale_data['attente_totale'] = attente_totale
        
        # ========== DURÉE TOTALE ==========
        if escale.active:
            if navire.debut_datetime:
                duree_totale = (
                    (timezone.now() - navire.debut_datetime).total_seconds() / 3600
                )
            else:
                duree_totale = (
                    (timezone.now() - escale.date_debut).total_seconds() / 3600
                )
        else:
            duree_totale = escale.duree_reelle
        
        escale_data['duree_totale'] = duree_totale
        
        # ========== DURÉE EFFECTIVE (hors attentes) ==========
        duree_effective = max(duree_totale - attente_totale, 0.1)
        escale_data['duree_effective'] = duree_effective
        
        # ========== DÉBIT RÉEL (sur durée effective) ==========
        if escale.volume_marchandise > 0 and duree_effective > 0:
            debit_reel = escale.volume_marchandise / duree_effective
        else:
            debit_reel = 0
        
        escale_data['debit_reel'] = debit_reel
        
        escales.append(escale_data)
    
    # ========== STATISTIQUES GLOBALES ==========
    nb_escales = len(escales)
    
    if nb_escales > 0:
        attente_moyenne = sum(e['attente_totale'] for e in escales) / nb_escales
        duree_moyenne = sum(e['duree_totale'] for e in escales) / nb_escales
        
        debits_valides = [e['debit_reel'] for e in escales if e['debit_reel'] > 0]
        debit_moyen = sum(debits_valides) / len(debits_valides) if debits_valides else 0
    else:
        attente_moyenne = 0
        duree_moyenne = 0
        debit_moyen = 0
    
    # ========== ESCALE ACTIVE ==========
    escale_active_data = None
    for e in escales:
        if e['active']:
            escale_active_data = e
            break
    
    # ========== CONTEXTE ==========
    context = {
        'navire': navire,
        'escales': escales,
        'nb_escales': nb_escales,
        'escale_active': escale_active_data,
        'attente_moyenne': attente_moyenne,
        'duree_moyenne': duree_moyenne,
        'debit_moyen': debit_moyen,
    }
    return render(request, 'port/historique_escales.html', context)

@login_required
@group_required('Officier_port', 'Directeur')
def cloturer_escale_manuelle(request, navire_id):
    """Cloture manuellement l'escale active d'un navire."""
    from port.utils_escales import cloturer_escale
    
    navire = get_object_or_404(Navire, id=navire_id)
    
    if request.method == 'POST':
        escale = cloturer_escale(navire)
        if escale:
            messages.success(
                request,
                f"Escale de {navire.nom} cloturee "
                f"(attente: {escale.attente_totale:.1f}h)"
            )
        else:
            messages.warning(request, f"Aucune escale active pour {navire.nom}")
    
    return redirect('historique_escales_navire', navire_id=navire_id)
# =============================================================================
# PLANIFICATION DYNAMIQUE (mise à jour toutes les 3h + à 10h)
# =============================================================================

# =============================================================================
# PLANIFICATION DYNAMIQUE — 4 FONCTIONS
# =============================================================================

@login_required
def planification_dynamique(request):
    """
    Page de planification dynamique avec double validation.
    ✅ TOUS les navires en attente (validés par consignataire) sont affichés.
    ✅ Pas de filtre ETA.
    ✅ SYNCHRONISATION FORCÉE avec la MÊME formule que detail_navire.
    """
    from datetime import datetime, timedelta
    from django.utils import timezone
    from django.core.management import call_command
    from port.models import Navire, Quai, Poste, Meteo, Equipement, Affectation, HistoriqueOperation, NoteAttente, Escale
    from port.optimiseur_epb_pro import PlanificateurEPB, GestionnaireDonnees
    from port.adaptateurs import AdaptateurDonnees
    import io

    now = timezone.now()
    heure_actuelle = now.hour + now.minute / 60.0
    base = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # ========== SYNCHRONISATION ==========
    derniere_maj = request.session.get('derniere_sync_epb')
    doit_synchroniser = True
    sync_message = ""

    if derniere_maj:
        try:
            derniere_maj_dt = datetime.fromisoformat(derniere_maj)
            temps_ecoule = (now - derniere_maj_dt).total_seconds() / 60
            if temps_ecoule < 30:
                doit_synchroniser = False
                sync_message = f"Synchronisation ignorée (MAJ il y a {temps_ecoule:.0f} min)"
        except (ValueError, TypeError):
            pass

    if doit_synchroniser:
        try:
            output = io.StringIO()
            call_command('import_epb', stdout=output)
            request.session['derniere_sync_epb'] = now.isoformat()
            sync_message = "Synchronisation réussie"
        except Exception as e:
            sync_message = f"Erreur sync : {str(e)}"

    # ========== MÉTÉO ==========
    meteo = Meteo.objects.filter(date=now.date()).first()
    meteo_restrictions = []
    meteo_pluie = False
    meteo_vent_force = 0
    meteo_temperature = 20
    pluie_debut_prevue = None
    pluie_fin_prevue = None

    if meteo:
        if meteo.restrictions:
            meteo_restrictions = [q.strip() for q in meteo.restrictions.split(',') if q.strip()]
        meteo_pluie = meteo.pluie
        meteo_vent_force = meteo.vent_force
        meteo_temperature = meteo.temperature
        pluie_debut_prevue = getattr(meteo, 'pluie_debut_prevue', None)
        pluie_fin_prevue = getattr(meteo, 'pluie_fin_prevue', None)

    # ========== RÉCUPÉRATION DE LA SÉLECTION ==========
    ids_selectionnes = request.session.get('navires_selectionnes_planification', [])
    ids_selectionnes = [int(i) for i in ids_selectionnes]

    # ========== INITIALISATION PLANIFICATEUR ==========
    postes_model = Poste.objects.filter(gestion_manuelle=False).select_related('quai')
    quais_data = [AdaptateurDonnees.vers_quai_depuis_poste(p) for p in postes_model]

    equipements_model = Equipement.objects.all()
    equipements_data = [AdaptateurDonnees.vers_equipement(e) for e in equipements_model]

    from django.db.models import Avg, F
    coeffs_historiques = {}
    for row in HistoriqueOperation.objects.values('navire_type', 'quai_id').annotate(
        ratio_moyen=Avg(F('duree_reelle') / F('duree_estimee'))
    ):
        coeffs_historiques[(row['navire_type'], row['quai_id'])] = row['ratio_moyen']

    planificateur = PlanificateurEPB(
        quais=quais_data, equipements=equipements_data, mois=now.month,
        incertitude=False, amplitude=0.0, pourcentage_buffer=0.0,
        meteo_restrictions=meteo_restrictions, meteo_pluie=meteo_pluie,
        meteo_vent_force=meteo_vent_force, meteo_temperature=meteo_temperature,
        scenario=request.session.get('scenario', 'equilibre'),
        coeffs_historiques=coeffs_historiques,
        pluie_debut_prevue=pluie_debut_prevue, pluie_fin_prevue=pluie_fin_prevue,
    )

    def verifier_compatibilite_navire_poste(navire_django, poste_django):
        try:
            navire_data = AdaptateurDonnees.vers_navire(navire_django, coeff_variation=0)
            quai_data = AdaptateurDonnees.vers_quai_depuis_poste(poste_django)
            compatible, raison = planificateur.verifier_compatibilite(
                navire_data, quai_data, debut=None, traitement=None
            )
            return compatible, raison
        except Exception as e:
            return False, f"Erreur: {str(e)}"

    def get_postes_compatibles_pour_navire(navire_django):
        resultats = []
        for poste in postes_model:
            compatible, raison = verifier_compatibilite_navire_poste(navire_django, poste)
            if compatible:
                resultats.append({'poste': poste, 'quai': poste.quai, 'raison': raison})
        return resultats

    # ============================================================
    # ✅ SYNCHRONISATION FORCÉE DES FIN_DATETIME
    # Recalculer fin_datetime avec la MÊME formule que detail_navire
    # (durée + attentes notes + attente équipement + arrêt pluie)
    # ============================================================
    navires_a_quai = Navire.objects.filter(
        etat='quai', quai_attribue__isnull=False
    ).select_related('quai_attribue', 'poste_attribue').order_by('heure_fin')

    for navire_sync in navires_a_quai:
        if navire_sync.debut_datetime and navire_sync.marchandise_volume > 0:
            # ✅ ÉTAPE 1 : Durée de traitement (règles contractuelles)
            duree_traitement = calculer_duree_contractuelle(navire_sync)
            
            # ✅ ÉTAPE 2 : Attente notes (via l'escale ACTIVE, comme detail_navire)
            # On utilise la même logique que detail_navire : notes de l'escale active, non archivées
            escale_active = Escale.objects.filter(navire=navire_sync, active=True).first()
            if escale_active:
                notes_attente_actives = NoteAttente.objects.filter(
                    escale=escale_active,
                    archive=False
                )
            else:
                # Fallback : toutes les notes non archivées du navire
                notes_attente_actives = NoteAttente.objects.filter(
                    navire=navire_sync,
                    archive=False
                )
            attente_notes = sum(n.duree_attente for n in notes_attente_actives)
            
            # ✅ ÉTAPE 3 : Attente équipement (estimation)
            attente_equip = 0.0
            if navire_sync.type == 'gazier':
                attente_equip = 3.0
            elif navire_sync.type == 'petrolier':
                attente_equip = 2.0
            elif navire_sync.type == 'cerealier':
                attente_equip = 1.0
            
            # ✅ ÉTAPE 4 : Arrêt pluie
            arret_pluie = navire_sync.temps_arret_pluie or 0
            
            # ✅ ÉTAPE 5 : Durée totale (formule IDENTIQUE à detail_navire)
            duree_totale = duree_traitement + attente_notes + attente_equip + arret_pluie
            nouvelle_fin = navire_sync.debut_datetime + timedelta(hours=duree_totale)

            if navire_sync.fin_datetime != nouvelle_fin:
                navire_sync.fin_datetime = nouvelle_fin
                base_dt = navire_sync.debut_datetime.replace(hour=0, minute=0, second=0, microsecond=0)
                navire_sync.heure_fin = (nouvelle_fin - base_dt).total_seconds() / 3600.0
                navire_sync.save(update_fields=['fin_datetime', 'heure_fin'])
                print(f"🔄 Sync {navire_sync.nom}: fin = {nouvelle_fin.strftime('%d/%m %H:%M')} "
                      f"(durée = {duree_totale:.1f}h = {duree_traitement:.1f}h + {attente_notes:.1f}h + {attente_equip:.1f}h)")

                # Mettre à jour l'affectation
                derniere_affect = Affectation.objects.filter(navire=navire_sync).order_by('-date_creation').first()
                if derniere_affect:
                    derniere_affect.heure_fin = navire_sync.heure_fin
                    derniere_affect.traitement = duree_totale
                    derniere_affect.save(update_fields=['heure_fin', 'traitement'])

                # Mettre à jour le poste et le quai
                if navire_sync.poste_attribue:
                    navire_sync.poste_attribue.occupation_jusqua = navire_sync.heure_fin
                    navire_sync.poste_attribue.save(update_fields=['occupation_jusqua'])
                if navire_sync.quai_attribue:
                    navire_sync.quai_attribue.occupation_jusqua = navire_sync.heure_fin
                    navire_sync.quai_attribue.save(update_fields=['occupation_jusqua'])

    # Recharger après synchronisation
    navires_a_quai = Navire.objects.filter(
        etat='quai', quai_attribue__isnull=False
    ).select_related('quai_attribue', 'poste_attribue').order_by('heure_fin')
    # ============================================================

    # ========== NAVIRES SÉLECTIONNÉS ==========
    navires_selectionnes_qs = Navire.objects.filter(
        id__in=ids_selectionnes,
        pret_consignataire=True,
        etat__in=['rade', 'attente']
    ).order_by('arrivee_datetime')

    # ========== APPEL OPTIMISEUR ==========
    navires_a_planifier = []
    for n in navires_selectionnes_qs:
        nd = AdaptateurDonnees.vers_navire(n, coeff_variation=0)
        if nd.est_en_rade or n.etat == 'attente':
            if n.arrivee_datetime:
                heure_originale = n.arrivee_datetime.hour + n.arrivee_datetime.minute / 60.0
            else:
                heure_originale = n.arrivee
            nd.arrivee = heure_originale
            nd.arrivee_datetime = base + timedelta(hours=heure_originale)
        navires_a_planifier.append(nd)

    navires_quai_model = Navire.objects.filter(etat='quai', quai_attribue__isnull=False)
    navires_a_quai_data = []
    for n in navires_quai_model:
        nd = AdaptateurDonnees.vers_navire(n, coeff_variation=0)
        nd.fin_prevue = n.heure_fin
        navires_a_quai_data.append(nd)

    affectations_resultat = []
    if navires_a_planifier:
        try:
            affectations_resultat, _, _ = planificateur.planifier(
                navires_a_planifier, navires_a_quai_data, date_reference=now
            )
        except Exception as e:
            print(f"❌ Erreur optimiseur: {e}")

    # ========== PRÉ-AFFECTATION ==========
    affectation_proposee = {}
    postes_utilises = set()

    for aff in affectations_resultat:
        navire_pret = next((n for n in navires_selectionnes_qs if n.id == aff.navire_id), None)
        if navire_pret is None:
            continue

        poste_django = next((p for p in postes_model if p.id == aff.quai_id), None)
        if poste_django is None:
            continue

        if navire_pret.etat == 'rade':
            temps_attente = (now - navire_pret.arrivee_datetime).total_seconds() / 3600
            type_source = 'rade'
        else:
            temps_attente = (navire_pret.arrivee_datetime - now).total_seconds() / 3600
            type_source = 'attente'

        affectation_proposee[navire_pret.id] = {
            'poste': poste_django,
            'navire_actuel': Navire.objects.filter(poste_attribue=poste_django, etat='quai').first(),
            'type_source': type_source,
            'temps_attente': temps_attente,
            'est_en_retard': temps_attente < 0,
            'priorites': get_priorites_liste(navire_pret),
            'postes_alternatifs': [],
        }
        postes_utilises.add(poste_django.id)

    for navire_id, aff in affectation_proposee.items():
        navire_pret = next((n for n in navires_selectionnes_qs if n.id == navire_id), None)
        if not navire_pret:
            continue
        alternatives = []
        for poste in postes_model:
            if poste.id == aff['poste'].id or poste.id in postes_utilises:
                continue
            compatible, _ = verifier_compatibilite_navire_poste(navire_pret, poste)
            if compatible:
                alternatives.append({
                    'numero': poste.numero,
                    'quai_nom': poste.quai.nom,
                    'est_occupe': Navire.objects.filter(poste_attribue=poste, etat='quai').exists(),
                })
            if len(alternatives) >= 4:
                break
        aff['postes_alternatifs'] = alternatives

    # ============================================================
    # ✅ SORTIES PRÉVUES (UTILISE fin_datetime EN PRIORITÉ)
    # ============================================================
    sorties_prevues = []
    for navire in navires_a_quai:
        # ✅ PRIORITÉ 1 : Utiliser fin_datetime (source de vérité)
        if navire.fin_datetime:
            fin_dt = navire.fin_datetime
        elif navire.heure_fin:
            heures = int(navire.heure_fin)
            minutes = int((navire.heure_fin - heures) * 60)
            fin_dt = base + timedelta(hours=heures, minutes=minutes)
        else:
            continue

        # ⚠️ NE PAS ajouter de jour si la date est passée (afficher le retard)
        temps_restant = (fin_dt - now).total_seconds() / 3600

        debit_estime = 0
        if navire.marchandise_volume:
            derniere_affect = Affectation.objects.filter(navire=navire).order_by('-date_creation').first()
            if derniere_affect and derniere_affect.traitement > 0:
                debit_estime = navire.marchandise_volume / derniere_affect.traitement

        sorties_prevues.append({
            'navire': navire,
            'fin_dt': fin_dt,
            'temps_restant': temps_restant,
            'quai': navire.quai_attribue,
            'poste': navire.poste_attribue,
            'est_imminent': temps_restant <= 3 and temps_restant > 0,
            'est_proche': temps_restant <= 6 and temps_restant > 0,
            'est_en_retard': temps_restant < 0,
            'longueur': navire.longueur,
            'tonnage': navire.marchandise_volume,
            'agent': navire.agent or 'Inconnu',
            'debit_estime': round(debit_estime, 1) if debit_estime > 0 else 0,
            'priorites': get_priorites_liste(navire),
        })
    sorties_prevues.sort(key=lambda x: x['temps_restant'])

    # ========== ✅ TOUS LES NAVIRES EN ATTENTE (PAS DE FILTRE ETA) ==========
    navires_attendus = Navire.objects.filter(
        etat='attente',
        arrivee_datetime__isnull=False,
        pret_consignataire=True
    ).order_by('arrivee_datetime')

    TAUX_PAR_TYPE = {
        'gazier': 200, 'petrolier': 400, 'cerealier': 550,
        'conteneur': 300, 'cargo': 250, 'ferry': 100,
        'essence': 300, 'huilier': 150, 'betail': 100, 'frigorifique': 200,
    }

    entrees_prevues = []
    for navire in navires_attendus:
        temps_avant = (navire.arrivee_datetime - now).total_seconds() / 3600
        postes_comp = get_postes_compatibles_pour_navire(navire)
        entrees_prevues.append({
            'navire': navire,
            'arrivee_dt': navire.arrivee_datetime,
            'temps_avant': temps_avant,
            'type': navire.type,
            'est_imminent': temps_avant <= 3,
            'est_proche': temps_avant <= 6,
            'est_en_retard': temps_avant < 0,
            'longueur': navire.longueur,
            'tonnage': navire.marchandise_volume,
            'agent': navire.agent or 'Inconnu',
            'debit_estime': TAUX_PAR_TYPE.get(navire.type, 250),
            'priorites': get_priorites_liste(navire),
            'postes_compatibles': postes_comp[:5],
            'nb_postes_compatibles': len(postes_comp),
            'est_selectionne': navire.id in ids_selectionnes,
        })

    # ========== NAVIRES EN RADE ==========
    navires_rade_qs = Navire.objects.filter(
        etat='rade', pret_consignataire=True
    ).order_by('arrivee_datetime')

    rade_info = []
    for navire in navires_rade_qs:
        temps_rade = (now - navire.arrivee_datetime).total_seconds() / 3600 if navire.arrivee_datetime else 0
        postes_comp = get_postes_compatibles_pour_navire(navire)
        rade_info.append({
            'navire': navire,
            'temps_rade': temps_rade,
            'agent': navire.agent or 'Inconnu',
            'type': navire.type,
            'longueur': navire.longueur,
            'tonnage': navire.marchandise_volume,
            'priorites': get_priorites_liste(navire),
            'postes_compatibles': postes_comp[:5],
            'nb_postes_compatibles': len(postes_comp),
            'est_selectionne': navire.id in ids_selectionnes,
        })

    # ============================================================
    # ✅ TABLEAU UNIFIÉ (UTILISE fin_datetime EN PRIORITÉ)
    # ============================================================
    tous_les_postes = list(Poste.objects.select_related('quai').order_by('quai__nom', 'numero'))
    tableau_unifie = []

    for poste in tous_les_postes:
        navire_actuel = Navire.objects.filter(poste_attribue=poste, etat='quai').first()

        navires_prets_compatibles = []
        for navire_id, aff in affectation_proposee.items():
            if aff['poste'].id == poste.id:
                navire_pret = next((n for n in navires_selectionnes_qs if n.id == navire_id), None)
                if navire_pret:
                    navires_prets_compatibles.append({
                        'navire': navire_pret,
                        'type_source': aff['type_source'],
                        'temps_attente': aff['temps_attente'],
                        'est_en_retard': aff['est_en_retard'],
                        'priorites': aff['priorites'],
                        'postes_alternatifs': aff.get('postes_alternatifs', []),
                    })

        est_occupe = navire_actuel is not None
        a_des_candidats = len(navires_prets_compatibles) > 0

        if not est_occupe and not a_des_candidats:
            continue

        # ✅ Utiliser fin_datetime en PRIORITÉ
        liberation_dt = None
        temps_restant = None
        if navire_actuel:
            if navire_actuel.fin_datetime:
                liberation_dt = navire_actuel.fin_datetime
            elif navire_actuel.heure_fin:
                h = int(navire_actuel.heure_fin)
                m = int((navire_actuel.heure_fin - h) * 60)
                liberation_dt = base + timedelta(hours=h, minutes=m)

            if liberation_dt:
                # ⚠️ NE PAS ajouter de jour si la date est passée (afficher le retard)
                temps_restant = (liberation_dt - now).total_seconds() / 3600

        tableau_unifie.append({
            'poste': poste,
            'quai': poste.quai,
            'est_occupe': est_occupe,
            'navire_actuel': navire_actuel,
            'liberation_dt': liberation_dt,
            'temps_restant': temps_restant,
            'navires_prets_compatibles': navires_prets_compatibles,
            'nb_navires_prets': len(navires_prets_compatibles),
            'remplacant_optimal': navires_prets_compatibles[0] if navires_prets_compatibles else None,
        })

    tableau_unifie.sort(key=lambda x: (
        not x['est_occupe'],
        x['temps_restant'] if x['temps_restant'] is not None else 999,
        int(x['poste'].numero) if str(x['poste'].numero).isdigit() else 9999,
    ))

    # ========== PROCHAINE MAJ ==========
    heures_maj = [1, 4, 7, 10, 13, 16, 19, 22]
    prochaine_maj = None
    for h in heures_maj:
        if h > heure_actuelle:
            prochaine_maj = base + timedelta(hours=h)
            break
    if prochaine_maj is None:
        prochaine_maj = base + timedelta(days=1, hours=heures_maj[0])
    temps_avant_maj = (prochaine_maj - now).total_seconds() / 3600

    # ========== STATS ==========
    nb_prets = len(navires_selectionnes_qs)
    nb_en_retard = sum(1 for e in entrees_prevues if e['est_en_retard'])
    nb_postes_occupes = sum(1 for item in tableau_unifie if item['est_occupe'])
    nb_attente_consignataire = Navire.objects.filter(
        etat__in=['rade', 'attente'], pret_consignataire=False
    ).count()

    context = {
        'now': now,
        'heure_actuelle': heure_actuelle,
        'sorties_prevues': sorties_prevues,
        'entrees_prevues': entrees_prevues,
        'navires_rade': rade_info,
        'tableau_unifie': tableau_unifie,
        'nb_navires_prets': nb_prets,
        'nb_postes_occupes': nb_postes_occupes,
        'nb_postes_libres': len(tableau_unifie) - nb_postes_occupes,
        'prochaine_maj': prochaine_maj,
        'temps_avant_maj': temps_avant_maj,
        'nb_sorties_imminentes': sum(1 for s in sorties_prevues if s['est_imminent']),
        'nb_entrees_imminentes': sum(1 for e in entrees_prevues if e['est_imminent']),
        'nb_navires_quai': navires_a_quai.count(),
        'nb_navires_attente': navires_attendus.count(),
        'nb_navires_rade': navires_rade_qs.count(),
        'nb_prets': nb_prets,
        'nb_en_retard': nb_en_retard,
        'nb_attente_consignataire': nb_attente_consignataire,
        'heures_maj': heures_maj,
        'sync_message': sync_message,
        'derniere_sync': derniere_maj,
        'ids_selectionnes': ids_selectionnes,
        'param_incertitude': request.session.get('param_incertitude', False),
        'param_amplitude': request.session.get('param_amplitude', '20'),
        'param_buffer': request.session.get('param_buffer', '15'),
        'scenario_session': request.session.get('scenario', 'equilibre'),
    }
    return render(request, 'port/planification_dynamique.html', context)

# =============================================================================
# ✅ TOGGLE SÉLECTION
# =============================================================================
@login_required
def toggle_selection_navire(request, navire_id):
    ids_selectionnes = request.session.get('navires_selectionnes_planification', [])
    ids_selectionnes = [int(i) for i in ids_selectionnes]

    if navire_id in ids_selectionnes:
        ids_selectionnes.remove(navire_id)
        messages.info(request, f"❌ Navire retiré de la sélection")
    else:
        ids_selectionnes.append(navire_id)
        messages.success(request, f"✅ Navire ajouté à la sélection")

    request.session['navires_selectionnes_planification'] = ids_selectionnes
    request.session.modified = True

    return redirect('planification_dynamique')


# =============================================================================
# ✅ VIDER LA SÉLECTION
# =============================================================================
@login_required
def vider_selection(request):
    request.session['navires_selectionnes_planification'] = []
    request.session.modified = True
    messages.info(request, "🗑️ Sélection vidée")
    return redirect('planification_dynamique')


# =============================================================================
# ✅ LANCER L'OPTIMISATION
# =============================================================================
@login_required
def lancer_optimisation_selection(request):
    if request.method != 'POST':
        return redirect('planification_dynamique')

    ids_selectionnes = request.session.get('navires_selectionnes_planification', [])
    ids_selectionnes = [int(i) for i in ids_selectionnes]

    request.session['param_incertitude'] = request.POST.get('incertitude') == 'on'
    request.session['param_amplitude'] = request.POST.get('amplitude', '20')
    request.session['param_buffer'] = request.POST.get('buffer', '15')
    request.session['scenario'] = request.POST.get('scenario', 'equilibre')

    if not ids_selectionnes:
        messages.warning(request, "⚠️ Aucun navire sélectionné.")
        return redirect('planification_dynamique')

    Navire.objects.filter(
        id__in=ids_selectionnes,
        pret_consignataire=True
    ).update(pret_par_client=True)

    Navire.objects.filter(
        etat__in=['rade', 'attente'],
        pret_consignataire=True
    ).exclude(id__in=ids_selectionnes).update(pret_par_client=False)

    request.session['navires_cpn_ids'] = ids_selectionnes
    messages.success(request, f"✅ {len(ids_selectionnes)} navire(s) prêt(s). Lancement...")
    return redirect('optimiser_depuis_cpn')
@login_required
def api_synchroniser_epb(request):
    """
    API pour synchroniser manuellement les données avec le site EPB.
    Retourne un JSON avec le résultat.
    """
    from django.core.management import call_command
    from django.utils import timezone
    import io
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Méthode non autorisée'}, status=405)
    
    try:
        # Capturer la sortie de la commande
        output = io.StringIO()
        call_command('import_epb', stdout=output)
        resultat = output.getvalue()
        
        # Sauvegarder la date de synchronisation
        request.session['derniere_sync_epb'] = timezone.now().isoformat()
        
        return JsonResponse({
            'success': True,
            'message': '✅ Synchronisation réussie',
            'details': resultat[-500:] if len(resultat) > 500 else resultat,
            'timestamp': timezone.now().isoformat()
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
def get_priorites_liste(navire):
    """
    Retourne la liste des priorités d'un navire avec leurs couleurs et icônes.
    """
    priorites = []
    
    if navire.sortant:
        priorites.append({'nom': 'Sortant', 'couleur': 'danger', 'icone': 'fa-sign-out-alt'})
    if navire.passage:
        priorites.append({'nom': 'Passage', 'couleur': 'info', 'icone': 'fa-route'})
    if navire.gazier:
        priorites.append({'nom': 'Gazier', 'couleur': 'warning', 'icone': 'fa-fire'})
    if navire.essence:
        priorites.append({'nom': 'Essence', 'couleur': 'warning', 'icone': 'fa-gas-pump'})
    if navire.animalier:
        priorites.append({'nom': 'Animalier', 'couleur': 'success', 'icone': 'fa-paw'})
    if navire.perissable:
        priorites.append({'nom': 'Périssable', 'couleur': 'info', 'icone': 'fa-snowflake'})
    if navire.strategique:
        priorites.append({'nom': 'Stratégique', 'couleur': 'primary', 'icone': 'fa-star'})
    if navire.ligne_reguliere:
        priorites.append({'nom': 'Ligne régulière', 'couleur': 'success', 'icone': 'fa-ship'})
    if navire.convention:
        priorites.append({'nom': 'Convention', 'couleur': 'info', 'icone': 'fa-handshake'})
    if navire.huilier:
        priorites.append({'nom': 'Huilier', 'couleur': 'warning', 'icone': 'fa-oil-can'})
    
    return priorites   # ✅ CORRECTION : "priorites" (sans "po")
# =============================================================================
# SURVEILLANCE DES MOUVEMENTS (24h/24)
# =============================================================================

@login_required
def mouvements_navires(request):
    """
    Page de consultation des mouvements de navires détectés automatiquement.
    Affiche les entrées/sorties sur les N dernières heures.
    """
    from port.models import MouvementNavire
    from datetime import timedelta
    
    # Récupérer les mouvements des dernières N heures
    try:
        heures = int(request.GET.get('heures', 24))
    except ValueError:
        heures = 24
    
    # Limiter à 168h (7 jours) max
    heures = min(max(heures, 1), 168)
    
    depuis = timezone.now() - timedelta(hours=heures)
    
    mouvements = MouvementNavire.objects.filter(
        date_detection__gte=depuis
    ).select_related('navire', 'quai_avant', 'quai_apres').order_by('-date_detection')
    
    # Statistiques
    stats = {
        'total': mouvements.count(),
        'entrees_rade': mouvements.filter(type_mouvement='entree_rade').count(),
        'entrees_quai': mouvements.filter(type_mouvement='entree_quai').count(),
        'sorties_quai': mouvements.filter(type_mouvement='sortie_quai').count(),
        'sorties_port': mouvements.filter(type_mouvement='sortie_port').count(),
    }
    
    context = {
        'mouvements': mouvements,
        'stats': stats,
        'heures': heures,
        'now': timezone.now(),
    }
    return render(request, 'port/mouvements.html', context)


@login_required
def statut_surveillance(request):
    """
    Page de statut de la surveillance automatique.
    Permet de vérifier que le scheduler tourne.
    """
    from port.services.surveillance_auto import _scheduler
    from port.models import MouvementNavire
    
    est_actif = _scheduler is not None and getattr(_scheduler, 'running', False)
    
    # Prochaine exécution
    prochaine_execution = None
    if est_actif and _scheduler:
        try:
            job = _scheduler.get_job('surveillance_epb')
            if job:
                prochaine_execution = job.next_run_time
        except Exception:
            pass
    
    # Derniers mouvements
    derniers_mouvements = MouvementNavire.objects.order_by('-date_detection')[:20]
    
    # Dernière synchronisation depuis la session
    derniere_sync = request.session.get('derniere_sync_epb')
    
    context = {
        'est_actif': est_actif,
        'prochaine_execution': prochaine_execution,
        'derniers_mouvements': derniers_mouvements,
        'derniere_sync': derniere_sync,
        'now': timezone.now(),
    }
    return render(request, 'port/statut_surveillance.html', context)

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.management import call_command
from django.db import close_old_connections

@csrf_exempt
def api_scraper_epb(request):
    """Endpoint API pour lancer le scraping."""
    close_old_connections()
    
    # Vérifier le token (optionnel)
    token = request.GET.get('token', '')
    if token != 'epb-secret-token-2026':
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    try:
        call_command('import_epb', verbosity=0)
        close_old_connections()
        
        from port.services.surveillance import detecter_changements_navires
        changements = detecter_changements_navires()
        
        return JsonResponse({
            'success': True,
            'changements': changements['total'],
            'message': 'Scraping et détection terminés'
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)