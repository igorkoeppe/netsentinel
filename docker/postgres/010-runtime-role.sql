-- Executed only when the official PostgreSQL image initializes an empty volume.
-- psql literal quoting protects passwords containing quotes or SQL characters.
\getenv runtime_password NETSENTINEL_DB_PASSWORD
CREATE ROLE netsentinel_app WITH LOGIN PASSWORD :'runtime_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
\unset runtime_password

GRANT CONNECT ON DATABASE netsentinel TO netsentinel_app;
GRANT USAGE ON SCHEMA public TO netsentinel_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO netsentinel_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO netsentinel_app;

-- Migrations must run as the owner (netsentinel), not as netsentinel_app.
ALTER DEFAULT PRIVILEGES FOR ROLE netsentinel IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE ON TABLES TO netsentinel_app;
ALTER DEFAULT PRIVILEGES FOR ROLE netsentinel IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO netsentinel_app;
