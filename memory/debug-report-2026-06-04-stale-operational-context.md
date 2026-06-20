# Debug report: stale operational context

Date: 2026-06-04

## Symptom

The UI header kept showing `Contexto operativo PR03DP` for EUDY ESPINOZA even though the current employee parquet resolves the user to `PS02DP`.

## Root cause

`employee_delivery_permissions()` is cached in-process with `@lru_cache(maxsize=512)` in `backend/apps/logistics/parquet_master_data.py`.

The active Gunicorn workers had a stale cache entry for the actor `edespinoza@familiabercomat.com`, returning `authorized_warehouses=["PR03DP"]`. A new Django shell process read the current parquet and returned `authorized_warehouses=["PS02DP"]`.

There was also an active Django session with:

- `usuario`: `EUDY ESPINOZA`
- `email`: `edespinoza@familiabercomat.com`
- `active_warehouse_ref`: `PR03DP`
- `authorized_warehouses`: `["PR03DP"]`

After the backend restart, the same session cookie resolved to `PS02DP`, proving the stale in-process cache was the effective cause.

## Action

Restarted the backend container:

```bash
docker compose restart backend
```

## Evidence

Before restart:

- `GET /api/v1/logistics/context/` with `X-Actor: edespinoza@familiabercomat.com` returned `warehouse_ref=PR03DP` in 20/20 calls.
- A fresh Django shell process returned `authorized_warehouses=["PS02DP"]` from `/srv/data/parquet/empleados.parquet`.

After restart:

- `GET /api/v1/logistics/context/` with `X-Actor: edespinoza@familiabercomat.com` returned `warehouse_ref=PS02DP` in 12/12 calls.
- The existing active session cookie also returned `warehouse_ref=PS02DP`.
- `GET /api/v1/health/` returned `status=ok`.

## Status

DONE_WITH_CONCERNS: The immediate stale context was cleared by restarting the backend. A future code change should invalidate or version the employee permissions cache when parquet master data changes, so a container restart is not required.
