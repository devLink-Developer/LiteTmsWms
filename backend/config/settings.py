from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-tms-wms-secret")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [host for host in os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",") if host]

INSTALLED_APPS = [
    "whitenoise.runserver_nostatic",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.common",
    "apps.core",
    "apps.integrations.legacy",
    "apps.inventory",
    "apps.transfers",
    "apps.fulfillment",
    "apps.vehicles",
    "apps.routes",
    "apps.audits",
    "apps.dispatch",
    "apps.shipping",
    "apps.logistics",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DEFAULT_SQLITE_PATH = BASE_DIR / "db.sqlite3"
TMSWMS_DB_SCHEMA = os.getenv("TMSWMS_DB_SCHEMA", "tmswms")


def postgres_options(schema: str, *, include_public: bool = False) -> dict[str, str]:
    suffix = ",public" if include_public else ""
    return {"options": f"-c search_path={schema}{suffix}"}

DATABASES = {
    "default": {
        "ENGINE": os.getenv("POSTGRES_ENGINE", "django.db.backends.sqlite3"),
        "NAME": os.getenv("POSTGRES_DB_NAME", str(DEFAULT_SQLITE_PATH)),
        "USER": os.getenv("POSTGRES_DB_USER", ""),
        "PASSWORD": os.getenv("POSTGRES_DB_PASS", ""),
        "HOST": os.getenv("POSTGRES_DB_HOST", ""),
        "PORT": os.getenv("POSTGRES_DB_PORT", ""),
        "OPTIONS": postgres_options(TMSWMS_DB_SCHEMA),
    },
    "litecore": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("LITECORE_DB_NAME", os.getenv("POSTGRES_DB_NAME", "litecore")),
        "USER": os.getenv("LITECORE_DB_USER", os.getenv("POSTGRES_DB_USER", "litecore")),
        "PASSWORD": os.getenv("LITECORE_DB_PASS", os.getenv("POSTGRES_DB_PASS", "")),
        "HOST": os.getenv("LITECORE_DB_HOST", os.getenv("POSTGRES_DB_HOST", "10.11.0.30")),
        "PORT": os.getenv("LITECORE_DB_PORT", os.getenv("POSTGRES_DB_PORT", "5433")),
        "OPTIONS": postgres_options("public"),
    },
}

if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(DEFAULT_SQLITE_PATH),
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es-ar"
TIME_ZONE = "America/Argentina/Buenos_Aires"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
TMSWMS_API_VERSION = "v1"
TMSWMS_DEFAULT_ACTOR = os.getenv("TMSWMS_DEFAULT_ACTOR", "")
DATABASE_ROUTERS = ["apps.core.dbrouters.TmsWmsDatabaseRouter"]
MASTER_DATA_PARQUET_DIR = os.getenv("MASTER_DATA_PARQUET_DIR", "/srv/data/parquet")
MASTER_DATA_PARQUET_FALLBACK_DIRS = [
    path
    for path in os.getenv("MASTER_DATA_PARQUET_FALLBACK_DIRS", "/srv/data/paarquet,C:/cache").split(",")
    if path
]
