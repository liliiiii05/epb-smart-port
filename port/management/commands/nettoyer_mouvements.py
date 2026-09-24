# port/management/commands/nettoyer_mouvements.py
"""
Supprime les mouvements en doublon (même navire + type dans un délai court).

Usage :
    python manage.py nettoyer_mouvements --dry-run      # Test sans modifier
    python manage.py nettoyer_mouvements                # Applique (délai 30 min par défaut)
    python manage.py nettoyer_mouvements --seuil-minutes 15
"""
from django.core.management.base import BaseCommand
from port.models import MouvementNavire


class Command(BaseCommand):
    help = "Nettoie les mouvements en doublon (même navire + type + délai)"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Affiche sans supprimer')
        parser.add_argument('--seuil-minutes', type=int, default=30,
                            help='Délai minimum entre 2 mouvements du même type (défaut: 30 min)')

    def handle(self, *args, **options):
        dry = options['dry_run']
        seuil_min = options['seuil_minutes']
        seuil_sec = seuil_min * 60

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{'='*60}\n"
            f"NETTOYAGE DES MOUVEMENTS EN DOUBLON\n"
            f"Seuil : {seuil_min} minutes\n"
            f"{'='*60}\n"
        ))

        if dry:
            self.stdout.write(self.style.WARNING("🔍 DRY-RUN : aucune suppression\n"))

        total_avant = MouvementNavire.objects.count()
        self.stdout.write(f"📊 Total mouvements actuellement : {total_avant}\n")

        # Trier par navire + type + date
        mouvements = MouvementNavire.objects.order_by(
            'navire_id', 'type_mouvement', 'date_detection'
        )

        a_supprimer = []
        dernier_par_cle = {}  # (navire_id, type) → dernier mouvement gardé

        for m in mouvements:
            cle = (m.navire_id, m.type_mouvement)
            dernier = dernier_par_cle.get(cle)

            if dernier:
                delta = (m.date_detection - dernier.date_detection).total_seconds()
                if delta < seuil_sec:
                    a_supprimer.append(m)
                    if dry:
                        self.stdout.write(
                            f"  [DRY] {m.navire.nom:25s} | {m.type_mouvement:15s} | "
                            f"{m.date_detection.strftime('%d/%m %H:%M')} "
                            f"(+{int(delta/60)}min)"
                        )
                    continue

            dernier_par_cle[cle] = m

        self.stdout.write(f"\n🗑️  Doublons détectés : {len(a_supprimer)}")

        if dry:
            self.stdout.write(self.style.WARNING(
                "\n🔍 DRY-RUN terminé. Relancez sans --dry-run pour appliquer.\n"
            ))
            return

        if a_supprimer:
            ids = [m.id for m in a_supprimer]
            MouvementNavire.objects.filter(id__in=ids).delete()
            total_apres = MouvementNavire.objects.count()
            self.stdout.write(self.style.SUCCESS(
                f"✅ {len(a_supprimer)} mouvements supprimés\n"
                f"📊 Total après nettoyage : {total_apres}\n"
            ))
        else:
            self.stdout.write(self.style.SUCCESS("✅ Aucun doublon détecté\n"))