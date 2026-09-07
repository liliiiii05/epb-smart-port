import subprocess
from datetime import datetime

def generate_all_sql_manual():
    """Génère le SQL pour toutes les migrations de port (liste manuelle)"""
    
    # Liste complète de vos migrations d'après votre showmigrations
    migrations = [
        "0001_initial", "0002_navire_duree_traitement", "0003_navire_convention_speciale_navire_est_passage_and_more",
        "0004_equipement_sessionoptimisation_and_more", "0005_alter_equipement_options_alter_navire_options_and_more",
        "0006_navire_pret_pour_quai", "0007_affectation_equipements_utilises", "0008_affectation_equipements_utilises_ids",
        "0009_affectation_date_debut_reel_and_more", "0010_alter_affectation_attente_and_more", "0011_navire_pret_par_client",
        "0012_equipement_en_panne_equipement_temps_reparation", "0013_snapshotnavire", "0014_alter_snapshotnavire_options_navire_arrivee_datetime",
        "0015_navire_debut_datetime", "0016_quai_performance", "0017_affectation_buffer_debut_affectation_buffer_fin_and_more",
        "0018_navire_coeff_variation_alter_quai_performance", "0019_alter_equipement_id", "0020_affectation_etat_initial",
        "0021_sessionoptimisation_amplitude_pct_and_more", "0022_equipement_panne_debut", "0023_meteo",
        "0024_meteo_vent_direction", "0025_meteo_description_meteo_pluie_meteo_precipitation_and_more",
        "0026_meteo_temperature_alter_meteo_hauteur_houle_and_more", "0027_sessionoptimisation_scenario", "0028_historiqueoperation",
        "0029_alerte", "0030_quai_bloque", "0031_alter_navire_options", "0032_alter_quai_id",
        "0033_alter_equipement_type_mouvement", "0034_alter_alerte_options_alter_equipement_type",
        "0035_equipement_latitude_equipement_longitude_and_more", "0036_navire_coord_x_navire_coord_y_quai_coord_x_and_more",
        "0037_remove_equipement_latitude_and_more", "0038_profile", "0039_creneaureserve", "0040_navire_agent",
        "0041_quai_coeff_manoeuvre", "0042_quai_capacite_max", "0043_quai_type_navire_autorise", "0044_poste",
        "0045_alter_creneaureserve_options_alter_poste_options", "0046_alter_creneaureserve_options_alter_poste_options_and_more",
        "0047_poste_gestion_manuelle", "0048_navire_entite", "0049_equipe_affectationequipe", "0050_affectation_poste",
        "0051_navire_poste_attribue", "0052_navire_fin_datetime", "0053_alter_equipement_options_and_more",
        "0054_alter_equipement_capacite", "0055_alter_equipement_options_and_more", "0056_shift_effectifshift",
        "0057_rename_affectes_effectifshift_effectifs_affectes_and_more", "0058_utilisationequipement",
        "0059_historiqueoperation_debit_reel_and_more", "0060_historiqueoperation_poste",
        "0061_navire_nb_equipes_requises_navire_shift_requis", "0062_historiqueoperation_attente_shift_and_more"
    ]
    
    output_file = 'port_complete_schema.sql'
    
    print(f"📊 Génération du SQL pour {len(migrations)} migrations...")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"-- ============================================\n")
        f.write(f"-- Schema complet pour l'application port\n")
        f.write(f"-- Nombre de migrations: {len(migrations)}\n")
        f.write(f"-- Généré le: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"-- ============================================\n\n")
        
        for i, migration in enumerate(migrations, 1):
            print(f"⚙️  [{i}/{len(migrations)}] Traitement: {migration[:50]}...")
            f.write(f"-- Migration: {migration}\n")
            
            result = subprocess.run(
                ['python', 'manage.py', 'sqlmigrate', 'port', migration],
                capture_output=True,
                text=True
            )
            
            if result.stdout:
                f.write(result.stdout)
            else:
                f.write(f"-- Pas de SQL généré pour cette migration\n")
            
            f.write("\n\n")
    
    print(f"\n✅ SQL généré avec succès dans: {output_file}")

if __name__ == '__main__':
    generate_all_sql_manual()
