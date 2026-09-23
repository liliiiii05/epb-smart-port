from django.urls import path
from . import views
from port.views import recalculer_affectations_avec_bon_taux


urlpatterns = [
    # ==================== PAGE D'ACCUEIL ====================
    path('', views.redirection_apres_connexion, name='accueil'),
    path('dashboard/', views.index, name='dashboard'),

    # ==================== NAVIRES ====================
    path('navires/', views.liste_navires, name='liste_navires'),
    path('navires/ajouter/', views.ajouter_navire, name='ajouter_navire'),
    path('navires/<int:navire_id>/', views.detail_navire, name='detail_navire'),
    path('navires/<int:navire_id>/modifier/', views.modifier_navire, name='modifier_navire'),
    path('navires/<int:navire_id>/supprimer/', views.supprimer_navire, name='supprimer_navire'),

    # ==================== HISTORIQUE DES ESCALES ====================
    path('navires/<int:navire_id>/historique-escales/', 
         views.historique_escales_navire, 
         name='historique_escales_navire'),
    path('navires/<int:navire_id>/cloturer-escale/', 
         views.cloturer_escale_manuelle, 
         name='cloturer_escale_manuelle'),

    # ==================== QUAIS ====================
    path('quais/', views.liste_quais, name='liste_quais'),
    path('quais/ajouter/', views.ajouter_quai, name='ajouter_quai'),
    path('quais/<int:quai_id>/', views.detail_quai, name='detail_quai'),
    path('quais/<int:quai_id>/modifier/', views.modifier_quai, name='modifier_quai'),
    path('quais/<int:quai_id>/supprimer/', views.supprimer_quai, name='supprimer_quai'),

    # ==================== POSTES ====================
    path('postes/ajouter/', views.ajouter_poste, name='ajouter_poste'),
    path('modifier-poste/', views.modifier_poste, name='modifier_poste'),
    path('liberer-poste/<int:poste_id>/', views.liberer_poste, name='liberer_poste'),

    # ==================== ÉQUIPEMENTS ====================
    path('equipements/', views.liste_equipements, name='liste_equipements'),
    path('equipements/ajouter/', views.ajouter_equipement, name='ajouter_equipement'),
    path('equipements/<int:equipement_id>/modifier/', views.modifier_equipement, name='modifier_equipement'),
    path('equipements/<int:equipement_id>/supprimer/', views.supprimer_equipement, name='supprimer_equipement'),
    path('equipement/<int:equipement_id>/toggle-panne/', views.basculer_panne_equipement, name='toggle_panne'),
    path('equipement/<int:equipement_id>/declare-panne/', views.declarer_panne, name='declarer_panne'),
    path('equipement/<int:equipement_id>/repare/', views.reparer_equipement, name='reparer_equipement'),
    path('planifier-equipements/', views.planifier_equipements, name='planifier_equipements'),

    # ==================== PRIORITÉS ====================
    path('priorites/', views.grille_priorites, name='priorites'),

    # ==================== PLANIFICATION ====================
    path('planifier/', views.lancer_planification, name='planification'),
    path('resultats/<int:session_id>/', views.resultats_planification, name='resultats_planification'),
    path('exporter/<int:session_id>/', views.exporter_planification_csv, name='exporter_csv'),
    path('exporter-pdf/<int:session_id>/', views.exporter_pdf, name='exporter_pdf'),

    # ==================== CPN ====================
    path('cpn/', views.cpn, name='cpn'),
    path('optimiser-depuis-cpn/', views.optimiser_depuis_cpn, name='optimiser_depuis_cpn'),
    path('valider-planification/', views.valider_planification, name='valider_planification'),

    # ==================== ACTIONS OFFICIER RADIO ====================
    path('valider-rade/', views.valider_arrivee_rade, name='valider_rade'),
    path('terminer-navires/', views.terminer_navires_confirm, name='terminer_navires_confirm'),
    path('terminer-navires/execute/', views.terminer_navires_execute, name='terminer_navires_execute'),
    path('mise-a-jour-rade/', views.mise_a_jour_rade, name='mise_a_jour_rade'),

    # ==================== NOTES D'ATTENTE ====================
    path('ajouter-note-attente/', views.ajouter_note_attente, name='ajouter_note_attente'),
    path('ajax/ajouter-note-attente/', views.ajouter_note_attente_ajax, name='ajouter_note_attente_ajax'),
    path('ajax/supprimer-note-attente/<int:note_id>/', views.supprimer_note_attente, name='supprimer_note_attente'),
    path('replanifier-avec-notes/', views.replanifier_avec_notes, name='replanifier_avec_notes'),

    # ==================== MODE MANUEL ====================
    path('mode-manuel/', views.mode_manuel, name='mode_manuel'),
    path('mode-manuel/deplacer/<int:navire_id>/', views.deplacer_navire, name='deplacer_navire'),
    path('mode-manuel/bloquer-quai/<int:quai_id>/', views.basculer_blocage_quai, name='basculer_blocage_quai'),
    path('mode-manuel/bloquer-poste/<int:poste_id>/', views.basculer_blocage_poste, name='basculer_blocage_poste'),
    path('mode-manuel/changer-poste/<int:navire_id>/', views.changer_poste_navire, name='changer_poste_navire'),
    path('mode-manuel/forcer-priorite/<int:navire_id>/', views.forcer_priorite, name='forcer_priorite'),
    path('affecter-poste-manuel/', views.affecter_poste_manuel, name='affecter_poste_manuel'),

    # ==================== EFFECTIFS SHIFTS ====================
    path('effectifs-shifts/', views.effectifs_shifts, name='effectifs_shifts'),

    # ==================== MÉTÉO ====================
    path('meteo/', views.modifier_meteo, name='modifier_meteo'),
    path('actualiser-meteo/', views.actualiser_meteo, name='actualiser_meteo'),

    # ==================== STATISTIQUES ====================
    path('statistiques/', views.statistiques, name='statistiques'),

    # ==================== UTILISATEURS ====================
    path('gestion-utilisateurs/', views.gestion_utilisateurs, name='gestion_utilisateurs'),
    path('ajouter-utilisateur/', views.ajouter_utilisateur, name='ajouter_utilisateur'),
    path('modifier-utilisateur/<int:user_id>/', views.modifier_utilisateur, name='modifier_utilisateur'),
    path('supprimer-utilisateur/<int:user_id>/', views.supprimer_utilisateur, name='supprimer_utilisateur'),
    path('utilisateur/<int:user_id>/activer/', views.activer_utilisateur, name='activer_utilisateur'),
    path('utilisateur/<int:user_id>/desactiver/', views.desactiver_utilisateur, name='desactiver_utilisateur'),

    # ==================== CARTE ====================
    path('carte/', views.carte_schematique, name='carte_schematique'),
    path('api/carte-data/', views.api_carte_data, name='api_carte_data'),

    # ==================== ALERTES & NOTIFICATIONS (officier/directeur) ====================
    path('api/notifications/', views.api_notifications, name='api_notifications'),
    path('api/alerte/lire/<int:alerte_id>/', views.marquer_alerte_lue, name='marquer_alerte_lue'),
    path('api/alerte/supprimer/<int:alerte_id>/', views.supprimer_alerte, name='supprimer_alerte'),
    path('api/notifications/mark-all-read/', views.marquer_toutes_alertes_lues, name='mark_all_read'),
    path('alertes/', views.liste_alertes, name='liste_alertes'),

    # ==================== CONSIGNATAIRE ====================
    path('consignataire/', views.consignataire_dashboard, name='consignataire_dashboard'),
    path('consignataire/notifications/api/', views.api_notifications_consignataire, name='api_notifications_consignataire'),
    path('consignataire/notification/marquer-lu/<int:pk>/', views.marquer_notification_lue, name='marquer_notification_lue'),
    path('consignataire/notification/supprimer/<int:pk>/', views.supprimer_notification, name='supprimer_notification'),
    path('consignataire/notifications/marquer-tout-lu/', views.marquer_toutes_lues, name='marquer_toutes_lues_consignataire'),

    # ==================== API STATISTIQUES ====================
    path('api/stats/attentes/', views.api_stats_attentes, name='api_attentes'),
    path('api/stats/attentes-evolution/', views.api_stats_attentes_evolution, name='api_attentes_evolution'),
    path('api/stats/sessions/', views.api_stats_sessions, name='api_sessions'),
    path('api/stats/occupation/', views.api_stats_occupation, name='api_occupation'),
    path('api/stats/occupation-quais/', views.api_stats_occupation_quais, name='api_stats_occupation_quais'),
    path('api/stats/dashboard/', views.api_stats_dashboard, name='api_dashboard'),
    path('api/stats/equipements-sollicites/', views.api_stats_equipements_sollicites, name='api_equipements_sollicites'),

    # ==================== API GANTT ====================
    path('api/gantt/<int:session_id>/', views.api_gantt_data, name='api_gantt'),
    path('api/gantt-poste/<int:session_id>/', views.api_gantt_postes, name='api_gantt_poste'),

    # ==================== HISTORIQUE DES ACTIONS ====================
    path('historique/', views.historique_actions, name='historique_actions'),

    # ==================== SYNCHRONISATION EPB ====================
    path('synchroniser-epb/', views.synchroniser_epb, name='synchroniser_epb'),
    path('planification-dynamique/', views.planification_dynamique, name='planification_dynamique'),
    path('planification-dynamique/toggle/<int:navire_id>/', views.toggle_selection_navire, name='toggle_selection_navire'),
    path('planification-dynamique/vider/', views.vider_selection, name='vider_selection'),
    path('planification-dynamique/lancer/', views.lancer_optimisation_selection, name='lancer_optimisation_selection'),

    # ==================== RECALCUL ====================
    # ==================== PLANIFICATION DYNAMIQUE ====================
    # ==================== POSTES ====================
    path('postes/ajouter/', views.ajouter_poste, name='ajouter_poste'),
    path('modifier-poste/', views.modifier_poste, name='modifier_poste'),
    path('basculer-statut-poste/<int:poste_id>/', views.basculer_statut_poste, name='basculer_statut_poste'),  # ← NOUVEAU
    path('liberer-poste/<int:poste_id>/', views.liberer_poste, name='liberer_poste'),
    path('mouvements/', views.mouvements_navires, name='mouvements_navires'),
    path('api/scraper/', views.api_scraper_epb, name='api_scraper_epb'),
    path('statut-surveillance/', views.statut_surveillance, name='statut_surveillance'),
    path('planification-dynamique/', views.planification_dynamique, name='planification_dynamique'),
    path('planification-dynamique/toggle/<int:navire_id>/', views.toggle_selection_navire, name='toggle_selection_navire'),
    path('planification-dynamique/vider/', views.vider_selection, name='vider_selection'),
    path('planification-dynamique/lancer/', views.lancer_optimisation_selection, name='lancer_optimisation_selection'),
    path('api/synchroniser-epb/', views.api_synchroniser_epb, name='api_synchroniser_epb'),
    path('planification-dynamique/', views.planification_dynamique, name='planification_dynamique'),
    path('recalculer-affectations/', recalculer_affectations_avec_bon_taux, name='recalculer_affectations'),
    path('recalculer-affectations/<int:navire_id>/', recalculer_affectations_avec_bon_taux, name='recalculer_affectations_navire'),
]