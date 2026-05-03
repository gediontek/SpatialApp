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

    var CLUSTER_THRESHOLD = 200;  // Auto-cluster when point count exceeds this

    function addLayer(name, geojson, style) {
        // Remove existing layer with same name
        if (layers[name]) {
            removeLayer(name);
        }

        style = style || {};
        // Sanitize color at input time to prevent injection via style properties
        var safeColor = (style.color || '#3388ff').replace(/[^#a-fA-F0-9]/g, '');
        var defaultStyle = {
            color: safeColor,
            weight: style.weight || 2,
            fillOpacity: style.fillOpacity || 0.3
        };

        var styleFunc = style.styleFunction || function(feature) {
            return defaultStyle;
        };

        var featureCount = geojson.features ? geojson.features.length : 0;

        // Check if this is a point-heavy layer that should be clustered
        var pointCount = 0;
        if (geojson.features) {
            for (var i = 0; i < geojson.features.length; i++) {
                var geomType = geojson.features[i].geometry ? geojson.features[i].geometry.type : '';
                if (geomType === 'Point' || geomType === 'MultiPoint') pointCount++;
            }
        }
        var useClustering = window.L && L.markerClusterGroup && pointCount > CLUSTER_THRESHOLD;

        var geoJsonLayer = L.geoJSON(geojson, {
            style: styleFunc,
            pointToLayer: useClustering ? function(feature, latlng) {
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

        var leafletLayer;
        if (useClustering) {
            leafletLayer = L.markerClusterGroup({
                maxClusterRadius: 50,
                spiderfyOnMaxZoom: true,
                showCoverageOnHover: false,
                disableClusteringAtZoom: 18,
            });
            leafletLayer.addLayer(geoJsonLayer);
        } else {
            leafletLayer = geoJsonLayer;
        }

        leafletLayer.addTo(map);

        layers[name] = {
            leafletLayer: leafletLayer,
            visible: true,
            featureCount: featureCount,
            style: defaultStyle,
            clustered: useClustering
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
            map.removeLayer(layers[name].leafletLayer);
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

    function toggleLayer(name) {
        if (!layers[name] || !layers[name].leafletLayer) return;

        if (layers[name].visible) {
            map.removeLayer(layers[name].leafletLayer);
            layers[name].visible = false;
        } else {
            layers[name].leafletLayer.addTo(map);
            layers[name].visible = true;
        }

        refreshUI();
    }

    function showLayer(name) {
        if (!layers[name] || !layers[name].leafletLayer) return;
        if (!layers[name].visible) {
            layers[name].leafletLayer.addTo(map);
            layers[name].visible = true;
            refreshUI();
        }
    }

    function hideLayer(name) {
        if (!layers[name] || !layers[name].leafletLayer) return;
        if (layers[name].visible) {
            map.removeLayer(layers[name].leafletLayer);
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
        var leafletLayer = layers[name].leafletLayer;
        if (typeof leafletLayer.setStyle === 'function' && !layers[name].clustered) {
            leafletLayer.setStyle(style);
        } else {
            eachFeatureLayer(leafletLayer, function(featureLayer) {
                if (typeof featureLayer.setStyle === 'function') {
                    featureLayer.setStyle(style);
                }
            });
        }
        // Update stored style for UI color swatch
        if (style.color) layers[name].style.color = style.color;
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
        styleLayer: styleLayer
    };
})();
