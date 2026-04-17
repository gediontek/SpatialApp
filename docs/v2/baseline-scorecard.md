# SpatialApp v2.1 — Tool Selection Baseline

- **Run timestamp:** 2026-04-17T20:17:25.217795+00:00
- **Mode:** live
- **Provider:** gemini
- **Model:** gemini-2.5-flash
- **Query count:** 62
- **Raw results:** [`baseline-results.json`](baseline-results.json)

---

## Summary

- **Total queries**: 62
- **Full match**: 32
- **Partial match**: 7
- **No match**: 23
- **Tool selection accuracy**: **51.6%**
- **Parameter accuracy**: **60.0%** (21/35 queries with param checks)
- **Chain accuracy** (multi-tool queries): **27.3%** (3/11 multi-tool queries)

## Accuracy by Complexity

| Complexity | Accuracy | Count |
|------------|----------|-------|
| complex | 0.0% | 2 |
| moderate | 37.5% | 8 |
| multi_step | 0.0% | 2 |
| simple | 58.0% | 50 |

## Accuracy by Category

| Category | Accuracy | Count |
|----------|----------|-------|
| advanced | 0.0% | 1 |
| annotation | 33.3% | 3 |
| data_acquisition | 100.0% | 5 |
| data_quality | 60.0% | 5 |
| geometry | 60.0% | 10 |
| import_export | 71.4% | 7 |
| layer_management | 50.0% | 4 |
| measurement | 66.7% | 3 |
| overlay | 25.0% | 4 |
| routing | 33.3% | 6 |
| spatial_analysis | 41.7% | 12 |
| visualization | 0.0% | 2 |

## Chain Accuracy by Complexity

Multi-tool queries only: correct relative order of expected tools within the actual tool list.

| Complexity | Chain Accuracy | Multi-tool Count |
|------------|----------------|------------------|
| moderate | 42.9% | 7 |
| complex | 0.0% | 2 |
| multi_step | 0.0% | 2 |

## Mismatched Queries

### Q010: Which district contains the point at 51.5074, -0.1278?
- **Match**: none
- **Complexity**: simple
- **Category**: spatial_analysis
- **Expected**: ['point_in_polygon']
- **Actual**: ['fetch_osm']
- **Missing**: ['point_in_polygon']
- **Extra**: ['fetch_osm']
- **Param mismatch**: yes

### Q011: Tag each store with its census tract
- **Match**: none
- **Complexity**: moderate
- **Category**: spatial_analysis
- **Expected**: ['point_in_polygon']
- **Actual**: []
- **Missing**: ['point_in_polygon']
- **Param mismatch**: yes

### Q012: Are the crime points spatially clustered?
- **Match**: none
- **Complexity**: simple
- **Category**: spatial_analysis
- **Expected**: ['spatial_statistics']
- **Actual**: []
- **Missing**: ['spatial_statistics']
- **Param mismatch**: yes

### Q013: Run DBSCAN clustering on the restaurant data with 200m radius and minimum 3 points
- **Match**: none
- **Complexity**: simple
- **Category**: spatial_analysis
- **Expected**: ['spatial_statistics']
- **Actual**: []
- **Missing**: ['spatial_statistics']
- **Param mismatch**: yes

### Q014: Draw a boundary around the crime data points
- **Match**: none
- **Complexity**: simple
- **Category**: geometry
- **Expected**: ['convex_hull']
- **Actual**: []
- **Missing**: ['convex_hull']

### Q018: Merge the zoning polygons by zone_type
- **Match**: none
- **Complexity**: simple
- **Category**: geometry
- **Expected**: ['dissolve']
- **Actual**: []
- **Missing**: ['dissolve']
- **Param mismatch**: yes

### Q019: Create a 2km buffer around the hospital
- **Match**: none
- **Complexity**: moderate
- **Category**: geometry
- **Expected**: ['geocode', 'buffer']
- **Actual**: []
- **Missing**: ['geocode', 'buffer']
- **Param mismatch**: yes

### Q021: Remove water areas from the land use layer
- **Match**: none
- **Complexity**: simple
- **Category**: overlay
- **Expected**: ['difference']
- **Actual**: []
- **Missing**: ['difference']

### Q022: What features are unique to each layer — parks vs green spaces?
- **Match**: none
- **Complexity**: simple
- **Category**: overlay
- **Expected**: ['symmetric_difference']
- **Actual**: ['fetch_osm', 'fetch_osm']
- **Missing**: ['symmetric_difference']
- **Extra**: ['fetch_osm', 'fetch_osm']

### Q027: Show only buildings taller than 20 meters and highlight the commercial ones
- **Match**: none
- **Complexity**: multi_step
- **Category**: layer_management
- **Expected**: ['filter_layer', 'highlight_features']
- **Actual**: []
- **Missing**: ['filter_layer', 'highlight_features']

### Q030: Import this WKT polygon: POLYGON((-73.98 40.76, -73.97 40.76, -73.97 40.77, -73.98 40.77, -73.98 40.76))
- **Match**: none
- **Complexity**: simple
- **Category**: import_export
- **Expected**: ['import_wkt']
- **Actual**: []
- **Missing**: ['import_wkt']

### S005: Show me all saved annotations
- **Match**: none
- **Complexity**: simple
- **Category**: annotation
- **Expected**: ['get_annotations']
- **Actual**: []
- **Missing**: ['get_annotations']

### S006: Export all annotations as GeoJSON
- **Match**: none
- **Complexity**: simple
- **Category**: annotation
- **Expected**: ['export_annotations']
- **Actual**: []
- **Missing**: ['export_annotations']

### S007: Create a heatmap of the crime incident points
- **Match**: none
- **Complexity**: simple
- **Category**: visualization
- **Expected**: ['heatmap']
- **Actual**: []
- **Missing**: ['heatmap']

### S008: Classify the land cover types in the area
- **Match**: none
- **Complexity**: simple
- **Category**: visualization
- **Expected**: ['classify_landcover']
- **Actual**: []
- **Missing**: ['classify_landcover']

### S009: Optimize the delivery route visiting these 5 warehouse locations
- **Match**: none
- **Complexity**: simple
- **Category**: routing
- **Expected**: ['optimize_route']
- **Actual**: []
- **Missing**: ['optimize_route']

### S011: Create Voronoi service areas from the fire station locations
- **Match**: none
- **Complexity**: simple
- **Category**: geometry
- **Expected**: ['voronoi']
- **Actual**: ['fetch_osm']
- **Missing**: ['voronoi']
- **Extra**: ['fetch_osm']

### S012: Add population data to the district polygons by matching district_id
- **Match**: none
- **Complexity**: simple
- **Category**: spatial_analysis
- **Expected**: ['attribute_join']
- **Actual**: []
- **Missing**: ['attribute_join']
- **Param mismatch**: yes

### S015: Show the 10-minute driving coverage from all fire stations
- **Match**: none
- **Complexity**: simple
- **Category**: routing
- **Expected**: ['service_area']
- **Actual**: ['fetch_osm']
- **Missing**: ['service_area']
- **Extra**: ['fetch_osm']
- **Param mismatch**: yes

### S020: Show only the events between 2025-01-01 and 2025-12-31 from the events layer
- **Match**: none
- **Complexity**: simple
- **Category**: spatial_analysis
- **Expected**: ['temporal_filter']
- **Actual**: []
- **Missing**: ['temporal_filter']
- **Param mismatch**: yes

### S022: Compute the origin-destination matrix between the warehouses and customers layers
- **Match**: none
- **Complexity**: simple
- **Category**: routing
- **Expected**: ['od_matrix']
- **Actual**: ['execute_code']
- **Missing**: ['od_matrix']
- **Extra**: ['execute_code']

### S029: Import this GeoParquet file as a parcels layer
- **Match**: none
- **Complexity**: simple
- **Category**: import_export
- **Expected**: ['import_geoparquet']
- **Actual**: []
- **Missing**: ['import_geoparquet']

### S032: Compute the minimum bounding rectangle for all features in the buildings layer
- **Match**: none
- **Complexity**: simple
- **Category**: advanced
- **Expected**: ['execute_code']
- **Actual**: ['bounding_box']
- **Missing**: ['execute_code']
- **Extra**: ['bounding_box']

### Q008: How many buildings are in downtown Seattle?
- **Match**: partial
- **Complexity**: moderate
- **Category**: measurement
- **Expected**: ['fetch_osm', 'aggregate']
- **Actual**: ['fetch_osm']
- **Missing**: ['aggregate']
- **Param mismatch**: yes

### Q009: Which restaurants are within 500 meters of Central Park?
- **Match**: partial
- **Complexity**: complex
- **Category**: spatial_analysis
- **Expected**: ['geocode', 'buffer', 'search_nearby', 'spatial_query']
- **Actual**: ['geocode', 'search_nearby']
- **Missing**: ['buffer', 'spatial_query']

### Q020: Show where parks and commercial zones overlap in downtown Seattle
- **Match**: partial
- **Complexity**: complex
- **Category**: overlay
- **Expected**: ['fetch_osm', 'fetch_osm', 'intersection']
- **Actual**: ['fetch_osm', 'fetch_osm']
- **Missing**: ['intersection']

### Q023: Plan a driving route from Times Square to Brooklyn Bridge
- **Match**: partial
- **Complexity**: simple
- **Category**: routing
- **Expected**: ['find_route']
- **Actual**: ['find_route', 'map_command']
- **Extra**: ['map_command']
- **Param mismatch**: yes

### Q026: Find restaurants within 500m of Central Park and color them red
- **Match**: partial
- **Complexity**: multi_step
- **Category**: layer_management
- **Expected**: ['search_nearby', 'style_layer']
- **Actual**: ['search_nearby']
- **Missing**: ['style_layer']

### S023: Check if the imported_parcels polygons are valid and fix any topology errors
- **Match**: partial
- **Complexity**: moderate
- **Category**: data_quality
- **Expected**: ['validate_topology', 'repair_topology']
- **Actual**: ['validate_topology']
- **Missing**: ['repair_topology']
- **Param mismatch**: yes

### S031: Validate topology on the boundaries layer, and if there are issues, repair them into a clean version
- **Match**: partial
- **Complexity**: moderate
- **Category**: data_quality
- **Expected**: ['validate_topology', 'repair_topology']
- **Actual**: ['validate_topology']
- **Missing**: ['repair_topology']
- **Param mismatch**: yes
