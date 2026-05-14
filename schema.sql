BEGIN;

CREATE TABLE IF NOT EXISTS airports (
  airport_code        VARCHAR(10) PRIMARY KEY,
  name                TEXT NOT NULL,
  inn                 VARCHAR(12) NOT NULL,
  address             TEXT,
  city                TEXT,
  country             TEXT,
  phone               TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  departures_count    INTEGER NOT NULL DEFAULT 0,
  arrivals_count      INTEGER NOT NULL DEFAULT 0,
  CONSTRAINT airports_inn_chk CHECK (inn ~ '^[0-9]{10}([0-9]{2})?$'),
  CONSTRAINT airports_dep_chk CHECK (departures_count >= 0),
  CONSTRAINT airports_arr_chk CHECK (arrivals_count >= 0)
);

CREATE TABLE IF NOT EXISTS positions (
  position_code       VARCHAR(20) PRIMARY KEY,
  name                TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS crews (
  crew_code           VARCHAR(20) PRIMARY KEY,
  name                TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS services (
  service_code        VARCHAR(20) PRIMARY KEY,
  name                TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS airplanes (
  airport_code        VARCHAR(10) NOT NULL,
  airplane_code       VARCHAR(20) NOT NULL,
  name                TEXT NOT NULL,
  model               TEXT,
  seats               INTEGER CHECK (seats IS NULL OR seats > 0),
  in_service          BOOLEAN NOT NULL DEFAULT TRUE,
  routes_assigned_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (airport_code, airplane_code),
  CONSTRAINT airplanes_airport_fk
    FOREIGN KEY (airport_code) REFERENCES airports(airport_code)
      ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT airplanes_routes_cnt_chk CHECK (routes_assigned_count >= 0)
);

CREATE TABLE IF NOT EXISTS personnel (
  airport_code        VARCHAR(10) NOT NULL,
  person_inn          VARCHAR(12) NOT NULL,
  full_name           TEXT NOT NULL,
  position_code       VARCHAR(20) NOT NULL,
  crew_code           VARCHAR(20),
  service_code        VARCHAR(20) NOT NULL,
  hired_at            DATE,
  PRIMARY KEY (airport_code, person_inn),
  CONSTRAINT personnel_inn_chk CHECK (person_inn ~ '^[0-9]{10}([0-9]{2})?$'),
  CONSTRAINT personnel_airport_fk
    FOREIGN KEY (airport_code) REFERENCES airports(airport_code)
      ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT personnel_position_fk
    FOREIGN KEY (position_code) REFERENCES positions(position_code)
      ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT personnel_crew_fk
    FOREIGN KEY (crew_code) REFERENCES crews(crew_code)
      ON UPDATE CASCADE ON DELETE SET NULL,
  CONSTRAINT personnel_service_fk
    FOREIGN KEY (service_code) REFERENCES services(service_code)
      ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS routes (
  route_code              BIGSERIAL PRIMARY KEY,
  start_airport_code      VARCHAR(10) NOT NULL,
  end_airport_code        VARCHAR(10) NOT NULL,
  flight_hours            NUMERIC(6,2) NOT NULL,
  airplane_airport_code   VARCHAR(10) NOT NULL,
  airplane_code           VARCHAR(20) NOT NULL,
  departure_time          TIMESTAMPTZ NOT NULL,
  flight_no               TEXT,
  notes                   TEXT,
  transit_stop_count      INTEGER NOT NULL DEFAULT 0,
  CONSTRAINT routes_hours_chk CHECK (flight_hours > 0),
  CONSTRAINT routes_transit_cnt_chk CHECK (transit_stop_count >= 0),
  CONSTRAINT routes_start_fk
    FOREIGN KEY (start_airport_code) REFERENCES airports(airport_code)
      ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT routes_end_fk
    FOREIGN KEY (end_airport_code) REFERENCES airports(airport_code)
      ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT routes_airplane_fk
    FOREIGN KEY (airplane_airport_code, airplane_code)
      REFERENCES airplanes(airport_code, airplane_code)
      ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS transit_routes (
  route_code            BIGINT NOT NULL,
  stop_no               INTEGER NOT NULL,
  stand_no              INTEGER,
  stop_airport_code     VARCHAR(10) NOT NULL,
  arrival_time          TIMESTAMPTZ NOT NULL,
  departure_time        TIMESTAMPTZ,
  PRIMARY KEY (route_code, stop_no),
  CONSTRAINT transit_routes_route_fk
    FOREIGN KEY (route_code) REFERENCES routes(route_code)
      ON UPDATE CASCADE ON DELETE CASCADE,
  CONSTRAINT transit_routes_airport_fk
    FOREIGN KEY (stop_airport_code) REFERENCES airports(airport_code)
      ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT transit_routes_times_chk CHECK (
    departure_time IS NULL OR departure_time >= arrival_time
  )
);

CREATE INDEX IF NOT EXISTS idx_airports_city ON airports(city);
CREATE INDEX IF NOT EXISTS idx_airplanes_airport ON airplanes(airport_code);
CREATE INDEX IF NOT EXISTS idx_personnel_airport ON personnel(airport_code);
CREATE INDEX IF NOT EXISTS idx_personnel_service ON personnel(service_code);
CREATE INDEX IF NOT EXISTS idx_routes_departure ON routes(departure_time);
CREATE INDEX IF NOT EXISTS idx_routes_start_end ON routes(start_airport_code, end_airport_code);
CREATE INDEX IF NOT EXISTS idx_transit_route ON transit_routes(route_code);

ALTER TABLE airports ADD COLUMN IF NOT EXISTS departures_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE airports ADD COLUMN IF NOT EXISTS arrivals_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE airplanes ADD COLUMN IF NOT EXISTS routes_assigned_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE routes ADD COLUMN IF NOT EXISTS transit_stop_count INTEGER NOT NULL DEFAULT 0;


CREATE OR REPLACE FUNCTION refresh_airport_route_totals(p_airport_code VARCHAR)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
  UPDATE airports
  SET
    departures_count = (SELECT COUNT(*)::integer FROM routes r WHERE r.start_airport_code = airports.airport_code),
    arrivals_count   = (SELECT COUNT(*)::integer FROM routes r WHERE r.end_airport_code = airports.airport_code)
  WHERE airport_code = p_airport_code;
END;
$$;

CREATE OR REPLACE FUNCTION refresh_airplane_route_usage(p_airport_code VARCHAR, p_airplane_code VARCHAR)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
  UPDATE airplanes
  SET routes_assigned_count = (
    SELECT COUNT(*)::integer
    FROM routes r
    WHERE r.airplane_airport_code = airplanes.airport_code
      AND r.airplane_code = airplanes.airplane_code
  )
  WHERE airport_code = p_airport_code
    AND airplane_code = p_airplane_code;
END;
$$;

CREATE OR REPLACE FUNCTION refresh_route_transit_stop_count(p_route_code BIGINT)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
  UPDATE routes
  SET transit_stop_count = (
    SELECT COUNT(*)::integer FROM transit_routes t WHERE t.route_code = routes.route_code
  )
  WHERE route_code = p_route_code;
END;
$$;

CREATE OR REPLACE FUNCTION trg_transit_routes_refresh_route_count()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  rc BIGINT;
BEGIN
  IF TG_OP = 'DELETE' THEN
    rc := OLD.route_code;
  ELSE
    rc := NEW.route_code;
  END IF;
  PERFORM refresh_route_transit_stop_count(rc);
  IF TG_OP = 'UPDATE' AND OLD.route_code IS DISTINCT FROM NEW.route_code THEN
    PERFORM refresh_route_transit_stop_count(OLD.route_code);
  END IF;
  RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE OR REPLACE FUNCTION trg_routes_refresh_airports_and_plane()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  acode VARCHAR;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF OLD.start_airport_code IS NOT DISTINCT FROM NEW.start_airport_code
       AND OLD.end_airport_code IS NOT DISTINCT FROM NEW.end_airport_code
       AND OLD.airplane_airport_code IS NOT DISTINCT FROM NEW.airplane_airport_code
       AND OLD.airplane_code IS NOT DISTINCT FROM NEW.airplane_code THEN
      RETURN NEW;
    END IF;
  END IF;

  IF TG_OP = 'INSERT' THEN
    PERFORM refresh_airport_route_totals(NEW.start_airport_code);
    PERFORM refresh_airport_route_totals(NEW.end_airport_code);
    PERFORM refresh_airplane_route_usage(NEW.airplane_airport_code, NEW.airplane_code);
  ELSIF TG_OP = 'DELETE' THEN
    PERFORM refresh_airport_route_totals(OLD.start_airport_code);
    PERFORM refresh_airport_route_totals(OLD.end_airport_code);
    PERFORM refresh_airplane_route_usage(OLD.airplane_airport_code, OLD.airplane_code);
  ELSE
    FOR acode IN
      SELECT DISTINCT x FROM unnest(ARRAY[
        OLD.start_airport_code,
        NEW.start_airport_code,
        OLD.end_airport_code,
        NEW.end_airport_code
      ]) AS t(x)
    LOOP
      PERFORM refresh_airport_route_totals(acode);
    END LOOP;
    IF OLD.airplane_airport_code IS DISTINCT FROM NEW.airplane_airport_code
       OR OLD.airplane_code IS DISTINCT FROM NEW.airplane_code THEN
      PERFORM refresh_airplane_route_usage(OLD.airplane_airport_code, OLD.airplane_code);
    END IF;
    PERFORM refresh_airplane_route_usage(NEW.airplane_airport_code, NEW.airplane_code);
  END IF;

  RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS tr_transit_routes_denorm ON transit_routes;
CREATE TRIGGER tr_transit_routes_denorm
  AFTER INSERT OR UPDATE OR DELETE ON transit_routes
  FOR EACH ROW
  EXECUTE FUNCTION trg_transit_routes_refresh_route_count();

DROP TRIGGER IF EXISTS tr_routes_denorm ON routes;
CREATE TRIGGER tr_routes_denorm
  AFTER INSERT OR UPDATE OR DELETE ON routes
  FOR EACH ROW
  EXECUTE FUNCTION trg_routes_refresh_airports_and_plane();

UPDATE routes r
SET transit_stop_count = (
  SELECT COUNT(*)::integer FROM transit_routes t WHERE t.route_code = r.route_code
);

UPDATE airports a
SET
  departures_count = (SELECT COUNT(*)::integer FROM routes r WHERE r.start_airport_code = a.airport_code),
  arrivals_count   = (SELECT COUNT(*)::integer FROM routes r WHERE r.end_airport_code = a.airport_code);

UPDATE airplanes p
SET routes_assigned_count = (
  SELECT COUNT(*)::integer
  FROM routes r
  WHERE r.airplane_airport_code = p.airport_code
    AND r.airplane_code = p.airplane_code
);

DROP VIEW IF EXISTS v_route_schedule CASCADE;
DROP VIEW IF EXISTS v_airports_departures_agg CASCADE;
DROP VIEW IF EXISTS v_airports_catalog CASCADE;

CREATE VIEW v_airports_catalog AS
SELECT
  airport_code,
  name,
  inn,
  address,
  city,
  country,
  phone,
  created_at,
  departures_count,
  arrivals_count
FROM airports;

CREATE VIEW v_route_schedule AS
SELECT
  r.route_code,
  r.flight_no,
  r.departure_time,
  r.flight_hours,
  r.transit_stop_count,
  r.start_airport_code,
  sa.name AS start_airport_name,
  r.end_airport_code,
  ea.name AS end_airport_name,
  r.airplane_airport_code,
  r.airplane_code,
  pl.name AS airplane_name
FROM routes r
JOIN airports sa ON sa.airport_code = r.start_airport_code
JOIN airports ea ON ea.airport_code = r.end_airport_code
JOIN airplanes pl
  ON pl.airport_code = r.airplane_airport_code
 AND pl.airplane_code = r.airplane_code;

CREATE VIEW v_airports_departures_agg AS
SELECT
  a.airport_code,
  a.name AS airport_name,
  COUNT(r.route_code) AS departure_routes,
  COALESCE(SUM(r.transit_stop_count), 0) AS total_transit_stops
FROM airports a
JOIN routes r ON r.start_airport_code = a.airport_code
GROUP BY a.airport_code, a.name
HAVING COUNT(r.route_code) >= 1;

COMMIT;

