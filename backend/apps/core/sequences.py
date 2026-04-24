from __future__ import annotations

from django.db import DatabaseError, connection, transaction
from django.utils import timezone


class SequenceConfigError(ValueError):
    pass


def _sequence_table_ref() -> str:
    if connection.vendor == "postgresql":
        return "public.maestros_pagos_sequenceconfig"
    return "maestros_pagos_sequenceconfig"


def allocate_sequence_number(name: str, *, actor: str) -> str:
    sequence_name = (name or "").strip()
    if not sequence_name:
        raise SequenceConfigError("El nombre de la secuencia es obligatorio.")

    table_ref = _sequence_table_ref()
    lock_clause = " FOR UPDATE" if connection.vendor == "postgresql" else ""
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        "RecId",
                        "Prefix",
                        "Suffix",
                        "PaddingLength",
                        "CurrentNumber",
                        "Increment",
                        "Active",
                        "Estado"
                    FROM {table_ref}
                    WHERE "Name" = %s
                    {lock_clause}
                    """,
                    [sequence_name],
                )
                rows = cursor.fetchall()
                if not rows:
                    raise SequenceConfigError(
                        f"No existe una secuencia activa configurada con Name='{sequence_name}'."
                    )
                if len(rows) > 1:
                    raise SequenceConfigError(
                        f"La secuencia Name='{sequence_name}' esta duplicada en maestros_pagos_sequenceconfig."
                    )

                rec_id, prefix, suffix, padding_length, current_number, increment, active, estado = rows[0]
                if not active or not estado:
                    raise SequenceConfigError(f"La secuencia Name='{sequence_name}' esta inactiva.")

                increment = int(increment or 0)
                if increment <= 0:
                    raise SequenceConfigError(
                        f"La secuencia Name='{sequence_name}' tiene un incremento invalido."
                    )

                next_number = int(current_number or 0) + increment
                cursor.execute(
                    f"""
                    UPDATE {table_ref}
                    SET
                        "CurrentNumber" = %s,
                        "ModificadoEn" = %s,
                        "ModificadoPor" = %s
                    WHERE "RecId" = %s
                    """,
                    [next_number, timezone.now(), (actor or "").strip(), rec_id],
                )
                if cursor.rowcount != 1:
                    raise SequenceConfigError(
                        f"No se pudo actualizar la secuencia Name='{sequence_name}'."
                    )
    except SequenceConfigError:
        raise
    except DatabaseError as exc:
        raise SequenceConfigError(
            f"No se pudo leer o actualizar public.maestros_pagos_sequenceconfig para Name='{sequence_name}'."
        ) from exc

    padded_number = str(next_number).zfill(max(int(padding_length or 0), 0))
    return f"{prefix or ''}{padded_number}{suffix or ''}"
