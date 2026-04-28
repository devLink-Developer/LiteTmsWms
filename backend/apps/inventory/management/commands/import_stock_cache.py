from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.inventory.stock_cache_import import (
    StockCacheImportError,
    import_stock_cache,
    parse_stock_cache_mappings,
)


class Command(BaseCommand):
    help = "Imports stock_cache.parquet into inventory balances."

    def add_arguments(self, parser):
        parser.add_argument("--path", default="", help="Archivo o directorio de stock_cache.parquet.")
        parser.add_argument(
            "--mapping",
            action="append",
            default=[],
            help=(
                "Mapping stock_state=columna. Default: packed=disponible_entrega. "
                "Ejemplo: --mapping on_hand=disponible_venta --mapping reserved=comprometido"
            ),
        )
        parser.add_argument("--actor", default="", help="Usuario tecnico para auditoria simple de balances.")
        parser.add_argument("--batch-size", type=int, default=5000)
        parser.add_argument("--uom", default="UN")
        parser.add_argument("--include-zero", action="store_true", help="Tambien escribe balances con cantidad cero.")
        parser.add_argument("--allow-negative", action="store_true", help="Conserva cantidades negativas del parquet.")
        parser.add_argument(
            "--reset-state",
            action="store_true",
            help="Borra balances existentes de los estados importados antes de cargar.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Lee y cuenta sin escribir en base.")

    def handle(self, *args, **options):
        try:
            mappings = parse_stock_cache_mappings(options["mapping"])
            result = import_stock_cache(
                path=options["path"] or None,
                mappings=mappings,
                actor=options["actor"] or settings.TMSWMS_DEFAULT_ACTOR or "stock-cache-import",
                batch_size=options["batch_size"],
                uom=options["uom"],
                include_zero=options["include_zero"],
                allow_negative=options["allow_negative"],
                reset_state=options["reset_state"],
                dry_run=options["dry_run"],
            )
        except StockCacheImportError as exc:
            raise CommandError(str(exc)) from exc

        mappings_text = ", ".join(f"{mapping.stock_state}<={mapping.quantity_field}" for mapping in result.mappings)
        status = "DRY-RUN" if result.dry_run else "OK"
        self.stdout.write(f"{status} stock_cache: {result.source_path}")
        self.stdout.write(f"Mappings: {mappings_text}")
        self.stdout.write(
            "Filas={rows} candidatos={candidates} escritos={written} borrados={deleted}".format(
                rows=result.source_rows,
                candidates=result.candidate_balances,
                written=result.written_balances,
                deleted=result.deleted_balances,
            )
        )
        self.stdout.write(
            "Omitidos: claves_vacias={missing} ceros={zeros} invalidos={invalid} negativos_clampeados={negative}".format(
                missing=result.skipped_missing_keys,
                zeros=result.skipped_zero_quantity,
                invalid=result.invalid_quantities,
                negative=result.clamped_negative_quantities,
            )
        )
