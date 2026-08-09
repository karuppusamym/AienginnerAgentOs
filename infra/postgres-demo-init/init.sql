-- DataPilot Demo PostgreSQL Database
-- Runs automatically on first container start (mounted to /docker-entrypoint-initdb.d/)

-- Create demo schema
CREATE SCHEMA IF NOT EXISTS demo;

-- ─────────────────────────────────────────
-- CUSTOMERS
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS demo.customers (
    customer_id  SERIAL       PRIMARY KEY,
    first_name   VARCHAR(80)  NOT NULL,
    last_name    VARCHAR(80)  NOT NULL,
    email        VARCHAR(200) NOT NULL,
    phone        VARCHAR(30),
    status       VARCHAR(20)  NOT NULL DEFAULT 'active',
    segment      VARCHAR(40)  NOT NULL DEFAULT 'retail',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

INSERT INTO demo.customers (first_name, last_name, email, phone, status, segment)
SELECT * FROM (VALUES
    ('Alice',  'Morgan', 'alice.morgan@demobank.io',  '555-0201', 'active',    'retail'),
    ('Bob',    'Chen',   'bob.chen@demobank.io',      '555-0202', 'active',    'premium'),
    ('Carol',  'Davis',  'carol.davis@demobank.io',   '555-0203', 'inactive',  'retail'),
    ('David',  'Kim',    'david.kim@demobank.io',     '555-0204', 'active',    'corporate'),
    ('Eva',    'Patel',  'eva.patel@demobank.io',     '555-0205', 'active',    'premium'),
    ('Frank',  'Lopez',  'frank.lopez@demobank.io',   '555-0206', 'active',    'retail'),
    ('Grace',  'Wilson', 'grace.wilson@demobank.io',  '555-0207', 'suspended', 'retail'),
    ('Hiro',   'Tanaka', 'hiro.tanaka@demobank.io',   '555-0208', 'active',    'corporate'),
    ('Iris',   'Brown',  'iris.brown@demobank.io',    '555-0209', 'active',    'retail'),
    ('James',  'Smith',  'james.smith@demobank.io',   '555-0210', 'inactive',  'premium')
) AS v(first_name, last_name, email, phone, status, segment)
WHERE NOT EXISTS (SELECT 1 FROM demo.customers LIMIT 1);

-- ─────────────────────────────────────────
-- ORDERS
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS demo.orders (
    order_id     SERIAL         PRIMARY KEY,
    customer_id  INT            NOT NULL,
    order_date   DATE           NOT NULL,
    status       VARCHAR(20)    NOT NULL DEFAULT 'pending',
    total_amount NUMERIC(12,2)  NOT NULL,
    currency     CHAR(3)        NOT NULL DEFAULT 'USD',
    notes        TEXT
);

INSERT INTO demo.orders (customer_id, order_date, status, total_amount, currency, notes)
SELECT * FROM (VALUES
    (1, '2026-01-15'::date, 'completed',  245.00,  'USD', 'Standard delivery'),
    (2, '2026-01-20'::date, 'completed',  1890.50, 'USD', 'Priority shipping'),
    (3, '2026-02-01'::date, 'cancelled',  75.25,   'USD', 'Customer request'),
    (4, '2026-02-10'::date, 'completed',  4200.00, 'USD', 'Corporate bulk order'),
    (5, '2026-02-18'::date, 'processing', 320.99,  'USD', NULL),
    (1, '2026-03-05'::date, 'completed',  88.00,   'USD', NULL),
    (6, '2026-03-12'::date, 'completed',  155.75,  'USD', 'Gift wrap requested'),
    (7, '2026-03-20'::date, 'pending',    45.00,   'USD', NULL),
    (8, '2026-04-01'::date, 'completed',  6750.00, 'USD', 'Annual corporate contract'),
    (9, '2026-04-15'::date, 'processing', 210.30,  'USD', NULL)
) AS v(customer_id, order_date, status, total_amount, currency, notes)
WHERE NOT EXISTS (SELECT 1 FROM demo.orders LIMIT 1);

-- ─────────────────────────────────────────
-- PAYMENTS
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS demo.payments (
    payment_id   SERIAL         PRIMARY KEY,
    order_id     INT            NOT NULL,
    payment_date DATE           NOT NULL,
    method       VARCHAR(30)    NOT NULL,
    amount       NUMERIC(12,2)  NOT NULL,
    status       VARCHAR(20)    NOT NULL DEFAULT 'pending',
    reference    VARCHAR(80)
);

INSERT INTO demo.payments (order_id, payment_date, method, amount, status, reference)
SELECT * FROM (VALUES
    (1, '2026-01-15'::date, 'credit_card',   245.00,  'settled',  'TXN-PG001'),
    (2, '2026-01-20'::date, 'bank_transfer', 1890.50, 'settled',  'TXN-PG002'),
    (3, '2026-02-01'::date, 'credit_card',   75.25,   'refunded', 'TXN-PG003'),
    (4, '2026-02-10'::date, 'bank_transfer', 4200.00, 'settled',  'TXN-PG004'),
    (5, '2026-02-18'::date, 'credit_card',   320.99,  'pending',  'TXN-PG005'),
    (6, '2026-03-05'::date, 'debit_card',    88.00,   'settled',  'TXN-PG006'),
    (7, '2026-03-12'::date, 'credit_card',   155.75,  'settled',  'TXN-PG007'),
    (8, '2026-03-20'::date, 'credit_card',   45.00,   'pending',  'TXN-PG008'),
    (9, '2026-04-01'::date, 'bank_transfer', 6750.00, 'settled',  'TXN-PG009'),
    (10,'2026-04-15'::date, 'debit_card',    210.30,  'pending',  'TXN-PG010')
) AS v(order_id, payment_date, method, amount, status, reference)
WHERE NOT EXISTS (SELECT 1 FROM demo.payments LIMIT 1);
