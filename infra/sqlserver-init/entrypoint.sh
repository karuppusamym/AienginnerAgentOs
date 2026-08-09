#!/bin/bash
# Start SQL Server in background, wait for it to be ready, then run init script

/opt/mssql/bin/sqlservr &
MSSQL_PID=$!

echo "Waiting for SQL Server to accept connections..."
for i in $(seq 1 60); do
    /opt/mssql-tools18/bin/sqlcmd \
        -S localhost \
        -U sa \
        -P "$MSSQL_SA_PASSWORD" \
        -Q "SELECT 1" \
        -C \
        2>/dev/null && break
    echo "  attempt $i/60 — not ready yet"
    sleep 2
done

echo "Running init.sql..."
/opt/mssql-tools18/bin/sqlcmd \
    -S localhost \
    -U sa \
    -P "$MSSQL_SA_PASSWORD" \
    -d master \
    -i /docker-entrypoint-initdb.d/init.sql \
    -C
echo "init.sql complete."

# Keep SQL Server running
wait $MSSQL_PID
