-- DataPilot Demo SQL Server Database
-- Runs automatically on first container start via entrypoint

-- Wait for SQL Server to be ready (retry logic is in the shell entrypoint)
-- Create database
IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = 'DemoDB')
BEGIN
    CREATE DATABASE DemoDB;
END
GO

USE DemoDB;
GO

-- Create demo schema
IF NOT EXISTS (SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'demo')
BEGIN
    EXEC('CREATE SCHEMA demo');
END
GO

-- ─────────────────────────────────────────
-- CUSTOMERS
-- ─────────────────────────────────────────
IF NOT EXISTS (SELECT * FROM information_schema.tables
               WHERE table_schema = 'demo' AND table_name = 'customers')
BEGIN
    CREATE TABLE demo.customers (
        customer_id   INT          PRIMARY KEY IDENTITY(1,1),
        first_name    NVARCHAR(80)  NOT NULL,
        last_name     NVARCHAR(80)  NOT NULL,
        email         NVARCHAR(200) NOT NULL,
        phone         NVARCHAR(30),
        status        NVARCHAR(20)  NOT NULL DEFAULT 'active',
        segment       NVARCHAR(40)  NOT NULL DEFAULT 'retail',
        created_at    DATETIME2     NOT NULL DEFAULT GETUTCDATE()
    );

    INSERT INTO demo.customers (first_name, last_name, email, phone, status, segment)
    VALUES
        ('Alice',   'Morgan',   'alice.morgan@example.com',   '555-0101', 'active',   'retail'),
        ('Bob',     'Chen',     'bob.chen@example.com',       '555-0102', 'active',   'premium'),
        ('Carol',   'Davis',    'carol.davis@example.com',    '555-0103', 'inactive', 'retail'),
        ('David',   'Kim',      'david.kim@example.com',      '555-0104', 'active',   'corporate'),
        ('Eva',     'Patel',    'eva.patel@example.com',      '555-0105', 'active',   'premium'),
        ('Frank',   'Lopez',    'frank.lopez@example.com',    '555-0106', 'active',   'retail'),
        ('Grace',   'Wilson',   'grace.wilson@example.com',   '555-0107', 'suspended','retail'),
        ('Hiro',    'Tanaka',   'hiro.tanaka@example.com',    '555-0108', 'active',   'corporate'),
        ('Iris',    'Brown',    'iris.brown@example.com',     '555-0109', 'active',   'retail'),
        ('James',   'Smith',    'james.smith@example.com',    '555-0110', 'inactive', 'premium');
END
GO

-- ─────────────────────────────────────────
-- ORDERS
-- ─────────────────────────────────────────
IF NOT EXISTS (SELECT * FROM information_schema.tables
               WHERE table_schema = 'demo' AND table_name = 'orders')
BEGIN
    CREATE TABLE demo.orders (
        order_id      INT           PRIMARY KEY IDENTITY(1001,1),
        customer_id   INT           NOT NULL,
        order_date    DATE          NOT NULL,
        status        NVARCHAR(20)  NOT NULL DEFAULT 'pending',
        total_amount  DECIMAL(12,2) NOT NULL,
        currency      NCHAR(3)      NOT NULL DEFAULT 'USD',
        notes         NVARCHAR(500)
    );

    INSERT INTO demo.orders (customer_id, order_date, status, total_amount, currency, notes)
    VALUES
        (1, '2026-01-15', 'completed', 245.00, 'USD', 'Standard delivery'),
        (2, '2026-01-20', 'completed', 1890.50,'USD', 'Priority shipping'),
        (3, '2026-02-01', 'cancelled', 75.25,  'USD', 'Customer request'),
        (4, '2026-02-10', 'completed', 4200.00,'USD', 'Corporate bulk order'),
        (5, '2026-02-18', 'processing',320.99, 'USD', NULL),
        (1, '2026-03-05', 'completed', 88.00,  'USD', NULL),
        (6, '2026-03-12', 'completed', 155.75, 'USD', 'Gift wrap requested'),
        (7, '2026-03-20', 'pending',   45.00,  'USD', NULL),
        (8, '2026-04-01', 'completed', 6750.00,'USD', 'Annual corporate contract'),
        (9, '2026-04-15', 'processing',210.30, 'USD', NULL);
END
GO

-- ─────────────────────────────────────────
-- PAYMENTS
-- ─────────────────────────────────────────
IF NOT EXISTS (SELECT * FROM information_schema.tables
               WHERE table_schema = 'demo' AND table_name = 'payments')
BEGIN
    CREATE TABLE demo.payments (
        payment_id    INT           PRIMARY KEY IDENTITY(5001,1),
        order_id      INT           NOT NULL,
        payment_date  DATE          NOT NULL,
        method        NVARCHAR(30)  NOT NULL,
        amount        DECIMAL(12,2) NOT NULL,
        status        NVARCHAR(20)  NOT NULL DEFAULT 'pending',
        reference     NVARCHAR(80)
    );

    INSERT INTO demo.payments (order_id, payment_date, method, amount, status, reference)
    VALUES
        (1001, '2026-01-15', 'credit_card', 245.00,  'settled',  'TXN-AA001'),
        (1002, '2026-01-20', 'bank_transfer',1890.50,'settled',  'TXN-BB002'),
        (1003, '2026-02-01', 'credit_card', 75.25,   'refunded', 'TXN-CC003'),
        (1004, '2026-02-10', 'bank_transfer',4200.00,'settled',  'TXN-DD004'),
        (1005, '2026-02-18', 'credit_card', 320.99,  'pending',  'TXN-EE005'),
        (1006, '2026-03-05', 'debit_card',  88.00,   'settled',  'TXN-FF006'),
        (1007, '2026-03-12', 'credit_card', 155.75,  'settled',  'TXN-GG007'),
        (1008, '2026-03-20', 'credit_card', 45.00,   'pending',  'TXN-HH008'),
        (1009, '2026-04-01', 'bank_transfer',6750.00,'settled',  'TXN-II009'),
        (1010, '2026-04-15', 'debit_card',  210.30,  'pending',  'TXN-JJ010');
END
GO
