from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    notnull: bool
    pk: bool
    default: Optional[str]


class Database:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=True)

    def close(self) -> None:
        self.conn.close()

    def execute_script(self, sql: str) -> None:
        # psycopg executes one statement at a time; we keep schema.sql as a file and
        # rely on `psql -f` for initial setup. Still, allow scripts for small admin tasks.
        with self.conn.cursor() as cur:
            for stmt in _split_sql_statements(sql):
                if stmt.strip():
                    cur.execute(stmt)

    def execute(self, sql: str, params: Iterable[Any] = ()) -> psycopg.Cursor[Any]:
        cur = self.conn.cursor()
        cur.execute(sql, tuple(params))
        return cur

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return list(cur.fetchall())

    def list_tables(self) -> list[str]:
        rows = self.query(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        )
        return [str(r["table_name"]) for r in rows]

    def table_columns(self, table: str) -> list[Column]:
        rows = self.query(
            """
            SELECT
              c.column_name,
              c.data_type,
              c.is_nullable,
              c.column_default,
              (tc.constraint_type = 'PRIMARY KEY') AS is_pk
            FROM information_schema.columns c
            LEFT JOIN information_schema.key_column_usage kcu
              ON kcu.table_schema = c.table_schema
             AND kcu.table_name = c.table_name
             AND kcu.column_name = c.column_name
            LEFT JOIN information_schema.table_constraints tc
              ON tc.table_schema = kcu.table_schema
             AND tc.table_name = kcu.table_name
             AND tc.constraint_name = kcu.constraint_name
            WHERE c.table_schema = 'public'
              AND c.table_name = %s
            ORDER BY c.ordinal_position
            """,
            (table,),
        )
        return [
            Column(
                name=str(r["column_name"]),
                type=str(r["data_type"] or ""),
                notnull=(str(r["is_nullable"]) == "NO"),
                pk=bool(r["is_pk"]),
                default=(str(r["column_default"]) if r["column_default"] is not None else None),
            )
            for r in rows
        ]

    def primary_keys(self, table: str) -> list[str]:
        rows = self.query(
            """
            SELECT a.attname AS column_name
            FROM pg_index i
            JOIN pg_class t ON t.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(i.indkey)
            WHERE i.indisprimary
              AND n.nspname = 'public'
              AND t.relname = %s
            ORDER BY array_position(i.indkey, a.attnum)
            """,
            (table,),
        )
        return [str(r["column_name"]) for r in rows]

    def primary_key(self, table: str) -> str:
        pk = self.primary_keys(table)
        if len(pk) != 1:
            raise ValueError(f"Expected single-column PK for table '{table}', got {pk}")
        return pk[0]

    def insert_row(self, table: str, values: dict[str, Any]) -> Optional[dict[str, Any]]:
        cols = list(values.keys())
        if not cols:
            raise ValueError("No values to insert")
        placeholders = ", ".join(["%s"] * len(cols))
        col_sql = ", ".join([f'"{c}"' for c in cols])
        sql = f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders}) RETURNING *;'
        with self.conn.cursor() as cur:
            cur.execute(sql, [values[c] for c in cols])
            row = cur.fetchone()
            return dict(row) if row is not None else None

    def update_row(
        self, table: str, pk_cols: Sequence[str], pk_vals: Sequence[Any], values: dict[str, Any]
    ) -> None:
        if len(pk_cols) != len(pk_vals):
            raise ValueError("PK columns/values mismatch")
        set_cols = [c for c in values.keys() if c not in pk_cols]
        if not set_cols:
            return
        set_sql = ", ".join([f'"{c}" = %s' for c in set_cols])
        where_sql = " AND ".join([f'"{c}" = %s' for c in pk_cols])
        sql = f'UPDATE "{table}" SET {set_sql} WHERE {where_sql};'
        params = [values[c] for c in set_cols] + list(pk_vals)
        self.execute(sql, params)

    def delete_row(self, table: str, pk_cols: Sequence[str], pk_vals: Sequence[Any]) -> None:
        where_sql = " AND ".join([f'"{c}" = %s' for c in pk_cols])
        sql = f'DELETE FROM "{table}" WHERE {where_sql};'
        self.execute(sql, list(pk_vals))


def _split_sql_statements(sql: str) -> list[str]:
    # Minimal splitter: good enough for simple scripts (not for complex PL/pgSQL).
    statements: list[str] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        if ch == ";" and not in_single and not in_double:
            statements.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements

