$(document).ready(function() {
    // Audit H1: centralized auth — attach BOTH CSRF token AND
    // Authorization: Bearer (when present) on every state-mutating
    // jQuery ajax. Helper lives in static/js/auth.js (loaded earlier
    // by templates/index.html).
    $.ajaxSetup({
        beforeSend: function(xhr, settings) {
            if (window.SpatialAuth && typeof window.SpatialAuth.authedAjaxBeforeSend === 'function') {
                window.SpatialAuth.authedAjaxBeforeSend(xhr, settings);
            }
        }
    });

    // HTML escaping to prevent XSS
    function escapeHtml(str) {
        if (typeof str !== 'string') return '';
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    }

    // Toast notification system
    function showToast(message, type) {
        type = type || 'info';
        var toast = document.createElement('div');
        toast.className = 'toast ' + type;
        toast.textContent = message;
        var $toast = $(toast);
        $('#toast-container').append($toast);

        setTimeout(function() {
            $toast.addClass('fade-out');
            setTimeout(function() {
                $toast.remove();
            }, 300);
        }, 4000);
    }

    // Loading overlay functions
    function showLoading(text) {
        $('#loading-text').text(text || 'Loading...');
        $('#loading-overlay').removeClass('hidden');
    }

    function hideLoading() {
        $('#loading-overlay').addClass('hidden');
    }

    // Initialize map
    var map = L.map('map').setView([47.6062, -122.3321], 13);
    // Expose the Leaflet map alongside window.LayerManager and
    // window.baseMaps so tests + chat handlers can observe map state
    // without reaching into the IIFE closure. The bare `<div id="map">`
    // would otherwise shadow this via the legacy named-element global.
    window.map = map;

    var osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    var googleLayer = L.tileLayer('https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', {
        maxZoom: 20,
        subdomains: ['mt0', 'mt1', 'mt2', 'mt3'],
        attribution: 'Map data © Google'
    });

    var baseMaps = {
        "OpenStreetMap": osmLayer,
        "Google Satellite": googleLayer
    };

    // Expose baseMaps globally for chat basemap switching
    window.baseMaps = baseMaps;

    L.control.layers(baseMaps).addTo(map);

    var imageOverlay;

    // Handle Raster Upload
    $('#uploadForm').on('submit', function(event) {
        event.preventDefault();

        var fileInput = $('#file')[0];
        if (!fileInput.files.length) {
            showToast('Please select a file to upload.', 'warning');
            return;
        }

        var formData = new FormData(this);
        showLoading('Uploading raster file...');
        $('#uploadBtn').prop('disabled', true);

        $.ajax({
            url: '/upload',
            type: 'POST',
            data: formData,
            contentType: false,
            processData: false,
            success: function(data) {
                hideLoading();
                $('#uploadBtn').prop('disabled', false);

                if (imageOverlay) {
                    map.removeLayer(imageOverlay);
                }
                imageOverlay = L.imageOverlay(data.image_url, data.image_bounds, { opacity: 0.4 }).addTo(map);
                map.fitBounds(data.image_bounds);

                // Show the opacity controls now that a raster is loaded
                $('#raster-controls').show();
                $('#transparency-slider').val(0.4);

                showToast('Raster file uploaded successfully!', 'success');
            },
            error: function(xhr) {
                hideLoading();
                $('#uploadBtn').prop('disabled', false);
                var message = xhr.responseJSON ? xhr.responseJSON.message : 'Error uploading image.';
                showToast(message, 'error');
                console.error('Error loading image:', xhr.responseText);
            }
        });
    });

    // Handle Transparency Slider
    $('#transparency-slider').on('input', function() {
        var opacity = parseFloat(this.value);
        if (imageOverlay) {
            imageOverlay.setOpacity(opacity);
        }
    });

    var drawnItems = new L.FeatureGroup();
    map.addLayer(drawnItems);

    var drawControl = new L.Control.Draw({
        draw: {
            rectangle: {
                shapeOptions: {
                    color: $('#color').val(),
                    weight: 2
                },
                repeatMode: true
            },
            polygon: {
                allowIntersection: false,
                showArea: true,
                drawError: {
                    color: '#e1e100',
                    message: '<strong>Error:</strong> Shapes cannot intersect!'
                },
                shapeOptions: {
                    color: $('#color').val(),
                    weight: 2
                }
            },
            circle: {
                shapeOptions: {
                    color: $('#color').val(),
                    weight: 2
                },
                repeatMode: true
            },
            polyline: {
                shapeOptions: {
                    color: $('#color').val(),
                    weight: 2
                },
                repeatMode: true
            },
            marker: false,
            circlemarker: false
        },
        edit: {
            featureGroup: drawnItems
        }
    });
    map.addControl(drawControl);

    // Update draw control color based on selected color
    $('#color').on('change', function() {
        var newColor = $(this).val();
        drawControl.setDrawingOptions({
            rectangle: { shapeOptions: { color: newColor, weight: 2 } },
            polygon: { shapeOptions: { color: newColor, weight: 2 } },
            circle: { shapeOptions: { color: newColor, weight: 2 } },
            polyline: { shapeOptions: { color: newColor, weight: 2 } }
        });
    });

    // Handle Drawing Created
    map.on(L.Draw.Event.CREATED, function(event) {
        var layer = event.layer;
        drawnItems.addLayer(layer);

        var geoJson = layer.toGeoJSON();
        geoJson.properties = {
            category_name: $('#category_name').val(),
            color: $('#color').val()
        };

        $.ajax({
            url: '/save_annotation',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(geoJson),
            success: function(response) {
                if (response.success) {
                    showToast('Annotation saved (ID: ' + response.id + ')', 'success');
                    refreshTable();

                    // Restart polygon drawing mode
                    if (event.layerType === 'polygon') {
                        new L.Draw.Polygon(map, drawControl.options.draw.polygon).enable();
                    }
                }
            },
            error: function(xhr) {
                var message = xhr.responseJSON ? xhr.responseJSON.error : 'Error saving annotation.';
                showToast(message, 'error');
                console.error('Error saving annotation:', xhr.responseText);
            }
        });
    });

    // Refresh annotations table
    function refreshTable() {
        $.getJSON('/get_annotations', function(data) {
            if (data.features && data.features.length > 0) {
                $.ajax({
                    url: '/display_table',
                    type: 'POST',
                    contentType: 'application/json',
                    data: JSON.stringify(data),
                    success: function(html) {
                        $('#attributeTable').html(html);
                    },
                    error: function(xhr) {
                        console.error('Error displaying table:', xhr.responseText);
                    }
                });
            } else {
                $('#attributeTable').html('<p>No annotations yet.</p>');
            }
        });
    }

    // Clear Annotations
    $('#clearAnnotationsBtn').on('click', function() {
        if (!confirm('Are you sure you want to clear all annotations? A backup will be created.')) {
            return;
        }

        showLoading('Clearing annotations...');

        $.ajax({
            url: '/clear_annotations',
            type: 'POST',
            success: function(response) {
                hideLoading();
                drawnItems.clearLayers();
                $('#attributeTable').html('<p>No annotations yet.</p>');
                showToast('All annotations cleared. Backup created.', 'success');
            },
            error: function(xhr) {
                hideLoading();
                var message = xhr.responseJSON ? xhr.responseJSON.error : 'Error clearing annotations.';
                showToast(message, 'error');
                console.error('Error clearing annotations:', xhr.responseText);
            }
        });
    });

    // Open Saved Annotations
    $('#openSavedAnnotationsBtn').on('click', function() {
        window.open('/saved_annotations', '_blank');
    });

    // Finalize Annotations
    $('#finalizeAnnotationsBtn').on('click', function() {
        showLoading('Finalizing annotations...');

        $.ajax({
            url: '/finalize_annotations',
            type: 'POST',
            success: function(response) {
                hideLoading();
                if (response.success) {
                    showToast('Annotations finalized! Total: ' + response.count, 'success');
                } else {
                    showToast('Error finalizing annotations.', 'error');
                }
            },
            error: function(xhr) {
                hideLoading();
                var message = xhr.responseJSON ? xhr.responseJSON.error : 'Error finalizing annotations.';
                showToast(message, 'error');
                console.error('Error finalizing annotations:', xhr.responseText);
            }
        });
    });

    // Export functions
    function exportAnnotations(format) {
        showLoading('Exporting as ' + format + '...');
        window.location.href = '/export_annotations/' + format;
        setTimeout(function() {
            hideLoading();
            showToast('Export started. Check your downloads.', 'info');
        }, 1000);
    }

    $('#exportGeoJsonBtn').on('click', function() {
        exportAnnotations('geojson');
    });

    $('#exportShapefileBtn').on('click', function() {
        exportAnnotations('shapefile');
    });

    $('#exportGeoPackageBtn').on('click', function() {
        exportAnnotations('geopackage');
    });

    // Fetch OSM Data
    $('#fetchOsmBtn').on('click', function() {
        var categoryName = $('#category_name').val().trim();

        // Validate category name is set
        if (!categoryName) {
            showToast('Please enter a Category Name before fetching OSM data.', 'warning');
            $('#category_name').focus();
            return;
        }

        var zoom = map.getZoom();
        if (zoom < 10) {
            showToast('Zoom in to level 10 or higher to fetch OSM data.', 'warning');
            return;
        }

        var bounds = map.getBounds();
        var bbox = [bounds.getSouth(), bounds.getWest(), bounds.getNorth(), bounds.getEast()].join(',');
        var featureType = $('#osm_feature').val();

        showLoading('Fetching OSM data...');
        $('#fetchOsmBtn').prop('disabled', true);

        $.ajax({
            url: '/fetch_osm_data',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ bbox: bbox, feature_type: featureType, category_name: categoryName }),
            success: function(data) {
                hideLoading();
                $('#fetchOsmBtn').prop('disabled', false);

                if (data.error) {
                    showToast(data.error, 'error');
                    return;
                }

                if (data.features && data.features.length > 0) {
                    var geoJsonLayer = L.geoJson(data, {
                        style: function(feature) {
                            return { color: '#3388ff', weight: 2 };
                        },
                        onEachFeature: function(feature, layer) {
                            var props = feature.properties || {};
                            var popup = '<b>' + escapeHtml(props.category_name || 'Feature') + '</b>';
                            if (props.osm_id) {
                                popup += '<br>OSM ID: ' + escapeHtml(String(props.osm_id));
                            }
                            layer.bindPopup(popup);
                        }
                    });

                    drawnItems.addLayer(geoJsonLayer);

                    // Add fetched data to annotations
                    $.ajax({
                        url: '/add_osm_annotations',
                        type: 'POST',
                        contentType: 'application/json',
                        data: JSON.stringify(data),
                        success: function(response) {
                            if (response.success) {
                                showToast('Added ' + response.added + ' OSM features.', 'success');
                                refreshTable();
                            }
                        },
                        error: function(xhr) {
                            var message = xhr.responseJSON ? xhr.responseJSON.error : 'Error adding OSM annotations.';
                            showToast(message, 'error');
                        }
                    });
                } else {
                    showToast('No OSM data found for the given parameters.', 'info');
                }
            },
            error: function(xhr) {
                hideLoading();
                $('#fetchOsmBtn').prop('disabled', false);
                var message = xhr.responseJSON ? xhr.responseJSON.error : 'Error fetching OSM data.';
                showToast(message, 'error');
                console.error('Error fetching OSM data:', xhr.responseText);
            }
        });
    });

    // Disabled: Don't load previous annotations on page load
    // Each session starts fresh - annotations are created and exported as needed
    /*
    $.getJSON('/get_annotations', function(data) {
        if (data.features && data.features.length > 0) {
            annotationCount = data.features.length;
            updateAnnotationCount(annotationCount);

            L.geoJson(data, {
                style: function(feature) {
                    return {
                        color: (feature.properties && feature.properties.color) || '#3388ff',
                        weight: 2
                    };
                },
                onEachFeature: function(feature, layer) {
                    drawnItems.addLayer(layer);
                    if (feature.properties) {
                        var popup = '<b>' + (feature.properties.category_name || 'Feature') + '</b>';
                        layer.bindPopup(popup);
                    }
                }
            });

            refreshTable();
        }
    }).fail(function() {
        console.error('Error loading annotations.');
    });
    */

    // Handle double-click to finish polygon drawing
    map.on('dblclick', function(e) {
        var polygonDrawer = drawControl._toolbars.draw._modes.polygon.handler;
        if (polygonDrawer && polygonDrawer._drawing) {
            polygonDrawer._finishShape();
        }
    });

    // Keyboard shortcuts
    $(document).on('keydown', function(e) {
        // Escape to cancel drawing
        if (e.key === 'Escape') {
            if (drawControl._toolbars.draw._activeMode) {
                drawControl._toolbars.draw._activeMode.handler.disable();
            }
        }
    });

    // ============================================================
    // Tab Navigation
    // ============================================================

    var classifiedLayer = null;
    var classifiedFilePath = null;

    // Tab switching
    $('.tab-btn').on('click', function() {
        var tabId = $(this).data('tab');

        // Update button states
        $('.tab-btn').removeClass('active');
        $(this).addClass('active');

        // Show/hide tab content
        $('.tab-content').removeClass('active');
        $('#tab-' + tabId).addClass('active');
    });

    // ============================================================
    // Auto Classification Functions
    // ============================================================

    function setAutoStatus(message, statusClass) {
        var $status = $('#auto-status');
        $status.text(message);
        $status.removeClass('loading success error').addClass(statusClass || '');
    }

    function buildLegend(colors) {
        var $legend = $('#classification-legend');
        $legend.empty();

        var categories = [
            { key: 'builtup_area', label: 'Built-up Area' },
            { key: 'water', label: 'Water' },
            { key: 'bare_earth', label: 'Bare Earth' },
            { key: 'forest', label: 'Forest' },
            { key: 'farmland', label: 'Farmland' },
            { key: 'grassland', label: 'Grassland' },
            { key: 'aquaculture', label: 'Aquaculture' }
        ];

        categories.forEach(function(cat) {
            var color = colors[cat.key] || '#808080';
            $legend.append(
                '<div class="legend-item">' +
                '<span class="legend-color" style="background-color: ' + color + ';"></span>' +
                '<span class="legend-label">' + cat.label + '</span>' +
                '</div>'
            );
        });

        $('#legend-section').show();
    }

    function displayClassifiedData(geojson, colors) {
        // Remove existing classified layer
        if (classifiedLayer) {
            map.removeLayer(classifiedLayer);
        }

        // Add new layer with category-based styling
        classifiedLayer = L.geoJSON(geojson, {
            style: function(feature) {
                var category = feature.properties.classname || 'unknown';
                var color = colors[category] || '#808080';
                return {
                    fillColor: color,
                    color: '#333',
                    weight: 1,
                    fillOpacity: 0.7
                };
            },
            onEachFeature: function(feature, layer) {
                var props = feature.properties || {};
                var popup = '<b>' + escapeHtml(props.classname || 'Unknown') + '</b>';
                if (props.landuse) {
                    popup += '<br>Original: ' + escapeHtml(props.landuse);
                }
                layer.bindPopup(popup);
            }
        }).addTo(map);

        // Fit map to classified data bounds
        if (classifiedLayer.getBounds().isValid()) {
            map.fitBounds(classifiedLayer.getBounds());
        }
    }

    // Pan to location (geocode only)
    $('#panToLocationBtn').on('click', function() {
        var location = $('#auto-location').val().trim();
        if (!location) {
            showToast('Please enter a location name.', 'warning');
            return;
        }

        setAutoStatus('Searching for location...', 'loading');

        $.ajax({
            url: '/api/geocode',
            type: 'GET',
            data: { q: location },
            success: function(data) {
                if (data.error) {
                    setAutoStatus('Location not found.', 'error');
                    showToast(data.error, 'error');
                    return;
                }
                map.setView([data.lat, data.lon], 13);
                setAutoStatus('Centered on: ' + data.display_name.split(',')[0], 'success');
                showToast('Panned to ' + data.display_name.split(',')[0], 'success');
            },
            error: function(xhr) {
                var message = xhr.responseJSON ? xhr.responseJSON.error : 'Error searching location.';
                setAutoStatus('Search failed.', 'error');
                showToast(message, 'error');
            }
        });
    });

    // Select All / Deselect All classes
    $('#selectAllClasses').on('click', function() {
        $('.class-filter').prop('checked', true);
    });

    $('#deselectAllClasses').on('click', function() {
        $('.class-filter').prop('checked', false);
    });

    // Get selected classes
    function getSelectedClasses() {
        var selected = [];
        $('.class-filter:checked').each(function() {
            selected.push($(this).val());
        });
        return selected;
    }

    // Auto classify
    $('#autoClassifyBtn').on('click', function() {
        var useCurrentExtent = $('#use-current-extent').is(':checked');
        var location = $('#auto-location').val().trim();
        var selectedClasses = getSelectedClasses();

        // Validate input
        if (!useCurrentExtent && !location) {
            showToast('Please enter a location name or check "Use current map extent".', 'warning');
            return;
        }

        if (selectedClasses.length === 0) {
            showToast('Please select at least one landcover class.', 'warning');
            return;
        }

        // Build request data
        var requestData = {
            selected_classes: selectedClasses
        };

        if (useCurrentExtent) {
            var bounds = map.getBounds();
            requestData.bbox = {
                north: bounds.getNorth(),
                south: bounds.getSouth(),
                east: bounds.getEast(),
                west: bounds.getWest()
            };
        } else {
            requestData.place = location;
        }

        setAutoStatus('Downloading OSM data...', 'loading');
        showLoading('Downloading and classifying landcover data...\nThis may take a few minutes for large areas.');
        $('#autoClassifyBtn').prop('disabled', true);

        $.ajax({
            url: '/api/auto-classify',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(requestData),
            timeout: 600000, // 10 minute timeout for large areas
            success: function(data) {
                hideLoading();
                $('#autoClassifyBtn').prop('disabled', false);

                if (data.error) {
                    setAutoStatus('Classification failed.', 'error');
                    showToast(data.error, 'error');
                    return;
                }

                // Display classified data on map
                displayClassifiedData(data.geojson, data.colors);

                // Build legend
                buildLegend(data.colors);

                // Update status
                setAutoStatus('Classified ' + data.features + ' features', 'success');
                showToast('Classified ' + data.features + ' landcover features!', 'success');

                // Enable export and show file path
                classifiedFilePath = data.saved_to;
                $('#exportClassifiedBtn').prop('disabled', false);
                $('#classified-file-info').text('Saved to: ' + data.saved_to);
            },
            error: function(xhr) {
                hideLoading();
                $('#autoClassifyBtn').prop('disabled', false);
                var message = xhr.responseJSON ? xhr.responseJSON.error : 'Classification error.';
                setAutoStatus('Classification failed.', 'error');
                showToast(message, 'error');
            }
        });
    });

    // Enter key triggers classify
    $('#auto-location').on('keypress', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            $('#autoClassifyBtn').click();
        }
    });

    // Export classified data
    $('#exportClassifiedBtn').on('click', function() {
        if (classifiedFilePath) {
            showToast('Classified data already saved to: ' + classifiedFilePath, 'info');
        } else {
            showToast('No classified data to export.', 'warning');
        }
    });

    // Clear classified data
    $('#clearClassifiedBtn').on('click', function() {
        if (classifiedLayer) {
            map.removeLayer(classifiedLayer);
            classifiedLayer = null;
        }
        classifiedFilePath = null;
        $('#legend-section').hide();
        $('#exportClassifiedBtn').prop('disabled', true);
        $('#classified-file-info').text('');
        setAutoStatus('Ready', '');
        showToast('Classified data cleared.', 'info');
    });

    // ============================================================
    // Initialize Layer Manager and Chat Panel
    // ============================================================

    if (typeof LayerManager !== 'undefined') {
        LayerManager.init(map);
    }

    if (typeof ChatPanel !== 'undefined') {
        ChatPanel.init(map, LayerManager);
    }
});
