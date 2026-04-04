# SpatialApp

NL-to-GIS web application: natural language chat interface for geospatial operations powered by Claude API.

## Project Plan

Always check `.project_plan/STATUS.md` for current project status, architecture, and known limitations before making changes.

## Quick Start

```bash
source venv/bin/activate
python3 app.py              # Runs on port 5000 (or PORT env var)
pytest tests/ -v             # 236 tests
```

## Key Files

| File | Purpose |
|------|---------|
| `app.py` | Flask app, 24 routes, session/layer management |
| `nl_gis/chat.py` | Claude API integration, tool dispatch loop |
| `nl_gis/tool_handlers.py` | 24 tool handler implementations |
| `nl_gis/tools.py` | Tool schemas (JSON Schema for Claude) |
| `nl_gis/geo_utils.py` | ValidatedPoint, projections, spatial ops |
| `services/database.py` | SQLite CRUD, migrations, metrics |
| `services/valhalla_client.py` | Routing + isochrone via Valhalla |
| `config.py` | All configuration from env vars |

## Conventions

- **Coordinate order**: ValidatedPoint enforces `.as_leaflet()` [lat,lng] vs `.as_geojson()` [lng,lat]. Never use raw tuples.
- **Thread safety**: Use `annotation_lock` for `geo_coco_annotations`, `layer_lock` for `layer_store`. Use `_get_layer_snapshot()` for reads in tool handlers.
- **Database**: All mutations should write to both in-memory state AND database. DB failures are logged as warnings, not errors.
- **Error messages**: Never leak exception details to users. Log with `exc_info=True`, return generic message.
- **Tool responses**: Include `"error"` key on failure. Layer-producing tools must include `"geojson"` and `"layer_name"`.
- **Tests**: Run `venv/bin/python3 -m pytest tests/ -v` before committing. E2E tests need Playwright (`venv/bin/python3 -m playwright install chromium`).

## Configuration

Required: `ANTHROPIC_API_KEY` in `.env` (empty = fallback to rule-based chat)
Optional: `CHAT_API_TOKEN`, `CLAUDE_MODEL`, `DATABASE_PATH`, `PORT`

## Architecture Decisions

- **Claude tool_use** over text-to-SQL (security, 86% accuracy)
- **SSE streaming** over WebSocket (simpler, sufficient)
- **Valhalla** over OSRM (true network isochrones)
- **SQLite + WAL** over PostGIS (simpler deployment; migrate when scaling)
- **ValidatedPoint** for coordinate safety (prevents lat/lon swap bugs)
