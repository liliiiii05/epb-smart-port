def consignataire_context(request):
    is_consignataire = False
    if request.user.is_authenticated:
        is_consignataire = request.user.groups.filter(name='Consignataire').exists()
    return {'is_consignataire': is_consignataire}