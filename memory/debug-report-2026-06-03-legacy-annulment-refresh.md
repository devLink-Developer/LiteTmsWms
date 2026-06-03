# Debug Report: Legacy Annulment Refresh

Date: 2026-06-03

## Symptom

Delivery, order, and reparto screens could show stale availability for P orders when matching legacy A annulment documents existed but had not been processed by the regular sync path.

## Root Cause

The backend already treats only legacy type P as deliverable and type A/D as impacts, but `expedition_queue` refreshed legacy impacts only when searching by sales order number. Searches by customer/DNI, and the reparto confirmation queue, could serialize local fulfillment rows without first refreshing exact A/D impacts linked by `SalesOrderNumberOrig`.

## Fix

- Added `refresh_legacy_impacts_for_fulfillments`.
- `expedition_queue` refreshes impacts for returned P fulfillments for all search modes.
- `reparto_confirmation_queue` refreshes impacts for delivery and uncreated fulfillment rows, then rereads rows before serialization.
- Ledger idempotency keys produced during annulment reservation release are compacted when they exceed the 120-character DB limit.
- Computed expedition quantities are normalized without trailing zeroes for stable API output.

## Scope Note

The existing annulment rule still protects quantities already remitted by a real delivery document (`ordered - remitted - cancelled`). Reversing remitted/documented quantities requires a separate business rule for remito/document/ledger reversal and was not changed in this fix.

## Evidence

- `python manage.py test tests.test_fulfillment_delivery_flow tests.test_api_filters --keepdb`: 59 tests passed.
- `GET http://localhost:8021/api/v1/fulfillment/expedition-queue/?customer_ref=20000070`: 200 OK, 79 rows, all `sales_order_type=P`.
- `VENT8-100001969`: still `pending`, `cancelled=0`, `pending=27`, matching current exact source data.
- Real data sample with applied impacts: `VENT8-100001767`, cancelled 4, pending 0, impacts 2.
- `GET http://localhost:8021/api/v1/fulfillment/reparto-confirmation/`: 200 OK.

## Regression Tests

- `DeliveryPreparationFlowTests.test_expedition_queue_refreshes_legacy_impacts_for_customer_search`
- `ApiFilterTests.test_reparto_confirmation_queue_refreshes_impacts_before_serializing_uncreated`

## Status

DONE_WITH_CONCERNS
