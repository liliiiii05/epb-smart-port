# port/utils_escales.py
"""
Utilitaires pour la gestion des escales des navires.

Ce module contient toutes les fonctions nécessaires pour :
- Créer une nouvelle escale quand un navire revient au port
- Clôturer une escale quand un navire quitte le port
- Archiver les notes d'attente pour l'IA
- Construire le dataset d'entraînement
- Prédire la durée d'attente
"""
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# FONCTIONS UTILITAIRES DE BASE
# =============================================================================

def get_meteo_actuelle():
    """Retourne la météo du jour ou None."""
    from port.models import Meteo
    try:
        return Meteo.objects.get(date=timezone.now().date())
    except Meteo.DoesNotExist:
        return None


def get_shift_actuel(heure=None):
    """
    Retourne le shift actuel ('matin', 'soir', 'nuit', 'double_nuit').
    
    Args:
        heure: heure au format décimal (0-24). Si None, utilise l'heure actuelle.
    
    Returns:
        str: 'matin', 'soir', 'nuit' ou 'double_nuit'
    """
    if heure is None:
        now = timezone.now()
        heure = now.hour + now.minute / 60.0
    
    h = heure % 24
    if 7 <= h < 13:
        return 'matin'
    elif 13 <= h < 19:
        return 'soir'
    elif 19 <= h < 24:
        return 'nuit'
    else:
        return 'double_nuit'


# =============================================================================
# GESTION DES ESCALES
# =============================================================================

@transaction.atomic
def gerer_nouvelle_escale(navire, date_arrivee=None):
    """
    Gère l'arrivée d'un navire au port.
    
    Comportement :
    1. Cherche une escale active pour ce navire.
    2. Si une escale active existe ET date de moins de 24h → la réutilise.
    3. Si une escale active existe ET date de plus de 24h → la clôture.
    4. Crée une nouvelle escale active dans tous les cas où nécessaire.
    5. Archive les notes d'attente de l'ancienne escale.
    
    Args:
        navire: instance de Navire
        date_arrivee: datetime (optionnel, par défaut maintenant)
    
    Returns:
        Escale: la nouvelle escale (ou celle réutilisée)
    """
    from port.models import Escale, NoteAttente
    
    if date_arrivee is None:
        date_arrivee = timezone.now()
    
    # 1. Chercher une escale active existante
    escale_active = Escale.objects.filter(navire=navire, active=True).first()
    
    if escale_active:
        # Vérifier la fraîcheur de l'escale
        ecart_heures = (timezone.now() - escale_active.date_debut).total_seconds() / 3600
        
        if ecart_heures < 24:
            # Escale récente : on la réutilise
            logger.info(
                f"♻️ Escale {escale_active.id} réutilisée pour {navire.nom} "
                f"(créée il y a {ecart_heures:.1f}h)"
            )
            return escale_active
        
        # Escale trop ancienne : on la clôture
        logger.info(
            f"🔒 Clôture de l'escale {escale_active.id} pour {navire.nom} "
            f"(ancienne de {ecart_heures:.1f}h)"
        )
        
        # Calculer les statistiques finales
        notes = NoteAttente.objects.filter(escale=escale_active)
        escale_active.attente_totale = sum(n.duree_attente for n in notes)
        
        if navire.debut_datetime and navire.fin_datetime:
            escale_active.duree_reelle = (
                (navire.fin_datetime - navire.debut_datetime).total_seconds() / 3600
            )
        elif navire.debut_datetime:
            escale_active.duree_reelle = (
                (timezone.now() - navire.debut_datetime).total_seconds() / 3600
            )
        
        if escale_active.duree_reelle > 0 and escale_active.volume_marchandise > 0:
            escale_active.debit_reel = (
                escale_active.volume_marchandise / escale_active.duree_reelle
            )
        
        escale_active.date_fin = timezone.now()
        escale_active.active = False
        escale_active.quai_utilise = navire.quai_attribue
        escale_active.poste_utilise = navire.poste_attribue
        escale_active.save()
        
        # Archiver les notes de l'ancienne escale
        nb_archivees = notes.update(archive=True, prise_en_compte=True)
        logger.info(f"📦 {nb_archivees} notes archivées pour l'escale {escale_active.id}")
    
    # 2. Créer une nouvelle escale
    meteo = get_meteo_actuelle()
    now = timezone.now()
    
    nouvelle_escale = Escale.objects.create(
        navire=navire,
        date_debut=date_arrivee,
        active=True,
        meteo_pluie=meteo.pluie if meteo else False,
        meteo_vent_force=meteo.vent_force if meteo else 0,
        volume_marchandise=navire.marchandise_volume or 0.0,
        agent=navire.agent or '',
        type_navire=navire.type or '',
        shift_debut=get_shift_actuel(now.hour + now.minute / 60.0),
    )
    
    logger.info(f"✅ Nouvelle escale {nouvelle_escale.id} créée pour {navire.nom}")
    return nouvelle_escale


@transaction.atomic
def cloturer_escale(navire, quai_utilise=None, poste_utilise=None):
    """
    Clôture l'escale active d'un navire et archive ses notes.
    
    À appeler quand un navire quitte le port (état = 'termine').
    
    Args:
        navire: instance de Navire
        quai_utilise: Quai (optionnel, prend celui du navire par défaut)
        poste_utilise: Poste (optionnel, prend celui du navire par défaut)
    
    Returns:
        Escale: l'escale clôturée, ou None si aucune escale active
    """
    from port.models import Escale, NoteAttente
    
    escale = Escale.objects.filter(navire=navire, active=True).first()
    if not escale:
        logger.warning(f"⚠️ Aucune escale active pour {navire.nom}")
        return None
    
    # Calculer les statistiques finales
    notes = NoteAttente.objects.filter(escale=escale)
    escale.attente_totale = sum(n.duree_attente for n in notes)
    
    # Durée réelle
    if navire.debut_datetime and navire.fin_datetime:
        escale.duree_reelle = (
            (navire.fin_datetime - navire.debut_datetime).total_seconds() / 3600
        )
    elif navire.debut_datetime:
        escale.duree_reelle = (
            (timezone.now() - navire.debut_datetime).total_seconds() / 3600
        )
    
    # Débit réel
    if escale.duree_reelle > 0 and escale.volume_marchandise > 0:
        escale.debit_reel = escale.volume_marchandise / escale.duree_reelle
    
    # Finaliser
    escale.date_fin = timezone.now()
    escale.active = False
    escale.quai_utilise = quai_utilise or navire.quai_attribue
    escale.poste_utilise = poste_utilise or navire.poste_attribue
    escale.save()
    
    # Archiver les notes
    nb_archivees = notes.update(archive=True, prise_en_compte=True)
    
    logger.info(
        f"✅ Escale {escale.id} clôturée pour {navire.nom} "
        f"(attente: {escale.attente_totale:.1f}h, "
        f"durée: {escale.duree_reelle:.1f}h, "
        f"{nb_archivees} notes archivées)"
    )
    return escale


@transaction.atomic
def creer_escale_pour_navires_actifs():
    """
    Crée une escale active pour chaque navire actif qui n'en a pas.
    
    Utile après une migration ou pour initialiser le système.
    
    Returns:
        int: nombre d'escales créées
    """
    from port.models import Navire, Escale, NoteAttente
    
    navires_actifs = Navire.objects.filter(etat__in=['attente', 'rade', 'quai'])
    nb_crees = 0
    
    for navire in navires_actifs:
        escale = Escale.objects.filter(navire=navire, active=True).first()
        if not escale:
            escale = gerer_nouvelle_escale(navire)
            nb_crees += 1
            logger.info(f"✅ Escale {escale.id} créée pour {navire.nom}")
    
    logger.info(f"📊 Total : {nb_crees} escales créées")
    return nb_crees


@transaction.atomic
def lier_notes_orphelines():
    """
    Lie les notes d'attente sans escale à l'escale active de leur navire.
    
    Utile après une migration pour récupérer les anciennes notes.
    
    Returns:
        int: nombre de notes liées
    """
    from port.models import Navire, Escale, NoteAttente
    
    nb_liees = 0
    notes_orphelines = NoteAttente.objects.filter(escale__isnull=True)
    
    for note in notes_orphelines:
        navire = note.navire
        escale = Escale.objects.filter(navire=navire, active=True).first()
        
        if not escale:
            # Créer une escale si nécessaire
            escale = gerer_nouvelle_escale(navire)
        
        note.escale = escale
        note.save()
        nb_liees += 1
    
    logger.info(f"🔗 {nb_liees} notes orphelines liées à des escales")
    return nb_liees


# =============================================================================
# PRÉDICTION IA
# =============================================================================

def construire_dataset_attentes():
    """
    Construit le dataset pour entraîner un modèle Random Forest
    qui prédit la durée d'attente d'un navire.
    
    Utilise UNIQUEMENT les notes archivées (escales passées).
    
    Returns:
        pandas.DataFrame: dataset avec features + target
    """
    import pandas as pd
    from port.models import NoteAttente
    
    # Récupérer les notes archivées avec relations
    notes = NoteAttente.objects.filter(
        archive=True,
        escale__isnull=False
    ).select_related('navire', 'escale', 'escale__quai_utilise')
    
    data = []
    for note in notes:
        escale = note.escale
        navire = note.navire
        
        if not escale or not navire:
            continue
        
        data.append({
            # ========== FEATURES ==========
            'type_navire': navire.type or '',
            'volume': escale.volume_marchandise or 0,
            'longueur': navire.longueur or 0,
            'tirant': navire.tirant or 0,
            'agent': navire.agent or '',
            'entite': getattr(navire, 'entite', '') or '',
            'shift': note.shift or 'matin',
            'meteo_pluie': int(escale.meteo_pluie),
            'meteo_vent_force': escale.meteo_vent_force or 0,
            'mois': escale.date_debut.month if escale.date_debut else 1,
            'jour_semaine': escale.date_debut.weekday() if escale.date_debut else 0,
            'heure_arrivee': escale.date_debut.hour if escale.date_debut else 0,
            'quai_id': escale.quai_utilise.id if escale.quai_utilise else 0,
            'duree_escale': escale.duree_reelle or 0,
            
            # ========== TARGET ==========
            'duree_attente': note.duree_attente,
        })
    
    df = pd.DataFrame(data)
    logger.info(f"📊 Dataset construit : {len(df)} exemples")
    return df


def predire_attente_navire(navire, modele_rf=None):
    """
    Prédit la durée d'attente pour un navire via Random Forest.
    
    Utilise les données de l'escale ACTIVE.
    
    Args:
        navire: instance de Navire
        modele_rf: modèle Random Forest entraîné (joblib)
    
    Returns:
        float: durée d'attente prédite (heures)
    """
    import pandas as pd
    
    escale = navire.escale_active
    if not escale:
        logger.warning(f"⚠️ Aucune escale active pour {navire.nom}, retour 6h par défaut")
        return 6.0
    
    if modele_rf is None:
        logger.info(f"ℹ️ Aucun modèle RF pour {navire.nom}, retour 6h par défaut")
        return 6.0
    
    now = timezone.now()
    
    # Construire les features
    features_dict = {
        'type_navire': navire.type or '',
        'volume': escale.volume_marchandise or 0,
        'longueur': navire.longueur or 0,
        'tirant': navire.tirant or 0,
        'agent': navire.agent or '',
        'entite': getattr(navire, 'entite', '') or '',
        'shift': get_shift_actuel(now.hour + now.minute / 60.0),
        'meteo_pluie': int(escale.meteo_pluie),
        'meteo_vent_force': escale.meteo_vent_force or 0,
        'mois': now.month,
        'jour_semaine': now.weekday(),
        'heure_arrivee': now.hour,
        'quai_id': 0,
        'duree_escale': 0,
    }
    
    try:
        X = pd.DataFrame([features_dict])
        prediction = modele_rf.predict(X)[0]
        return max(0.0, float(prediction))
    except Exception as e:
        logger.error(f"❌ Erreur prédiction attente pour {navire.nom} : {e}")
        return 6.0


# =============================================================================
# STATISTIQUES
# =============================================================================

def statistiques_escales(navire=None):
    """
    Retourne des statistiques sur les escales.
    
    Args:
        navire: si fourni, limite les stats à ce navire
    
    Returns:
        dict: statistiques
    """
    from port.models import Escale
    from django.db.models import Avg, Sum, Count
    
    qs = Escale.objects.all()
    if navire:
        qs = qs.filter(navire=navire)
    
    stats = qs.aggregate(
        nb_total=Count('id'),
        nb_actives=Count('id', filter=models.Q(active=True)),
        attente_moyenne=Avg('attente_totale'),
        duree_moyenne=Avg('duree_reelle'),
        debit_moyen=Avg('debit_reel'),
    )
    
    return {
        'nb_total': stats['nb_total'] or 0,
        'nb_actives': stats['nb_actives'] or 0,
        'attente_moyenne': round(stats['attente_moyenne'] or 0, 2),
        'duree_moyenne': round(stats['duree_moyenne'] or 0, 2),
        'debit_moyen': round(stats['debit_moyen'] or 0, 2),
    }