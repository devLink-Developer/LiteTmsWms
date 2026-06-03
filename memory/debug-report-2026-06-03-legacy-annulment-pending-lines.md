# Debug Report: Legacy Annulment Pending Lines

Date: 2026-06-03

## Symptom

After a partial annulment of `VENT8-100001969`, the three annulled lines still appeared as pending/deliverable in expedition.

## Root Cause

The legacy A document existed and was linked correctly:

- A order: `VENT8-100002337`
- Original P order: `VENT8-100001969`
- Lines annulled: `108284`, `106708`, `106704`

The impact processing failed because annulment tried to post a `PACKED` stock decrease before updating the fulfillment line cancellation. Local packed stock for these items was zero, so inventory rejected the ledger movement with "La operacion dejaria stock negativo". The transaction rolled back and no `cancelled_qty` was applied.

## Fix

Annulment no longer posts a packed-stock decrease. It reduces the pending line by applying `cancelled_qty` to the fulfillment line and releases any non-remitted delivery reservations. This matches the business rule that the A document discounts the pending quantity of the P order.

## Evidence

- Regression tests:
  - `test_annulment_impact_cancels_non_remitted_qty_and_releases_reservation`
  - `test_annulment_impact_cancels_pending_line_when_packed_stock_is_already_zero`
- `python manage.py test tests.test_fulfillment_delivery_flow tests.test_api_filters --keepdb`: 60 tests passed.
- Real verification after restart:
  - `VENT8-100001969`: 1 impact applied, cancelled total 3, pending total 24.
  - Lines `108284`, `106708`, `106704`: `cancelled_qty=1`, `pending_qty=0`.

## Status

DONE
