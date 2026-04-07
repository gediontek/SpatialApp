/**
 * Chat panel for NL-to-GIS interaction.
 * Connects to /api/chat via SSE and renders results on the Leaflet map.
 */
var ChatPanel = (function() {
    var eventSource = null;
    var sessionId = 'session_' + Date.now();
    var _layerManager = null;

    function init(map, layerManager) {
        _layerManager = layerManager;
        bindEvents(map, layerManager);
    }

    function bindEvents(map, layerManager) {
        $('#chatSendBtn').on('click', function() {
            sendMessage(map, layerManager);
        });

        $('#chatInput').on('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage(map, layerManager);
            }
        });

        // Quick action buttons
        $('.quick-action-btn').on('click', function() {
            var msg = $(this).data('msg');
            if (msg) {
                $('#chatInput').val(msg);
                sendMessage(map, layerManager);
            }
        });
    }

    function sendMessage(map, layerManager) {
        var input = $('#chatInput');
        var message = input.val().trim();
        if (!message) return;

        // Display user message
        appendMessage('user', message);
        input.val('');
        input.focus();

        // Disable input while processing
        input.prop('disabled', true);
        $('#chatSendBtn').prop('disabled', true);

        // Build map context
        var bounds = map.getBounds();
        var context = {
            bounds: {
                south: bounds.getSouth(),
                west: bounds.getWest(),
                north: bounds.getNorth(),
                east: bounds.getEast()
            },
            zoom: map.getZoom(),
            active_layers: layerManager ? layerManager.getLayerNames() : []
        };

        // Show typing indicator
        var typingId = showTyping();

        // Send via fetch + SSE
        fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                session_id: sessionId,
                context: context
            })
        }).then(function(response) {
            if (!response.ok) {
                throw new Error('Chat request failed: ' + response.status);
            }
            return response.body.getReader();
        }).then(function(reader) {
            var decoder = new TextDecoder();
            var buffer = '';

            function processStream() {
                return reader.read().then(function(result) {
                    if (result.done) {
                        removeTyping(typingId);
                        enableInput();
                        return;
                    }

                    buffer += decoder.decode(result.value, { stream: true });

                    // Parse SSE events from buffer
                    var lines = buffer.split('\n');
                    buffer = '';

                    var currentEvent = null;
                    for (var i = 0; i < lines.length; i++) {
                        var line = lines[i];

                        if (line.startsWith('event: ')) {
                            currentEvent = line.substring(7).trim();
                        } else if (line.startsWith('data: ')) {
                            var dataStr = line.substring(6);
                            try {
                                var data = JSON.parse(dataStr);
                                handleEvent(currentEvent || data.type, data, map, layerManager);
                            } catch (e) {
                                // Could be incomplete JSON split across chunks — buffer remaining lines
                                var remaining = lines.slice(i).join('\n');
                                if (remaining.length < 10000) {
                                    buffer = remaining;
                                } else {
                                    // Too large to be a split — malformed event, discard and continue
                                    console.warn('Discarding malformed SSE event:', dataStr.substring(0, 200));
                                    buffer = '';
                                }
                                break;
                            }
                            currentEvent = null;
                        } else if (line === '') {
                            // Empty line = event boundary
                            currentEvent = null;
                        } else {
                            // Incomplete line, put back
                            buffer = lines.slice(i).join('\n');
                            break;
                        }
                    }

                    return processStream();
                });
            }

            return processStream();
        }).catch(function(err) {
            removeTyping(typingId);
            enableInput();
            appendMessage('error', 'Connection error: ' + err.message);
        });
    }

    function handleEvent(type, data, map, layerManager) {
        switch (type) {
            case 'tool_start':
                appendToolStep(data.tool, 'Running ' + data.tool + '...', 'loading');
                break;

            case 'tool_result':
                updateToolStep(data.tool, formatToolResult(data.tool, data.result), 'done');
                break;

            case 'layer_add':
                if (layerManager && data.geojson) {
                    // For classified data with per-category colors
                    if (data.colors) {
                        layerManager.addLayer(data.name, data.geojson, {
                            styleFunction: function(feature) {
                                var cat = feature.properties.classname || 'unknown';
                                return {
                                    fillColor: data.colors[cat] || '#808080',
                                    color: '#333',
                                    weight: 1,
                                    fillOpacity: 0.7
                                };
                            }
                        });
                    } else {
                        layerManager.addLayer(data.name, data.geojson, data.style || {});
                    }
                }
                break;

            case 'layer_command':
                if (layerManager && data.layer_name) {
                    if (data.action === 'show') layerManager.showLayer(data.layer_name);
                    else if (data.action === 'hide') layerManager.hideLayer(data.layer_name);
                    else if (data.action === 'remove') layerManager.removeLayer(data.layer_name);
                }
                break;

            case 'highlight':
                if (layerManager && data.layer_name) {
                    layerManager.highlightFeatures(
                        data.layer_name, data.attribute, data.value, data.color || '#ff0000'
                    );
                }
                break;

            case 'heatmap':
                if (window.L && window.L.heatLayer && data.points) {
                    var heatLayer = L.heatLayer(data.points, data.options || {});
                    heatLayer.addTo(map);
                }
                break;

            case 'layer_style':
                if (layerManager && data.layer_name && data.style) {
                    layerManager.styleLayer(data.layer_name, data.style);
                }
                break;

            case 'map_command':
                executeMapCommand(data, map);
                break;

            case 'message':
                removeTyping();
                appendMessage('assistant', data.text);
                if (data.done) {
                    enableInput();
                }
                break;

            case 'error':
                removeTyping();
                appendMessage('error', data.text);
                enableInput();
                break;
        }
    }

    function executeMapCommand(cmd, map) {
        var action = cmd.action;

        if (action === 'pan' || action === 'pan_and_zoom') {
            var zoom = cmd.zoom || map.getZoom();
            map.setView([cmd.lat, cmd.lon], zoom);
        } else if (action === 'zoom') {
            map.setZoom(cmd.zoom);
        } else if (action === 'zoom_relative') {
            map.setZoom(map.getZoom() + (cmd.delta || 0));
        } else if (action === 'fit_bounds') {
            if (cmd.bbox && cmd.bbox.length === 4) {
                map.fitBounds([
                    [cmd.bbox[0], cmd.bbox[1]],
                    [cmd.bbox[2], cmd.bbox[3]]
                ]);
            }
        } else if (action === 'change_basemap') {
            if (window.baseMaps) {
                // Remove all basemaps first, then add the requested one
                Object.values(window.baseMaps).forEach(function(layer) {
                    if (map.hasLayer(layer)) map.removeLayer(layer);
                });
                if (cmd.basemap === 'satellite') {
                    var sat = window.baseMaps['Google Satellite'] || Object.values(window.baseMaps)[1];
                    if (sat) sat.addTo(map);
                } else {
                    var osm = window.baseMaps['OpenStreetMap'] || Object.values(window.baseMaps)[0];
                    if (osm) osm.addTo(map);
                }
            }
        }
    }

    function formatToolResult(tool, result) {
        if (result.error) return 'Error: ' + result.error;

        switch (tool) {
            case 'geocode':
                return result.display_name + ' (' + result.lat.toFixed(4) + ', ' + result.lon.toFixed(4) + ')';
            case 'fetch_osm':
            case 'search_nearby':
                var msg = result.feature_count + ' features';
                if (result.capped) msg += ' (limit reached)';
                return msg;
            case 'map_command':
                return result.description || 'Done';
            case 'calculate_area':
                return result.total_area_sq_km.toFixed(2) + ' sq km (' + result.feature_count + ' features)';
            case 'measure_distance':
                return result.distance_km.toFixed(1) + ' km (' + result.distance_mi.toFixed(1) + ' mi)';
            case 'buffer':
                return 'Buffer ' + result.buffer_distance_m + 'm (' + result.area_sq_km + ' sq km)';
            case 'spatial_query':
                return result.feature_count + '/' + result.source_total + ' features match (' + result.match_percentage + '%)';
            case 'aggregate':
                if (result.total !== undefined) return 'Total: ' + result.total;
                if (result.total_area_sq_km) return result.total_area_sq_km + ' sq km';
                return JSON.stringify(result).substring(0, 80);
            case 'classify_landcover':
                return result.feature_count + ' features classified';
            case 'add_annotation':
                return result.added + ' annotation(s) saved';
            case 'get_annotations':
                return result.total + ' annotations';
            case 'export_annotations':
                return result.count + ' annotations → ' + result.format;
            case 'find_route':
                return result.distance_km + ' km, ' + result.duration_min + ' min (' + result.profile + ')';
            case 'isochrone':
                return result.area_sq_km + ' sq km reachable (' + result.profile + ')';
            case 'heatmap':
                return result.point_count + ' points';
            case 'highlight_features':
                return result.highlighted + '/' + result.total + ' features highlighted';
            case 'filter_layer':
                return result.feature_count + '/' + result.original_count + ' features matched';
            case 'style_layer':
                return result.description || 'Styled';
            case 'show_layer':
            case 'hide_layer':
            case 'remove_layer':
                return result.description || 'Done';
            default:
                return JSON.stringify(result).substring(0, 100);
        }
    }

    function appendMessage(role, text) {
        var msgClass = role === 'user' ? 'chat-msg-user' :
                       role === 'error' ? 'chat-msg-error' : 'chat-msg-assistant';
        var content;
        if (role === 'assistant' && window.marked && window.DOMPurify) {
            content = DOMPurify.sanitize(marked.parse(text));
        } else {
            content = escapeHtml(text);
        }

        var msgDiv = document.createElement('div');
        msgDiv.className = 'chat-msg ' + msgClass;
        var contentDiv = document.createElement('div');
        contentDiv.className = 'chat-msg-content';
        contentDiv.innerHTML = content;  // Already sanitized by DOMPurify above
        msgDiv.appendChild(contentDiv);
        document.getElementById('chatMessages').appendChild(msgDiv);

        // Make layer names clickable using safe DOM APIs
        if (role === 'assistant' && _layerManager) {
            var layerNames = _layerManager.getLayerNames();
            // Walk text nodes and wrap layer name matches in clickable spans
            layerNames.forEach(function(name) {
                var walker = document.createTreeWalker(contentDiv, NodeFilter.SHOW_TEXT, null, false);
                var textNode;
                while ((textNode = walker.nextNode())) {
                    var idx = textNode.nodeValue.indexOf(name);
                    if (idx >= 0) {
                        var before = textNode.nodeValue.substring(0, idx);
                        var after = textNode.nodeValue.substring(idx + name.length);
                        var span = document.createElement('span');
                        span.className = 'layer-ref';
                        span.textContent = name;  // Safe: textContent, not innerHTML
                        span.addEventListener('click', (function(n) {
                            return function() { if (_layerManager) _layerManager.fitToLayer(n); };
                        })(name));
                        var parent = textNode.parentNode;
                        if (before) parent.insertBefore(document.createTextNode(before), textNode);
                        parent.insertBefore(span, textNode);
                        if (after) parent.insertBefore(document.createTextNode(after), textNode);
                        parent.removeChild(textNode);
                        break;  // One replacement per layer name per message
                    }
                }
            });
        }

        scrollToBottom();
    }

    function appendToolStep(toolName, text, status) {
        var safeName = toolName.replace(/[^a-z0-9_]/gi, '');
        var id = 'tool-' + safeName;
        var statusClass = status === 'loading' ? 'tool-loading' : 'tool-done';
        var html = '<div class="chat-tool-step ' + statusClass + '" id="' + escapeHtml(id) + '">' +
                   '<span class="tool-icon">' + (status === 'loading' ? '⟳' : '✓') + '</span> ' +
                   '<span class="tool-text">' + escapeHtml(text) + '</span>' +
                   '</div>';
        $('#chatMessages').append(html);
        scrollToBottom();
    }

    function updateToolStep(toolName, text, status) {
        var id = '#tool-' + toolName.replace(/[^a-z0-9]/g, '');
        var el = $(id);
        if (el.length) {
            el.removeClass('tool-loading').addClass('tool-done');
            el.find('.tool-icon').text('✓');
            el.find('.tool-text').text(text);
        }
    }

    function showTyping() {
        var id = 'typing-' + Date.now();
        var html = '<div class="chat-typing" id="' + id + '">' +
                   '<span class="typing-dot"></span>' +
                   '<span class="typing-dot"></span>' +
                   '<span class="typing-dot"></span>' +
                   '</div>';
        $('#chatMessages').append(html);
        scrollToBottom();
        return id;
    }

    function removeTyping(id) {
        if (id) {
            $('#' + id).remove();
        } else {
            $('.chat-typing').remove();
        }
    }

    function enableInput() {
        $('#chatInput').prop('disabled', false);
        $('#chatSendBtn').prop('disabled', false);
        $('#chatInput').focus();
    }

    function scrollToBottom() {
        var container = document.getElementById('chatMessages');
        if (container) {
            container.scrollTop = container.scrollHeight;
        }
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(text));
        return div.innerHTML;
    }

    return { init: init };
})();
