/**
 * Named layer management for SpatialApp.
 * Tracks layers by name, provides toggle/remove/fit-to functionality.
 */
var LayerManager = (function() {
    var layers = {};  // { name: { leafletLayer, visible, featureCount, style } }
    var map = null;

    function init(leafletMap) {
        map = leafletMap;
        refreshUI();
    }

    var CLUSTER_THRESHOLD = 200;          // point clustering kicks in
    var POLY_DENSE_THRESHOLD = 200;       // thinner stroke + lower fill at this size
    var POLY_VARIED_THRESHOLD = 50;       // per-feature hashed color kicks in
    // Centroid clustering kicks in when EITHER many polygons OR moderate
    // count over a wide area (the latter catches "show hospitals in
    // Chicago" — only 59 features but each <100m and bounds ~30km, so
    // every polygon paints sub-pixel at the zoom fitToLayer picks).
    var POLY_CLUSTER_THRESHOLD = 100;
    var POLY_WIDE_BBOX_KM = 5;            // bounds diagonal in km
    var POLY_WIDE_BBOX_MIN_COUNT = 30;    // ...with at least this many polygons
    var ZOOM_TOGGLE_LEVEL = 15;           // below: cluster, at/above: real polygons

    /**
     * Approximate centroid of a polygon/line geometry. Cheap arithmetic
     * mean of the outer ring vertices — good enough for clustering, not
     * a true area-weighted centroid. Returns [lat, lng] (Leaflet order)
     * or null for unsupported geometries.
     */
    function _polygonCentroid(geom) {
        if (!geom) return null;
        var coords;
        if (geom.type === 'Polygon') coords = geom.coordinates && geom.coordinates[0];
        else if (geom.type === 'MultiPolygon') coords = geom.coordinates && geom.coordinates[0] && geom.coordinates[0][0];
        else if (geom.type === 'LineString') coords = geom.coordinates;
        else if (geom.type === 'Point') return [geom.coordinates[1], geom.coordinates[0]];
        else return null;
        if (!coords || coords.length === 0) return null;
        var lat = 0, lng = 0, n = 0;
        for (var i = 0; i < coords.length; i++) {
            if (coords[i] && coords[i].length >= 2) {
                lng += coords[i][0]; lat += coords[i][1]; n++;
            }
        }
        if (n === 0) return null;
        return [lat / n, lng / n];
    }

    /**
     * Bounding box diagonal in kilometers from a feature list.
     * Cheap haversine-free approximation (110 km per degree).
     * Used to detect "wide-area" queries that need clustering even at
     * moderate feature counts because individual polygons would paint
     * sub-pixel at the zoom that fits the whole bbox.
     */
    function _bboxDiagKm(features) {
        var minLng = Infinity, maxLng = -Infinity;
        var minLat = Infinity, maxLat = -Infinity;
        function walk(c) {
            if (!c || c.length === 0) return;
            if (typeof c[0] === 'number') {
                if (c[0] < minLng) minLng = c[0];
                if (c[0] > maxLng) maxLng = c[0];
                if (c[1] < minLat) minLat = c[1];
                if (c[1] > maxLat) maxLat = c[1];
            } else {
                for (var k = 0; k < c.length; k++) walk(c[k]);
            }
        }
        for (var i = 0; i < features.length; i++) {
            var g = features[i].geometry;
            if (g && g.coordinates) walk(g.coordinates);
        }
        if (!isFinite(minLng)) return 0;
        var midLat = (minLat + maxLat) / 2;
        var dLngKm = (maxLng - minLng) * 111 * Math.cos(midLat * Math.PI / 180);
        var dLatKm = (maxLat - minLat) * 111;
        return Math.sqrt(dLngKm * dLngKm + dLatKm * dLatKm);
    }

    /**
     * Deterministic hashed color for a feature. Uses osm_id when present,
     * else feature index, mapped to HSL hue via golden-angle multiplier so
     * adjacent features get distinguishable colors. Used when many
     * polygons would otherwise merge into a single-color blob at low zoom.
     */
    function _hashedColor(feature, idx) {
        var seed;
        var props = feature.properties || {};
        if (props.osm_id) {
            seed = parseInt(props.osm_id, 10);
        }
        if (!seed || isNaN(seed)) seed = (idx || 0) + 1;
        var hue = (seed * 137) % 360;
        if (hue < 0) hue += 360;
        return 'hsl(' + hue + ', 65%, 45%)';
    }

    function addLayer(name, geojson, style) {
        // Remove existing layer with same name
        if (layers[name]) {
            removeLayer(name);
        }

        style = style || {};
        // Sanitize color at input time to prevent injection via style properties
        var safeColor = (style.color || '#3388ff').replace(/[^#a-fA-F0-9]/g, '');

        var features = (geojson && geojson.features) || [];
        var featureCount = features.length;

        // Count geometry types to decide which rendering strategy to use.
        var pointCount = 0, polygonCount = 0;
        for (var i = 0; i < features.length; i++) {
            var gt = features[i].geometry ? features[i].geometry.type : '';
            if (gt === 'Point' || gt === 'MultiPoint') pointCount++;
            else if (gt === 'Polygon' || gt === 'MultiPolygon') polygonCount++;
        }

        // Fix #1: density-aware default style. Wide-area queries return
        // hundreds-to-thousands of overlapping polygons; the previous
        // default (weight=2, fillOpacity=0.3) merged them into a solid
        // blob at typical city zoom. Thinner stroke + lower fill at high
        // count keeps individual outlines visible.
        var dense = featureCount > POLY_DENSE_THRESHOLD;
        var defaultStyle = {
            color: safeColor,
            weight: style.weight || (dense ? 1 : 2),
            fillOpacity: style.fillOpacity !== undefined ? style.fillOpacity : (dense ? 0.15 : 0.3)
        };

        // Fix #4: deterministic per-feature varied color. Only when no
        // explicit style has been requested AND there are enough polygons
        // for the all-one-color problem to bite.
        var useVariedColor = (
            !style.color &&
            !style.styleFunction &&
            polygonCount >= POLY_VARIED_THRESHOLD
        );

        var styleFunc = style.styleFunction || function(feature) {
            if (!useVariedColor) return defaultStyle;
            var idx = features.indexOf(feature);
            var c = _hashedColor(feature, idx);
            return {
                color: c, fillColor: c,
                weight: defaultStyle.weight,
                fillOpacity: defaultStyle.fillOpacity
            };
        };

        var usePointClustering = window.L && L.markerClusterGroup && pointCount > CLUSTER_THRESHOLD;

        // Fix #3: polygon centroid clustering. Triggers on EITHER
        //  (a) lots of polygons (POLY_CLUSTER_THRESHOLD), OR
        //  (b) moderate count over a wide bbox (POLY_WIDE_BBOX_MIN_COUNT
        //      polygons spread across ≥ POLY_WIDE_BBOX_KM).
        // The (b) branch catches the canonical "show hospitals in
        // Chicago" failure mode: only 59 features but each ~50m wide
        // and bounds ~30km, so every polygon collapses to sub-pixel at
        // the fit zoom and the user sees a blank map.
        var bboxDiagKm = (polygonCount > 0 && pointCount === 0)
            ? _bboxDiagKm(features) : 0;
        var usePolygonClustering = (
            window.L && L.markerClusterGroup && pointCount === 0 && (
                polygonCount >= POLY_CLUSTER_THRESHOLD ||
                (polygonCount >= POLY_WIDE_BBOX_MIN_COUNT &&
                 bboxDiagKm >= POLY_WIDE_BBOX_KM)
            )
        );

        var geoJsonLayer = L.geoJSON(geojson, {
            style: styleFunc,
            pointToLayer: usePointClustering ? function(feature, latlng) {
                return L.circleMarker(latlng, {
                    radius: 6,
                    fillColor: defaultStyle.color,
                    color: '#333',
                    weight: 1,
                    fillOpacity: 0.7
                });
            } : undefined,
            onEachFeature: function(feature, layer) {
                var props = feature.properties || {};
                var popup = '<b>' + escapeHtml(props.category_name || props.classname || 'Feature') + '</b>';
                if (props.osm_id) popup += '<br>OSM ID: ' + escapeHtml(String(props.osm_id));
                if (props.feature_type) popup += '<br>Type: ' + escapeHtml(String(props.feature_type));
                layer.bindPopup(popup);
            }
        });

        var primaryLayer = geoJsonLayer;
        var clusterLayer = null;
        var swapHandler = null;

        if (usePointClustering) {
            primaryLayer = L.markerClusterGroup({
                maxClusterRadius: 50,
                spiderfyOnMaxZoom: true,
                showCoverageOnHover: false,
                disableClusteringAtZoom: 18,
            });
            primaryLayer.addLayer(geoJsonLayer);
            primaryLayer.addTo(map);
        } else if (usePolygonClustering) {
            // Build the centroid cluster layer (shown only at low zoom).
            clusterLayer = L.markerClusterGroup({
                maxClusterRadius: 60,
                spiderfyOnMaxZoom: false,
                showCoverageOnHover: false,
                disableClusteringAtZoom: ZOOM_TOGGLE_LEVEL + 1,
            });
            for (var ci = 0; ci < features.length; ci++) {
                var ctr = _polygonCentroid(features[ci].geometry);
                if (!ctr) continue;
                var markerColor = useVariedColor ? _hashedColor(features[ci], ci) : safeColor;
                var marker = L.circleMarker([ctr[0], ctr[1]], {
                    radius: 5,
                    fillColor: markerColor,
                    color: '#333',
                    weight: 1,
                    fillOpacity: 0.85
                });
                var props = features[ci].properties || {};
                marker.bindPopup('<b>' + escapeHtml(props.category_name || 'Feature') + '</b>');
                clusterLayer.addLayer(marker);
            }
            // Swap behavior: keep only one layer on the map at a time so
            // we don't pay double-render cost. Honors `visible=false`.
            swapHandler = function() {
                if (!layers[name] || !layers[name].visible) return;
                var z = map.getZoom();
                if (z < ZOOM_TOGGLE_LEVEL) {
                    if (map.hasLayer(geoJsonLayer)) map.removeLayer(geoJsonLayer);
                    if (!map.hasLayer(clusterLayer)) clusterLayer.addTo(map);
                } else {
                    if (map.hasLayer(clusterLayer)) map.removeLayer(clusterLayer);
                    if (!map.hasLayer(geoJsonLayer)) geoJsonLayer.addTo(map);
                }
            };
            map.on('zoomend', swapHandler);
            // Initial state.
            if (map.getZoom() < ZOOM_TOGGLE_LEVEL) {
                clusterLayer.addTo(map);
            } else {
                geoJsonLayer.addTo(map);
            }
        } else {
            primaryLayer.addTo(map);
        }

        layers[name] = {
            leafletLayer: primaryLayer,
            clusterLayer: clusterLayer,
            swapHandler: swapHandler,
            visible: true,
            featureCount: featureCount,
            style: defaultStyle,
            clustered: usePointClustering,
            polygonClustered: !!usePolygonClustering,
            useVariedColor: useVariedColor,
        };

        refreshUI();
        return layers[name];
    }

    /**
     * Initialize an empty layer for chunked delivery.
     * Creates the layer entry so subsequent appendFeatures calls can add data.
     */
    function initLayer(name, style, totalFeatures) {
        // Remove existing layer with same name
        if (layers[name]) {
            removeLayer(name);
        }

        style = style || {};
        var safeColor = (style.color || '#3388ff').replace(/[^#a-fA-F0-9]/g, '');
        var defaultStyle = {
            color: safeColor,
            weight: style.weight || 2,
            fillOpacity: style.fillOpacity || 0.3
        };

        var geoJsonLayer = L.geoJSON(null, {
            style: function() { return defaultStyle; },
            onEachFeature: function(feature, layer) {
                var props = feature.properties || {};
                var popup = '<b>' + escapeHtml(props.category_name || props.classname || 'Feature') + '</b>';
                if (props.osm_id) popup += '<br>OSM ID: ' + escapeHtml(String(props.osm_id));
                if (props.feature_type) popup += '<br>Type: ' + escapeHtml(String(props.feature_type));
                layer.bindPopup(popup);
            }
        });

        geoJsonLayer.addTo(map);

        layers[name] = {
            leafletLayer: geoJsonLayer,
            visible: true,
            featureCount: 0,
            totalExpected: totalFeatures || 0,
            style: defaultStyle,
            clustered: false,
            _isChunked: true
        };

        refreshUI();
        return layers[name];
    }

    /**
     * Append features from a chunk to an existing layer created by initLayer.
     */
    function appendFeatures(name, geojson) {
        if (!layers[name] || !layers[name].leafletLayer) return;

        var leafletLayer = layers[name].leafletLayer;
        if (typeof leafletLayer.addData === 'function' && geojson && geojson.features) {
            leafletLayer.addData(geojson);
            layers[name].featureCount += geojson.features.length;
            refreshUI();
        }
    }

    function removeLayer(name) {
        if (layers[name]) {
            if (layers[name].swapHandler) {
                map.off('zoomend', layers[name].swapHandler);
            }
            if (layers[name].leafletLayer && map.hasLayer(layers[name].leafletLayer)) {
                map.removeLayer(layers[name].leafletLayer);
            }
            if (layers[name].clusterLayer && map.hasLayer(layers[name].clusterLayer)) {
                map.removeLayer(layers[name].clusterLayer);
            }
            delete layers[name];
            refreshUI();

            // Audit M1: server-side delete must include CSRF + Bearer
            // auth or the 400 from CSRFProtect leaves a server-side
            // ghost layer. Use the shared authedFetch helper.
            (window.authedFetch || fetch)(
                '/api/layers/' + encodeURIComponent(name),
                { method: 'DELETE' }
            ).catch(function () { /* best effort */ });
        }
    }

    function _hideAllLayerMembers(entry) {
        if (entry.leafletLayer && map.hasLayer(entry.leafletLayer)) {
            map.removeLayer(entry.leafletLayer);
        }
        if (entry.clusterLayer && map.hasLayer(entry.clusterLayer)) {
            map.removeLayer(entry.clusterLayer);
        }
    }

    function _showLayerMembers(entry) {
        if (entry.swapHandler) {
            // Polygon-cluster layer: the swap handler picks the right
            // member (cluster vs polygon) based on current zoom.
            entry.swapHandler();
        } else if (entry.leafletLayer) {
            entry.leafletLayer.addTo(map);
        }
    }

    function toggleLayer(name) {
        if (!layers[name] || !layers[name].leafletLayer) return;

        if (layers[name].visible) {
            _hideAllLayerMembers(layers[name]);
            layers[name].visible = false;
        } else {
            layers[name].visible = true;
            _showLayerMembers(layers[name]);
        }

        refreshUI();
    }

    function showLayer(name) {
        if (!layers[name] || !layers[name].leafletLayer) return;
        if (!layers[name].visible) {
            layers[name].visible = true;
            _showLayerMembers(layers[name]);
            refreshUI();
        }
    }

    function hideLayer(name) {
        if (!layers[name] || !layers[name].leafletLayer) return;
        if (layers[name].visible) {
            _hideAllLayerMembers(layers[name]);
            layers[name].visible = false;
            refreshUI();
        }
    }

    function fitToLayer(name) {
        if (!layers[name] || !layers[name].leafletLayer) return;

        try {
            var bounds = layers[name].leafletLayer.getBounds();
            if (bounds.isValid()) {
                map.fitBounds(bounds);
            }
        } catch (e) {
            console.warn('fitToLayer: could not get bounds for "' + name + '":', e.message);
        }
    }

    function getLayerNames() {
        return Object.keys(layers);
    }

    function getLayerCount() {
        return Object.keys(layers).length;
    }

    var MAX_RECURSION_DEPTH = 10;

    /**
     * Recursively iterate all feature layers, handling markerClusterGroups
     * and nested layer groups to reach individual feature layers.
     * Depth parameter guards against infinite recursion on circular references.
     */
    function eachFeatureLayer(layer, callback, depth) {
        depth = depth || 0;
        if (depth > MAX_RECURSION_DEPTH) return;

        if (layer.feature) {
            // This is an individual feature layer
            callback(layer);
        } else if (typeof layer.eachLayer === 'function') {
            // This is a group (markerClusterGroup, GeoJSON group, etc.) — recurse
            layer.eachLayer(function(child) {
                eachFeatureLayer(child, callback, depth + 1);
            });
        }
    }

    function styleLayer(name, style) {
        if (!layers[name] || !layers[name].leafletLayer) return;
        var entry = layers[name];
        var leafletLayer = entry.leafletLayer;
        if (typeof leafletLayer.setStyle === 'function' && !entry.clustered) {
            leafletLayer.setStyle(style);
        } else {
            eachFeatureLayer(leafletLayer, function(featureLayer) {
                if (typeof featureLayer.setStyle === 'function') {
                    featureLayer.setStyle(style);
                }
            });
        }
        // Also restyle cluster markers (centroid view) if present so the
        // cluster bubbles match the polygon stroke at low zoom.
        if (entry.clusterLayer) {
            eachFeatureLayer(entry.clusterLayer, function(fl) {
                if (typeof fl.setStyle === 'function') fl.setStyle(style);
            });
        }
        // Update stored style for UI color swatch
        if (style.color) entry.style.color = style.color;
    }

    /**
     * Show only the features whose original index is in `indices`. Used
     * by the animate_layer player: each time-step contains
     * feature_indices, and we want the map to show only those features
     * for the current step. Hidden features are zero-opacity styled so
     * we don't pay the cost of removing/re-adding them per frame.
     */
    function filterToIndices(layerName, indices) {
        if (!layers[layerName]) return;
        var entry = layers[layerName];
        var indexSet = {};
        for (var i = 0; i < indices.length; i++) indexSet[indices[i]] = true;
        var defaultStyle = entry.style || {};
        var visibleStyle = {
            opacity: 1,
            fillOpacity: defaultStyle.fillOpacity || 0.3,
        };
        var hiddenStyle = { opacity: 0, fillOpacity: 0 };
        var idx = 0;
        eachFeatureLayer(entry.leafletLayer, function(featureLayer) {
            if (typeof featureLayer.setStyle !== 'function') { idx++; return; }
            featureLayer.setStyle(indexSet[idx] ? visibleStyle : hiddenStyle);
            idx++;
        });
    }

    /** Restore the layer to its default visible style after filterToIndices. */
    function clearFilter(layerName) {
        if (!layers[layerName]) return;
        var entry = layers[layerName];
        var defaultStyle = entry.style || {};
        var restore = {
            opacity: 1,
            fillOpacity: defaultStyle.fillOpacity || 0.3,
        };
        eachFeatureLayer(entry.leafletLayer, function(featureLayer) {
            if (typeof featureLayer.setStyle === 'function') {
                featureLayer.setStyle(restore);
            }
        });
    }

    function highlightFeatures(layerName, attribute, value, color) {
        if (!layers[layerName]) return;

        var leafletLayer = layers[layerName].leafletLayer;
        eachFeatureLayer(leafletLayer, function(featureLayer) {
            var props = featureLayer.feature ? featureLayer.feature.properties || {} : {};
            var tags = props.osm_tags || {};
            if (String(props[attribute]) === String(value) || String(tags[attribute]) === String(value)) {
                featureLayer.setStyle({ color: color, weight: 3, fillColor: color, fillOpacity: 0.5 });
            }
        });
    }

    function refreshUI() {
        var container = $('#layerList');
        if (!container.length) return;

        container.empty();

        var names = Object.keys(layers);
        if (names.length === 0) {
            container.html('<p class="hint">No layers yet. Use chat or OSM fetch to add layers.</p>');
            $('#layerCount').text('');
            return;
        }

        $('#layerCount').text('(' + names.length + ')');

        names.forEach(function(name) {
            var layer = layers[name];
            var visClass = layer.visible ? '' : ' layer-hidden';
            var eyeIcon = layer.visible ? '👁' : '👁‍🗨';

            var html = '<div class="layer-item' + visClass + '" tabindex="0">' +
                       '<span class="layer-color" style="background-color:' + (layer.style.color || '#3388ff').replace(/[^#a-fA-F0-9]/g, '') + '"></span>' +
                       '<span class="layer-name" data-name="' + escapeAttr(name) + '">' + escapeHtml(name) + '</span>' +
                       '<span class="layer-count">' + layer.featureCount + '</span>' +
                       '<button class="layer-toggle-btn" data-name="' + escapeAttr(name) + '" title="Toggle visibility" aria-label="Toggle layer visibility" aria-pressed="' + (layer.visible ? 'true' : 'false') + '">' + eyeIcon + '</button>' +
                       '<button class="layer-fit-btn" data-name="' + escapeAttr(name) + '" title="Zoom to layer" aria-label="Fit map to layer">⊡</button>' +
                       '<button class="layer-delete-btn" data-name="' + escapeAttr(name) + '" title="Remove layer" aria-label="Remove layer">×</button>' +
                       '</div>';
            container.append(html);
        });

        // Bind events (use off() to prevent listener accumulation)
        container.find('.layer-toggle-btn').off('click').on('click', function() {
            toggleLayer($(this).data('name'));
        });

        container.find('.layer-fit-btn').off('click').on('click', function() {
            fitToLayer($(this).data('name'));
        });

        container.find('.layer-delete-btn').off('click').on('click', function() {
            removeLayer($(this).data('name'));
        });

        container.find('.layer-name').off('click').on('click', function() {
            fitToLayer($(this).data('name'));
        });
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(text));
        return div.innerHTML;
    }

    function escapeAttr(text) {
        return text.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    return {
        init: init,
        addLayer: addLayer,
        initLayer: initLayer,
        appendFeatures: appendFeatures,
        removeLayer: removeLayer,
        toggleLayer: toggleLayer,
        showLayer: showLayer,
        hideLayer: hideLayer,
        fitToLayer: fitToLayer,
        getLayerNames: getLayerNames,
        getLayerCount: getLayerCount,
        highlightFeatures: highlightFeatures,
        styleLayer: styleLayer,
        filterToIndices: filterToIndices,
        clearFilter: clearFilter
    };
})();
