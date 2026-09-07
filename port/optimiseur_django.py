# port/optimiseur_django.py
"""
Optimiseur EPB pour Django - VERSION CORRIGÉE
Connecte l'optimiseur avec les modèles Django
"""

from datetime import datetime
from typing import List, Dict, Any, Optional
from .models import Quai as QuaiModel, Navire as NavireModel, Equipement as EquipementModel
from .models import Affectation, SessionOptimisation
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# ADAPTATEURS POUR CONVERTIR MODÈLES DJANGO → DATACLASSES
# =============================================================================

class AdaptateurDjango:
    """Convertit les modèles Django en dataclasses pour l'optimiseur"""
    
    @classmethod
    def vers_quai_dataclass(cls, quai_model):
        from .optimiseur_epb_pro import Quai as QuaiData
        
        return QuaiData(
            id=quai_model.id,
            nom=quai_model.nom,
            longueur=float(quai_model.longueur),
            profondeur=float(quai_model.profondeur),
            specialite=quai_model.specialite,
            disponible=quai_model.disponible,
            libre=float(quai_model.occupation_jusqua),
            performance=1.0,
            equipements_fixes=[]
        )
    
    @classmethod
    def vers_equipement_dataclass(cls, equip_model):
        from .optimiseur_epb_pro import Equipement as EquipData
        
        return EquipData(
            id=equip_model.id,
            type=equip_model.type,
            capacite=float(equip_model.capacite),
            nombre=equip_model.nombre,
            dispo=equip_model.disponibles,
            en_panne=equip_model.en_panne,
            temps_reparation=equip_model.temps_reparation
        )
    
    @classmethod
    def vers_navire_dataclass(cls, navire_model, coeff_variation=0.15):
        from .optimiseur_epb_pro import (
            Navire as NavireData,
            PrioritesNavire,
            Marchandise,
            EquipementPropre,
            TypeNavire
        )
        from .priorites import calculer_priorite_navire
        
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
        
        type_navire = type_map.get(navire_model.type, TypeNavire.CARGO)
        
        priorites = PrioritesNavire(
            sortant=navire_model.sortant,
            passage=navire_model.passage,
            gazier=navire_model.gazier,
            essence=navire_model.essence,
            animalier=navire_model.animalier,
            perissable=navire_model.perissable,
            strategique=navire_model.strategique,
            ligne_reguliere=navire_model.ligne_reguliere,
            convention=navire_model.convention,
            huilier=navire_model.huilier
        )
        
        marchandise = Marchandise(
            type=navire_model.marchandise_type or "standard",
            volume=float(navire_model.marchandise_volume or 1000),
            dangereux=navire_model.marchandise_dangereuse,
            frigo=navire_model.marchandise_frigo,
            duree_limite=24 if navire_model.perissable else None
        )
        
        equip_propre = EquipementPropre(
            a_grue_bord=navire_model.a_grue_bord,
            capacite=float(navire_model.grue_capacite or 0)
        )
        
        return NavireData(
            id=navire_model.id,
            nom=navire_model.nom,
            type=type_navire,
            longueur=float(navire_model.longueur),
            tirant=float(navire_model.tirant),
            arrivee=float(navire_model.arrivee),
            priorites=priorites,
            marchandise=marchandise,
            equipement_propre=equip_propre,
            priorite_calculee=calculer_priorite_navire(navire_model),
            coeff_variation=coeff_variation
        )

# =============================================================================
# PLANIFICATEUR DJANGO
# =============================================================================

class PlanificateurEPBDjango:
    """Version Django du planificateur"""
    
    def __init__(self, mois=None, incertitude=True, amplitude=0.2, pourcentage_buffer=0.15):
        from .optimiseur_epb_pro import PlanificateurEPB
        self.mois = mois or datetime.now().month
        self.incertitude = incertitude
        self.amplitude = amplitude
        self.pourcentage_buffer = pourcentage_buffer
        self.planificateur = None
        self.logger = logging.getLogger('EPB_Django')
    
    def planifier(self, navires_ids=None):
        from .optimiseur_epb_pro import PlanificateurEPB
        
        try:
            # Récupérer les données depuis Django
            quais_model = list(QuaiModel.objects.all().order_by('id'))
            
            if navires_ids:
                navires_model = list(NavireModel.objects.filter(id__in=navires_ids, etat='attente'))
            else:
                navires_model = list(NavireModel.objects.filter(etat='attente'))
            
            equipements_model = list(EquipementModel.objects.all())
            
            if not navires_model:
                return {'success': False, 'message': 'Aucun navire en attente'}
            
            self.logger.info(f"🚀 Lancement optimisation pour {len(navires_model)} navires")
            
            # Convertir en dataclasses
            quais = [AdaptateurDjango.vers_quai_dataclass(q) for q in quais_model]
            equipements = [AdaptateurDjango.vers_equipement_dataclass(e) for e in equipements_model]
            navires = [AdaptateurDjango.vers_navire_dataclass(n) for n in navires_model]
            
            # Créer le planificateur
            self.planificateur = PlanificateurEPB(
                quais, equipements, mois=self.mois,
                incertitude=self.incertitude,
                amplitude=self.amplitude,
                pourcentage_buffer=self.pourcentage_buffer
            )
            
            # Lancer l'optimisation
            affectations, score_total, attente_totale = self.planificateur.planifier(navires)
            
            if not affectations:
                return {'success': False, 'message': "L'optimisation n'a produit aucune affectation"}
            
            # Créer la session
            session = SessionOptimisation.objects.create(
                nom=f"Planification {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                nb_navires=len(affectations),
                nb_quais=len(quais),
                score_total=float(score_total),
                attente_totale=float(attente_totale),
                attente_moyenne=float(attente_totale / len(affectations)) if affectations else 0,
                taux_occupation=float((len(set(a.quai_id for a in affectations)) / len(quais)) * 100),
                saison='hiver' if self.mois in [11,12,1,2,3] else 'ete'
            )
            
            self.logger.info(f"✅ Session #{session.id} créée")
            
            # Sauvegarder les affectations
            affectations_creees = 0
            for a in affectations:
                try:
                    navire = NavireModel.objects.get(id=a.navire_id)
                    quai = QuaiModel.objects.get(id=a.quai_id)
                    
                    affect = Affectation.objects.create(
                        navire=navire,
                        quai=quai,
                        heure_debut=float(a.heure_accostage),
                        heure_fin=float(a.heure_fin),
                        attente=float(a.attente),
                        traitement=float(a.traitement),
                        score_contribution=float(a.score_contribution),
                        priorites_texte=a.priorites_speciale,
                        utilise_grues_bord=a.utilise_grues_bord,
                        buffer_debut=a.buffer_debut,
                        buffer_fin=a.buffer_fin,
                        heure_debut_reel=a.heure_debut_securise,
                        heure_fin_reel=a.heure_fin_securise,
                        etat_initial=navire.etat,
                        equipements_utilises=", ".join(a.equipements) if a.equipements else ""
                    )
                    
                    # Mettre à jour le navire
                    navire.etat = 'quai'
                    navire.quai_attribue = quai
                    navire.heure_debut = float(a.heure_accostage)
                    navire.heure_fin = float(a.heure_fin)
                    navire.save()
                    
                    # Mettre à jour le quai
                    quai.disponible = False
                    quai.occupation_jusqua = float(a.heure_fin)
                    quai.save()
                    
                    affectations_creees += 1
                    
                except Exception as e:
                    self.logger.error(f"Erreur sauvegarde affectation {a.navire_nom}: {e}")
                    continue
            
            self.logger.info(f"✅ {affectations_creees} affectations sauvegardées")
            
            return {
                'success': True,
                'session': session,
                'nb_planifies': affectations_creees,
                'score_total': float(score_total),
                'attente_totale': float(attente_totale)
            }
            
        except Exception as e:
            self.logger.error(f"❌ Erreur lors de l'optimisation: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'message': str(e)}