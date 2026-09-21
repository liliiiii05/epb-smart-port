@login_required
def mouvements_navires(request):
    """Page de consultation des mouvements de navires détectés automatiquement."""
    from port.models import MouvementNavire
    from port.services.surveillance import get_statistiques_mouvements
    
    # Récupérer les mouvements des dernières 24h
    heures = int(request.GET.get('heures', 24))
    depuis = timezone.now() - timedelta(hours=heures)
    
    mouvements = MouvementNavire.objects.filter(
        date_detection__gte=depuis
    ).select_related('navire', 'quai_avant', 'quai_apres').order_by('-date_detection')
    
    # Statistiques
    stats = get_statistiques_mouvements(heures=heures)
    
    context = {
        'mouvements': mouvements,
        'stats': stats,
        'heures': heures,
        'now': timezone.now(),
    }
    return render(request, 'port/mouvements.html', context)