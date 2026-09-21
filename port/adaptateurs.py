# adaptateurs.py
from datetime import datetime
from django.utils import timezone
from .models import Navire as NavireModel, Quai as QuaiModel, Equipement as EquipementModel, Poste as PosteModel
from .optimiseur_epb_pro import (
    Navire as NavireData, Quai as QuaiData, Equipement as EquipementData,
    PrioritesNavire, Marchandise, EquipementPropre, TypeNavire
)
from .priorites import calculer_priorite_navire


class AdaptateurDonnees:
    """Convertit les modèles Django en dataclasses pour l'optimiseur"""

    @staticmethod
    def vers_quai(quai: QuaiModel) -> QuaiData:
        """Convertit un Quai Django en dataclass Quai"""
        return QuaiData(
            id=quai.id,
            nom=quai.nom,
            longueur=float(quai.longueur),
            profondeur=float(quai.profondeur),
            specialite=quai.specialite,
            disponible=quai.disponible,
            libre=float(quai.occupation_jusqua),
            performance=quai.performance,
            equipements_fixes=[],
            coeff_manoeuvre=getattr(quai, 'coeff_manoeuvre', 1.0),
        )

    @staticmethod
    def vers_quai_depuis_poste(poste: PosteModel) -> QuaiData:
        """Convertit un Poste (avec son Quai parent) en dataclass Quai pour l'optimiseur"""
        quai_parent = poste.quai
        return QuaiData(
            id=poste.id,  # on utilise l'id du poste comme identifiant unique
            nom=f"{quai_parent.nom} - Poste {poste.numero}",
            longueur=float(poste.longueur),
            profondeur=float(poste.profondeur),
            specialite=poste.specialite,
            disponible=poste.disponible,
            libre=float(poste.occupation_jusqua),
            performance=quai_parent.performance,
            equipements_fixes=[],
            coeff_manoeuvre=getattr(quai_parent, 'coeff_manoeuvre', 1.0),
            poste_numero=int(poste.numero) if str(poste.numero).isdigit() else 0,
        )

    @staticmethod
    def vers_equipement(equip: EquipementModel) -> EquipementData:
        """Convertit un Equipement Django en dataclass Equipement pour l'optimiseur"""
        
        try:
            capacite_val = float(equip.capacite) if equip.capacite else 0.0
        except ValueError:
            capacite_val = 0.0        

        # IMPORTANT: Utiliser designation pour correspondre au mapping
        return EquipementData(
            id=equip.id,
            type=equip.designation,  # ← Utiliser designation, pas categorie !
            capacite=capacite_val,
            nombre=equip.engins_existants,
            dispo=equip.engins_en_marche,
            en_panne=(equip.engins_en_panne > 0),
            temps_reparation=equip.temps_reparation,
            panne_debut=None,
        )

    @staticmethod
    def vers_navire(navire: NavireModel, coeff_variation: float = 0.15) -> NavireData:
        """Convertit un Navire Django en dataclass Navire pour l'optimiseur"""
        
        # ========== MAPPING DES TYPES ==========
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
            'roulier': TypeNavire.ROULIER,
            'chimiquier': TypeNavire.CHIMIQUIER,
        }
        type_navire = type_map.get(navire.type, TypeNavire.CARGO)

        # ========== PRIORITÉS (CRUCIAL pour les règles EPB) ==========
        priorites = PrioritesNavire(
            sortant=navire.sortant,
            passage=navire.passage,
            gazier=navire.gazier,
            essence=navire.essence,
            animalier=navire.animalier,
            perissable=navire.perissable,
            strategique=navire.strategique,
            ligne_reguliere=navire.ligne_reguliere,
            convention=navire.convention,
            huilier=navire.huilier,
        )

        # ========== IMPORTANCE DE LA MARCHANDISE ==========
        importance = 0
        if navire.marchandise_dangereuse:
            importance += 50
        if navire.marchandise_frigo:
            importance += 30
        if (navire.marchandise_volume or 0) > 10000:
            importance += 20
        if navire.strategique:
            importance += 50
        if navire.perissable:
            importance += 25

        # ========== MARCHANDISE ==========
        marchandise = Marchandise(
            type=navire.marchandise_type or "standard",
            volume=float(navire.marchandise_volume or 1000),
            dangereux=navire.marchandise_dangereuse,
            frigo=navire.marchandise_frigo,
            duree_limite=24 if navire.perissable else None,
            importance=importance,
        )

        # ========== ÉQUIPEMENT PROPRE ==========
        equip_propre = EquipementPropre(
            a_grue_bord=navire.a_grue_bord,
            capacite=float(navire.grue_capacite or 0),
        )

        # ========== ✅ HEURE D'ARRIVÉE ABSOLUE ==========
        # CORRECTION CRITIQUE : l'optimiseur utilise navire.arrivee pour :
        #   - Vérifier les shifts (ferry 7h-19h, céréalier pas 1h-7h)
        #   - Calculer l'attente (debut - arrivee)
        # Il faut donc une heure ABSOLUE (0-24), pas relative.
        if navire.arrivee_datetime:
            arrivee_heures = navire.arrivee_datetime.hour + navire.arrivee_datetime.minute / 60.0
        else:
            arrivee_heures = float(navire.arrivee or 0)

        # ========== HEURE DE FIN PRÉVUE (pour navires à quai) ==========
        fin_prevue = None
        if navire.etat == 'quai' and navire.heure_fin is not None:
            fin_prevue = navire.heure_fin

        # ========== CRÉATION DU NAVIRE DATACLASS ==========
        return NavireData(
            id=navire.id,
            nom=navire.nom,
            type=type_navire,
            longueur=float(navire.longueur),
            tirant=float(navire.tirant),
            arrivee=arrivee_heures,
            priorites=priorites,
            marchandise=marchandise,
            equipement_propre=equip_propre,
            priorite_calculee=calculer_priorite_navire(navire),
            coeff_variation=coeff_variation,
            arrivee_datetime=navire.arrivee_datetime,
            fin_prevue=fin_prevue,
            agent=navire.agent or "",
            entite=navire.entite or "",
            est_en_rade=(navire.etat == 'rade'),
            nb_equipes_requises=getattr(navire, 'nb_equipes_requises', 1),
            shift_requis=getattr(navire, 'shift_requis', 'matin'),
        )