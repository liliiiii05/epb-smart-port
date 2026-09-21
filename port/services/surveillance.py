# port/services/surveillance.py
"""
Service de surveillance automatique du port.
Détecte les entrées/sorties de navires en comparant les snapshots.
"""
import logging
from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Q

from port.models import Navire, SnapshotNavire, MouvementNavire, Alerte

logger = logging.getLogger(__name__)


def detecter_changements_navires():
    """
    Compare l'état actuel des navires avec l'état précédent.
    Détecte les entrées/sorties et crée des alertes.
    
    Returns:
        dict: Résumé des changements détectés
    """
    maintenant = timezone.now()
    hier = maintenant - timedelta(hours=24)
    
    changements = {
        'entrees_rade': [],
        'entrees_quai': [],
        'sorties_quai': [],
        'sorties_port': [],
        'total': 0
    }
    
    # ========== 1. DÉTECTER LES ENTRÉES EN RADE ==========
    # Navires actuellement en rade mais qui étaient en attente il y a 24h
    navires_rade_actuels = Navire.objects.filter(etat='rade')
    
    for navire in navires_rade_actuels:
        # Vérifier s'il y a un mouvement récent
        mouvement_recent = MouvementNavire.objects.filter(
            navire=navire,
            type_mouvement='entree_rade',
            date_detection__gte=hier
        ).exists()
        
        if not mouvement_recent:
            # Vérifier le snapshot précédent
            snapshot_precedent = SnapshotNavire.objects.filter(
                navire=navire,
                date__lt=maintenant.date()
            ).order_by('-date').first()
            
            if snapshot_precedent and snapshot_precedent.etat == 'attente':
                # Le navire est passé de attente -> rade
                creer_mouvement(
                    navire=navire,
                    type_mouvement='entree_rade',
                    etat_avant='attente',
                    etat_apres='rade',
                    details={'detection': 'automatique'}
                )
                changements['entrees_rade'].append(navire.nom)
                logger.info(f"🚢 ENTRÉE EN RADE: {navire.nom}")
    
    # ========== 2. DÉTECTER LES ENTRÉES À QUAI ==========
    navires_quai_actuels = Navire.objects.filter(etat='quai')
    
    for navire in navires_quai_actuels:
        mouvement_recent = MouvementNavire.objects.filter(
            navire=navire,
            type_mouvement='entree_quai',
            date_detection__gte=hier
        ).exists()
        
        if not mouvement_recent:
            snapshot_precedent = SnapshotNavire.objects.filter(
                navire=navire,
                date__lt=maintenant.date()
            ).order_by('-date').first()
            
            if snapshot_precedent and snapshot_precedent.etat in ['attente', 'rade']:
                creer_mouvement(
                    navire=navire,
                    type_mouvement='entree_quai',
                    etat_avant=snapshot_precedent.etat,
                    etat_apres='quai',
                    quai_apres=navire.quai_attribue,
                    details={'detection': 'automatique'}
                )
                changements['entrees_quai'].append(navire.nom)
                logger.info(f"⚓ ENTRÉE À QUAI: {navire.nom} -> {navire.quai_attribue.nom if navire.quai_attribue else 'N/A'}")
                
                # Créer une alerte
                Alerte.objects.create(
                    message=f"⚓ Le navire {navire.nom} est entré à quai ({navire.quai_attribue.nom if navire.quai_attribue else 'N/A'})",
                    niveau='info',
                    source='Surveillance',
                    est_lue=False,
                    lien=f'/port/navires/{navire.id}/'
                )
    
    # ========== 3. DÉTECTER LES SORTIES DE QUAI ==========
    # Navires qui étaient à quai et qui ne le sont plus
    mouvements_quai_hier = MouvementNavire.objects.filter(
        type_mouvement='entree_quai',
        date_detection__gte=hier - timedelta(hours=24),
        date_detection__lt=hier
    ).values_list('navire_id', flat=True)
    
    for navire_id in mouvements_quai_hier:
        try:
            navire = Navire.objects.get(id=navire_id)
            if navire.etat != 'quai':
                # Vérifier si une sortie n'a pas déjà été enregistrée
                sortie_existe = MouvementNavire.objects.filter(
                    navire=navire,
                    type_mouvement__in=['sortie_quai', 'sortie_port'],
                    date_detection__gte=hier
                ).exists()
                
                if not sortie_existe:
                    creer_mouvement(
                        navire=navire,
                        type_mouvement='sortie_quai' if navire.etat != 'termine' else 'sortie_port',
                        etat_avant='quai',
                        etat_apres=navire.etat,
                        quai_avant=navire.quai_attribue,
                        details={'detection': 'automatique'}
                    )
                    changements['sorties_quai'].append(navire.nom)
                    logger.info(f"🚪 SORTIE DE QUAI: {navire.nom}")
        except Navire.DoesNotExist:
            pass
    
    # ========== 4. DÉTECTER LES SORTIES DU PORT ==========
    # Navires qui étaient actifs il y a 24h et qui sont maintenant terminés
    navires_termines_recents = Navire.objects.filter(
        etat='termine',
        fin_datetime__gte=hier
    )
    
    for navire in navires_termines_recents:
        sortie_existe = MouvementNavire.objects.filter(
            navire=navire,
            type_mouvement='sortie_port',
            date_detection__gte=hier
        ).exists()
        
        if not sortie_existe:
            creer_mouvement(
                navire=navire,
                type_mouvement='sortie_port',
                etat_avant='quai',
                etat_apres='termine',
                details={'detection': 'automatique'}
            )
            changements['sorties_port'].append(navire.nom)
            logger.info(f"🛳️ SORTIE DU PORT: {navire.nom}")
            
            # Créer une alerte
            Alerte.objects.create(
                message=f"🛳️ Le navire {navire.nom} a quitté le port",
                niveau='success',
                source='Surveillance',
                est_lue=False,
                lien=f'/port/navires/{navire.id}/'
            )
    
    changements['total'] = (
        len(changements['entrees_rade']) +
        len(changements['entrees_quai']) +
        len(changements['sorties_quai']) +
        len(changements['sorties_port'])
    )
    
    return changements


def creer_mouvement(navire, type_mouvement, etat_avant='', etat_apres='', 
                    quai_avant=None, quai_apres=None, details=None):
    """Crée un enregistrement de mouvement."""
    return MouvementNavire.objects.create(
        navire=navire,
        type_mouvement=type_mouvement,
        etat_avant=etat_avant,
        etat_apres=etat_apres,
        quai_avant=quai_avant,
        quai_apres=quai_apres,
        details=details or {}
    )


def get_statistiques_mouvements(heures=24):
    """
    Retourne les statistiques des mouvements sur les N dernières heures.
    """
    depuis = timezone.now() - timedelta(hours=heures)
    
    mouvements = MouvementNavire.objects.filter(date_detection__gte=depuis)
    
    return {
        'total': mouvements.count(),
        'entrees_rade': mouvements.filter(type_mouvement='entree_rade').count(),
        'entrees_quai': mouvements.filter(type_mouvement='entree_quai').count(),
        'sorties_quai': mouvements.filter(type_mouvement='sortie_quai').count(),
        'sorties_port': mouvements.filter(type_mouvement='sortie_port').count(),
        'par_navire': list(mouvements.values('navire__nom', 'type_mouvement', 'date_detection').order_by('-date_detection')[:20])
    }