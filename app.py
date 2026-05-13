from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import psycopg

from db import Database


APP_TABLES = [
    "airports",
    "airplanes",
    "positions",
    "crews",
    "services",
    "personnel",
    "routes",
    "transit_routes",
]


@dataclass
class TableState:
    table: str
    limit: int = 20
    offset: int = 0
    filter_col: Optional[str] = None
    filter_op: str = "="
    filter_val: Optional[str] = None
    order_col: Optional[str] = None
    order_dir: str = "ASC"


def _prompt(msg: str, *, default: Optional[str] = None) -> str:
    if default is None:
        try:
            return input(msg).strip()
        except EOFError:
            return ""
    v = input(f"{msg} [{default}] ").strip()
    return v if v else default


def _read_cmd(prompt: str = "> ") -> Optional[str]:
    try:
        return input(prompt).strip()
    except EOFError:
        return None


def _parse_timestamptz(v: str) -> datetime:
    # Accept: "YYYY-MM-DD HH:MM" or ISO.
    v = v.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            pass
    return datetime.fromisoformat(v)


def _print_rows(rows: list[dict[str, Any]], *, max_width: int = 28) -> None:
    if not rows:
        print("(нет данных)")
        return
    cols = list(rows[0].keys())
    widths: dict[str, int] = {c: min(max(len(str(c)), *(len(str(r.get(c, ""))) for r in rows)), max_width) for c in cols}

    def _cell(x: Any, w: int) -> str:
        s = "" if x is None else str(x)
        if len(s) > w:
            return s[: max(0, w - 1)] + "…"
        return s.ljust(w)

    header = " | ".join(_cell(c, widths[c]) for c in cols)
    sep = "-+-".join("-" * widths[c] for c in cols)
    print(header)
    print(sep)
    for r in rows:
        print(" | ".join(_cell(r.get(c), widths[c]) for c in cols))


def _build_select(state: TableState, cols: list[str]) -> tuple[str, list[Any]]:
    col_sql = ", ".join([f'"{c}"' for c in cols])
    sql = f'SELECT {col_sql} FROM "{state.table}"'
    params: list[Any] = []
    if state.filter_col and state.filter_val is not None:
        sql += f' WHERE "{state.filter_col}" {state.filter_op} %s'
        params.append(state.filter_val)
    if state.order_col:
        sql += f' ORDER BY "{state.order_col}" {state.order_dir}'
    sql += " LIMIT %s OFFSET %s"
    params.extend([state.limit, state.offset])
    return sql, params


def _table_mode(db: Database, table: str) -> None:
    state = TableState(table=table)
    cols_meta = db.table_columns(table)
    cols = [c.name for c in cols_meta]
    pk_cols = db.primary_keys(table)

    def _reload() -> list[dict[str, Any]]:
        sql, params = _build_select(state, cols)
        return db.query(sql, params)

    rows = _reload()
    idx = 0

    while True:
        print()
        print(f"Таблица: {table} | выборка {state.limit} | offset {state.offset} | строк: {len(rows)} | idx: {idx}")
        if state.filter_col:
            print(f"Фильтр: {state.filter_col} {state.filter_op} {state.filter_val}")
        if state.order_col:
            print(f"Сортировка: {state.order_col} {state.order_dir}")
        _print_rows(rows)
        print()
        print("Команды: n/p=перемещение, next/prev=страница, a=добавить, e=редакт, d=удалить,")
        print("         s=поиск (LIKE), f=фильтр, o=сортировка, r=перечитать, q=назад")

        cmd_raw = _read_cmd("> ")
        if cmd_raw is None:
            print()
            print("Ввод завершён (EOF). Выход в меню.")
            return
        cmd = cmd_raw.lower()
        if cmd in ("q", "quit", "exit"):
            return
        if cmd == "r":
            rows = _reload()
            idx = 0
            continue
        if cmd == "n":
            if rows:
                idx = min(idx + 1, len(rows) - 1)
            continue
        if cmd == "p":
            if rows:
                idx = max(idx - 1, 0)
            continue
        if cmd == "next":
            state.offset += state.limit
            rows = _reload()
            idx = 0
            continue
        if cmd == "prev":
            state.offset = max(0, state.offset - state.limit)
            rows = _reload()
            idx = 0
            continue
        if cmd == "o":
            col = _prompt(f"Поле сортировки ({', '.join(cols)}): ", default=state.order_col or cols[0])
            if col not in cols:
                print("Неизвестное поле.")
                continue
            direction = _prompt("Направление (ASC/DESC): ", default=state.order_dir).upper()
            if direction not in ("ASC", "DESC"):
                print("Неверное направление.")
                continue
            state.order_col = col
            state.order_dir = direction
            rows = _reload()
            idx = 0
            continue
        if cmd == "f":
            col = _prompt(f"Поле фильтра ({', '.join(cols)}), пусто=сброс: ", default=state.filter_col or "")
            if not col:
                state.filter_col = None
                state.filter_val = None
                rows = _reload()
                idx = 0
                continue
            if col not in cols:
                print("Неизвестное поле.")
                continue
            op = _prompt("Оператор (=, <, >, <=, >=, <>): ", default=state.filter_op)
            val = _prompt("Значение: ")
            state.filter_col = col
            state.filter_op = op
            state.filter_val = val
            rows = _reload()
            idx = 0
            continue
        if cmd == "s":
            col = _prompt(f"Поле поиска ({', '.join(cols)}): ", default=cols[0])
            if col not in cols:
                print("Неизвестное поле.")
                continue
            term = _prompt("Искомая подстрока: ")
            col_sql = ", ".join([f'"{c}"' for c in cols])
            sql = f'SELECT {col_sql} FROM "{table}" WHERE CAST("{col}" AS TEXT) ILIKE %s'
            params: list[Any] = [f"%{term}%"]
            if state.order_col:
                sql += f' ORDER BY "{state.order_col}" {state.order_dir}'
            sql += " LIMIT %s OFFSET %s"
            params.extend([state.limit, state.offset])
            rows = db.query(sql, params)
            idx = 0
            continue
        if cmd == "a":
            values: dict[str, Any] = {}
            print("Ввод (пусто = NULL/по умолчанию).")
            for c in cols_meta:
                if c.default is not None and c.name in pk_cols and "nextval" in c.default:
                    continue  # serial/bigserial
                raw = _prompt(f"{c.name} ({c.type}) = ")
                if raw == "":
                    continue
                values[c.name] = raw
            try:
                inserted = db.insert_row(table, values)
                print("Добавлено.")
                if inserted:
                    _print_rows([inserted])
            except psycopg.Error as e:
                print(f"Ошибка БД: {e}")
            rows = _reload()
            idx = 0
            continue
        if cmd == "e":
            if not rows:
                print("Нет текущей записи.")
                continue
            current = rows[idx]
            if not pk_cols:
                print("Таблица без PK — редактирование отключено.")
                continue
            pk_vals = [current[c] for c in pk_cols]
            values: dict[str, Any] = {}
            print("Редактирование (Enter = оставить как есть).")
            for c in cols_meta:
                old = current.get(c.name)
                raw = _prompt(f"{c.name} ({c.type})", default="" if old is None else str(old))
                if raw == ("" if old is None else str(old)):
                    continue
                # allow setting NULL explicitly
                if raw.upper() == "NULL":
                    values[c.name] = None
                else:
                    values[c.name] = raw
            try:
                db.update_row(table, pk_cols, pk_vals, values)
                print("Обновлено.")
            except psycopg.Error as e:
                print(f"Ошибка БД: {e}")
            rows = _reload()
            idx = 0
            continue
        if cmd == "d":
            if not rows:
                print("Нет текущей записи.")
                continue
            current = rows[idx]
            if not pk_cols:
                print("Таблица без PK — удаление отключено.")
                continue
            if _prompt("Точно удалить? (y/N): ", default="N").lower() != "y":
                continue
            pk_vals = [current[c] for c in pk_cols]
            try:
                db.delete_row(table, pk_cols, pk_vals)
                print("Удалено.")
            except psycopg.Error as e:
                print(f"Ошибка БД: {e}")
            rows = _reload()
            idx = 0
            continue

        print("Неизвестная команда.")


def _create_route_with_transit(db: Database) -> None:
    print()
    print("Создание маршрута (routes) + транзитные стоянки (transit_routes).")
    start_code = _prompt("start_airport_code: ")
    end_code = _prompt("end_airport_code: ")
    flight_hours = _prompt("flight_hours (например 2.5): ")
    airplane_airport_code = _prompt("airplane_airport_code (аэропорт приписки самолёта): ")
    airplane_code = _prompt("airplane_code: ")
    dep = _parse_timestamptz(_prompt('departure_time (YYYY-MM-DD HH:MM): '))
    flight_no = _prompt("flight_no (опц): ")
    notes = _prompt("notes (опц): ")

    with db.conn.transaction():
        route_row = db.insert_row(
            "routes",
            {
                "start_airport_code": start_code,
                "end_airport_code": end_code,
                "flight_hours": flight_hours,
                "airplane_airport_code": airplane_airport_code,
                "airplane_code": airplane_code,
                "departure_time": dep,
                "flight_no": flight_no or None,
                "notes": notes or None,
            },
        )
        if not route_row:
            raise RuntimeError("Route insert failed")
        route_code = route_row["route_code"]
        print(f"Маршрут создан: route_code={route_code}")

        stop_no = 1
        while True:
            add = _prompt("Добавить стоянку? (y/N): ", default="N").lower()
            if add != "y":
                break
            stop_airport_code = _prompt(" stop_airport_code: ")
            stand_no_raw = _prompt(" stand_no (опц): ")
            arr = _parse_timestamptz(_prompt(" arrival_time (YYYY-MM-DD HH:MM): "))
            dep2_raw = _prompt(" departure_time (опц, YYYY-MM-DD HH:MM): ")
            dep2 = _parse_timestamptz(dep2_raw) if dep2_raw else None
            stand_no = int(stand_no_raw) if stand_no_raw else None
            db.insert_row(
                "transit_routes",
                {
                    "route_code": route_code,
                    "stop_no": stop_no,
                    "stand_no": stand_no,
                    "stop_airport_code": stop_airport_code,
                    "arrival_time": arr,
                    "departure_time": dep2,
                },
            )
            stop_no += 1

    print("Готово.")


def _report_routes_to_destination(db: Database) -> None:
    print()
    print("Отчет: по конечному пункту назначения — возможные маршруты (включая транзит).")
    end_code = _prompt("Код конечного аэропорта (end_airport_code): ")
    sort = _prompt("Сортировка (1=departure_time, 2=flight_hours, 3=stops_count): ", default="1")
    sort_sql = {
        "1": 'r."departure_time"',
        "2": 'r."flight_hours"',
        "3": "stops_count",
    }.get(sort, 'r."departure_time"')
    direction = _prompt("Направление (ASC/DESC): ", default="ASC").upper()
    if direction not in ("ASC", "DESC"):
        direction = "ASC"

    rows = db.query(
        f"""
        SELECT
          r.route_code,
          r.start_airport_code,
          r.end_airport_code,
          r.departure_time,
          r.flight_hours,
          COALESCE(t.stops_count, 0) AS stops_count,
          CASE
            WHEN t.path IS NULL THEN r.start_airport_code || ' → ' || r.end_airport_code
            ELSE r.start_airport_code || ' → ' || t.path || ' → ' || r.end_airport_code
          END AS path,
          (r.flight_hours + COALESCE(t.ground_hours, 0)) AS total_trip_hours
        FROM routes r
        LEFT JOIN (
          SELECT
            route_code,
            COUNT(*) AS stops_count,
            STRING_AGG(stop_airport_code, ' → ' ORDER BY stop_no) AS path,
            SUM(
              GREATEST(
                0,
                EXTRACT(EPOCH FROM (COALESCE(departure_time, arrival_time) - arrival_time)) / 3600.0
              )
            ) AS ground_hours
          FROM transit_routes
          GROUP BY route_code
        ) t ON t.route_code = r.route_code
        WHERE r.end_airport_code = %s
        ORDER BY {sort_sql} {direction}
        """,
        (end_code,),
    )
    _print_rows(rows)
    print(f"Итого маршрутов: {len(rows)}")


def _report_upcoming_flights(db: Database) -> None:
    print()
    print("Отчет: список ближайших рейсов.")
    start_code = _prompt("Фильтр по стартовому аэропорту (опц): ")
    hours = int(_prompt("Окно в часах (например 24): ", default="24"))
    sort = _prompt("Сортировка (1=departure_time, 2=end_airport_code): ", default="1")
    sort_sql = {"1": 'r."departure_time"', "2": 'r."end_airport_code"'}.get(sort, 'r."departure_time"')
    direction = _prompt("Направление (ASC/DESC): ", default="ASC").upper()
    if direction not in ("ASC", "DESC"):
        direction = "ASC"

    params: list[Any] = [hours]
    where = 'r."departure_time" BETWEEN now() AND (now() + (%s::int * interval \'1 hour\'))'
    if start_code.strip():
        where += ' AND r."start_airport_code" = %s'
        params.append(start_code.strip())

    rows = db.query(
        f"""
        SELECT
          r.route_code,
          r.flight_no,
          r.start_airport_code,
          r.end_airport_code,
          r.departure_time,
          r.flight_hours,
          (r.departure_time + (r.flight_hours * interval '1 hour')) AS eta,
          a.name AS airplane_name
        FROM routes r
        JOIN airplanes a
          ON a.airport_code = r.airplane_airport_code
         AND a.airplane_code = r.airplane_code
        WHERE {where}
        ORDER BY {sort_sql} {direction}
        """,
        params,
    )
    _print_rows(rows)
    print(f"Итого рейсов: {len(rows)}")


def _report_personnel_by_service(db: Database) -> None:
    print()
    print("Отчет: персонал по службам и должностям (группировка + итоги).")
    airport_code = _prompt("Фильтр по аэропорту (опц): ")
    sort = _prompt("Сортировка (1=service, 2=count desc): ", default="1")
    order_sql = {
        "1": 's."name", p."name"',
        "2": "staff_count DESC, s.name, p.name",
    }.get(sort, 's."name", p."name"')

    params: list[Any] = []
    where = "TRUE"
    if airport_code.strip():
        where = 'per."airport_code" = %s'
        params.append(airport_code.strip())

    rows = db.query(
        f"""
        WITH base AS (
          SELECT
            per.airport_code,
            per.service_code,
            per.position_code,
            COUNT(*) AS staff_count,
            COUNT(DISTINCT per.crew_code) AS crews_involved,
            ROUND(COUNT(*)::numeric / NULLIF(COUNT(DISTINCT per.crew_code), 0), 2) AS avg_staff_per_crew
          FROM personnel per
          WHERE {where}
          GROUP BY per.airport_code, per.service_code, per.position_code
        )
        SELECT
          b.airport_code,
          s.name AS service_name,
          p.name AS position_name,
          b.staff_count,
          b.crews_involved,
          COALESCE(b.avg_staff_per_crew, b.staff_count::numeric) AS avg_staff_per_crew
        FROM base b
        JOIN services s ON s.service_code = b.service_code
        JOIN positions p ON p.position_code = b.position_code
        ORDER BY {order_sql}
        """,
        params,
    )
    _print_rows(rows)
    total = db.query(f'SELECT COUNT(*) AS total_staff FROM personnel per WHERE {where}', params)
    if total:
        print(f"Итого персонала: {total[0]['total_staff']}")


def _reports_menu(db: Database) -> None:
    while True:
        print()
        print("Отчеты:")
        print(" 1) Возможные маршруты по конечному пункту")
        print(" 2) Ближайшие рейсы")
        print(" 3) Персонал по службам/должностям (итоги)")
        print(" 0) Назад")
        c = _read_cmd("> ")
        if c is None:
            print()
            print("Ввод завершён (EOF). Выход в меню.")
            return
        c = c.strip()
        if c == "0":
            return
        if c == "1":
            _report_routes_to_destination(db)
        elif c == "2":
            _report_upcoming_flights(db)
        elif c == "3":
            _report_personnel_by_service(db)
        else:
            print("Неизвестный пункт.")


def main() -> None:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("PG_DSN")
    if not dsn:
        print("Нужен DSN для PostgreSQL.")
        print("Пример:")
        print('  export DATABASE_URL="postgresql://user:pass@localhost:5432/airdb"')
        return

    db = Database(dsn)
    try:
        while True:
            print()
            print("Главное меню:")
            print(" 1) Таблицы (CRUD)")
            print(" 2) Форма 1:M: маршрут + транзитные стоянки")
            print(" 3) Отчеты")
            print(" 0) Выход")
            c = _read_cmd("> ")
            if c is None:
                print()
                print("Ввод завершён (EOF). Завершение.")
                return
            c = c.strip()
            if c == "0":
                return
            if c == "1":
                while True:
                    print()
                    print("Таблицы:")
                    for i, t in enumerate(APP_TABLES, start=1):
                        print(f" {i}) {t}")
                    print(" 0) Назад")
                    cc = _read_cmd("> ")
                    if cc is None:
                        print()
                        print("Ввод завершён (EOF). Выход в меню.")
                        break
                    cc = cc.strip()
                    if cc == "0":
                        break
                    try:
                        idx = int(cc) - 1
                        if idx < 0 or idx >= len(APP_TABLES):
                            raise ValueError
                        _table_mode(db, APP_TABLES[idx])
                    except ValueError:
                        print("Неверный выбор.")
            elif c == "2":
                _create_route_with_transit(db)
            elif c == "3":
                _reports_menu(db)
            else:
                print("Неизвестный пункт.")
    finally:
        db.close()


if __name__ == "__main__":
    main()