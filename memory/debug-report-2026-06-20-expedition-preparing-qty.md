# Debug Report: Expedition Missing Preparing Quantities

## Symptom
- The expedition table showed `Reservado`, `Preparado`, and `Pendiente`, but not the quantity currently in preparation.
- Rows sent to preparation could appear as still only reserved/prepared `0`, hiding the operational state between reservation and prepared.

## Root Cause
- `expedition_queue` serialized `planned_qty`, `reserved_qty`, and `prepared_qty`, but did not split active delivery quantities by preparation state.
- When `send_delivery_to_prepare` runs, the delivery status changes to `preparing`, but `FulfillmentOrderLine.reserved_qty` is only decremented later when the task is marked prepared.
- The frontend had no `preparing_qty` field or column, so the quantity was not visible.

## Fix
- Backend:
  - Added `preparing_qty` to fulfillment line serialization.
  - Computes it from active `DeliveryOrderLine` rows whose delivery is `preparing`.
- Frontend:
  - Added `preparing_qty` to the API type.
  - Added `preparingQty` to the expedition row model.
  - Added an `En prep.` column.
  - Adjusted the displayed `Reservado` quantity so it does not double-count quantities already shown as `En prep.` or `Preparado`.

## Evidence
- `python manage.py test tests.test_fulfillment_delivery_flow.DeliveryPreparationFlowTests.test_preparation_task_flow_marks_delivery_prepared_and_allows_remito --keepdb` passed.
- `npm test -- --run src/features/deliveries/DeliveryExpeditionPage.test.tsx` passed: 18 tests.
- `python manage.py test tests --keepdb` passed: 135 tests.
- `npm run build` passed.
- Restarted backend and verified `GET /api/v1/fulfillment/expedition-queue/?sales_order_number=VENT8-100002531` returns `preparing_qty`.

## Status
DONE
