from django.utils import timezone
from datetime import timedelta
from django.db.models import Q
from .models import Alerte, Navire, Equipement, Affectation

def generer_toutes_alertes():
    print("Génération des alertes...")
    seuil = timezone.now() - timedelta(days=7)
    Alerte.objects.filter(date_resolution__lte=seuil).delete()
    generer_alertes_conflit_quai()
    generer_alertes_manque_equipement()
    generer_alertes_navire_critique()
    print("Génération des alertes terminée")

def generer_alertes_conflit_quai():
    now = timezone.now()
    heure_actuelle = now.hour + now.minute / 60.0
    horizon = now + timedelta(hours=6)
    heure_horizon = horizon.hour + horizon.minute / 60.0
    affectations = Affectation.objects.filter(
        date_creation__date=now.date(),
        heure_debut__isnull=False,
        heure_debut__gte=heure_actuelle,
        heure_debut__lte=heure_horizon
    ).select_related('navire', 'quai')
    for aff in affectations:
        conflit = Navire.objects.filter(
            etat='quai',
            quai_attribue=aff.quai,
            heure_fin__isnull=False,
            heure_fin__gt=aff.heure_debut
        ).exists()
        if conflit:
            msg = f"⚠️ Conflit sur {aff.quai.nom} : {aff.navire.nom} prévu à {aff.heure_debut:.1f}h mais quai occupé."
            Alerte.objects.update_or_create(
                type='conflit_quai',
                message=msg,
                defaults={
                    'niveau': 'danger',
                    'lien': f'/quais/{aff.quai.id}/'
                }
            )

def generer_alertes_manque_equipement():
    mapping = {
        'conteneur': ["grue_gottwald_260e", "reach_stacker", "chariot_32t"],
        'cerealier': ["suceuse_cereales", "convoyeur_bande", "tracteur_remorque_50t"],
        'ferry': ["passerelle_acces", "systeme_amarrage_rapide", "rampe_chargement"],
        'gazier': ["bras_chargement_gnl", "tuyauterie_cryogenique"],
        'frigorifique': ["grue_mobile_50t", "chariot_10t"],
        'betail': ["passerelle_acces", "systeme_ventilation", "abreuvement"],
        'essence': ["bras_chargement_essence", "pompe_anti_deflagrante", "systeme_recuperation_vapeur"],
        'huilier': ["bras_chargement_huile", "pompe_alimentaire", "filtre"],
        'petrolier': ["bras_chargement_petrolier", "pompe_haute_capacite", "systeme_anti_deflagrant"],
        'cargo': ["grue_mobile_50t", "chariot_10t"],
    }
    navires_rade = Navire.objects.filter(etat='rade', a_grue_bord=False)
    for nav in navires_rade:
        necessaires = mapping.get(nav.type, ["grue_mobile_50t", "chariot_10t"])
        manquants = []
        for eq in necessaires:
            try:
                obj = Equipement.objects.get(type=eq)
                if obj.disponibles <= 0:
                    manquants.append(eq)
            except Equipement.DoesNotExist:
                manquants.append(eq)
        if manquants:
            msg = f"🔧 {nav.nom} (type {nav.type}) bloqué : manque {', '.join(manquants)}."
            Alerte.objects.update_or_create(
                type='manque_equipement',
                message=msg,
                defaults={
                    'niveau': 'warning',
                    'lien': f'/navires/{nav.id}/modifier/'
                }
            )

from .email_utils import envoyer_alerte_critique
from django.contrib.auth.models import User

def generer_alertes_navire_critique():
    seuil = timezone.now() - timedelta(hours=12)
    navires = Navire.objects.filter(
        etat='rade',
        arrivee_datetime__isnull=False,
        arrivee_datetime__lte=seuil
    ).filter(Q(strategique=True) | Q(animalier=True) | Q(perissable=True))
    
    for nav in navires:
        duree = (timezone.now() - nav.arrivee_datetime).total_seconds() / 3600
        msg = f"🚨 {nav.nom} ({nav.get_type_display()}) en attente critique depuis {duree:.0f}h."
        alerte, created = Alerte.objects.update_or_create(
            type='navire_critique',
            message=msg,
            defaults={
                'niveau': 'danger',
                'lien': f'/cpn/?navire={nav.id}'
            }
        )
        # Envoi email uniquement si l'alerte vient d'être créée (ou à chaque fois selon besoin)
        if created:
            utilisateurs = User.objects.filter(groups__name__in=['Directeur', 'Officier_port'])
            envoyer_alerte_critique(alerte, utilisateurs)