-- Extensions required by the schema. Migrations also create these
-- (belt-and-braces), but having them in init.sql means a fresh volume is
-- ready even before the first `make migrate`.
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pg_trgm";    -- trigram search on transcripts (Phase 1)
