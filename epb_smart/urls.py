from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from port import views

urlpatterns = [
    # Administration
    path('admin/', admin.site.urls),

    # Redirection personnalisée à la racine (selon le groupe de l'utilisateur)
    path('', views.redirection_apres_connexion, name='accueil'),

    # Toutes les URLs de l'application port (sauf la racine) sont préfixées par 'port/'
    path('port/', include('port.urls')),

    # Authentification
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),

    # Réinitialisation du mot de passe
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='registration/password_reset.html',
        email_template_name='registration/password_reset_email.html',
        subject_template_name='registration/password_reset_subject.txt'
    ), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='registration/password_reset_done.html'
    ), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='registration/password_reset_confirm.html'
    ), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='registration/password_reset_complete.html'
    ), name='password_reset_complete'),

    # Profil et changement de mot de passe
    path('profil/', views.profil, name='profil'),
    path('password-change/', auth_views.PasswordChangeView.as_view(
        template_name='registration/password_change.html',
        success_url='/profil/'
    ), name='password_change'),
    path('password-change/done/', auth_views.PasswordChangeDoneView.as_view(
        template_name='registration/password_change_done.html'
    ), name='password_change_done'),
]