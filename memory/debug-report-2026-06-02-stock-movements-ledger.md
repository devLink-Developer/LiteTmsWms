# Debug report - stock movements ledger

Date: 2026-06-02

## Symptom

`/stock/movimientos` showed repeated-looking stock movements after searching item `100100` for `02/06/2026`. Rows shared the same document reference and movement type, so the grid looked duplicated and did not explain source/target stock effects.

## Root cause

The route used the generic `OperationalPage` with ledger rows. The generic grid used `document_ref` as the visible movement reference and hid ledger differentiators such as `direction`, `location_ref`, `stock_state`, and `item_ref`.

The generic filters also sent `q`, `status`, and `planned_date`; the ledger endpoint expected ledger-specific fields such as `item`, `movement_type`, `direction`, `stock_state`, `date_from`, and `date_to`. As a result, the search/fecha shown in the UI did not reliably constrain the backend query.

## Fix

- Added a dedicated `StockMovementsPage` for `/stock/movimientos`.
- Removed `stock-movements` from generic routed operational modules.
- Added ledger-specific frontend API filters.
- Grouped paired `decrease/increase` ledger impacts into one WMS movement row when they share document, item, warehouse, lot, quantity, UOM, movement family, and close posting time.
- Kept atomic ledger entries visible in the detail panel for audit.
- Extended ledger serialization with audit/reversal/legacy references.
- Added backend support for `q/search` and single-date aliases (`date`, `posted_date`, `planned_date`, `fecha`).

## Evidence

- Frontend focused tests passed: `npm test -- --run src/features/stock/StockMovementsPage.test.tsx src/app/router.test.tsx`.
- Backend ledger filter tests passed: `python manage.py test tests.test_api_filters.ApiFilterTests.test_inventory_ledger_filters_by_supported_fields tests.test_api_filters.ApiFilterTests.test_inventory_ledger_supports_reference_and_state_aliases tests.test_api_filters.ApiFilterTests.test_inventory_ledger_supports_search_and_single_posted_date_alias`.
- Stock frontend tests passed: `npm test -- --run src/features/stock`.
- Frontend build passed: `npm run build`.
- Local API after backend restart returns 9 rows for `q=100100&planned_date=2026-06-02`, matching the expected filtered search.

## Status

DONE
