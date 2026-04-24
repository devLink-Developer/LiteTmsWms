from __future__ import annotations

import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections


class Command(BaseCommand):
    help = "Creates the isolated TMS/WMS PostgreSQL schema used by Django migrations."

    def add_arguments(self, parser):
        parser.add_argument("--database", default="default")

    def handle(self, *args, **options):
        database = options["database"]
        schema = settings.TMSWMS_DB_SCHEMA
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", schema):
            raise CommandError("TMSWMS_DB_SCHEMA must be a simple PostgreSQL identifier.")

        connection = connections[database]
        if connection.vendor != "postgresql":
            self.stdout.write(self.style.WARNING(f"{database} is not PostgreSQL; schema bootstrap skipped."))
            return

        with connection.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            cursor.execute("SHOW search_path")
            search_path = cursor.fetchone()[0]
            cursor.execute("SELECT current_schema()")
            current_schema = cursor.fetchone()[0]

        self.stdout.write(self.style.SUCCESS(f'Schema "{schema}" is available on {database}.'))
        self.stdout.write(f"search_path={search_path}")
        self.stdout.write(f"current_schema={current_schema}")
        if current_schema != schema:
            raise CommandError(
                f'Current schema is "{current_schema}", expected "{schema}". '
                "Check DATABASES default OPTIONS before running migrations."
            )
