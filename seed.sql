-- Тестовые данные для демонстрации таблиц и отчётов в приложении.
-- Применение: psql -d airdb -f seed.sql
--
-- Очищает данные в дочерних таблицах и заполняет заново (идемпотентный набор).

BEGIN;

-- Одна команда: учитывает FK между transit_routes и routes; CASCADE снимает зависимости.
TRUNCATE TABLE
  transit_routes,
  routes,
  personnel,
  airplanes,
  airports,
  positions,
  crews,
  services
RESTART IDENTITY CASCADE;

-- Аэропорты (ИНН: 10 или 12 цифр по CHECK в схеме)
INSERT INTO airports (airport_code, name, inn, address, city, country, phone) VALUES
  ('SVO', 'Шереметьево', '7707083893', 'Московская обл.', 'Химки', 'Россия', '+7 495 578-65-65'),
  ('DME', 'Домодедово', '5001007327', 'д. Домодедово', 'Домодедово', 'Россия', '+7 495 933-66-66'),
  ('LED', 'Пулково', '7801234567', 'ул. Пулковское шоссе', 'Санкт-Петербург', 'Россия', '+7 812 337-38-22'),
  ('KGD', 'Храброво', '3900000001', 'пос. Храброво', 'Калининград', 'Россия', '+7 4012 610-888'),
  ('SVX', 'Кольцово', '6608000000', 'ул. Бахчиванджи', 'Екатеринбург', 'Россия', '+7 343 267-88-88');

INSERT INTO positions (position_code, name) VALUES
  ('PILOT', 'Пилот'),
  ('NAV', 'Штурман'),
  ('DISP', 'Диспетчер');

INSERT INTO crews (crew_code, name) VALUES
  ('CRW01', 'Экипаж «Север»'),
  ('CRW02', 'Экипаж «Орион»');

INSERT INTO services (service_code, name) VALUES
  ('GND', 'Наземное обслуживание'),
  ('SEC', 'Авиационная безопасность');

INSERT INTO airplanes (airport_code, airplane_code, name, model, seats) VALUES
  ('SVO', 'SU321', 'Airbus A321', 'A321-200', 180),
  ('SVO', 'SU773', 'Boeing 777-300ER', 'B777-300ER', 350),
  ('DME', 'U6232', 'Boeing 737-800', 'B737-800', 189),
  ('LED', 'DP190', 'Airbus A320', 'A320neo', 174);

INSERT INTO personnel (airport_code, person_inn, full_name, position_code, crew_code, service_code, hired_at) VALUES
  ('SVO', '770123456789', 'Иванов Иван Иванович', 'PILOT', 'CRW01', 'GND', '2018-03-01'),
  ('SVO', '770123456788', 'Петрова Мария Сергеевна', 'NAV', 'CRW01', 'GND', '2019-07-15'),
  ('SVO', '770123456787', 'Сидоров Алексей Петрович', 'DISP', NULL, 'SEC', '2020-01-10'),
  ('DME', '500123456789', 'Козлов Дмитрий Олегович', 'PILOT', 'CRW02', 'GND', '2017-11-20'),
  ('LED', '780123456789', 'Смирнова Елена Викторовна', 'DISP', NULL, 'SEC', '2021-05-01'),
  ('LED', '780123456788', 'Волков Павел Николаевич', 'PILOT', 'CRW02', 'GND', '2022-02-14');

-- Маршруты: часть с вылетом в ближайшие часы (для отчёта «ближайшие рейсы»)
INSERT INTO routes (
  start_airport_code, end_airport_code, flight_hours,
  airplane_airport_code, airplane_code, departure_time, flight_no, notes
) VALUES
  ('SVO', 'LED', 1.50, 'SVO', 'SU321', now() + interval '45 minutes', 'SU100', 'Прямой'),
  ('DME', 'LED', 1.75, 'DME', 'U6232', now() + interval '2 hours', 'U6102', 'Прямой'),
  ('SVO', 'KGD', 2.25, 'SVO', 'SU773', now() + interval '5 hours', 'SU204', 'С пересадкой в LED'),
  ('LED', 'SVX', 2.80, 'LED', 'DP190', now() + interval '26 hours', 'DP33', 'Прямой'),
  ('SVO', 'SVX', 3.50, 'SVO', 'SU321', now() + interval '30 hours', 'SU150', 'Прямой'),
  ('LED', 'KGD', 1.20, 'LED', 'DP190', now() + interval '3 days', 'DP901', 'Редкий рейс'),
  ('DME', 'KGD', 2.00, 'DME', 'U6232', now() + interval '4 days', 'U6200', 'Прямой');

-- Транзит: маршрут SVO -> KGD через LED (route_code = 3 после RESTART IDENTITY если только seed)
WITH r AS (
  SELECT route_code, departure_time
  FROM routes
  WHERE flight_no = 'SU204'
  LIMIT 1
)
INSERT INTO transit_routes (route_code, stop_no, stand_no, stop_airport_code, arrival_time, departure_time)
SELECT
  r.route_code,
  1,
  12,
  'LED',
  r.departure_time + interval '1 hour 10 minutes',
  r.departure_time + interval '1 hour 40 minutes'
FROM r;

COMMIT;
