"""
Organization service database schemas.
Adds organizations, departments, teams, locations tables.
Also adds organization_id to jobs table (nullable - no disruption to existing data).
"""

ADD_ORG_TABLES_POSTGRES = """
CREATE TABLE IF NOT EXISTS organizations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID,
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(255) UNIQUE,
    legal_name      VARCHAR(255),
    previous_names  JSONB DEFAULT '[]',
    industry        VARCHAR(100),
    size            VARCHAR(50),
    website         VARCHAR(255),
    logo_url        TEXT,
    description     TEXT,
    country         VARCHAR(2) DEFAULT 'NG',
    rc_number       VARCHAR(50),
    tin             VARCHAR(50),
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS departments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID,
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    code            VARCHAR(50),
    parent_id       UUID REFERENCES departments(id),
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS teams (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID,
    department_id   UUID REFERENCES departments(id),
    name            VARCHAR(255) NOT NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS locations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID,
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    address         TEXT,
    city            VARCHAR(100),
    state           VARCHAR(100),
    country         VARCHAR(2) DEFAULT 'NG',
    is_remote       BOOLEAN DEFAULT FALSE,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orgs_tenant      ON organizations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_orgs_slug        ON organizations(slug);
CREATE INDEX IF NOT EXISTS idx_depts_org        ON departments(organization_id);
CREATE INDEX IF NOT EXISTS idx_locations_org    ON locations(organization_id);

-- Link jobs to organizations (nullable - existing jobs unaffected)
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id);
CREATE INDEX IF NOT EXISTS idx_jobs_org ON jobs(organization_id);
"""

ADD_ORG_TABLES_SQLITE = """
CREATE TABLE IF NOT EXISTS organizations (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    tenant_id       TEXT,
    name            TEXT NOT NULL,
    slug            TEXT UNIQUE,
    legal_name      TEXT,
    previous_names  TEXT DEFAULT '[]',
    industry        TEXT,
    size            TEXT,
    website         TEXT,
    logo_url        TEXT,
    description     TEXT,
    country         TEXT DEFAULT 'NG',
    rc_number       TEXT,
    tin             TEXT,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS departments (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    tenant_id       TEXT,
    organization_id TEXT REFERENCES organizations(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    code            TEXT,
    parent_id       TEXT REFERENCES departments(id),
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS teams (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    tenant_id       TEXT,
    department_id   TEXT REFERENCES departments(id),
    name            TEXT NOT NULL,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS locations (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    tenant_id       TEXT,
    organization_id TEXT REFERENCES organizations(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    address         TEXT,
    city            TEXT,
    state           TEXT,
    country         TEXT DEFAULT 'NG',
    is_remote       INTEGER DEFAULT 0,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_orgs_tenant      ON organizations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_orgs_slug        ON organizations(slug);
CREATE INDEX IF NOT EXISTS idx_depts_org        ON departments(organization_id);
CREATE INDEX IF NOT EXISTS idx_locations_org    ON locations(organization_id);
"""

# Run separately since ALTER TABLE IF NOT EXISTS column doesn't work in all SQLite versions
ADD_ORG_COLUMN_TO_JOBS_SQLITE = """
ALTER TABLE jobs ADD COLUMN organization_id TEXT REFERENCES organizations(id);
"""
