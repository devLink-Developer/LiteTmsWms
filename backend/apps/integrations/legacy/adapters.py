from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from apps.integrations.legacy.models import LegacyItem, LegacyOrder, LegacyOrderLine


@dataclass(frozen=True)
class LegacyOrderLineSnapshot:
    retail_line_item_id: str
    sales_order_number: str
    transaction_number: str
    item_ref: str
    warehouse_ref: str
    ordered_qty: Decimal
    delivered_qty: Decimal
    remaining_qty: Decimal
    uom: str


class LegacyOrderAdapter:
    using = "litecore"

    def get_order(self, sales_order_number: str) -> LegacyOrder:
        return LegacyOrder.objects.using(self.using).get(sales_order_number=sales_order_number)

    def get_order_lines(self, sales_order_number: str) -> list[LegacyOrderLineSnapshot]:
        lines = LegacyOrderLine.objects.using(self.using).filter(sales_order_number=sales_order_number)
        return [
            LegacyOrderLineSnapshot(
                retail_line_item_id=str(line.retail_line_item_id),
                sales_order_number=line.sales_order_number or "",
                transaction_number=line.transaction_number,
                item_ref=line.item_number,
                warehouse_ref=line.shipping_warehouse_id or line.warehouse,
                ordered_qty=line.ordered_sales_quantity,
                delivered_qty=line.sales_quantity_delivered or Decimal("0"),
                remaining_qty=line.remain_sales_physical or line.ordered_sales_quantity,
                uom=line.sales_unit_symbol,
            )
            for line in lines
        ]


class LegacyItemAdapter:
    using = "litecore"

    def get_capacity_attributes(self, item_ref: str) -> dict[str, Decimal | str]:
        item = LegacyItem.objects.using(self.using).get(numero_producto=item_ref)
        return {
            "item_ref": item.numero_producto,
            "name": item.nombre_producto or "",
            "uom": item.um_base_codigo or "",
            "weight": item.peso_bruto or Decimal("0"),
            "volume": item.volumen or Decimal("0"),
        }
