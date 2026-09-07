from pathlib import Path
import os
from dotenv import load_dotenv  # ← NOUVEAU

# Charger les variables d'environnement depuis le fichier .env
load_dotenv()  # ← NOUVEAU

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# ==================== SÉCURITÉ ====================
# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY')  # ← MODIFIÉ

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'False') == 'True'  # ← MODIFIÉ

ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'testserver']  # ← MODIFIÉ (ajout de testserver)

# ==================== APPLICATION DEFINITION ====================
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'port',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'epb_smart.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'port.context_processors.consignataire_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'epb_smart.wsgi.application'

# ==================== BASE DE DONNÉES ====================
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.getenv('DB_NAME'),  # ← MODIFIÉ
        'USER': os.getenv('DB_USER'),  # ← MODIFIÉ
        'PASSWORD': os.getenv('DB_PASSWORD'),  # ← MODIFIÉ
        'HOST': os.getenv('DB_HOST'),  # ← MODIFIÉ
        'PORT': os.getenv('DB_PORT'),  # ← MODIFIÉ
        'OPTIONS': {
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

# ==================== AUTHENTIFICATION ====================
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'

# ==================== INTERNATIONALISATION ====================
LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Africa/Algiers'

USE_I18N = True
USE_TZ = False

# ==================== FICHIERS STATIQUES ====================
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

# ==================== VALIDATION DES MOTS DE PASSE ====================
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ==================== CONFIGURATION EMAIL ====================
import ssl
from django.core.mail.backends.smtp import EmailBackend

class UnsafeSMTPBackend(EmailBackend):
    """Backend SMTP qui ignore les erreurs SSL - UNIQUEMENT pour développement"""
    
    def open(self):
        if self.connection:
            return False
        
        try:
            self.ssl_context = ssl._create_unverified_context()
        except AttributeError:
            self.ssl_context = None
        
        return super().open()

EMAIL_BACKEND = 'epb_smart.settings.UnsafeSMTPBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')  # ← MODIFIÉ
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')  # ← MODIFIÉ
DEFAULT_FROM_EMAIL = os.getenv('EMAIL_HOST_USER')  # ← MODIFIÉ

BASE_URL = 'http://127.0.0.1:8000'