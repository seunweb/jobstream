"""
RBAC database tables and seed data.
Creates roles, permissions, role_permissions, user_roles tables.
Seeds all system roles and permissions on startup.
"""

RBAC_TABLES_POSTGRES = """
CREATE TABLE IF NOT EXISTS permissions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        VARCHAR(100) UNIQUE NOT NULL,
    name        VARCHAR(255) NOT NULL,
    module      VARCHAR(50) NOT NULL DEFAULT 'platform',
    description TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS roles (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID,
    name        VARCHAR(100) NOT NULL,
    slug        VARCHAR(100) NOT NULL,
    scope       VARCHAR(20) NOT NULL DEFAULT 'organization',
    description TEXT,
    is_system   BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, slug)
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id         UUID REFERENCES roles(id) ON DELETE CASCADE,
    permission_id   UUID REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    role_id     UUID REFERENCES roles(id) ON DELETE CASCADE,
    tenant_id   UUID,
    assigned_by UUID REFERENCES users(id),
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, role_id, tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_roles_tenant    ON roles(tenant_id);
CREATE INDEX IF NOT EXISTS idx_roles_slug      ON roles(slug);
CREATE INDEX IF NOT EXISTS idx_user_roles_user ON user_roles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles(role_id);
"""

RBAC_TABLES_SQLITE = """
CREATE TABLE IF NOT EXISTS permissions (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    slug        TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    module      TEXT NOT NULL DEFAULT 'platform',
    description TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS roles (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    tenant_id   TEXT,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL,
    scope       TEXT NOT NULL DEFAULT 'organization',
    description TEXT,
    is_system   INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id         TEXT REFERENCES roles(id) ON DELETE CASCADE,
    permission_id   TEXT REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id     TEXT REFERENCES users(id) ON DELETE CASCADE,
    role_id     TEXT REFERENCES roles(id) ON DELETE CASCADE,
    tenant_id   TEXT,
    assigned_by TEXT REFERENCES users(id),
    assigned_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, role_id, tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_roles_tenant    ON roles(tenant_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_user ON user_roles(user_id);
"""


def seed_system_roles_and_permissions():
    """
    Seed all system roles and permissions into the database.
    Safe to run multiple times — uses INSERT OR IGNORE / ON CONFLICT DO NOTHING.
    """
    from core.database import get_conn, USE_POSTGRES
    from core.rbac import SYSTEM_ROLES, ALL_PERMISSIONS
    import uuid

    log_prefix = "[RBAC Seed]"

    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # 1. Insert all permissions
            for slug, name in ALL_PERMISSIONS.items():
                module = slug.split(".")[0]
                if USE_POSTGRES:
                    cur.execute("""
                        INSERT INTO permissions (slug, name, module)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (slug) DO NOTHING
                    """, (slug, name, module))
                else:
                    cur.execute("""
                        INSERT OR IGNORE INTO permissions (id, slug, name, module)
                        VALUES (?, ?, ?, ?)
                    """, (str(uuid.uuid4()), slug, name, module))

            # 2. Fetch permission id map
            cur.execute("SELECT id, slug FROM permissions")
            perm_map = {dict(r)["slug"]: dict(r)["id"] for r in cur.fetchall()}

            # 3. Insert system roles (tenant_id = NULL = global)
            for slug, role_def in SYSTEM_ROLES.items():
                role_id_query = None
                if USE_POSTGRES:
                    cur.execute("""
                        INSERT INTO roles (slug, name, scope, description, is_system)
                        VALUES (%s, %s, %s, %s, TRUE)
                        ON CONFLICT (tenant_id, slug) DO NOTHING
                        RETURNING id
                    """, (slug, role_def["name"], role_def["scope"],
                          role_def.get("description", "")))
                    row = cur.fetchone()
                    role_id_query = dict(row)["id"] if row else None
                else:
                    cur.execute(
                        "SELECT id FROM roles WHERE slug = ? AND tenant_id IS NULL",
                        (slug,)
                    )
                    existing = cur.fetchone()
                    if not existing:
                        role_id_str = str(uuid.uuid4())
                        cur.execute("""
                            INSERT OR IGNORE INTO roles
                                (id, slug, name, scope, description, is_system)
                            VALUES (?,?,?,?,?,1)
                        """, (role_id_str, slug, role_def["name"],
                              role_def["scope"], role_def.get("description", "")))
                        role_id_query = role_id_str
                    else:
                        role_id_query = dict(existing)["id"]

                if not role_id_query:
                    # Already exists — get its ID
                    cur.execute(
                        "SELECT id FROM roles WHERE slug = %s AND tenant_id IS NULL" if USE_POSTGRES
                        else "SELECT id FROM roles WHERE slug = ? AND tenant_id IS NULL",
                        (slug,)
                    )
                    row = cur.fetchone()
                    role_id_query = dict(row)["id"] if row else None

                if not role_id_query:
                    continue

                # 4. Assign permissions to role
                perms = role_def.get("permissions", [])
                if "*" in perms:
                    perms = list(ALL_PERMISSIONS.keys())

                for perm_slug in perms:
                    perm_id = perm_map.get(perm_slug)
                    if not perm_id:
                        continue
                    if USE_POSTGRES:
                        cur.execute("""
                            INSERT INTO role_permissions (role_id, permission_id)
                            VALUES (%s, %s)
                            ON CONFLICT DO NOTHING
                        """, (str(role_id_query), str(perm_id)))
                    else:
                        cur.execute("""
                            INSERT OR IGNORE INTO role_permissions
                                (role_id, permission_id)
                            VALUES (?, ?)
                        """, (str(role_id_query), str(perm_id)))

        print(f"{log_prefix} Seeded {len(ALL_PERMISSIONS)} permissions, "
              f"{len(SYSTEM_ROLES)} system roles")

    except Exception as e:
        print(f"{log_prefix} Seed failed: {e}")
