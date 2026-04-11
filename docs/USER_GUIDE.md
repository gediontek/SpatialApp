# SpatialApp User Guide

SpatialApp is a natural language interface for geospatial operations. Type questions or commands in plain English, and the system translates them into GIS operations displayed on an interactive map.

---

## Getting Started

1. Open `http://localhost:5000` in your browser
2. The main view shows a Leaflet map with a chat panel
3. Type a message in the chat box and press Enter

---

## 10 Common Queries

### 1. Find and display features
```
Show all parks in downtown Chicago
```
Fetches park polygons from OpenStreetMap and displays them on the map.

### 2. Search nearby
```
Find restaurants within 500 meters of Times Square
```
Geocodes "Times Square", then searches for restaurants in a 500m radius.

### 3. Calculate distances
```
What's the distance from the White House to the US Capitol?
```
Returns distance in meters, kilometers, and miles.

### 4. Create buffers
```
Create a 1km buffer around Central Park
```
Generates a polygon showing the 1km zone around Central Park.

### 5. Get area measurements
```
What's the total area of parks in Seattle?
```
Fetches parks, then calculates geodesic area in sq meters, sq km, and acres.

### 6. Route finding
```
Find a driving route from LAX to Santa Monica Pier
```
Returns a route via Valhalla with distance, duration, and turn-by-turn directions.

### 7. Isochrone analysis
```
Show me what I can reach in 15 minutes driving from downtown Portland
```
Generates a polygon showing the 15-minute drivable area.

### 8. Spatial overlay
```
Where do parks and flood zones overlap?
```
Fetches both layers, then computes their geometric intersection.

### 9. Feature filtering
```
Show only buildings taller than 5 stories
```
Filters the building layer by the `building:levels` attribute.

### 10. Hot spot analysis
```
Analyze crime hot spots in this area
```
Runs Getis-Ord Gi* analysis on the data, coloring features red (hot), blue (cold), or gray (not significant).

---

## Plan Mode

Plan mode lets you preview what the system will do before executing.

### How to use

1. Toggle "Plan Mode" in the chat interface (or send `plan_mode: true` via API)
2. Type your query: `"Analyze hospital coverage for downtown Boston"`
3. The system returns a step-by-step plan without executing:
   ```
   Plan:
   1. Geocode "downtown Boston" to get bounding box
   2. Fetch hospitals via fetch_osm
   3. Generate 15-minute service areas
   4. Identify gaps in coverage
   ```
4. Review the plan and click "Execute" (or call `/api/chat/execute-plan`)
5. The system executes each step and streams results

Plan mode is useful for:
- Complex multi-step queries
- Verifying the system understood your intent
- Learning which tools are available

---

## Importing Data

### CSV (tabular data with coordinates)

Paste CSV content directly in the chat:
```
Import this CSV as sensor locations:
name,lat,lon,temperature
Sensor A,40.71,-74.01,72.5
Sensor B,40.75,-73.98,68.3
Sensor C,40.78,-73.97,71.1
```

The system detects lat/lon columns automatically. Override with:
```
Import this CSV using "latitude" and "longitude" columns
```

### GeoJSON

Paste GeoJSON directly:
```
Import this GeoJSON as my study area:
{"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[-74, 40.7], [-73.9, 40.7], [-73.9, 40.8], [-74, 40.8], [-74, 40.7]]]}, "properties": {"name": "Study Area"}}]}
```

### WKT (Well-Known Text)

```
Import this WKT polygon as the project boundary:
POLYGON((-87.7 41.8, -87.6 41.8, -87.6 41.9, -87.7 41.9, -87.7 41.8))
```

### KML

Paste KML content:
```
Import this KML data as waypoints:
<kml>...</kml>
```

### File upload

Upload GeoJSON, Shapefile (.zip), or GeoPackage (.gpkg) files via the API:
```bash
curl -X POST http://localhost:5000/api/import \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@buildings.geojson" \
  -F "layer_name=buildings"
```

---

## Exporting Results

### From the chat

```
Export the parks layer as a shapefile
```

Supported formats:
- **GeoJSON** (default) - for web applications
- **Shapefile** - for desktop GIS (ArcGIS, QGIS)
- **GeoPackage** - modern open format
- **GeoParquet** - for large datasets and data pipelines

### Exporting annotations

```
Export all annotations as GeoJSON
```

Or via the UI: navigate to `/saved_annotations` and click the export button.

---

## Dashboard

Access the dashboard at `/dashboard` for:

- **Session overview**: Active sessions, message counts, timestamps
- **Tool usage**: Which tools are called most, average response times
- **Layer inventory**: Current layers in memory with feature counts
- **System health**: Database status, memory usage

### API access

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/dashboard
```

---

## Layer Operations

### Viewing and hiding
```
Hide the buildings layer
Show the parks layer
```

### Styling
```
Color the parks layer green
Make the roads thicker
Set building fill opacity to 30%
```

### Combining layers
```
Merge the north parks and south parks layers
```

### Spatial operations
```
Clip the buildings to the city boundary
Find buildings within the flood zone
Calculate the intersection of parks and historic districts
```

---

## Advanced Analysis

### Spatial statistics
```
Run clustering analysis on the crime data
```
Returns nearest neighbor index and DBSCAN clusters.

### Interpolation
```
Interpolate temperature values from weather stations
```
Creates a contour surface from point values.

### Topology
```
Check the parcels layer for geometry errors
Fix invalid geometries in the parcels layer
```

### Attribute statistics
```
Show statistics for the population attribute in the census layer
```
Returns min, max, mean, median, standard deviation, percentiles.

---

## Troubleshooting

### "I didn't understand that"

The system falls back to rule-based responses when:
- The LLM API key is not configured
- The API rate limit is reached
- The message does not match any tool pattern

Try rephrasing with explicit terms: "Show me X", "Find Y near Z", "Calculate the area of W".

### Layer not found

The system can only operate on layers currently in memory. If you see "Layer not found":
- Check available layers: `"What layers do I have?"`
- The layer name may differ from what you expect: `"List all layers"`

### Slow responses

Complex tool chains (4+ steps) may take 10-30 seconds. Factors:
- LLM response time (2-5s per tool decision)
- External API calls (geocoding, OSM, routing)
- Spatial computations on large datasets

### Map not updating

If the map does not show new layers:
- Check the browser console for JavaScript errors
- Refresh the page (layers persist in server memory)
- Verify the layer was created: `"List all layers"`

### Data quality issues

Before analysis, consider cleaning your data:
```
Check for duplicate features in the parcels layer
Clean the buildings layer (remove null geometries)
Validate topology of the boundaries layer
```
