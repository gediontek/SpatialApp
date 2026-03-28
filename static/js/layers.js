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
        var defaultStyle = {
            color: style.color || '#3388ff',
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

    function removeLayer(name) {
        if (layers[name]) {
            map.removeLayer(layers[name].leafletLayer);
            delete layers[name];
            refreshUI();

            // Also remove from server
            fetch('/api/layers/' + encodeURIComponent(name), { method: 'DELETE' });
        }
    }

    function toggleLayer(name) {
        if (!layers[name]) return;

        if (layers[name].visible) {
            map.removeLayer(layers[name].leafletLayer);
            layers[name].visible = false;
        } else {
            layers[name].leafletLayer.addTo(map);
            layers[name].visible = true;
        }

        refreshUI();
    }

    function fitToLayer(name) {
        if (!layers[name] || !layers[name].leafletLayer) return;

        var bounds = layers[name].leafletLayer.getBounds();
        if (bounds.isValid()) {
            map.fitBounds(bounds);
        }
    }

    function getLayerNames() {
        return Object.keys(layers);
    }

    function getLayerCount() {
        return Object.keys(layers).length;
    }

    function highlightFeatures(layerName, attribute, value, color) {
        if (!layers[layerName]) return;

        var leafletLayer = layers[layerName].leafletLayer;
        leafletLayer.eachLayer(function(featureLayer) {
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

            var html = '<div class="layer-item' + visClass + '">' +
                       '<span class="layer-color" style="background-color:' + (layer.style.color || '#3388ff').replace(/[^#a-fA-F0-9]/g, '') + '"></span>' +
                       '<span class="layer-name" data-name="' + escapeAttr(name) + '">' + escapeHtml(name) + '</span>' +
                       '<span class="layer-count">' + layer.featureCount + '</span>' +
                       '<button class="layer-toggle-btn" data-name="' + escapeAttr(name) + '" title="Toggle visibility">' + eyeIcon + '</button>' +
                       '<button class="layer-fit-btn" data-name="' + escapeAttr(name) + '" title="Zoom to layer">⊡</button>' +
                       '<button class="layer-delete-btn" data-name="' + escapeAttr(name) + '" title="Remove layer">×</button>' +
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
        removeLayer: removeLayer,
        toggleLayer: toggleLayer,
        fitToLayer: fitToLayer,
        getLayerNames: getLayerNames,
        getLayerCount: getLayerCount,
        highlightFeatures: highlightFeatures
    };
})();
