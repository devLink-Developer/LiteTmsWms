from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest, JsonResponse


def parse_json_body(request: HttpRequest) -> dict[str, Any]:
    if not request.body:
        return {}
    return json.loads(request.body.decode("utf-8"))


def json_response(data: Any, status: int = 200) -> JsonResponse:
    return JsonResponse(data, status=status, safe=not isinstance(data, list))


def error_response(
    code: str,
    message: str,
    *,
    status: int = 400,
    details: dict[str, Any] | None = None,
    correlation_id: str = "",
) -> JsonResponse:
    return JsonResponse(
        {
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "correlation_id": correlation_id,
            }
        },
        status=status,
    )


def require_idempotency_key(request: HttpRequest) -> str:
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key:
        raise ValueError("Idempotency-Key header is required for mutating commands.")
    return key
