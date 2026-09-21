from django.db import models
from django.utils import timezone
from datetime import datetime, timedelta
from django.contrib.auth.models import User


# =============================================================================
# QUAI
# =============================================================================
class Quai(models.Model):
    id = models.AutoField(primary_key=True)
    nom = models.CharField(max_length=50)
    longueur = models.FloatField(help_text="Longueur en mètres")
    profondeur = models.FloatField(help_text="Profondeur en mètres")
    specialite = models.CharField(max_length=50)
    disponible = models.BooleanField(default=True)
    occupation_jusqua = models.FloatField(default=0.0, help_text="Heure de libération")
    performance = models.FloatField(default=1.0, help_text="Coefficient multiplicateur de cadence")
    bloque = models.BooleanField(default=False, help_text="Quai bloqué manuellement (indisponible)")
    coord_x = models.FloatField(null=True, blank=True, help_text="Coordonnée X sur le plan")
    coord_y = models.FloatField(null=True, blank=True, help_text="Coordonnée Y sur le plan")
    coeff_manoeuvre = models.FloatField(default=1.0, help_text="Coefficient multiplicateur du temps de manœuvre")
    capacite_max = models.FloatField(default=0, help_text="Capacité maximale d'accueil en tonnes (0 = illimitée)")
    type_navire_autorise = models.CharField(max_length=200, blank=True, help_text="Types de navires autorisés")

    def __str__(self):
        return f"{self.nom} ({self.longueur}m, {self.profondeur}m)"


# =============================================================================
# ÉQUIPEMENT
# =============================================================================
class Equipement(models.Model):
    CATEGORIE_CHOICES = [
        ('engin', 'Engins (chariots, tracteurs, pelles, chargeurs)'),
        ('grue', 'Grues et portiques'),
    ]

    categorie = models.CharField(max_length=50, blank=True, help_text="Catégorie fonctionnelle")
    designation = models.CharField(max_length=100)
    capacite = models.CharField(max_length=100, blank=True, verbose_name="Capacité / Type")
    engins_existants = models.PositiveIntegerField(default=0, verbose_name="Engins existants")
    engins_en_marche = models.PositiveIntegerField(default=0, verbose_name="Engins en marche")
    engins_en_panne = models.PositiveIntegerField(default=0, verbose_name="Engins en panne")
    temps_reparation = models.FloatField(default=2.0, verbose_name="Temps réparation (h)")
    famille = models.CharField(max_length=50, blank=True, help_text="Famille d'équipement")

    class Meta:
        unique_together = ('categorie', 'designation', 'capacite')

    def __str__(self):
        return f"{self.designation} ({self.capacite})"


# =============================================================================
# SHIFT
# =============================================================================
class Shift(models.Model):
    nom = models.CharField(max_length=20, unique=True)
    heure_debut = models.TimeField()
    heure_fin = models.TimeField()
    ordre = models.PositiveSmallIntegerField(default=0)

    def __str__(self):
        return self.nom

    class Meta:
        ordering = ['ordre']


class EffectifShift(models.Model):
    shift = models.ForeignKey(Shift, on_delete=models.CASCADE, related_name='effectifs')
    metier = models.CharField(max_length=30)
    effectifs_affectes = models.PositiveIntegerField(default=0)
    effectifs_presents = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('shift', 'metier')

    def __str__(self):
        return f"{self.shift.nom} - {self.metier}: {self.effectifs_presents}/{self.effectifs_affectes}"


# =============================================================================
# UTILISATION ÉQUIPEMENT
# =============================================================================
class UtilisationEquipement(models.Model):
    navire = models.ForeignKey('Navire', on_delete=models.CASCADE)
    equipement_type = models.CharField(max_length=50)
    unite_index = models.PositiveSmallIntegerField()
    quai = models.ForeignKey('Quai', on_delete=models.CASCADE)
    debut = models.DateTimeField()
    fin = models.DateTimeField()
    conflit = models.BooleanField(default=False)
    attente_navire = models.FloatField(default=0)
    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.navire.nom} - {self.equipement_type} unité {self.unite_index}"


# =============================================================================
# ESCALE (défini AVANT Navire et NoteAttente pour les FK)
# =============================================================================
class Escale(models.Model):
    """Représente une escale d'un navire au port (peut être multiple pour un même navire)."""
    navire = models.ForeignKey('Navire', on_delete=models.CASCADE, related_name='escales')
    date_debut = models.DateTimeField(auto_now_add=True)
    date_fin = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True, help_text="True si l'escale est en cours")

    # Statistiques de l'escale (pour l'IA)
    attente_totale = models.FloatField(default=0.0, help_text="Attente cumulée (h)")
    traitement_total = models.FloatField(default=0.0, help_text="Traitement total (h)")
    quai_utilise = models.ForeignKey(
        'Quai', on_delete=models.SET_NULL, null=True, blank=True, related_name='escales_utilisees'
    )
    poste_utilise = models.ForeignKey(
        'Poste', on_delete=models.SET_NULL, null=True, blank=True, related_name='escales_utilisees'
    )

    # Contexte météo (pour l'IA)
    meteo_pluie = models.BooleanField(default=False)
    meteo_vent_force = models.IntegerField(default=0)

    # Données pour l'IA
    volume_marchandise = models.FloatField(default=0.0)
    duree_reelle = models.FloatField(default=0.0, help_text="Durée réelle totale (h)")
    debit_reel = models.FloatField(default=0.0, help_text="Débit réel (t/h)")
    agent = models.CharField(max_length=100, blank=True)
    type_navire = models.CharField(max_length=20, blank=True)
    shift_debut = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ['-date_debut']
        verbose_name = "Escale"
        verbose_name_plural = "Escales"
        indexes = [
            models.Index(fields=['navire', 'active']),
            models.Index(fields=['date_debut']),
        ]

    def __str__(self):
        statut = "🟢 Active" if self.active else "⚫ Clôturée"
        return f"{statut} - {self.navire.nom} ({self.date_debut.strftime('%d/%m/%Y')})"

    @property
    def duree_sejour(self):
        """Durée totale de l'escale en heures."""
        fin = self.date_fin or timezone.now()
        return (fin - self.date_debut).total_seconds() / 3600.0

    @property
    def nb_notes_attente(self):
        """Nombre de notes d'attente de cette escale."""
        return self.notes_attente.count()


# =============================================================================
# NAVIRE
# =============================================================================
class Navire(models.Model):
    TYPE_CHOICES = [
        ('conteneur', 'Conteneur'),
        ('cerealier', 'Céréalier'),
        ('ferry', 'Ferry'),
        ('gazier', 'Gazier'),
        ('frigorifique', 'Frigorifique'),
        ('betail', 'Bétail'),
        ('essence', 'Essence'),
        ('huilier', 'Huilier'),
        ('petrolier', 'Pétrolier'),
        ('cargo', 'Cargo'),
    ]

    ETAT_CHOICES = [
        ('attente', '⏳ En attente'),
        ('rade', '⚓ En rade'),
        ('quai', '🚢 À quai'),
        ('termine', '✅ Terminé'),
    ]
    ENTITE_CHOICES = [
        ('EPB', 'EPB'),
        ('BMT', 'BMT'),
        ('CEVITAL', 'Cevital/COGB'),
        ('NAFTAL', 'NAFTAL'),
        ('STH', 'STH'),
        ('OAIC', 'OAIC'),
    ]

    nom = models.CharField(max_length=100)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    longueur = models.FloatField(help_text="Longueur en mètres")
    tirant = models.FloatField(help_text="Tirant d'eau en mètres")
    arrivee = models.FloatField(help_text="Heure d'arrivée (format décimal)")
    arrivee_datetime = models.DateTimeField(null=True, blank=True, help_text="Date et heure réelle d'arrivée en rade")
    heure_debut = models.FloatField(null=True, blank=True, help_text="Heure de début d'accostage")
    debut_datetime = models.DateTimeField(null=True, blank=True, help_text="Date et heure réelle de début à quai")
    heure_fin = models.FloatField(null=True, blank=True, help_text="Heure de fin d'accostage")
    coord_x = models.FloatField(null=True, blank=True, help_text="Position X sur le plan")
    coord_y = models.FloatField(null=True, blank=True, help_text="Position Y sur le plan")

    # Priorités
    sortant = models.BooleanField(default=False, help_text="Navire sortant")
    passage = models.BooleanField(default=False, help_text="Navire de passage")
    gazier = models.BooleanField(default=False, help_text="Gazier")
    essence = models.BooleanField(default=False, help_text="Caboteur essence")
    animalier = models.BooleanField(default=False, help_text="Animalier")
    perissable = models.BooleanField(default=False, help_text="Denrées périssables")
    strategique = models.BooleanField(default=False, help_text="Produit stratégique")
    ligne_reguliere = models.BooleanField(default=False, help_text="Ligne régulière (ferry)")
    convention = models.BooleanField(default=False, help_text="Convention spéciale")
    huilier = models.BooleanField(default=False, help_text="Huilier")

    # Marchandise
    marchandise_type = models.CharField(max_length=200, blank=True)
    marchandise_volume = models.FloatField(default=0)
    marchandise_dangereuse = models.BooleanField(default=False)
    marchandise_frigo = models.BooleanField(default=False)

    # Équipement propre
    a_grue_bord = models.BooleanField(default=False, help_text="Navire équipé de ses propres grues")
    grue_capacite = models.FloatField(default=0, help_text="Capacité des grues de bord (tonnes)")

    # Prêt pour affectation
    pret_pour_quai = models.BooleanField(default=True, help_text="Navire prêt pour affectation")
    pret_par_client = models.BooleanField(default=False, help_text="Le client a confirmé que le navire est prêt")

    # État
    etat = models.CharField(max_length=20, choices=ETAT_CHOICES, default='attente')
    quai_attribue = models.ForeignKey(Quai, on_delete=models.SET_NULL, null=True, blank=True)
    priorite_calculee = models.FloatField(default=0)
    agent = models.CharField(max_length=200, blank=True, verbose_name="Agent / Consignataire")
    entite = models.CharField(max_length=200, blank=True, verbose_name="Entité exploitante")
    coeff_variation = models.FloatField(default=0.15, help_text="Coefficient de variation pour la durée")
    poste_attribue = models.ForeignKey(
        'Poste', on_delete=models.SET_NULL, null=True, blank=True, related_name='navires'
    )
    fin_datetime = models.DateTimeField(null=True, blank=True)

    nb_equipes_requises = models.PositiveSmallIntegerField(default=1, verbose_name="Nombre d'équipes nécessaires")
    shift_requis = models.CharField(
        max_length=10,
        default='matin',
        choices=[('matin', 'Matin'), ('soir', 'Soir'), ('nuit', 'Nuit')],
        verbose_name="Shift requis"
    )
    pret_consignataire = models.BooleanField(default=False, verbose_name="Prêt pour le port")
    etat_precedent = models.CharField(max_length=20, blank=True, null=True)
    temps_arret_pluie = models.FloatField(default=0.0)

    # ========== PROPRIÉTÉS DE FORMATAGE ==========
    @property
    def heure_accostage_formatee(self):
        """Retourne l'heure d'accostage formatée HH:MM pour les navires à quai"""
        if self.etat == 'quai' and self.heure_debut is not None:
            heures = int(self.heure_debut)
            minutes = int((self.heure_debut - heures) * 60)
            return f"{heures:02d}:{minutes:02d}"
        return None

    @property
    def heure_arrivee_formatee(self):
        """Retourne l'heure d'arrivée formatée HH:MM"""
        if self.arrivee is not None and self.arrivee > 0:
            heures = int(self.arrivee)
            minutes = int((self.arrivee - heures) * 60)
            return f"{heures:02d}:{minutes:02d}"
        return None

    # ========== PROPRIÉTÉS LIÉES AUX ESCALES ==========
    @property
    def escale_active(self):
        """Retourne l'escale en cours du navire (ou None)."""
        return self.escales.filter(active=True).first()

    @property
    def notes_attente_actives(self):
        """Retourne uniquement les notes de l'escale en cours."""
        from port.models import NoteAttente  # Import local pour éviter les cycles
        escale = self.escale_active
        if escale:
            return NoteAttente.objects.filter(escale=escale, archive=False)
        return NoteAttente.objects.none()

    @property
    def attente_totale_actuelle(self):
        """Somme des notes d'attente de l'escale en cours."""
        return sum(n.duree_attente for n in self.notes_attente_actives)

    @property
    def historique_escales(self):
        """Toutes les escales passées (non actives)."""
        return self.escales.filter(active=False).order_by('-date_debut')

    @property
    def attente_moyenne_historique(self):
        """Attente moyenne sur toutes les escales passées."""
        escales = self.historique_escales
        if not escales.exists():
            return 0.0
        total = sum(e.attente_totale for e in escales)
        return total / escales.count()

    @property
    def nb_escales(self):
        """Nombre total d'escales."""
        return self.escales.count()

    # ========== AUTRES PROPRIÉTÉS ==========
    @property
    def progression(self):
        if self.etat != 'quai' or not self.debut_datetime or self.heure_fin is None:
            return 0
        now = timezone.now()
        fin = self.debut_datetime + timedelta(hours=self.heure_fin - self.heure_debut)
        if now <= self.debut_datetime:
            return 0
        if now >= fin:
            return 100
        total = (fin - self.debut_datetime).total_seconds()
        ecoule = (now - self.debut_datetime).total_seconds()
        return int((ecoule / total) * 100)

    @property
    def temps_attente_rade(self):
        if self.etat != 'rade' or not self.arrivee_datetime:
            return 0
        now = timezone.now()
        return (now - self.arrivee_datetime).total_seconds() / 3600

    @property
    def heure_fin_datetime(self):
        if not self.debut_datetime or self.heure_fin is None:
            return None
        return self.debut_datetime + timedelta(hours=self.heure_fin - self.heure_debut)

    class Meta:
        permissions = [
            ("can_manage_cpn", "Peut gérer la CPN"),
            ("can_optimize", "Peut lancer l'optimisation"),
            ("can_export", "Peut exporter les plannings"),
            ("can_finish_ships", "Peut terminer des navires"),
            ("can_validate_arrival", "Peut valider l'arrivée en rade"),
            ("can_execute_decision", "Peut exécuter une décision"),
            ("can_edit_ship", "Peut modifier un navire"),
            ("can_load_announcements", "Peut charger les annonces"),
            ("can_manage_users", "Peut gérer les utilisateurs"),
            ("can_view_user_logs", "Peut consulter l'historique des tâches"),
        ]

    def __str__(self):
        return f"{self.nom} - {self.get_type_display()}"

    def get_equipements_necessaires(self):
        """Retourne la liste des équipements nécessaires pour ce navire"""
        if self.a_grue_bord:
            return []
        from port.views import get_equipements_necessaires_par_type
        return get_equipements_necessaires_par_type(self.type)

    def get_arrivee_datetime(self):
        if self.arrivee_datetime:
            return self.arrivee_datetime
        if self.arrivee is not None and self.arrivee > 0:
            dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=self.arrivee)
            if dt > datetime.now():
                dt -= timedelta(days=1)
            return dt
        return None

    def get_heure_debut_datetime(self):
        if self.debut_datetime:
            return self.debut_datetime
        if self.heure_debut is not None:
            dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=self.heure_debut)
            if dt > datetime.now():
                dt -= timedelta(days=1)
            return dt
        return None


# =============================================================================
# AFFECTATION
# =============================================================================
class Affectation(models.Model):
    navire = models.ForeignKey('Navire', on_delete=models.CASCADE)
    quai = models.ForeignKey('Quai', on_delete=models.CASCADE)
    heure_debut = models.FloatField(verbose_name="Début")
    heure_fin = models.FloatField(verbose_name="Fin")
    attente = models.FloatField(help_text="Temps d'attente en heures", verbose_name="Attente")
    traitement = models.FloatField(help_text="Temps de traitement en heures", verbose_name="Traitement")
    score_contribution = models.FloatField(verbose_name="Score")
    priorites_texte = models.CharField(max_length=200, blank=True, verbose_name="Priorités")
    equipements = models.CharField(max_length=200, blank=True, help_text="IDs des équipements utilisés")
    utilise_grues_bord = models.BooleanField(default=False, verbose_name="Grues de bord")
    date_creation = models.DateTimeField(default=timezone.now, verbose_name="Date création")
    equipements_utilises = models.TextField(blank=True, help_text="Liste des équipements utilisés")
    equipements_utilises_ids = models.CharField(max_length=500, blank=True, help_text="IDs des équipements utilisés")
    date_debut_reel = models.DateTimeField(null=True, blank=True, verbose_name="Date début réelle")
    date_fin_reel = models.DateTimeField(null=True, blank=True, verbose_name="Date fin réelle")

    buffer_debut = models.FloatField(default=0, verbose_name="Buffer début (h)")
    buffer_fin = models.FloatField(default=0, verbose_name="Buffer fin (h)")
    heure_debut_reel = models.FloatField(null=True, blank=True, verbose_name="Début réel (avec buffer)")
    heure_fin_reel = models.FloatField(null=True, blank=True, verbose_name="Fin réelle (avec buffer)")

    etat_initial = models.CharField(
        max_length=20, choices=Navire.ETAT_CHOICES, null=True, blank=True, verbose_name="État initial"
    )
    poste = models.ForeignKey('Poste', on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.navire.nom} → {self.quai.nom}"

    def get_debut_datetime(self, date_reference=None):
        if self.date_debut_reel:
            return self.date_debut_reel
        if date_reference is None:
            date_reference = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return date_reference + timedelta(hours=self.heure_debut)

    def get_fin_datetime(self, date_reference=None):
        if self.date_fin_reel:
            return self.date_fin_reel
        if date_reference is None:
            date_reference = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return date_reference + timedelta(hours=self.heure_fin)


# =============================================================================
# SESSION OPTIMISATION
# =============================================================================
class SessionOptimisation(models.Model):
    nom = models.CharField(max_length=100)
    date_creation = models.DateTimeField(default=timezone.now)
    nb_navires = models.IntegerField()
    nb_quais = models.IntegerField()
    score_total = models.FloatField()
    attente_totale = models.FloatField()
    attente_moyenne = models.FloatField()
    taux_occupation = models.FloatField()
    saison = models.CharField(max_length=10, choices=[('hiver', 'Hiver'), ('ete', 'Été')])
    fichier_csv = models.CharField(max_length=200, blank=True)

    incertitude_utilisee = models.BooleanField(default=False, verbose_name="Incertitude activée")
    amplitude_pct = models.FloatField(default=20, verbose_name="Amplitude (%)")
    buffer_pct = models.FloatField(default=15, verbose_name="Buffer (%)")

    scenario = models.CharField(
        max_length=20,
        default='equilibre',
        choices=[
            ('rapide', 'Rapide'),
            ('equilibre', 'Équilibré'),
            ('securise', 'Sécurisé'),
        ],
        verbose_name="Scénario d'optimisation"
    )

    def __str__(self):
        return f"{self.nom} - {self.date_creation.strftime('%d/%m/%Y %H:%M')}"


# =============================================================================
# SNAPSHOT NAVIRE
# =============================================================================
class SnapshotNavire(models.Model):
    date = models.DateField()
    navire = models.ForeignKey(Navire, on_delete=models.CASCADE)
    etat = models.CharField(max_length=20, choices=Navire.ETAT_CHOICES)
    arrivee = models.FloatField()
    quai_attribue = models.ForeignKey(Quai, on_delete=models.SET_NULL, null=True, blank=True)
    heure_debut = models.FloatField(null=True, blank=True)
    heure_fin = models.FloatField(null=True, blank=True)

    class Meta:
        unique_together = ('date', 'navire')


# =============================================================================
# MÉTÉO
# =============================================================================
class Meteo(models.Model):
    date = models.DateField(unique=True)
    vent_force = models.IntegerField(default=0, help_text="Force du vent (Beaufort)")
    vent_direction = models.CharField(max_length=10, blank=True)
    hauteur_houle = models.FloatField(default=0, help_text="Hauteur de la houle en mètres")
    pluie = models.BooleanField(default=False, help_text="Pluie en cours")
    precipitation = models.FloatField(default=0, help_text="Précipitations (mm/h)")
    temperature = models.FloatField(default=20, help_text="Température (°C)")
    description = models.CharField(max_length=100, blank=True)
    restrictions = models.TextField(blank=True, help_text="Quais interdits (séparés par virgules)")
    updated_at = models.DateTimeField(auto_now=True)
    pluie_active = models.BooleanField(default=False)
    pluie_debut_reelle = models.DateTimeField(null=True, blank=True)
    pluie_debut_prevue = models.DateTimeField(null=True, blank=True)
    pluie_fin_prevue = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Météo du {self.date} – vent {self.vent_force} Bft, pluie: {'oui' if self.pluie else 'non'}"


# =============================================================================
# HISTORIQUE OPÉRATION
# =============================================================================
class HistoriqueOperation(models.Model):
    navire_type = models.CharField(max_length=20)
    quai_id = models.IntegerField()
    volume = models.FloatField()
    duree_estimee = models.FloatField(help_text="Durée estimée avant traitement (heures)")
    duree_reelle = models.FloatField(help_text="Durée réelle observée (heures)")
    date_operation = models.DateTimeField(auto_now_add=True)
    nb_equipes = models.PositiveSmallIntegerField(default=1)
    shift = models.CharField(
        max_length=12,
        blank=True,
        null=True,
        choices=[('matin', 'Matin'), ('soir', 'Soir'), ('nuit', 'Nuit'), ('double_nuit', 'Double nuit')]
    )
    tonnage_shift = models.FloatField(default=0.0)
    attente_shift = models.FloatField(default=0.0)
    debit_shift = models.FloatField(default=0.0)
    nb_equipements_utilises = models.PositiveSmallIntegerField(default=1)
    equipements_utilises = models.TextField(blank=True)
    debit_reel = models.FloatField(default=0.0, help_text="Tonnage par heure réel")
    poste = models.ForeignKey('Poste', on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['navire_type', 'quai_id']),
        ]

    def __str__(self):
        return f"{self.navire_type} sur quai {self.quai_id} : estimé {self.duree_estimee}h, réel {self.duree_reelle}h"


# =============================================================================
# ALERTE
# =============================================================================
class Alerte(models.Model):
    NIVEAUX = [
        ('info', 'ℹ️ Information'),
        ('warning', '⚠️ Attention'),
        ('danger', '🔴 Critique'),
    ]
    TYPES = [
        ('conflit_quai', 'Conflit de quai'),
        ('manque_equipement', 'Manque d\'équipement'),
        ('navire_critique', 'Navire critique en attente'),
        ('retard', 'Retard important'),
        ('meteo', 'Condition météo dangereuse'),
    ]

    type = models.CharField(max_length=30, choices=TYPES)
    niveau = models.CharField(max_length=10, choices=NIVEAUX, default='warning')
    message = models.TextField()
    lien = models.CharField(max_length=200, blank=True, help_text="URL pour résoudre l'alerte")
    est_lue = models.BooleanField(default=False)
    date_creation = models.DateTimeField(default=timezone.now)
    date_resolution = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=50, default='Système')

    def __str__(self):
        return f"[{self.get_niveau_display()}] {self.message[:50]}"


# =============================================================================
# MOUVEMENT
# =============================================================================
class Mouvement(models.Model):
    navire = models.ForeignKey('Navire', on_delete=models.CASCADE)
    ancien_quai = models.ForeignKey('Quai', on_delete=models.CASCADE, related_name='+')
    nouveau_quai = models.ForeignKey('Quai', on_delete=models.CASCADE, related_name='+')
    heure_prevue = models.FloatField(help_text="Heure à laquelle effectuer le mouvement")
    raison = models.CharField(max_length=200, blank=True)
    utilisateur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    statut = models.CharField(max_length=20, default='prevue', choices=[('prevue', 'Prévue'), ('executee', 'Exécutée')])
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date_creation']

    def __str__(self):
        return f"{self.navire.nom} → {self.nouveau_quai.nom} ({self.statut})"


# =============================================================================
# HISTORIQUE ACTION
# =============================================================================
class HistoriqueAction(models.Model):
    TYPES_ACTION = [
        ('affectation', 'Affectation de navire'),
        ('deplacement', 'Déplacement manuel'),
        ('priorite', 'Forçage de priorité'),
        ('blocage_quai', 'Blocage/Déblocage de quai'),
        ('terminaison', 'Terminaison de navire'),
        ('modification', 'Modification (CRUD)'),
        ('arrivee_rade', 'Validation arrivée rade'),
        ('affectation_manuelle', 'Affectation manuelle'),
    ]

    utilisateur = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    type_action = models.CharField(max_length=30, choices=TYPES_ACTION)
    description = models.TextField()
    date_action = models.DateTimeField(default=timezone.now)
    navire = models.ForeignKey('Navire', on_delete=models.SET_NULL, null=True, blank=True)
    quai = models.ForeignKey('Quai', on_delete=models.SET_NULL, null=True, blank=True)
    equipement = models.ForeignKey('Equipement', on_delete=models.SET_NULL, null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-date_action']
        verbose_name = "Historique d'action"
        verbose_name_plural = "Historiques des actions"

    def __str__(self):
        return f"{self.date_action.strftime('%d/%m/%Y %H:%M')} - {self.get_type_action_display()}"


# =============================================================================
# PROFILE
# =============================================================================
class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    matricule = models.CharField(max_length=20, unique=True, blank=True, null=True, help_text="Matricule EPB")
    date_naissance = models.DateField(null=True, blank=True, verbose_name="Date de naissance")
    telephone = models.CharField(max_length=20, blank=True, verbose_name="Téléphone")
    adresse = models.TextField(blank=True, verbose_name="Adresse")
    poste = models.CharField(max_length=100, blank=True, verbose_name="Poste / Fonction")
    photo = models.ImageField(upload_to='profiles/', blank=True, null=True, verbose_name="Photo")
    derniere_activite = models.DateTimeField(auto_now=True, verbose_name="Dernière activité")
    notes = models.TextField(blank=True, verbose_name="Notes internes")

    def __str__(self):
        return f"Profil de {self.user.username}"


from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)


# =============================================================================
# CRÉNEAU RÉSERVÉ
# =============================================================================
class CreneauReserve(models.Model):
    OPERATEURS = [
        ('MSC', 'MSC'),
        ('CMA_CGM', 'CMA CGM'),
        ('MAERSK', 'Maersk'),
    ]
    operateur = models.CharField(max_length=20, choices=OPERATEURS)
    quai = models.ForeignKey('Quai', on_delete=models.CASCADE)
    poste = models.ForeignKey(
        'Poste',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Poste spécifique (optionnel)"
    )
    date_debut = models.DateTimeField()
    date_fin = models.DateTimeField()
    duree_jours = models.IntegerField(default=4)
    actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Créneau réservé"
        verbose_name_plural = "Créneaux réservés"

    def __str__(self):
        return f"{self.operateur} sur {self.quai.nom} du {self.date_debut} au {self.date_fin}"


# =============================================================================
# POSTE
# =============================================================================
class Poste(models.Model):
    quai = models.ForeignKey('Quai', on_delete=models.CASCADE, related_name='postes')
    numero = models.CharField(max_length=10, help_text="Numéro du poste")
    longueur = models.FloatField(help_text="Longueur en mètres")
    profondeur = models.FloatField(help_text="Profondeur en mètres")
    specialite = models.CharField(max_length=50, blank=True)
    type_navire_autorise = models.CharField(max_length=200, blank=True)
    disponible = models.BooleanField(default=True)
    occupation_jusqua = models.FloatField(default=0.0)
    coord_x = models.FloatField(null=True, blank=True)
    coord_y = models.FloatField(null=True, blank=True)
    gestion_manuelle = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.quai.nom} - Poste {self.numero}"


# =============================================================================
# ÉQUIPE
# =============================================================================
class Equipe(models.Model):
    nom = models.CharField(max_length=100)
    shifts_couverts = models.CharField(max_length=100, help_text="Ex: 07h-13h,13h-19h")
    repos_min_heures = models.FloatField(default=8.0)
    max_heures_par_jour = models.FloatField(default=12.0)
    debut_journee = models.FloatField(default=7.0)
    disponible = models.BooleanField(default=True)

    def __str__(self):
        return self.nom

    def get_shifts_list(self):
        return [s.strip() for s in self.shifts_couverts.split(',')]


class AffectationEquipe(models.Model):
    equipe = models.ForeignKey(Equipe, on_delete=models.CASCADE)
    navire = models.ForeignKey(Navire, on_delete=models.CASCADE)
    shift = models.CharField(max_length=20)
    date_debut = models.DateTimeField()
    date_fin = models.DateTimeField()
    duree_heures = models.FloatField()
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('equipe', 'navire', 'shift', 'date_debut')


# =============================================================================
# NOTE ATTENTE (lié à une escale)
# =============================================================================
class NoteAttente(models.Model):
    SHIFT_CHOICES = [
        ('matin', 'Matin'),
        ('soir', 'Soir'),
        ('nuit', 'Nuit'),
        ('double_nuit', 'Double nuit'),
    ]

    navire = models.ForeignKey('Navire', on_delete=models.CASCADE)
    escale = models.ForeignKey(
        Escale,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notes_attente',
        help_text="Escale associée (None = ancienne note héritée)"
    )
    shift = models.CharField(max_length=20, choices=SHIFT_CHOICES, blank=True, null=True)
    duree_attente = models.FloatField()
    commentaire = models.TextField(blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    prise_en_compte = models.BooleanField(default=False)
    archive = models.BooleanField(default=False, help_text="True si l'escale est terminée (utilisée pour l'IA)")

    class Meta:
        ordering = ['-date_creation']
        indexes = [
            models.Index(fields=['navire', 'escale']),
            models.Index(fields=['archive']),
        ]

    def __str__(self):
        escale_id = self.escale.id if self.escale else "N/A"
        return f"{self.navire.nom} - {self.duree_attente}h (escale {escale_id})"


# =============================================================================
# AFFECTATION QUAI (pour l'IA)
# =============================================================================
class AffectationQuai(models.Model):
    navire = models.ForeignKey('Navire', on_delete=models.CASCADE)
    quai = models.ForeignKey('Quai', on_delete=models.CASCADE)
    poste = models.ForeignKey('Poste', on_delete=models.CASCADE, null=True)
    type_navire = models.CharField(max_length=20)
    volume = models.FloatField()
    longueur = models.FloatField()
    tirant = models.FloatField()
    agent = models.CharField(max_length=200, blank=True)
    entite = models.CharField(max_length=200, blank=True)
    shift_debut = models.CharField(max_length=10, blank=True)
    date_affectation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.navire.nom} → {self.quai.nom}"


# =============================================================================
# NOTIFICATION CONSIGNATAIRE
# =============================================================================
class NotificationConsignataire(models.Model):
    TYPES = (
        ('info', 'Information'),
        ('warning', 'Alerte'),
        ('success', 'Succès'),
        ('danger', 'Urgent'),
    )
    consignataire = models.ForeignKey(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    navire = models.ForeignKey('Navire', on_delete=models.CASCADE)
    message = models.CharField(max_length=255)
    type = models.CharField(max_length=10, choices=TYPES, default='info')
    est_lue = models.BooleanField(default=False)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date_creation']

    def __str__(self):
        return f"[{self.get_type_display()}] {self.message[:50]}"
class MouvementNavire(models.Model):
    """
    Trace les mouvements des navires détectés automatiquement.
    Permet de savoir quand un navire entre/sort du port.
    """
    TYPE_MOUVEMENT = [
        ('entree_rade', 'Entrée en rade'),
        ('entree_quai', 'Entrée à quai'),
        ('sortie_quai', 'Sortie du quai'),
        ('sortie_port', 'Sortie du port'),
        ('changement_etat', 'Changement d\'état'),
    ]
    
    navire = models.ForeignKey(Navire, on_delete=models.CASCADE, related_name='mouvements')
    type_mouvement = models.CharField(max_length=20, choices=TYPE_MOUVEMENT)
    etat_avant = models.CharField(max_length=20, blank=True)
    etat_apres = models.CharField(max_length=20, blank=True)
    quai_avant = models.ForeignKey(Quai, on_delete=models.SET_NULL, null=True, blank=True, related_name='mouvements_sortie')
    quai_apres = models.ForeignKey(Quai, on_delete=models.SET_NULL, null=True, blank=True, related_name='mouvements_entree')
    date_detection = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=50, default='scraping_auto')
    details = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-date_detection']
        verbose_name = "Mouvement de navire"
        verbose_name_plural = "Mouvements de navires"
    
    def __str__(self):
        return f"{self.navire.nom} - {self.get_type_mouvement_display()} - {self.date_detection.strftime('%d/%m %H:%M')}"