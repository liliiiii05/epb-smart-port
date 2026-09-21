from pathlib import Path
import os
import dj_database_url  # ← pour PostgreSQL
from dotenv import load_dotenv

# Charger les variables d'environnement depuis le fichier .env
load_dotenv()

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent

# ==================== SÉCURITÉ ====================
SECRET_KEY = os.getenv('SECRET_KEY')

DEBUG = os.getenv('DEBUG', 'False') == 'True'

ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'testserver', '.onrender.com', '.railway.app']

# ==================== APPLICATION DEFINITION ====================
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'port.apps.PortConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
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
# ✅ Configuration corrigée pour Neon (conn_max_age=0)
# - En production (Render) : utilise PostgreSQL (Neon)
# - En local : utilise MySQL
# - Fallback : SQLite

DATABASE_URL = os.getenv('DATABASE_URL')

if DATABASE_URL:
    # ✅ PostgreSQL (Neon) - utilisé en local ET en production
    # ⚠️ conn_max_age=0 : ferme la connexion après chaque requête
    #    (Neon ferme les connexions inactives après ~5 min)
    DATABASES = {
        'default': dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=0,
            conn_health_checks=True,
        )
    }
    print("🐘 [DB] Utilisation de PostgreSQL (Neon)")
else:
    # ✅ Fallback : MySQL local
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.getenv('DB_NAME', 'epb_smart'),
            'USER': os.getenv('DB_USER', 'root'),
            'PASSWORD': os.getenv('DB_PASSWORD', ''),
            'HOST': os.getenv('DB_HOST', 'localhost'),
            'PORT': os.getenv('DB_PORT', '3306'),
            'OPTIONS': {
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }
    # print("🐬 [DB] Utilisation de MySQL (local)")

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

# ✅ WhiteNoise pour servir les fichiers statiques en production
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

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
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = os.getenv('EMAIL_HOST_USER')

# ✅ URL de base : dynamique selon l'environnement
if DEBUG:
    BASE_URL = 'http://127.0.0.1:8000'
else:
    BASE_URL = os.getenv('BASE_URL', 'https://epb-smart-port.onrender.com')

# ==================== LOGGING ====================
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': 'surveillance_epb.log',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'port.services.surveillance_auto': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'port.services.surveillance': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# ==================== DEFAULT AUTO FIELD ====================
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'