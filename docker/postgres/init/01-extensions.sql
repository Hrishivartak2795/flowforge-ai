-- Runs once on first database initialization (mounted into
-- /docker-entrypoint-initdb.d). Makes the pgvector capability available.
--
-- NOTE: This only ensures the extension exists at the cluster level for local
-- dev convenience. The authoritative `CREATE EXTENSION` lives in the first
-- Alembic migration (M1), so schema setup is reproducible outside Docker too.
CREATE EXTENSION IF NOT EXISTS vector;
