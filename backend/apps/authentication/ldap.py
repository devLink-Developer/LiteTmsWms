from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings


@dataclass(frozen=True)
class LdapConfig:
    server: str
    domains: tuple[str, ...]
    timeout: int


def _config_ini_candidates() -> list[Path]:
    base_dir = Path(settings.BASE_DIR)
    return [
        base_dir / "config.ini",
        base_dir.parent / "config.ini",
        Path("/app/src/config.ini"),
        Path("/app/config.ini"),
    ]


def _load_config_ini() -> dict[str, str]:
    parser = configparser.ConfigParser()
    for path in _config_ini_candidates():
        if not path.exists():
            continue
        parser.read(path, encoding="utf-8")
        section = next((name for name in parser.sections() if name.lower() == "ldap"), "")
        if section:
            return {key.lower(): value for key, value in parser.items(section)}
    return {}


def load_ldap_config() -> LdapConfig | None:
    ini = _load_config_ini()
    server = os.getenv("LDAP_SERVER") or os.getenv("ldap_server") or ini.get("ldap_server") or ""
    domain = os.getenv("LDAP_DOMAIN") or os.getenv("ldap_domain") or ini.get("ldap_domain") or ""
    domain_tg = os.getenv("LDAP_DOMAIN_TG") or os.getenv("ldap_domain_tg") or ini.get("ldap_domain_tg") or ""
    raw_timeout = os.getenv("LDAP_TIMEOUT") or os.getenv("ldap_timeout") or ini.get("ldap_timeout") or "10"

    domains = tuple(value.strip() for value in [domain, domain_tg] if value and value.strip())
    if not server.strip() or not domains:
        return None

    try:
        timeout = int(raw_timeout)
    except ValueError:
        timeout = 10

    return LdapConfig(server=server.strip(), domains=domains, timeout=max(timeout, 1))


def normalize_login_username(username: str) -> str:
    normalized = str(username or "").strip().lower()
    if "@" in normalized:
        return normalized.split("@", 1)[0]
    return normalized


def authenticate_ldap(username: str, password: str) -> tuple[bool, str | None, str | None]:
    login_name = normalize_login_username(username)
    if not login_name or not password:
        return False, "Debes ingresar usuario y contrasena.", None

    ldap_config = load_ldap_config()
    if ldap_config is None:
        return False, "No se encontro configuracion LDAP.", None

    try:
        from ldap3 import Connection, Server
        from ldap3.core.exceptions import LDAPBindError, LDAPException, LDAPSocketOpenError
    except ModuleNotFoundError:
        return False, "ldap3 no esta instalado en el backend.", None

    server = Server(ldap_config.server, connect_timeout=ldap_config.timeout)
    for domain in ldap_config.domains:
        bind_user = f"{login_name}@{domain}"
        try:
            Connection(
                server,
                user=bind_user,
                password=password,
                auto_bind=True,
                receive_timeout=ldap_config.timeout,
            )
            return True, None, bind_user
        except LDAPSocketOpenError:
            return False, "No se pudo conectar al servidor LDAP (timeout). Intente nuevamente.", None
        except LDAPBindError:
            continue
        except LDAPException as exc:
            return False, str(exc), None

    return False, "Credenciales invalidas", None

