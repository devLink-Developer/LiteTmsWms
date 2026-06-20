# Debug Report: Materialized Legacy Sync For Expedition Search

## Symptom
- Searching one already-known order in expedition could take around 10-15 seconds.
- The request path was doing synchronous work against Litecore and Parquet: missing-order fallback, legacy impact refresh, customer snapshot resolution, DNI lookup, and material snapshot resolution.

## Root Cause
- `expedition_queue` was not a local-only read path. It could call Litecore and Parquet during a normal UI search.
- Customer and item data needed by the response was not fully materialized on `FulfillmentOrder` and `FulfillmentOrderLine`.

## Fix
- Added persisted local snapshots:
  - `FulfillmentOrder.customer_snapshot`
  - `FulfillmentOrder.customer_document`
  - `FulfillmentOrderLine.item_snapshot`
- Updated `ingest_legacy_order` to resolve and persist customer/material snapshots during sync.
- Existing non-pending orders now get missing/local-backfill customer snapshots completed when sync sees them again, without changing their operational state.
- Kept A/D processing in `process_legacy_order_impact`, so sync applies annulment/return impacts locally.
- Changed `expedition_queue`, reparto, preparation, split, and stock-check paths to consume stored snapshots instead of resolving customer/material data during normal reads.
- Removed expedition fallback ingestion and synchronous legacy impact refresh from the request path.
- Added migration `0013_fulfillmentorder_customer_document_and_more.py` with a local backfill.

## Migration Scope
- The DB router only allows non-legacy app migrations on `default`.
- The backfill uses `schema_editor.connection.alias` explicitly for reads and writes, so the data migration stays inside the same migration connection/schema and does not touch `litecore`.

## Evidence
- `python manage.py makemigrations --check --dry-run` passed with no changes detected.
- `python manage.py test tests.test_fulfillment_delivery_flow tests.test_api_filters --keepdb` passed: 71 tests.
- `python manage.py test tests --keepdb` passed: 133 tests.
- Added structural test that exact local expedition search performs default DB work and does not connect to `litecore`.

## Historical Backfill
- Ran `python manage.py backfill_fulfillment_snapshots --source legacy --all --batch-size 200 --actor historical.snapshot-backfill` in the backend container.
- Final TMS/WMS counts:
  - `FulfillmentOrder`: 1128 total, 0 missing `customer_snapshot`, 0 missing `customer_document`.
  - `FulfillmentOrderLine`: 2884 total, 0 missing `item_snapshot`.
  - Customer snapshot sources: 1128 `legacy`.
  - Item snapshot sources: 2592 `tmswms.material_master_snapshot`, 292 `fallback`.
- Verified `GET /api/v1/fulfillment/expedition-queue/?sales_order_number=VENT8-100002531` returned `200`.
- Verified `GET /api/v1/fulfillment/expedition-queue/?customer_dni=34598157` returned `200`.
