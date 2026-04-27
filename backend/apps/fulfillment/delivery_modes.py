from __future__ import annotations

from functools import lru_cache

from django.db import connection
from django.db.models import Q


@lru_cache(maxsize=1)
def shipping_delivery_mode_codes() -> set[str]:
    if connection.vendor != "postgresql":
        return set()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT "ModeId"
                FROM public.maestros_tiendas_deliverymode
                WHERE "Estado" IS TRUE
                  AND "IsShippingAllowed" IS TRUE
                  AND COALESCE("ModeId", '') <> ''
                """
            )
            return {str(row[0]).strip() for row in cursor.fetchall() if str(row[0]).strip()}
    except Exception:
        return set()


def is_shipping_delivery_mode(value: str | None) -> bool:
    mode = str(value or "").strip()
    if not mode:
        return False
    codes = shipping_delivery_mode_codes()
    if codes:
        return mode in codes
    return "repart" in mode.casefold()


def shipping_delivery_mode_q(field_name: str = "delivery_mode") -> Q:
    codes = shipping_delivery_mode_codes()
    if codes:
        return Q(**{f"{field_name}__in": list(codes)})
    return Q(**{f"{field_name}__icontains": "repart"})


def delivery_mode_filter_q(requested_mode: str, field_name: str = "delivery_mode") -> Q:
    requested = str(requested_mode or "").strip()
    if "repart" in requested.casefold():
        return shipping_delivery_mode_q(field_name)
    return Q(**{f"{field_name}__icontains": requested})
