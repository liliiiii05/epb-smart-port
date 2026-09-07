from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from .models import Quai, Navire, Equipement, Affectation, SessionOptimisation, Profile, HistoriqueAction, Alerte, Meteo, HistoriqueOperation

# ========== ADMIN POUR QUAI ==========
@admin.register(Quai)
class QuaiAdmin(admin.ModelAdmin):
    list_display = ('id', 'nom', 'longueur', 'profondeur', 'specialite', 'disponible', 'occupation_jusqua')
    list_editable = ('disponible', 'occupation_jusqua')
    list_filter = ('specialite', 'disponible')
    search_fields = ('nom', 'specialite')

# ========== ADMIN POUR NAVIRE ==========
@admin.register(Navire)
class NavireAdmin(admin.ModelAdmin):
    list_display = ('id', 'nom', 'type', 'arrivee', 'etat', 'priorite_calculee', 'strategique', 'gazier')
    list_filter = ('type', 'etat', 'gazier', 'essence', 'animalier', 'strategique')
    search_fields = ('nom',)
    list_editable = ('etat',)

# ========== ADMIN POUR EQUIPEMENT ==========
@admin.register(Equipement)
class EquipementAdmin(admin.ModelAdmin):
    list_display = ('id', 'categorie', 'designation', 'capacite', 'engins_existants', 'engins_en_marche', 'engins_en_panne')
    list_editable = ('engins_en_marche', 'engins_en_panne')
    list_filter = ('categorie',)
    search_fields = ('designation',)

# ========== ADMIN POUR AFFECTATION ==========
@admin.register(Affectation)
class AffectationAdmin(admin.ModelAdmin):
    list_display = ('navire', 'quai', 'get_heure_debut', 'get_heure_fin', 'get_attente', 'get_score', 'date_creation')
    list_filter = ('quai', 'date_creation')
    search_fields = ('navire__nom', 'quai__nom')
    date_hierarchy = 'date_creation'
    
    def get_heure_debut(self, obj):
        return f"{obj.heure_debut:.1f}h"
    get_heure_debut.short_description = "Début"
    
    def get_heure_fin(self, obj):
        return f"{obj.heure_fin:.1f}h"
    get_heure_fin.short_description = "Fin"
    
    def get_attente(self, obj):
        return f"{obj.attente:.1f}h"
    get_attente.short_description = "Attente"
    
    def get_score(self, obj):
        return f"{obj.score_contribution:.1f}"
    get_score.short_description = "Score"

# ========== ADMIN POUR SESSION OPTIMISATION ==========
@admin.register(SessionOptimisation)
class SessionOptimisationAdmin(admin.ModelAdmin):
    list_display = ('nom', 'date_creation', 'nb_navires', 'score_total', 'attente_moyenne', 'taux_occupation', 'saison')
    list_filter = ('saison', 'date_creation')
    search_fields = ('nom',)

# ========== ADMIN POUR PROFIL UTILISATEUR ==========
class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = "Profil EPB"
    fieldsets = (
        (None, {
            'fields': ('matricule', 'date_naissance', 'telephone', 'adresse', 'poste', 'photo', 'notes')
        }),
    )

class CustomUserAdmin(UserAdmin):
    inlines = [ProfileInline]
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_active', 'get_matricule', 'get_telephone', 'date_joined')
    list_filter = ('is_active', 'is_staff', 'groups')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'profile__matricule')
    
    def get_matricule(self, obj):
        return obj.profile.matricule if hasattr(obj, 'profile') else '-'
    get_matricule.short_description = 'Matricule'
    
    def get_telephone(self, obj):
        return obj.profile.telephone if hasattr(obj, 'profile') else '-'
    get_telephone.short_description = 'Téléphone'

# Désenregistrer l'admin par défaut et enregistrer le personnalisé
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)

# ========== ADMIN POUR PROFILE (direct) ==========
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'matricule', 'telephone', 'date_naissance', 'derniere_activite')
    search_fields = ('user__username', 'user__email', 'matricule', 'telephone')
    list_filter = ('date_naissance',)

# ========== ADMIN POUR HISTORIQUE ACTION ==========
@admin.register(HistoriqueAction)
class HistoriqueActionAdmin(admin.ModelAdmin):
    list_display = ('date_action', 'utilisateur', 'type_action', 'description', 'navire', 'quai')
    list_filter = ('type_action', 'date_action')
    search_fields = ('description', 'utilisateur__username', 'navire__nom')
    readonly_fields = ('date_action',)

# ========== ADMIN POUR ALERTE ==========
@admin.register(Alerte)
class AlerteAdmin(admin.ModelAdmin):
    list_display = ('date_creation', 'type', 'niveau', 'message', 'est_lue')
    list_filter = ('type', 'niveau', 'est_lue', 'date_creation')
    search_fields = ('message',)

# ========== ADMIN POUR METEO ==========
@admin.register(Meteo)
class MeteoAdmin(admin.ModelAdmin):
    list_display = ('date', 'vent_force', 'pluie', 'temperature', 'restrictions')
    list_filter = ('date', 'pluie')
    search_fields = ('date',)

# ========== ADMIN POUR HISTORIQUE OPERATION ==========
@admin.register(HistoriqueOperation)
class HistoriqueOperationAdmin(admin.ModelAdmin):
    list_display = ('navire_type', 'quai_id', 'duree_estimee', 'duree_reelle', 'date_operation')
    list_filter = ('navire_type', 'date_operation')
    search_fields = ('navire_type',)
from django.contrib import admin
from .models import Shift, EffectifShift

@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ('nom', 'heure_debut', 'heure_fin', 'ordre')
    list_editable = ('heure_debut', 'heure_fin', 'ordre')

@admin.register(EffectifShift)
class EffectifShiftAdmin(admin.ModelAdmin):
    list_display = ('shift', 'metier', 'effectifs_affectes', 'effectifs_presents')
    list_editable = ('effectifs_affectes', 'effectifs_presents')
    list_filter = ('shift',)