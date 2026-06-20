# Debug Report: Vite Proxy ECONNREFUSED During Backend Startup

## Symptom
- Vite logged repeated proxy failures for `/auth/api/session/`.
- Error: `connect ECONNREFUSED 172.19.0.3:8021`.

## Root Cause
- The backend container was up, but gunicorn was not listening on `8021`.
- Startup command runs `python manage.py migrate --noinput && gunicorn ...`.
- Migration `fulfillment.0013` contained a row-by-row `RunPython` backfill. That made backend startup block during migrations, so Vite had no backend process to proxy to.

## Fix
- Changed `fulfillment.0013` to be schema-only:
  - Adds `customer_document`.
  - Adds `customer_snapshot`.
  - Adds `item_snapshot`.
  - Adds the `customer_document` index.
- Moved the local data backfill into a separate management command:
  - `python manage.py backfill_fulfillment_snapshots`
  - Supports `--dry-run`, `--limit`, `--batch-size`, `--sales-order-number`, and `--all`.
- The backfill command only uses the `default` database, so it touches TMS/WMS only and never reads Litecore/Parquet.

## Evidence
- Restarted `backend`, `frontend`, and `legacy-order-sync`.
- Backend logs show `Applying fulfillment.0013... OK`, followed by gunicorn listening on `0.0.0.0:8021`.
- `GET http://localhost:8021/api/v1/health/` returned `200`.
- `GET http://localhost:8021/auth/api/session/` returned `200`.
- `docker compose exec -T backend python manage.py migrate --check` passed.
- `docker compose exec -T backend python manage.py backfill_fulfillment_snapshots --limit 1 --dry-run` completed without writes.
- `python manage.py test tests --keepdb` passed: 134 tests.

## Status
DONE
