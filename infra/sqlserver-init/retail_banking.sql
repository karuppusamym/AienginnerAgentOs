-- RetailBanking: the live database behind the "Banking demo warehouse" connector.
-- Same tables and columns as its catalog entries (core.customers, core.accounts,
-- activity.transactions), filled with deterministic sample data so chat, SQL and
-- query tools return real rows. Idempotent: safe to run on every container start.

IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = 'RetailBanking')
BEGIN
    CREATE DATABASE RetailBanking;
END
GO

USE RetailBanking;
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'core') EXEC('CREATE SCHEMA core');
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'activity') EXEC('CREATE SCHEMA activity');
GO

IF OBJECT_ID('core.customers') IS NULL
CREATE TABLE core.customers (
    customer_id BIGINT NOT NULL PRIMARY KEY,
    segment VARCHAR(20) NULL,
    created_at DATETIME2 NOT NULL,
    risk_rating VARCHAR(10) NULL
);
IF OBJECT_ID('core.accounts') IS NULL
CREATE TABLE core.accounts (
    account_id BIGINT NOT NULL PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES core.customers(customer_id),
    account_type VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL,
    opened_at DATETIME2 NOT NULL
);
IF OBJECT_ID('activity.transactions') IS NULL
CREATE TABLE activity.transactions (
    transaction_id BIGINT NOT NULL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES core.accounts(account_id),
    amount DECIMAL(18,2) NOT NULL,
    transaction_type VARCHAR(20) NOT NULL,
    posted_at DATETIME2 NOT NULL
);
GO

-- Sample data (only when empty). Numbers come from a cross join; values from CHECKSUM so every run is identical.
IF NOT EXISTS (SELECT 1 FROM core.customers)
BEGIN
    ;WITH n AS (SELECT TOP (1200) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS i FROM sys.all_objects a CROSS JOIN sys.all_objects b)
    INSERT INTO core.customers (customer_id, segment, created_at, risk_rating)
    SELECT 100000 + i,
           CHOOSE(1 + ABS(CHECKSUM(i * 7)) % 4, 'retail', 'retail', 'premier', 'business'),
           DATEADD(DAY, -(ABS(CHECKSUM(i * 13)) % 1460), '2026-09-01'),
           CHOOSE(1 + ABS(CHECKSUM(i * 17)) % 5, 'low', 'low', 'low', 'medium', 'high')
    FROM n;
END
GO

IF NOT EXISTS (SELECT 1 FROM core.accounts)
BEGIN
    ;WITH n AS (SELECT TOP (2000) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS i FROM sys.all_objects a CROSS JOIN sys.all_objects b)
    INSERT INTO core.accounts (account_id, customer_id, account_type, status, opened_at)
    SELECT 500000 + i,
           100001 + ABS(CHECKSUM(i * 31)) % 1200,
           CHOOSE(1 + ABS(CHECKSUM(i * 37)) % 5, 'checking', 'checking', 'savings', 'credit', 'loan'),
           CHOOSE(1 + ABS(CHECKSUM(i * 41)) % 10, 'active', 'active', 'active', 'active', 'active', 'active', 'active', 'dormant', 'dormant', 'closed'),
           DATEADD(DAY, -(ABS(CHECKSUM(i * 43)) % 1095), '2026-09-01')
    FROM n;
END
GO

IF NOT EXISTS (SELECT 1 FROM activity.transactions)
BEGIN
    ;WITH n AS (SELECT TOP (25000) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS i FROM sys.all_objects a CROSS JOIN sys.all_objects b),
    t AS (
        SELECT i,
               CHOOSE(1 + ABS(CHECKSUM(i * 53)) % 10, 'deposit', 'deposit', 'withdrawal', 'withdrawal', 'payment', 'payment', 'payment', 'transfer', 'fee', 'interest') AS kind
        FROM n
    )
    INSERT INTO activity.transactions (transaction_id, account_id, amount, transaction_type, posted_at)
    SELECT 9000000 + i,
           500001 + ABS(CHECKSUM(i * 59)) % 2000,
           CAST(CASE kind
                    WHEN 'deposit' THEN 50 + ABS(CHECKSUM(i * 61)) % 5000
                    WHEN 'withdrawal' THEN -(20 + ABS(CHECKSUM(i * 67)) % 800)
                    WHEN 'payment' THEN -(10 + ABS(CHECKSUM(i * 71)) % 1500)
                    WHEN 'transfer' THEN -(100 + ABS(CHECKSUM(i * 73)) % 3000)
                    WHEN 'fee' THEN -(1 + ABS(CHECKSUM(i * 79)) % 35)
                    ELSE 1 + ABS(CHECKSUM(i * 83)) % 60
                END + (ABS(CHECKSUM(i * 89)) % 100) / 100.0 AS DECIMAL(18,2)),
           kind,
           DATEADD(MINUTE, -(ABS(CHECKSUM(i * 97)) % 525600), '2026-09-01')
    FROM t;
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_transactions_account_posted')
    CREATE INDEX ix_transactions_account_posted ON activity.transactions (account_id, posted_at);
GO

PRINT 'RetailBanking ready';
GO
