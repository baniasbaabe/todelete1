-- Local development bootstrap, run once by the postgres image entrypoint.
--
-- Mirrors the production layout from infra/modules/postgres/main.tf and
-- scripts/bootstrap-db-roles.sh: Phoenix gets its own database rather than
-- sharing one with the Alembic-managed application tables.
CREATE DATABASE phoenix;

-- mem0's pgvector store creates its own tables and gets a dedicated schema, so
-- that in production the runtime role needs no DDL rights on public. Without
-- this schema locally, the same search_path silently falls through to public
-- and local runs stop resembling the deployed layout.
CREATE SCHEMA IF NOT EXISTS mem0;
