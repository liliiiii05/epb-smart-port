import logging
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

def envoyer_email_destinataires(sujet, message_html, destinataires):
    """Envoie un email HTML à une liste d'adresses email."""
    if not destinataires:
        return
    try:
        message_texte = strip_tags(message_html)
        email = EmailMultiAlternatives(
            subject=sujet,                     # important : 'subject' pas 'sujet'
            body=message_texte,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=destinataires,
        )
        email.attach_alternative(message_html, "text/html")
        email.send(fail_silently=False)
        logger.info(f"Email envoye a {', '.join(destinataires)} : {sujet}")  # sans emoji
    except Exception as e:
        logger.error(f"❌ Erreur envoi email: {e}")
def envoyer_alerte_critique(alerte, utilisateurs):
    """Envoie une alerte critique par email aux utilisateurs."""
    destinataires = [u.email for u in utilisateurs if u.email]
    if not destinataires:
        return
    sujet = f"[EPB Smart - ALERTE] {alerte.message[:80]}"
    contexte = {
        'alerte': alerte,
        'url_alertes': f"{settings.BASE_URL}/alertes/",
    }
    try:
        html = render_to_string('port/emails/alerte.html', contexte)
    except Exception:
        html = f"<p>{alerte.message}</p><p><a href='{settings.BASE_URL}/alertes/'>Voir les alertes</a></p>"
    envoyer_email_destinataires(sujet, html, destinataires)
def envoyer_notification_affectation(navire, quai, heure_debut, utilisateurs, session_id=None):
    """
    Envoie une notification d'affectation aux utilisateurs (liste d'objets User).
    Optionnellement, inclut un lien vers la session d'optimisation.
    """
    destinataires = [u.email for u in utilisateurs if u.email]
    if not destinataires:
        return

    sujet = f"[EPB Smart]  Affectation du navire {navire.nom}"
    
    # Construction de l'URL de planning (si session_id fourni)
    if session_id:
        url_planning = f"{settings.BASE_URL}/resultats_planification/{session_id}/"
    else:
        url_planning = settings.BASE_URL

    contexte = {
        'navire': navire,
        'quai': quai,
        'heure_debut': heure_debut,
        'url_planning': url_planning,
    }
    
    try:
        html = render_to_string('port/emails/affectation.html', contexte)
    except Exception as e:
        logger.error(f"Erreur rendu template email: {e}")
        # Fallback : envoyer un email texte simple
        html = f"<p>Bonjour,</p><p>Le navire {navire.nom} a été affecté au {quai.nom} à {heure_debut}h.</p>"

    envoyer_email_destinataires(sujet, html, destinataires)