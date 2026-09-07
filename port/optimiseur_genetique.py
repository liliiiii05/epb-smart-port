"""
Optimiseur génétique pour la planification des accostages (comparaison avec méthode gloutonne).
Prend en compte les équipements avec normalisation des noms.
"""

import random
from datetime import datetime, timedelta
from typing import List, Tuple
import numpy as np

from .models import Navire, Poste
from .optimiseur_epb_pro import TypeNavire
from .adaptateurs import AdaptateurDonnees
from .views import get_equipements_necessaires_par_type


class PlanificateurGenetique:
    """
    Planificateur utilisant un algorithme génétique.
    Représentation : liste d'affectations (navire_id, poste_id, debut, fin)
    Construit des solutions valides sans conflit de poste ni de matériel.
    """

    def __init__(self, navires_model, postes_model, equipements_model=None, date_reference=None,
                 population_size=30, generations=100,
                 mutation_rate=0.1, crossover_rate=0.8):
        """
        Args:
            navires_model: QuerySet de Navire (modèles Django)
            postes_model: QuerySet de Poste (seuls les postes disponibles)
            equipements_model: QuerySet de Equipement (optionnel, pour la contrainte)
            date_reference: datetime de référence (début de la simulation)
            population_size: nombre d'individus dans la population
            generations: nombre de générations
            mutation_rate: probabilité de mutation (entre 0 et 1)
            crossover_rate: probabilité de croisement
        """
        self.navires_model = list(navires_model)
        self.postes_model = list(postes_model)
        self.equipements_model = equipements_model or []
        self.date_reference = date_reference or datetime.now()
        self.population_size = population_size
        self.generations = generations
        self.mutation_rate = mutation_rate
        self.crossover_rate = crossover_rate

        # Convertir les navires en dataclasses
        self.navires_data = [AdaptateurDonnees.vers_navire(n, coeff_variation=0) for n in self.navires_model]
        self.navires_dict = {nav.id: nav for nav in self.navires_data}
        self.postes_dict = {p.id: p for p in self.postes_model}

        # Pré-calcul des postes compatibles
        self.compat_postes = {}
        for nav in self.navires_data:
            compat = []
            for p in self.postes_model:
                if self._est_compatible(nav, p):
                    compat.append(p.id)
            self.compat_postes[nav.id] = compat

        # Dictionnaire des équipements avec normalisation des noms
        self.equipements_dict = {}
        for eq in self.equipements_model:
            # Nettoyer le nom : supprimer espaces multiples, passage en minuscule
            nom_clean = ' '.join(eq.designation.split()).lower()
            self.equipements_dict[nom_clean] = eq.engins_en_marche

        self.poids_attente = 3.0

    # ==================================================================
    # Règles de compatibilité (réplique du glouton)
    # ==================================================================
    def _est_compatible(self, navire, poste):
        if navire.longueur > poste.longueur or navire.tirant > poste.profondeur:
            return False

        try:
            numero = int(poste.numero)
        except ValueError:
            numero = 0

        type_nav = navire.type.value
        specialite = poste.specialite

        if type_nav == 'cerealier':
            return numero in [15, 16, 17, 21, 23] and specialite in ['cerealier', 'grand']
        if type_nav == 'conteneur':
            agent = getattr(navire, 'agent', '')
            if 'MSC' in agent.upper() and numero != 22:
                return False
            if ('CMA' in agent.upper() or 'CGM' in agent.upper()) and numero != 24:
                return False
            if 'MAERSK' in agent.upper() and numero not in [22, 24]:
                return False
            return numero in [22, 24] and specialite in ['conteneurs', 'grand']
        if type_nav == 'cargo':
            return numero in [11, 14, 18, 19] and specialite in ['general', 'grand']
        if type_nav == 'petrolier':
            return numero in [1, 2, 3] or specialite == 'grand'
        if type_nav == 'gazier':
            return numero in [24, 26] and specialite in ['gazier', 'grand']
        if type_nav == 'huilier':
            return numero in [23, 26] and specialite in ['huiliers', 'gazier', 'grand']
        if type_nav == 'ferry':
            return numero in [8, 12, 13] and specialite in ['ferry', 'general']
        if type_nav == 'essence':
            return numero == 19 and specialite in ['general', 'grand']
        return specialite in ['general', 'grand']

    # ==================================================================
    # Calcul de la durée de traitement
    # ==================================================================
    def _estimer_traitement(self, navire, poste):
        volume = navire.marchandise.volume
        if volume <= 0:
            return 24.0
        taux_par_type = {
            TypeNavire.CEREALIER: 550,
            TypeNavire.CARGO: 400,
            TypeNavire.CONTENEUR: 300,
            TypeNavire.GAZIER: 200,
            TypeNavire.HUILIER: 150,
            TypeNavire.PETROLIER: 400,
            TypeNavire.ESSENCE: 300,
            TypeNavire.FERRY: 100,
        }
        taux = taux_par_type.get(navire.type, 250)
        return max(0.5, volume / taux)

    # ==================================================================
    # Calcul de l'attente
    # ==================================================================
    def _calculer_attente(self, navire, debut):
        if navire.arrivee_datetime:
            arrivee_heure = navire.arrivee_datetime.hour + navire.arrivee_datetime.minute / 60.0
            attente = debut - arrivee_heure
            if attente < 0:
                attente += 24
            today = self.date_reference.date()
            delta_jours = (today - navire.arrivee_datetime.date()).days
            attente += delta_jours * 24
            return max(0, attente)
        else:
            return max(0, debut - navire.arrivee)

    def _arrivee_heure(self, navire):
        if navire.arrivee_datetime:
            return navire.arrivee_datetime.hour + navire.arrivee_datetime.minute / 60.0
        return navire.arrivee

    # ==================================================================
    # Génération d'un individu valide (sans conflit de poste)
    # ==================================================================
    def generer_individu(self) -> List[Tuple]:
        """Génère un planning valide (sans chevauchement sur un même poste)."""
        navires_restants = list(self.navires_data)
        random.shuffle(navires_restants)
        dernier_fin_par_poste = {p.id: 0.0 for p in self.postes_model}
        affectations = []

        for navire in navires_restants:
            compat = self.compat_postes[navire.id]
            if not compat:
                continue
            postes_tries = sorted(compat, key=lambda pid: dernier_fin_par_poste[pid])

            meilleur_debut = None
            meilleur_poste = None
            meilleur_fin = None
            meilleur_score = float('inf')

            for poste_id in postes_tries:
                dernier = dernier_fin_par_poste[poste_id]
                debut = max(self._arrivee_heure(navire), dernier)
                traitement = self._estimer_traitement(navire, self.postes_dict[poste_id])
                fin = debut + traitement
                attente = self._calculer_attente(navire, debut)
                score = traitement + attente * self.poids_attente
                if score < meilleur_score:
                    meilleur_score = score
                    meilleur_debut = debut
                    meilleur_poste = poste_id
                    meilleur_fin = fin

            if meilleur_poste is not None:
                affectations.append((navire.id, meilleur_poste, meilleur_debut, meilleur_fin))
                dernier_fin_par_poste[meilleur_poste] = meilleur_fin

        return affectations

    # ==================================================================
    # Vérification des équipements (simultanéité)
    # ==================================================================
    def _equipements_suffisants(self, affectations):
        """Retourne True si les équipements sont suffisants, False sinon."""
        from collections import defaultdict

        intervals = defaultdict(list)
        for navire_id, poste_id, debut, fin in affectations:
            navire = self.navires_dict[navire_id]
            equip_types = get_equipements_necessaires_par_type(navire.type.value)
            for eq_type in equip_types:
                # Normalisation du nom de l'équipement
                eq_clean = ' '.join(eq_type.split()).lower()
                intervals[eq_clean].append((debut, fin))

        for eq_clean, ivs in intervals.items():
            units = self.equipements_dict.get(eq_clean, 0)
            if units == 0:
                # Équipement inexistant ou insuffisant -> solution invalide
                return False
            ivs.sort()
            max_concurrent = 0
            for i in range(len(ivs)):
                concurrent = 1
                for j in range(i + 1, len(ivs)):
                    if ivs[j][0] < ivs[i][1]:
                        concurrent += 1
                    else:
                        break
                if concurrent > max_concurrent:
                    max_concurrent = concurrent
            if max_concurrent > units:
                return False
        return True

    # ==================================================================
    # Évaluation d'une solution (score)
    # ==================================================================
    def evaluer_solution(self, affectations: List[Tuple]) -> float:
        """Calcule le score total (traitement + 3*attente) + pénalités."""
        if self._detecter_conflits(affectations):
            return 1e6
        if not self._equipements_suffisants(affectations):
            return 1e6

        score = 0.0
        for navire_id, poste_id, debut, fin in affectations:
            navire = self.navires_dict[navire_id]
            attente = self._calculer_attente(navire, debut)
            traitement = fin - debut
            score += traitement + attente * self.poids_attente
        return score

    def _detecter_conflits(self, affectations):
        """Retourne True si deux navires se chevauchent sur le même poste."""
        par_poste = {}
        for _, poste_id, debut, fin in affectations:
            par_poste.setdefault(poste_id, []).append((debut, fin))
        for creneaux in par_poste.values():
            creneaux.sort()
            for i in range(len(creneaux) - 1):
                if creneaux[i][1] > creneaux[i + 1][0]:
                    return True
        return False

    # ==================================================================
    # Opérateurs génétiques
    # ==================================================================
    def croiser(self, parent1, parent2):
        """Croisement à un point (les deux parents ont le même nombre d'affectations)."""
        if random.random() > self.crossover_rate:
            return parent1[:], parent2[:]
        point = random.randint(1, len(parent1) - 1)
        child1 = parent1[:point] + parent2[point:]
        child2 = parent2[:point] + parent1[point:]
        return child1, child2

    def muter(self, individu):
        """Mutation : change le poste ou le début d'un navire aléatoire."""
        if random.random() > self.mutation_rate:
            return individu[:]
        idx = random.randint(0, len(individu) - 1)
        navire_id, poste_id, debut, fin = individu[idx]
        navire = self.navires_dict[navire_id]

        if random.random() < 0.5:
            # Changer de poste
            compat = self.compat_postes[navire_id]
            if compat:
                nouveau_poste = random.choice(compat)
                individu[idx] = (navire_id, nouveau_poste, debut, fin)
        else:
            # Décaler le début (dans une plage raisonnable)
            new_debut = max(0, debut + random.uniform(-12, 12))
            new_fin = new_debut + (fin - debut)
            individu[idx] = (navire_id, poste_id, new_debut, new_fin)
        return individu

    def selection_tournoi(self, population, scores, taille_tournoi=3):
        meilleurs = []
        for _ in range(len(population)):
            participants = random.sample(list(zip(population, scores)), taille_tournoi)
            meilleur = min(participants, key=lambda x: x[1])
            meilleurs.append(meilleur[0])
        return meilleurs

    # ==================================================================
    # Algorithme principal
    # ==================================================================
    def optimiser(self):
        """Exécute l'algorithme génétique et retourne la meilleure solution et son score."""
        # Population initiale
        population = [self.generer_individu() for _ in range(self.population_size)]
        meilleur_score = float('inf')
        meilleure_solution = None
        courbe = []

        for gen in range(self.generations):
            scores = [self.evaluer_solution(ind) for ind in population]
            best_idx = np.argmin(scores)
            if scores[best_idx] < meilleur_score:
                meilleur_score = scores[best_idx]
                meilleure_solution = population[best_idx][:]
                print(f"Gen {gen}: nouveau meilleur score = {meilleur_score:.2f}")

            courbe.append(meilleur_score)

            # Sélection
            population = self.selection_tournoi(population, scores)

            # Croisement et mutation
            nouvelle_pop = []
            for i in range(0, len(population), 2):
                p1 = population[i]
                p2 = population[i + 1] if i + 1 < len(population) else population[0]
                e1, e2 = self.croiser(p1, p2)
                nouvelle_pop.append(self.muter(e1))
                nouvelle_pop.append(self.muter(e2))
            population = nouvelle_pop[:self.population_size]

        return meilleure_solution, meilleur_score, courbe

    # ==================================================================
    # Conversion pour affichage
    # ==================================================================
    def solution_to_affectations(self, solution):
        """Convertit la solution en liste de dict pour exploitation."""
        resultats = []
        for navire_id, poste_id, debut, fin in solution:
            navire = Navire.objects.get(id=navire_id)
            poste = Poste.objects.get(id=poste_id)
            resultats.append({
                'navire_id': navire_id,
                'navire_nom': navire.nom,
                'type_navire': navire.type,
                'poste_id': poste_id,
                'poste_numero': poste.numero,
                'quai_nom': poste.quai.nom,
                'debut': round(debut, 2),
                'fin': round(fin, 2),
                'attente': round(self._calculer_attente(self.navires_dict[navire_id], debut), 2),
                'traitement': round(fin - debut, 2),
            })
        return resultats