from __future__ import annotations

import json
from typing import Any

from django.contrib.auth import get_user_model, login as django_login, logout as django_logout
from django.http import HttpRequest, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from apps.authentication.ldap import authenticate_ldap, normalize_login_username
from apps.logistics.parquet_master_data import MasterDataSourceError, employee_delivery_permissions


def _json_error(message: str, *, status: int = 400) -> JsonResponse:
    return JsonResponse({"success": False, "error": message}, status=status)


def _parse_json_body(request: HttpRequest) -> dict[str, Any]:
    if not request.body:
        return {}
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        raise ValueError("JSON invalido")
    return payload if isinstance(payload, dict) else {}


def _workspace_from_permissions(actor: str, delivery_permissions: dict[str, Any]) -> dict[str, Any]:
    employee = delivery_permissions.get("employee") or {}
    warehouses = delivery_permissions.get("authorized_warehouses") or []
    return {
        "warehouse_ref": warehouses[0] if warehouses else "sin-warehouse",
        "branch_ref": employee.get("branch_ref") or "sin-sucursal",
        "role": employee.get("name") or actor or "Sin usuario operativo",
        "permissions": delivery_permissions.get("permissions") or [],
        "authorized_warehouses": warehouses,
        "employee": employee,
    }


def _workspace_for_actor(actor: str) -> dict[str, Any]:
    return _workspace_from_permissions(actor, employee_delivery_permissions(actor))


def _session_user(request: HttpRequest, workspace: dict[str, Any] | None) -> dict[str, str] | None:
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None

    employee = (workspace or {}).get("employee") or {}
    email = request.session.get("email") or employee.get("email") or getattr(user, "email", "") or user.get_username()
    alias = request.session.get("usuario_alias") or normalize_login_username(email)
    return {
        "username": user.get_username(),
        "email": email,
        "displayName": request.session.get("usuario") or employee.get("name") or alias,
        "alias": alias,
    }


def build_session_bootstrap(
    request: HttpRequest,
    *,
    delivery_permissions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    user = getattr(request, "user", None)
    authenticated = bool(user is not None and getattr(user, "is_authenticated", False))
    workspace = None

    if authenticated:
        actor = user.get_username()
        if delivery_permissions is None:
            workspace = _workspace_for_actor(actor)
        else:
            workspace = _workspace_from_permissions(actor, delivery_permissions)

    return {
        "authenticated": authenticated,
        "csrfToken": get_token(request),
        "appName": "Lite Logistic",
        "user": _session_user(request, workspace),
        "workspace": workspace,
    }


@ensure_csrf_cookie
@require_GET
def session_view(request: HttpRequest) -> JsonResponse:
    try:
        payload = build_session_bootstrap(request)
    except MasterDataSourceError as exc:
        return _json_error(str(exc), status=503)
    return JsonResponse(payload)


@require_POST
def login_view(request: HttpRequest) -> JsonResponse:
    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return _json_error(str(exc), status=400)

    username = normalize_login_username(str(payload.get("username") or ""))
    password = str(payload.get("password") or "")
    if not username or not password:
        return _json_error("Debes ingresar usuario y contrasena.", status=400)

    ok, error, email = authenticate_ldap(username, password)
    if not ok or not email:
        return _json_error(f"Credenciales incorrectas: {error or 'Credenciales invalidas'}", status=401)

    try:
        delivery_permissions = employee_delivery_permissions(email)
    except MasterDataSourceError as exc:
        return _json_error(str(exc), status=503)

    employee = delivery_permissions.get("employee") or {}
    warehouses = delivery_permissions.get("authorized_warehouses") or []
    if not employee:
        return _json_error(f"No se encontraron datos del empleado para {email}.", status=403)
    if not warehouses:
        return _json_error("No tienes depositos autorizados para operar Lite Logistic.", status=403)

    User = get_user_model()
    user, _ = User.objects.get_or_create(username=email, defaults={"email": email, "is_active": True})
    if not user.email:
        user.email = email
        user.save(update_fields=["email"])

    django_login(request, user)
    request.session.set_expiry(60 * 60 * 4)
    request.session["usuario"] = employee.get("name") or employee.get("email") or username
    request.session["usuario_alias"] = username
    request.session["email"] = employee.get("email") or email
    request.session["authorized_warehouses"] = warehouses
    request.session["permissions"] = delivery_permissions.get("permissions") or []
    request.session.modified = True

    return JsonResponse(
        {
            "success": True,
            "redirectTo": "/pedidos/entrega",
            "session": build_session_bootstrap(request, delivery_permissions=delivery_permissions),
        }
    )


@require_POST
def logout_view(request: HttpRequest) -> JsonResponse:
    for key in ["usuario", "usuario_alias", "email", "authorized_warehouses", "permissions"]:
        request.session.pop(key, None)
    django_logout(request)
    return JsonResponse({"success": True, "redirectTo": "/login/"})

