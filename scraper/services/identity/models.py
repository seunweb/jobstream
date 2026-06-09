"""
Identity service database schemas.
Includes: users, sessions, candidate_profiles, persons (unified people layer).
"""

ADD_AUTH_TABLES = """
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) UNIQUE NOT NULL,
    password_hash   TEXT,
    full_name       VARCHAR(255),
    avatar_url      TEXT,
    role            VARCHAR(50) DEFAULT 'candidate',
    status          VARCHAR(20) DEFAULT 'active',
    email_verified  BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    refresh_token   TEXT UNIQUE NOT NULL,
    ip_address      TEXT,
    user_agent      TEXT,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS candidate_profiles (
    id                  SERIAL PRIMARY KEY,
    user_id             UUID UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    full_name           VARCHAR(255),
    phone               VARCHAR(30),
    location            VARCHAR(255),
    bio                 TEXT,
    skills              TEXT DEFAULT '[]',
    linkedin_url        TEXT,
    resume_url          TEXT,
    years_experience    INTEGER,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email    ON users(email);
CREATE INDEX IF NOT EXISTS idx_sessions_user  ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(refresh_token);
"""

ADD_AUTH_TABLES_SQLITE = """
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    email           TEXT UNIQUE NOT NULL,
    password_hash   TEXT,
    full_name       TEXT,
    avatar_url      TEXT,
    role            TEXT DEFAULT 'candidate',
    status          TEXT DEFAULT 'active',
    email_verified  INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id         TEXT REFERENCES users(id) ON DELETE CASCADE,
    refresh_token   TEXT UNIQUE NOT NULL,
    ip_address      TEXT,
    user_agent      TEXT,
    expires_at      TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS candidate_profiles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             TEXT UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    full_name           TEXT,
    phone               TEXT,
    location            TEXT,
    bio                 TEXT,
    skills              TEXT DEFAULT '[]',
    linkedin_url        TEXT,
    resume_url          TEXT,
    years_experience    INTEGER,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_users_email    ON users(email);
CREATE INDEX IF NOT EXISTS idx_sessions_user  ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(refresh_token);
"""

# ── Persons unified layer ─────────────────────────────────────────────────────
# Push 3: unified people architecture
# One record per real human — candidate, employee, contact all in one table
# Linked to users table when they register on the platform

ADD_PERSONS_TABLES_POSTGRES = """
CREATE TABLE IF NOT EXISTS persons (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID,
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    first_name      VARCHAR(100),
    last_name       VARCHAR(100),
    middle_name     VARCHAR(100),
    preferred_name  VARCHAR(100),
    email           VARCHAR(255),
    phone           VARCHAR(30),
    date_of_birth   DATE,
    gender          VARCHAR(20),
    nationality     VARCHAR(2),
    avatar_url      TEXT,
    location        VARCHAR(255),
    bio             TEXT,
    linkedin_url    TEXT,
    resume_url      TEXT,
    portfolio_url   TEXT,
    years_experience INTEGER,
    lifecycle_stage VARCHAR(30) DEFAULT 'candidate',
    is_open_to_work BOOLEAN DEFAULT TRUE,
    work_preference VARCHAR(20) DEFAULT 'hybrid',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS person_skills (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id   UUID REFERENCES persons(id) ON DELETE CASCADE,
    skill       VARCHAR(100) NOT NULL,
    level       VARCHAR(20),
    years       DECIMAL(4,1),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS person_experience (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id   UUID REFERENCES persons(id) ON DELETE CASCADE,
    company     VARCHAR(255),
    title       VARCHAR(255),
    started_at  DATE,
    ended_at    DATE,
    is_current  BOOLEAN DEFAULT FALSE,
    description TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS person_education (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id   UUID REFERENCES persons(id) ON DELETE CASCADE,
    institution VARCHAR(255),
    degree      VARCHAR(100),
    field       VARCHAR(100),
    started_at  DATE,
    ended_at    DATE,
    grade       VARCHAR(50),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_persons_user       ON persons(user_id);
CREATE INDEX IF NOT EXISTS idx_persons_email      ON persons(email);
CREATE INDEX IF NOT EXISTS idx_persons_lifecycle  ON persons(lifecycle_stage);
CREATE INDEX IF NOT EXISTS idx_person_skills      ON person_skills(person_id);
CREATE INDEX IF NOT EXISTS idx_person_exp         ON person_experience(person_id);
"""

ADD_PERSONS_TABLES_SQLITE = """
CREATE TABLE IF NOT EXISTS persons (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    tenant_id       TEXT,
    user_id         TEXT REFERENCES users(id) ON DELETE SET NULL,
    first_name      TEXT,
    last_name       TEXT,
    middle_name     TEXT,
    preferred_name  TEXT,
    email           TEXT,
    phone           TEXT,
    date_of_birth   TEXT,
    gender          TEXT,
    nationality     TEXT,
    avatar_url      TEXT,
    location        TEXT,
    bio             TEXT,
    linkedin_url    TEXT,
    resume_url      TEXT,
    portfolio_url   TEXT,
    years_experience INTEGER,
    lifecycle_stage TEXT DEFAULT 'candidate',
    is_open_to_work INTEGER DEFAULT 1,
    work_preference TEXT DEFAULT 'hybrid',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS person_skills (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    person_id   TEXT REFERENCES persons(id) ON DELETE CASCADE,
    skill       TEXT NOT NULL,
    level       TEXT,
    years       REAL,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS person_experience (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    person_id   TEXT REFERENCES persons(id) ON DELETE CASCADE,
    company     TEXT,
    title       TEXT,
    started_at  TEXT,
    ended_at    TEXT,
    is_current  INTEGER DEFAULT 0,
    description TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS person_education (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    person_id   TEXT REFERENCES persons(id) ON DELETE CASCADE,
    institution TEXT,
    degree      TEXT,
    field       TEXT,
    started_at  TEXT,
    ended_at    TEXT,
    grade       TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_persons_user       ON persons(user_id);
CREATE INDEX IF NOT EXISTS idx_persons_email      ON persons(email);
CREATE INDEX IF NOT EXISTS idx_persons_lifecycle  ON persons(lifecycle_stage);
CREATE INDEX IF NOT EXISTS idx_person_skills      ON person_skills(person_id);
CREATE INDEX IF NOT EXISTS idx_person_exp         ON person_experience(person_id);
"""

# Link applications to persons gradually (nullable — existing data unaffected)
ADD_PERSON_ID_TO_APPLICATIONS_POSTGRES = """
ALTER TABLE applications ADD COLUMN IF NOT EXISTS person_id UUID REFERENCES persons(id);
CREATE INDEX IF NOT EXISTS idx_applications_person ON applications(person_id);
"""

ADD_PERSON_ID_TO_APPLICATIONS_SQLITE = """
ALTER TABLE applications ADD COLUMN person_id TEXT REFERENCES persons(id);
"""
