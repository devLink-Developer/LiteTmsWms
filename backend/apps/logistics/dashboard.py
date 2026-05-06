from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.http import HttpRequest
from django.utils import timezone

from apps.fulfillment.delivery_modes import shipping_delivery_mode_q
from apps.fulfillment.models import DeliveryOrder, DeliveryPreparationTask, FulfillmentOrder
from apps.inventory.models import (
    InventoryBalance,
    InventoryLedgerEntry,
    InventoryWriteOff,
    PurchaseOrderReceipt,
    StockState,
)
from apps.logistics.parquet_master_data import employee_delivery_permissions
from apps.routes.models import RouteSheet, RouteStop
from apps.shipping.models import Shipment
from apps.transfers.models import TransferOrder


FULFILLMENT_OPEN_STATUSES = [
    FulfillmentOrder.FulfillmentStatus.PENDING,
    FulfillmentOrder.FulfillmentStatus.ALLOCATED,
    FulfillmentOrder.FulfillmentStatus.PREPARING,
    FulfillmentOrder.FulfillmentStatus.READY_FOR_DISPATCH,
    FulfillmentOrder.FulfillmentStatus.PARTIALLY_DELIVERED,
    FulfillmentOrder.FulfillmentStatus.RESCHEDULED,
]

DELIVERY_ACTIVE_STATUSES = [
    DeliveryOrder.DeliveryStatus.CREATED,
    DeliveryOrder.DeliveryStatus.CONFIRMED,
    DeliveryOrder.DeliveryStatus.PLANNED,
    DeliveryOrder.DeliveryStatus.ASSIGNED,
    DeliveryOrder.DeliveryStatus.PREPARING,
    DeliveryOrder.DeliveryStatus.PREPARED,
    DeliveryOrder.DeliveryStatus.LOADED,
    DeliveryOrder.DeliveryStatus.IN_ROUTE,
    DeliveryOrder.DeliveryStatus.ATTEMPTED,
    DeliveryOrder.DeliveryStatus.DELIVERED_PARTIAL,
]

DELIVERY_ALERT_STATUSES = [
    DeliveryOrder.DeliveryStatus.ATTEMPTED,
    DeliveryOrder.DeliveryStatus.DELIVERED_PARTIAL,
    DeliveryOrder.DeliveryStatus.RETURNED,
    DeliveryOrder.DeliveryStatus.CANCELLED,
]

TASK_OPEN_STATUSES = [
    DeliveryPreparationTask.TaskStatus.ASSIGNED,
    DeliveryPreparationTask.TaskStatus.PREPARING,
]

ROUTE_ACTIVE_STATUSES = [
    RouteSheet.RouteStatus.PLANNED,
    RouteSheet.RouteStatus.CAPACITY_CHECKED,
    RouteSheet.RouteStatus.ASSIGNED,
    RouteSheet.RouteStatus.LOADING,
    RouteSheet.RouteStatus.IN_TRANSIT,
    RouteSheet.RouteStatus.SETTLEMENT_PENDING,
]

ROUTE_PENDING_STOP_STATUSES = [
    RouteStop.StopStatus.PENDING,
    RouteStop.StopStatus.PLANNED,
    RouteStop.StopStatus.ALLOCATED,
    RouteStop.StopStatus.LOADED,
    RouteStop.StopStatus.EN_ROUTE,
    RouteStop.StopStatus.ARRIVED,
]

ROUTED_DELIVERY_STATUSES = [
    DeliveryOrder.DeliveryStatus.ASSIGNED,
    DeliveryOrder.DeliveryStatus.CANCELLED,
    DeliveryOrder.DeliveryStatus.DELIVERED_COMPLETE,
    DeliveryOrder.DeliveryStatus.IN_ROUTE,
    DeliveryOrder.DeliveryStatus.LOADED,
    DeliveryOrder.DeliveryStatus.PLANNED,
    DeliveryOrder.DeliveryStatus.RETURNED,
]

MODULES = [
    ("orders", "Pedidos", "/pedidos"),
    ("deliveries", "Entregas", "/pedidos/entrega"),
    ("tasks", "Preparacion", "/pedidos/tareas"),
    ("distribution", "Reparto", "/reparto/confirmacion"),
    ("receipts", "Ingresos OC", "/ingresos/oc"),
    ("transfers", "Transferencias", "/ingresos/tr-depositos"),
    ("shipping", "Envios", "/envios"),
    ("returns", "Devoluciones", "/ingresos/devoluciones"),
    ("routes", "Hojas de ruta", "/reparto/hojas-ruta"),
    ("stock", "Stock", "/stock/almacenes"),
    ("ledger", "Ledger stock", "/stock/movimientos"),
    ("write_offs", "Roturas y perdidas", "/operaciones/roturas-perdidas"),
]


def _decimal_text(value: Decimal | None) -> str:
    value = value or Decimal("0")
    if value == value.to_integral_value():
        return format(value.quantize(Decimal("1")), "f")
    return format(value.normalize(), "f")


def _quantity_by_uom(qs, quantity_field: str = "quantity") -> list[dict]:
    return [
        {"uom": row["uom"] or "-", "quantity": _decimal_text(row["quantity"])}
        for row in qs.values("uom").annotate(quantity=Sum(quantity_field)).order_by("uom")
    ]


def _quantity_summary(rows: list[dict]) -> str:
    if not rows:
        return "sin cantidad positiva"
    return " / ".join(f'{row["quantity"]} {row["uom"]}' for row in rows[:3])


def _choice_rows(qs, choices) -> list[dict]:
    counts = {row["status"]: row["count"] for row in qs.values("status").annotate(count=Count("id"))}
    return [
        {"key": key, "label": str(label), "count": counts.get(key, 0)}
        for key, label in choices
    ]


def _session_warehouses(request: HttpRequest) -> list[str]:
    warehouses = request.session.get("authorized_warehouses") if hasattr(request, "session") else []
    return [str(warehouse).strip() for warehouse in (warehouses or []) if str(warehouse).strip()]


def _dashboard_scope(request: HttpRequest, actor: str) -> tuple[str, list[str]]:
    session_active = str(request.session.get("active_warehouse_ref", "") if hasattr(request, "session") else "").strip()
    session_authorized = _session_warehouses(request)
    if session_active and (not session_authorized or session_active in session_authorized):
        return session_active, session_authorized
    if session_authorized:
        return session_authorized[0], session_authorized

    permissions = employee_delivery_permissions(actor) if actor else {"authorized_warehouses": []}
    authorized = [
        str(warehouse).strip()
        for warehouse in (permissions.get("authorized_warehouses") or [])
        if str(warehouse).strip()
    ]
    return (authorized[0] if authorized else "sin-warehouse"), authorized


def _empty_module_counts() -> dict[str, int]:
    return {key: 0 for key, _label, _path in MODULES}


def _module_rows(counts: dict[str, int], active: dict[str, int], issues: dict[str, int]) -> list[dict]:
    rows = []
    for key, label, path in MODULES:
        issue_count = issues.get(key, 0)
        rows.append(
            {
                "key": key,
                "label": label,
                "path": path,
                "count": counts.get(key, 0),
                "active": active.get(key, 0),
                "issues": issue_count,
                "tone": "warning" if issue_count else "success",
            }
        )
    return rows


def _coverage_rows(counts: dict[str, int]) -> list[dict]:
    return [
        {"key": key, "label": label, "count": counts.get(key, 0)}
        for key, label, _path in MODULES
    ]


def _alert(alerts: list[dict], *, key: str, label: str, value: int, tone: str, detail: str) -> None:
    if value <= 0:
        return
    alerts.append({"key": key, "label": label, "value": value, "tone": tone, "detail": detail})


def build_operational_dashboard(request: HttpRequest, *, actor: str) -> dict:
    warehouse_ref, authorized_warehouses = _dashboard_scope(request, actor)
    today = timezone.localdate()
    ledger_start = today - timedelta(days=6)
    generated_at = timezone.now().isoformat()

    counts = _empty_module_counts()
    active_counts = _empty_module_counts()
    issue_counts = _empty_module_counts()
    alerts: list[dict] = []

    if not warehouse_ref or warehouse_ref == "sin-warehouse":
        return {
            "generated_at": generated_at,
            "scope": {
                "warehouse_ref": "sin-warehouse",
                "mode": "active_warehouse",
                "window": "operational_live",
                "authorized_warehouses": authorized_warehouses,
            },
            "kpis": [
                {
                    "key": "active_warehouse",
                    "label": "Almacen activo",
                    "value": 0,
                    "tone": "danger",
                    "detail": "sin almacen operativo",
                }
            ],
            "charts": {
                "fulfillment_status": [],
                "delivery_pipeline": [],
                "stock_by_state": [],
                "ledger_by_day": [],
                "route_load": [],
                "module_coverage": _coverage_rows(counts),
            },
            "alerts": [
                {
                    "key": "missing_scope",
                    "label": "Sin almacen activo",
                    "value": 1,
                    "tone": "danger",
                    "detail": "No se pudo resolver el scope operativo.",
                }
            ],
            "modules": _module_rows(counts, active_counts, issue_counts),
        }

    fulfillment_qs = FulfillmentOrder.objects.filter(warehouse_ref=warehouse_ref)
    delivery_qs = DeliveryOrder.objects.filter(warehouse_ref=warehouse_ref)
    task_qs = DeliveryPreparationTask.objects.filter(warehouse_ref=warehouse_ref)
    receipt_qs = PurchaseOrderReceipt.objects.filter(warehouse_ref=warehouse_ref)
    transfer_qs = TransferOrder.objects.filter(
        Q(origin_warehouse_ref=warehouse_ref) | Q(destination_warehouse_ref=warehouse_ref)
    )
    route_qs = RouteSheet.objects.filter(warehouse_ref=warehouse_ref)
    stock_positive_qs = InventoryBalance.objects.filter(warehouse_ref=warehouse_ref, quantity__gt=0)
    ledger_qs = InventoryLedgerEntry.objects.filter(
        warehouse_ref=warehouse_ref,
        posted_at__date__gte=ledger_start,
        posted_at__date__lte=today,
    )
    shipping_qs = Shipment.objects.filter(warehouse_ref=warehouse_ref)
    returned_shipping_qs = shipping_qs.filter(status=Shipment.ShipmentStatus.RETURNED)
    write_off_qs = InventoryWriteOff.objects.filter(warehouse_ref=warehouse_ref)

    open_orders = fulfillment_qs.filter(status__in=FULFILLMENT_OPEN_STATUSES)
    overdue_orders = open_orders.filter(requested_date__lt=today)
    orders_next_7 = open_orders.filter(requested_date__gte=today, requested_date__lte=today + timedelta(days=7))
    ready_orders = fulfillment_qs.filter(status=FulfillmentOrder.FulfillmentStatus.READY_FOR_DISPATCH)

    active_deliveries = delivery_qs.filter(status__in=DELIVERY_ACTIVE_STATUSES)
    overdue_deliveries = active_deliveries.filter(planned_date__lt=today)
    delivery_alerts = delivery_qs.filter(status__in=DELIVERY_ALERT_STATUSES)
    reparto_qs = delivery_qs.filter(shipping_delivery_mode_q())
    pending_route = reparto_qs.exclude(status__in=ROUTED_DELIVERY_STATUSES)

    open_tasks = task_qs.filter(status__in=TASK_OPEN_STATUSES)
    active_routes = route_qs.filter(status__in=ROUTE_ACTIVE_STATUSES)
    pending_stops = RouteStop.objects.filter(route__warehouse_ref=warehouse_ref, status__in=ROUTE_PENDING_STOP_STATUSES)
    route_issues = route_qs.filter(
        status__in=[RouteSheet.RouteStatus.CANCELLED, RouteSheet.RouteStatus.CLOSED_WITH_INCIDENT]
    )

    receipt_issues = receipt_qs.filter(status=PurchaseOrderReceipt.ReceiptStatus.WITH_INCIDENT)
    open_receipts = receipt_qs.exclude(
        status__in=[
            PurchaseOrderReceipt.ReceiptStatus.RECEIVED,
            PurchaseOrderReceipt.ReceiptStatus.CLOSED,
            PurchaseOrderReceipt.ReceiptStatus.CANCELLED,
        ]
    )
    transfer_issues = transfer_qs.filter(
        status__in=[TransferOrder.TransferStatus.DISCREPANT, TransferOrder.TransferStatus.PARTIAL_RECEIVED]
    )
    open_transfers = transfer_qs.exclude(
        status__in=[
            TransferOrder.TransferStatus.RECEIVED,
            TransferOrder.TransferStatus.CLOSED,
            TransferOrder.TransferStatus.CANCELLED,
        ]
    )
    scrapped_stock = stock_positive_qs.filter(stock_state=StockState.SCRAPPED)
    ledger_reversals = ledger_qs.filter(movement_type=InventoryLedgerEntry.MovementType.REVERSAL)

    counts.update(
        {
            "orders": fulfillment_qs.count(),
            "deliveries": delivery_qs.count(),
            "tasks": task_qs.count(),
            "distribution": reparto_qs.count(),
            "receipts": receipt_qs.count(),
            "transfers": transfer_qs.count(),
            "shipping": shipping_qs.count(),
            "returns": returned_shipping_qs.count(),
            "routes": route_qs.count(),
            "stock": stock_positive_qs.count(),
            "ledger": ledger_qs.count(),
            "write_offs": write_off_qs.count(),
        }
    )
    active_counts.update(
        {
            "orders": open_orders.count(),
            "deliveries": active_deliveries.count(),
            "tasks": open_tasks.count(),
            "distribution": pending_route.count(),
            "receipts": open_receipts.count(),
            "transfers": open_transfers.count(),
            "shipping": shipping_qs.exclude(
                status__in=[
                    Shipment.ShipmentStatus.DELIVERED,
                    Shipment.ShipmentStatus.CLOSED,
                    Shipment.ShipmentStatus.CANCELLED,
                ]
            ).count(),
            "returns": returned_shipping_qs.count(),
            "routes": active_routes.count(),
            "stock": stock_positive_qs.count(),
            "ledger": ledger_qs.count(),
            "write_offs": write_off_qs.exclude(
                status__in=[
                    InventoryWriteOff.WriteOffStatus.CANCELLED,
                    InventoryWriteOff.WriteOffStatus.REVERSED,
                ]
            ).count(),
        }
    )
    issue_counts.update(
        {
            "orders": overdue_orders.count(),
            "deliveries": overdue_deliveries.count() + delivery_alerts.count(),
            "receipts": receipt_issues.count(),
            "transfers": transfer_issues.count(),
            "returns": returned_shipping_qs.count(),
            "routes": route_issues.count(),
            "stock": scrapped_stock.count(),
            "ledger": ledger_reversals.count(),
        }
    )

    stock_quantity_rows = _quantity_by_uom(stock_positive_qs)
    route_weight = active_routes.aggregate(quantity=Sum("planned_weight_kg"))["quantity"] or Decimal("0")
    route_volume = active_routes.aggregate(quantity=Sum("planned_volume_m3"))["quantity"] or Decimal("0")

    _alert(
        alerts,
        key="overdue_orders",
        label="Pedidos vencidos",
        value=issue_counts["orders"],
        tone="warning",
        detail="Pedidos abiertos con fecha solicitada anterior a hoy.",
    )
    _alert(
        alerts,
        key="overdue_deliveries",
        label="Entregas vencidas",
        value=overdue_deliveries.count(),
        tone="warning",
        detail="Entregas activas con fecha planificada anterior a hoy.",
    )
    _alert(
        alerts,
        key="delivery_incidents",
        label="Entregas con atencion",
        value=delivery_alerts.count(),
        tone="warning",
        detail="Estados intento, parcial, devuelto o cancelado.",
    )
    _alert(
        alerts,
        key="transfer_issues",
        label="Transferencias con diferencias",
        value=transfer_issues.count(),
        tone="warning",
        detail="Transferencias parciales o discrepantes.",
    )
    _alert(
        alerts,
        key="scrapped_stock",
        label="Stock en merma",
        value=scrapped_stock.count(),
        tone="danger",
        detail="Buckets positivos en estado scrapped.",
    )

    ledger_counts = {
        (row["day"].isoformat(), row["direction"]): row["count"]
        for row in ledger_qs.annotate(day=TruncDate("posted_at")).values("day", "direction").annotate(count=Count("id"))
    }
    ledger_quantities: dict[tuple[str, str], list[dict]] = {}
    for row in (
        ledger_qs.annotate(day=TruncDate("posted_at"))
        .values("day", "direction", "uom")
        .annotate(quantity=Sum("quantity"))
        .order_by("day", "direction", "uom")
    ):
        ledger_quantities.setdefault((row["day"].isoformat(), row["direction"]), []).append(
            {"uom": row["uom"] or "-", "quantity": _decimal_text(row["quantity"])}
        )
    ledger_by_day = []
    for offset in range(7):
        day = ledger_start + timedelta(days=offset)
        day_key = day.isoformat()
        ledger_by_day.append(
            {
                "date": day_key,
                "increase_count": ledger_counts.get((day_key, InventoryLedgerEntry.Direction.INCREASE), 0),
                "decrease_count": ledger_counts.get((day_key, InventoryLedgerEntry.Direction.DECREASE), 0),
                "increase_quantity_by_uom": ledger_quantities.get((day_key, InventoryLedgerEntry.Direction.INCREASE), []),
                "decrease_quantity_by_uom": ledger_quantities.get((day_key, InventoryLedgerEntry.Direction.DECREASE), []),
            }
        )

    stock_counts = {
        row["stock_state"]: row["buckets"]
        for row in stock_positive_qs.values("stock_state").annotate(buckets=Count("id"))
    }
    stock_by_state = []
    for key, label in StockState.choices:
        state_qs = stock_positive_qs.filter(stock_state=key)
        stock_by_state.append(
            {
                "key": key,
                "label": str(label),
                "buckets": stock_counts.get(key, 0),
                "quantity_by_uom": _quantity_by_uom(state_qs),
            }
        )

    route_load = [
        {
            "route_number": row.route_number,
            "status": row.status,
            "planned_date": row.planned_date.isoformat(),
            "stops": row.stops_count,
            "planned_weight_kg": _decimal_text(row.planned_weight_kg),
            "planned_volume_m3": _decimal_text(row.planned_volume_m3),
        }
        for row in active_routes.annotate(stops_count=Count("stops")).order_by("planned_date", "route_number")[:12]
    ]

    data_modules = sum(1 for value in counts.values() if value > 0)
    total_modules = len(MODULES)

    return {
        "generated_at": generated_at,
        "scope": {
            "warehouse_ref": warehouse_ref,
            "mode": "active_warehouse",
            "window": "operational_live",
            "authorized_warehouses": authorized_warehouses,
        },
        "kpis": [
            {
                "key": "open_orders",
                "label": "Pedidos abiertos",
                "value": active_counts["orders"],
                "tone": "warning" if issue_counts["orders"] else "info",
                "detail": f'{ready_orders.count()} listos despacho / {orders_next_7.count()} proximos 7 dias',
            },
            {
                "key": "active_deliveries",
                "label": "Entregas activas",
                "value": active_counts["deliveries"],
                "tone": "warning" if issue_counts["deliveries"] else "success",
                "detail": f'{overdue_deliveries.count()} vencidas / {delivery_alerts.count()} con atencion',
            },
            {
                "key": "open_tasks",
                "label": "Tareas preparacion",
                "value": active_counts["tasks"],
                "tone": "info" if active_counts["tasks"] else "neutral",
                "detail": "assigned + preparing",
            },
            {
                "key": "pending_route",
                "label": "Reparto por rutear",
                "value": active_counts["distribution"],
                "tone": "warning" if active_counts["distribution"] else "success",
                "detail": f'{counts["distribution"]} reparto en scope',
            },
            {
                "key": "open_inbound",
                "label": "Ingresos abiertos",
                "value": active_counts["receipts"] + active_counts["transfers"],
                "tone": "warning" if issue_counts["receipts"] or issue_counts["transfers"] else "success",
                "detail": f'{counts["receipts"]} OC / {counts["transfers"]} TR',
            },
            {
                "key": "active_routes",
                "label": "Hojas activas",
                "value": active_counts["routes"],
                "tone": "info" if active_counts["routes"] else "neutral",
                "detail": f'{_decimal_text(route_weight)} kg / {_decimal_text(route_volume)} m3 plan',
            },
            {
                "key": "stock_buckets",
                "label": "Stock positivo",
                "value": counts["stock"],
                "tone": "danger" if issue_counts["stock"] else "success",
                "detail": _quantity_summary(stock_quantity_rows),
            },
            {
                "key": "ledger_7d",
                "label": "Ledger 7 dias",
                "value": counts["ledger"],
                "tone": "warning" if issue_counts["ledger"] else "info",
                "detail": "entradas y salidas por dia",
            },
            {
                "key": "module_coverage",
                "label": "Modulos con datos",
                "value": f"{data_modules}/{total_modules}",
                "tone": "success" if data_modules == total_modules else "warning",
                "detail": "ceros visibles, sin datos inventados",
            },
        ],
        "charts": {
            "fulfillment_status": _choice_rows(fulfillment_qs, FulfillmentOrder.FulfillmentStatus.choices),
            "delivery_pipeline": _choice_rows(delivery_qs, DeliveryOrder.DeliveryStatus.choices),
            "stock_by_state": stock_by_state,
            "ledger_by_day": ledger_by_day,
            "route_load": route_load,
            "module_coverage": _coverage_rows(counts),
        },
        "alerts": alerts[:8],
        "modules": _module_rows(counts, active_counts, issue_counts),
    }
