# PostgreSQL/PostGIS Migration Guide

This document describes how to migrate SpatialApp from SQLite to PostgreSQL/PostGIS.

## Status

**Current**: SQLite (default, production-ready for single-server deployment)
**Planned**: PostgreSQL/PostGIS (for scaling, concurrent writes, spatial indexing)

The database abstraction layer (`services/db_interface.py`) is in place.
The PostgreSQL stub (`services/postgres_db.py`) defines all method signatures
and documents the SQL that will be used. Implementation is pending.

## Prerequisites

- PostgreSQL 14+ (for JSONB improvements and performance)
- PostGIS 3.3+ (for geometry type support and spatial indexing)
- Python package: `psycopg2-binary` (or `psycopg2` for production builds)

```bash
# Install PostgreSQL and PostGIS (macOS)
brew install postgresql@14 postgis

# Install PostgreSQL and PostGIS (Ubuntu/Debian)
sudo apt install postgresql-14 postgresql-14-postgis-3

# Install Python driver
pip install psycopg2-binary
```

## Schema Creation

Run these SQL statements to create the PostGIS-enabled schema:

```sql
-- Enable PostGIS extension
CREATE EXTENSION IF NOT EXISTS postgis;

-- Users table
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    api_token TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Annotations with geometry column for spatial indexing
CREATE TABLE IF NOT EXISTS annotations (
    id SERIAL PRIMARY KEY,
    user_id TEXT DEFAULT 'anonymous',
    category_name TEXT NOT NULL,
    color TEXT DEFAULT '#3388ff',
    source TEXT DEFAULT 'manual',
    geometry_json JSONB NOT NULL,
    geom GEOMETRY(Geometry, 4326),
    properties_json JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_annotations_geom ON annotations USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_annotations_category ON annotations(category_name);
CREATE INDEX IF NOT EXISTS idx_annotations_source ON annotations(source);
CREATE INDEX IF NOT EXISTS idx_annotations_user ON annotations(user_id);

-- Layers with geometry column for spatial indexing
CREATE TABLE IF NOT EXISTS layers (
    name TEXT NOT NULL,
    user_id TEXT DEFAULT 'anonymous',
    geojson JSONB NOT NULL,
    geom GEOMETRY(Geometry, 4326),
    feature_count INTEGER DEFAULT 0,
    style_json JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (name, user_id)
);
CREATE INDEX IF NOT EXISTS idx_layers_geom ON layers USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_layers_user ON layers(user_id);

-- Chat sessions
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT DEFAULT 'anonymous',
    messages_json JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON chat_sessions(user_id);

-- Query metrics
CREATE TABLE IF NOT EXISTS query_metrics (
    id SERIAL PRIMARY KEY,
    user_id TEXT DEFAULT 'anonymous',
    session_id TEXT,
    message TEXT,
    tool_calls INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    error BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_metrics_created ON query_metrics(created_at);
CREATE INDEX IF NOT EXISTS idx_metrics_user ON query_metrics(user_id);
```

## Data Migration from SQLite

Use this script to export data from SQLite and import into PostgreSQL:

```bash
#!/bin/bash
# migrate_sqlite_to_postgres.sh
# Usage: ./migrate_sqlite_to_postgres.sh <sqlite_db_path> <postgres_connection_string>

SQLITE_DB="${1:-data/spatialapp.db}"
PG_CONN="${2:-postgresql://spatialapp:password@localhost:5432/spatialapp}"

echo "Exporting from SQLite: $SQLITE_DB"

# Export each table to CSV
for table in users annotations layers chat_sessions query_metrics; do
    sqlite3 -header -csv "$SQLITE_DB" "SELECT * FROM $table;" > "/tmp/${table}.csv"
    echo "  Exported $table: $(wc -l < /tmp/${table}.csv) rows"
done

echo "Importing into PostgreSQL: $PG_CONN"

# Import each table (order matters for foreign keys)
for table in users annotations layers chat_sessions query_metrics; do
    psql "$PG_CONN" -c "\\copy $table FROM '/tmp/${table}.csv' WITH CSV HEADER"
    echo "  Imported $table"
done

# Build geometry columns from GeoJSON
psql "$PG_CONN" <<'SQL'
UPDATE annotations
SET geom = ST_SetSRID(ST_GeomFromGeoJSON(geometry_json::text), 4326)
WHERE geom IS NULL AND geometry_json IS NOT NULL;

UPDATE layers
SET geom = ST_Collect(
    ARRAY(SELECT ST_SetSRID(ST_GeomFromGeoJSON(f->>'geometry'), 4326)
          FROM jsonb_array_elements(geojson->'features') AS f)
)
WHERE geom IS NULL AND geojson IS NOT NULL;
SQL

echo "Migration complete. Verify with:"
echo "  psql $PG_CONN -c 'SELECT COUNT(*) FROM annotations;'"
```

## Configuration Changes

Update your `.env` file:

```bash
# Switch to PostgreSQL backend
DATABASE_BACKEND=postgres
DATABASE_URL=postgresql://spatialapp:password@localhost:5432/spatialapp

# Remove or keep (ignored when using postgres)
# DATABASE_PATH=data/spatialapp.db
```

## Architecture: What Changes

| Aspect | SQLite | PostgreSQL/PostGIS |
|--------|--------|--------------------|
| Storage | Single file (`data/spatialapp.db`) | Server process |
| Concurrency | WAL mode (one writer) | MVCC (many writers) |
| Spatial queries | Full-scan on GeoJSON text | GIST index on geometry column |
| JSON queries | Text parsing | JSONB operators (`@>`, `?`, `->`) |
| Connections | Thread-local, no pooling | Connection pool (ThreadedConnectionPool) |
| Timestamps | TEXT (ISO 8601) | TIMESTAMPTZ (native) |
| Auto-increment | AUTOINCREMENT | SERIAL |
| Upsert | INSERT OR REPLACE | INSERT ... ON CONFLICT DO UPDATE |

## Performance Benefits

1. **Spatial indexing**: GIST indexes on geometry columns enable sub-millisecond
   spatial queries (ST_Within, ST_Intersects, ST_DWithin) instead of full-table
   scans deserializing GeoJSON text.

2. **Concurrent writes**: PostgreSQL MVCC allows multiple simultaneous writers
   without lock contention. SQLite WAL mode allows one writer at a time.

3. **JSONB queries**: Query inside JSON structures without deserializing:
   ```sql
   SELECT * FROM layers WHERE geojson @> '{"type": "FeatureCollection"}';
   SELECT * FROM annotations WHERE properties_json ? 'height';
   ```

4. **Connection pooling**: Reuse connections across requests instead of
   creating new connections per thread.

5. **Scalability**: Handles databases in the hundreds of GB range with
   proper indexing. SQLite practical limit is ~1 GB for web applications.

## What Does NOT Change

- All application code uses `state.db.<method>()` -- no changes needed
- API endpoints remain identical
- GeoJSON format stored in the database is the same
- User authentication and session management are unchanged
- The `DatabaseInterface` contract guarantees method compatibility

## Implementation Checklist

When ready to implement PostgreSQL support:

- [ ] Install `psycopg2-binary` and add to `requirements.txt`
- [ ] Implement `PostgresDatabase.__init__()` with connection pooling
- [ ] Implement all CRUD methods (follow SQL in docstrings)
- [ ] Add integration tests with a real PostgreSQL instance
- [ ] Add CI pipeline step with PostgreSQL service container
- [ ] Test data migration script with production-like data
- [ ] Update deployment documentation
- [ ] Add health check endpoint for database connectivity
