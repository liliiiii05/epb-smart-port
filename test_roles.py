import sys
from django.conf import settings
from django.contrib.auth.models import User, Group, Permission
from django.test import Client
from django.urls import reverse

settings.ALLOWED_HOSTS = ['testserver', '127.0.0.1', 'localhost']

users_data = [
    ('officier_port', 'Officier_port', 'Benhaddad123'),
    ('officier_radio', 'Officier_radio', 'radio123'),
    ('gestionnaire', 'Gestionnaire_escales', 'gest123'),
    ('directeur', 'Directeur', 'dir123'),
]

tests = [
    ('cpn', ['Officier_port', 'Directeur'], 'GET', None),
    ('optimiser_depuis_cpn', ['Officier_port', 'Directeur'], 'GET', None),
    ('valider_planification', ['Officier_port', 'Directeur'], 'GET', None),
    ('resultats_planification', ['Officier_port', 'Directeur'], 'GET', {'session_id': 1}),
    ('exporter_csv', ['Officier_port', 'Directeur'], 'GET', {'session_id': 1}),
    ('terminer_navires_confirm', ['Officier_port', 'Directeur'], 'GET', None),
    ('valider_rade', ['Officier_radio', 'Directeur'], 'GET', None),
    ('mode_manuel', ['Officier_radio', 'Directeur'], 'GET', None),
    ('deplacer_navire', ['Officier_radio', 'Directeur'], 'GET', {'navire_id': 1}),
    ('gestion_utilisateurs', ['Directeur'], 'GET', None),
    ('modifier_navire', ['Gestionnaire_escales', 'Directeur'], 'GET', {'navire_id': 1}),
    ('liste_navires', [], 'GET', None),
]

client = Client()
for username, group_name, password in users_data:
    print(f"\n{'='*60}")
    print(f"🔐 Test avec {username} (groupe {group_name})")
    print(f"{'='*60}")
    logged = client.login(username=username, password=password)
    print(f"Connexion réussie : {logged}")
    if not logged:
        print(f"  ⚠️ Échec de connexion – vérifiez le mot de passe")
        continue

    for url_name, allowed_groups, method, kwargs in tests:
        try:
            if kwargs:
                url = reverse(url_name, kwargs=kwargs)
            else:
                url = reverse(url_name)
        except Exception as e:
            print(f"  ⚠️ URL {url_name} non trouvée : {e}")
            continue
        response = client.get(url) if method == 'GET' else client.post(url)
        allowed = (group_name in allowed_groups) or (allowed_groups == [])
        if allowed:
            if response.status_code == 200:
                print(f"  ✅ {url_name} -> 200 (autorisé)")
            else:
                print(f"  ❌ {url_name} -> {response.status_code} (devrait être 200)")
        else:
            if response.status_code in [302, 403]:
                print(f"  ✅ {url_name} -> {response.status_code} (bloqué)")
            else:
                print(f"  ❌ {url_name} -> {response.status_code} (devrait être 302/403)")
    client.logout()

print("\n" + "="*60)
print("📋 Vérification des permissions via has_perm()")
print("="*60)

expected_perms = {
    'Officier_port': ['can_manage_cpn', 'can_optimize', 'can_export', 'can_finish_ships'],
    'Officier_radio': ['can_validate_arrival', 'can_execute_decision', 'can_load_announcements'],
    'Gestionnaire_escales': ['can_edit_ship', 'can_load_announcements'],
    'Directeur': [
        'can_manage_users', 'can_view_user_logs',
        'can_manage_cpn', 'can_optimize', 'can_export', 'can_finish_ships',
        'can_validate_arrival', 'can_execute_decision', 'can_load_announcements', 'can_edit_ship'
    ],
}

for username, group_name, password in users_data:
    user = User.objects.get(username=username)
    print(f"\n📌 {username} (groupe {group_name}) :")
    for perm in expected_perms.get(group_name, []):
        has = user.has_perm(f'port.{perm}')
        print(f"  {'✅' if has else '❌'} port.{perm}")
    all_perms = [p.split('.')[1] for p in user.get_all_permissions() if p.startswith('port.')]
    extra = [p for p in all_perms if p not in expected_perms.get(group_name, [])]
    if extra:
        print(f"  ⚠️ Permissions supplémentaires : {extra}")

print("\n✅ Test terminé. Si toutes les cases sont vertes, votre configuration est correcte.")