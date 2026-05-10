/**
 * Chat panel for NL-to-GIS interaction.
 * Connects to /api/chat via SSE and renders results on the Leaflet map.
 */
var ChatPanel = (function() {
    var MAX_LAYERS = 50;
    var eventSource = null;
    var sessionId = (function() {
        var stored = sessionStorage.getItem('chatSessionId');
        if (stored) return stored;
        var id;
        if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
            id = 'session_' + crypto.randomUUID();
        } else {
            var arr = new Uint8Array(16);
            crypto.getRandomValues(arr);
            id = 'session_' + Array.from(arr, function(b) { return b.toString(16).padStart(2, '0'); }).join('');
        }
        sessionStorage.setItem('chatSessionId', id);
        return id;
    })();
    var currentAbortController = null;
    var _layerManager = null;
    var toolStepCounter = 0;
    var _lastToolStepId = null;
    var _pendingPlan = null;  // Stores plan steps awaiting user approval
    var _map = null;  // Reference to map for plan execution

    // WebSocket state
    var _socket = null;
    var _useWebSocket = false;
    var _wsMap = null;
    var _wsLayerManager = null;
    var _wsTypingId = null;

    function init(map, layerManager) {
        _layerManager = layerManager;
        _map = map;
        bindEvents(map, layerManager);
        initNetworkStatusMonitor();
        initWebSocket(map, layerManager);
    }

    /**
     * Initialize WebSocket transport if Socket.IO client is available.
     * Falls back to SSE if Socket.IO is not loaded or connection fails.
     */
    function initWebSocket(map, layerManager) {
        if (typeof io === 'undefined') {
            console.log('ChatPanel: Socket.IO not available, using SSE transport');
            return;
        }

        _wsMap = map;
        _wsLayerManager = layerManager;

        try {
            var token = localStorage.getItem('api_token') || '';
            _socket = io({
                query: { token: token },
                transports: ['websocket', 'polling'],
                reconnection: true,
                reconnectionAttempts: 5,
                reconnectionDelay: 1000,
                reconnectionDelayMax: 5000
            });

            _socket.on('connect', function() {
                console.log('ChatPanel: WebSocket connected');
                _useWebSocket = true;
                // Join session room
                _socket.emit('join_session', { session_id: sessionId });
            });

            _socket.on('disconnect', function(reason) {
                console.log('ChatPanel: WebSocket disconnected:', reason);
                // Keep _useWebSocket true so reconnection attempts work.
                // Only fall back to SSE if we never connected successfully.
            });

            _socket.on('connect_error', function(err) {
                console.warn('ChatPanel: WebSocket connection error, falling back to SSE:', err.message);
                _useWebSocket = false;
                if (_socket) {
                    _socket.close();
                    _socket = null;
                }
            });

            _socket.on('session_joined', function(data) {
                console.log('ChatPanel: Joined session room', data.session_id);
            });

            _socket.on('chat_event', function(data) {
                var eventType = data.type || 'message';
                handleEvent(eventType, data, _wsMap, _wsLayerManager);

                // Clean up typing indicator and re-enable input on terminal events
                if (eventType === 'message' && data.done) {
                    removeTyping(_wsTypingId);
                    _wsTypingId = null;
                    enableInput();
                } else if (eventType === 'error') {
                    removeTyping(_wsTypingId);
                    _wsTypingId = null;
                    enableInput();
                }
            });

            _socket.on('error', function(data) {
                console.error('ChatPanel: WebSocket error event:', data);
                appendMessage('error', data.text || 'WebSocket error');
            });
        } catch (e) {
            console.warn('ChatPanel: Failed to initialize WebSocket, using SSE:', e);
            _useWebSocket = false;
        }
    }

    /**
     * Monitor online/offline events and show a banner when the network drops.
     */
    function initNetworkStatusMonitor() {
        window.addEventListener('offline', function() {
            showNetworkBanner(true);
        });
        window.addEventListener('online', function() {
            showNetworkBanner(false);
        });
    }

    function showNetworkBanner(isOffline) {
        var existing = document.getElementById('network-status-banner');
        if (isOffline) {
            if (!existing) {
                var banner = document.createElement('div');
                banner.id = 'network-status-banner';
                banner.style.cssText = 'position:fixed;top:0;left:0;right:0;background:#e74c3c;color:#fff;text-align:center;padding:8px;z-index:10000;font-weight:bold;';
                banner.textContent = 'You are offline. Some features may not work.';
                document.body.appendChild(banner);
            }
        } else {
            if (existing) {
                existing.parentNode.removeChild(existing);
            }
        }
    }

    function bindEvents(map, layerManager) {
        $('#chatSendBtn').on('click', function() {
            // Audit M2: Stop must abort SSE + plan-execute fetches AND
            // signal the server to cancel WebSocket-side tool dispatch.
            if ($(this).text() === 'Stop') {
                if (currentAbortController) {
                    try { currentAbortController.abort(); } catch (_e) {}
                    currentAbortController = null;
                }
                if (_useWebSocket && _socket && _socket.connected) {
                    try {
                        _socket.emit('chat_abort', { session_id: sessionId });
                    } catch (_e) {}
                }
                enableInput();
                return;
            }
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

        // Disable input while processing; transform send button to stop button
        input.prop('disabled', true);
        $('#chatSendBtn').text('Stop');

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

        // Use WebSocket transport if available and connected
        if (_useWebSocket && _socket && _socket.connected) {
            _wsTypingId = showTyping();
            _socket.emit('chat_message', {
                session_id: sessionId,
                message: message,
                context: context
            });
            return;
        }

        // --- SSE transport (default / fallback) ---

        // Abort any in-flight request
        if (currentAbortController) {
            currentAbortController.abort();
        }
        currentAbortController = new AbortController();

        // Show typing indicator
        var typingId = showTyping();

        // Audit H1: use centralized authedFetch (CSRF + Bearer).
        (window.authedFetch || fetch)('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: currentAbortController.signal,
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
            // Connection succeeded — reset retry counter
            sendMessage._retryCount = 0;
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
                                if (i === lines.length - 1) {
                                    // Last line in chunk — likely incomplete, buffer it
                                    buffer = lines[i];
                                    break;
                                } else {
                                    // Mid-chunk parse failure — malformed event, skip and continue
                                    console.warn('Skipping malformed SSE event:', dataStr.substring(0, 200));
                                }
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
            if (err.name === 'AbortError') {
                removeTyping(typingId);
                enableInput();
                currentAbortController = null;
                appendMessage('error', 'Request cancelled.');
                return;
            }

            // Retry with exponential backoff for connection errors
            var retryAttempt = (typeof sendMessage._retryCount === 'number') ? sendMessage._retryCount : 0;
            var MAX_RETRIES = 3;
            if (retryAttempt < MAX_RETRIES) {
                sendMessage._retryCount = retryAttempt + 1;
                var delay = Math.pow(2, retryAttempt) * 1000; // 1s, 2s, 4s
                appendMessage('error', 'Connection lost. Retrying in ' + (delay / 1000) + 's... (attempt ' + (retryAttempt + 1) + '/' + MAX_RETRIES + ')');
                setTimeout(function() {
                    // Re-send with same message by restoring input temporarily
                    input.val(message);
                    sendMessage(map, layerManager);
                }, delay);
            } else {
                sendMessage._retryCount = 0;
                removeTyping(typingId);
                enableInput();
                currentAbortController = null;
                appendMessage('error', 'Connection lost. Please try again.');
            }
        });
    }

    function handleEvent(type, data, map, layerManager) {
        switch (type) {
            case 'tool_start':
                _lastToolStepId = appendToolStep(data.tool, 'Running ' + data.tool + '...', 'loading');
                break;

            case 'tool_result':
                updateToolStep(_lastToolStepId, formatToolResult(data.tool, data.result), 'done');
                // Chart tools return a Chart.js-compatible spec with
                // action: 'chart'. Render it inline under the tool step.
                if (data.result && data.result.action === 'chart' && window.Chart) {
                    renderChartIntoStep(_lastToolStepId, data.result);
                }
                // animate_layer returns a time_steps spec — render a
                // play/pause/scrub player that filters the layer per step.
                if (data.result && data.result.action === 'animate' && _layerManager) {
                    renderAnimatePlayer(_lastToolStepId, data.result, _layerManager);
                }
                // visualize_3d returns a height-annotated GeoJSON —
                // open a deck.gl 3D extrusion view in a modal.
                if (data.result && data.result.action === '3d_buildings'
                        && window.deck) {
                    renderShow3DButton(_lastToolStepId, data.result);
                }
                // N31: choropleth_map handler returns a per-feature
                // styleMap + legendData. Apply the colors to the named
                // layer and render the legend under the tool step.
                // Pre-fix this fell through to the JSON-dump default
                // renderer and the layer was not recolored.
                if (data.result && data.result.action === 'choropleth'
                        && _layerManager) {
                    var painted = _layerManager.applyStyleMap(
                        data.result.layer_name,
                        data.result.styleMap || {}
                    );
                    if (painted && data.result.legendData) {
                        renderChoroplethLegend(_lastToolStepId, data.result.legendData);
                    }
                }
                break;

            case 'layer_add':
                if (layerManager && data.geojson) {
                    // Enforce client-side layer count limit
                    if (layerManager.getLayerCount() >= MAX_LAYERS) {
                        appendMessage('error', 'Maximum ' + MAX_LAYERS + ' layers reached. Remove some layers first.');
                        break;
                    }
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
                    // Plan 05 M3: surface server-side truncation so the user
                    // knows the map isn't showing the full result.
                    if (data.truncated && data.original_count) {
                        appendMessage('info',
                            'Showing first ' + data.feature_count + ' of ' +
                            data.original_count + ' features. ' +
                            'Use filter_layer to narrow the result.'
                        );
                    }
                    // Fix #2: when many features are returned, hint the
                    // user that the wide view is summarized. Without this,
                    // wide-area queries like "show buildings in Chicago"
                    // either (a) appear empty (sub-pixel polygons at low
                    // zoom) or (b) merge into a solid blob — both feel
                    // like rendering bugs even though the data is correct.
                    var addedFeatureCount = (data.geojson.features || []).length;
                    if (addedFeatureCount >= 500) {
                        appendMessage('info',
                            'Showing ' + addedFeatureCount + ' features. ' +
                            'Zoom in to see individual items; ' +
                            'cluster bubbles below zoom 15.'
                        );
                    }
                }
                break;

            case 'layer_init':
                // Create empty layer placeholder for chunked delivery
                if (layerManager) {
                    if (layerManager.getLayerCount() >= MAX_LAYERS) {
                        appendMessage('error', 'Maximum ' + MAX_LAYERS + ' layers reached. Remove some layers first.');
                        break;
                    }
                    layerManager.initLayer(data.name, data.style, data.total_features);
                }
                break;

            case 'layer_chunk':
                // Append features to an existing chunked layer
                if (layerManager && data.geojson) {
                    layerManager.appendFeatures(data.name, data.geojson);
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
                    var heatName = data.layer_name || 'Heatmap';
                    var heatLayer = L.heatLayer(data.points, data.options || {});
                    heatLayer.addTo(map);
                    if (layerManager) {
                        // Register with LayerManager: create entry with empty GeoJSON, then swap leaflet layer
                        var entry = layerManager.addLayer(heatName, { type: 'FeatureCollection', features: [] }, {});
                        if (entry) {
                            map.removeLayer(entry.leafletLayer);
                            entry.leafletLayer = heatLayer;
                            entry.featureCount = data.points.length;
                        }
                    }
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

            case 'plan':
                removeTyping();
                displayPlan(data.plan, data.summary);
                enableInput();
                break;

            case 'message':
                // Note: removeTyping() is called without an ID here because the server-sent
                // 'message' event does not include the typingId. This removes ALL typing
                // indicators, which is acceptable since the UI processes one request at a time.
                removeTyping();
                appendMessage('assistant', data.text);
                if (data.done) {
                    enableInput();
                }
                break;

            case 'error':
                // See 'message' case comment — same rationale for removing all typing indicators.
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
        var id = 'tool-' + safeName + '-' + (toolStepCounter++);
        var statusClass = status === 'loading' ? 'tool-loading' : 'tool-done';
        var html = '<div class="chat-tool-step ' + statusClass + '" id="' + escapeHtml(id) + '">' +
                   '<span class="tool-icon">' + (status === 'loading' ? '⟳' : '✓') + '</span> ' +
                   '<span class="tool-text">' + escapeHtml(text) + '</span>' +
                   '</div>';
        $('#chatMessages').append(html);
        scrollToBottom();
        return id;
    }

    function updateToolStep(stepId, text, status) {
        if (!stepId) return;
        var el = $('#' + stepId);
        if (el.length) {
            el.removeClass('tool-loading').addClass('tool-done');
            el.find('.tool-icon').text('✓');
            el.find('.tool-text').text(text);
        }
    }

    function renderAnimatePlayer(stepId, spec, layerManager) {
        // Renders a time-step player (slider + play/pause/reset) inside
        // the tool step. Each step calls layerManager.filterToIndices to
        // show only the features for that time step. `cumulative: true`
        // unions all steps up to the current one.
        if (!stepId || !spec || !spec.time_steps || !layerManager) return;
        var hostStep = document.getElementById(stepId);
        if (!hostStep) return;

        var layerName = spec.layer_name;
        var steps = spec.time_steps;
        var intervalMs = Math.max(50, spec.interval_ms || 1000);
        var cumulative = !!spec.cumulative;

        var container = document.createElement('div');
        container.className = 'chat-animate-player';
        container.style.cssText = 'margin-top:8px;display:flex;flex-direction:column;'
            + 'gap:6px;max-width:480px;padding:8px;background:#f6f8fa;'
            + 'border-radius:6px;';

        var labelEl = document.createElement('div');
        labelEl.className = 'chat-animate-label';
        labelEl.style.cssText = 'font-size:12px;color:#444;';

        var slider = document.createElement('input');
        slider.type = 'range';
        slider.min = '0';
        slider.max = String(Math.max(0, steps.length - 1));
        slider.value = '0';
        slider.step = '1';
        slider.className = 'chat-animate-slider';
        slider.style.cssText = 'width:100%;';

        var btnRow = document.createElement('div');
        btnRow.style.cssText = 'display:flex;gap:6px;';

        var playBtn = document.createElement('button');
        playBtn.textContent = '▶ Play';
        playBtn.className = 'chat-animate-play';
        playBtn.style.cssText = 'padding:4px 12px;cursor:pointer;border:1px solid #ccc;'
            + 'background:#fff;border-radius:4px;';

        var resetBtn = document.createElement('button');
        resetBtn.textContent = '⟲ Reset';
        resetBtn.className = 'chat-animate-reset';
        resetBtn.style.cssText = 'padding:4px 12px;cursor:pointer;border:1px solid #ccc;'
            + 'background:#fff;border-radius:4px;';

        btnRow.appendChild(playBtn);
        btnRow.appendChild(resetBtn);
        container.appendChild(labelEl);
        container.appendChild(slider);
        container.appendChild(btnRow);
        hostStep.appendChild(container);

        var playInterval = null;

        function applyStep(idx) {
            if (idx < 0 || idx >= steps.length) return;
            slider.value = String(idx);
            labelEl.textContent = 'Step ' + (idx + 1) + ' / ' + steps.length
                + ': ' + steps[idx].label;
            var visible;
            if (cumulative) {
                visible = [];
                for (var i = 0; i <= idx; i++) {
                    visible = visible.concat(steps[i].feature_indices || []);
                }
            } else {
                visible = steps[idx].feature_indices || [];
            }
            if (typeof layerManager.filterToIndices === 'function') {
                layerManager.filterToIndices(layerName, visible);
            }
        }

        function pause() {
            if (playInterval) {
                clearInterval(playInterval);
                playInterval = null;
            }
            playBtn.textContent = '▶ Play';
        }

        function play() {
            if (playInterval) return;
            playBtn.textContent = '⏸ Pause';
            playInterval = setInterval(function() {
                var cur = parseInt(slider.value, 10);
                var next = cur + 1;
                if (next >= steps.length) {
                    pause();
                    return;
                }
                applyStep(next);
            }, intervalMs);
        }

        playBtn.addEventListener('click', function() {
            if (playInterval) pause(); else play();
        });
        resetBtn.addEventListener('click', function() {
            pause();
            applyStep(0);
        });
        slider.addEventListener('input', function() {
            pause();
            applyStep(parseInt(slider.value, 10));
        });

        // Initial state — show only step 0.
        applyStep(0);
    }

    function renderShow3DButton(stepId, spec) {
        // 3D extrusion view is heavy (deck.gl init + WebGL canvas); we
        // gate it behind a button so the chat history stays light.
        if (!stepId || !spec || !spec.geojson) return;
        var hostStep = document.getElementById(stepId);
        if (!hostStep) return;

        var btn = document.createElement('button');
        btn.textContent = '🏙  Show 3D view (' + (spec.feature_count || 0) + ' buildings)';
        btn.className = 'chat-show-3d-btn';
        btn.style.cssText = 'margin-top:6px;padding:6px 12px;cursor:pointer;'
            + 'border:1px solid #ccc;background:#fff;border-radius:4px;font-size:13px;';
        btn.addEventListener('click', function() { open3DModal(spec); });
        hostStep.appendChild(btn);
    }

    function open3DModal(spec) {
        if (!window.deck) {
            appendMessage('error', '3D library (deck.gl) not loaded.');
            return;
        }
        // Compute centroid of layer for initial camera positioning.
        var feats = (spec.geojson && spec.geojson.features) || [];
        var sumLng = 0, sumLat = 0, n = 0;
        for (var i = 0; i < feats.length; i++) {
            var g = feats[i].geometry;
            if (!g || !g.coordinates) continue;
            var ring = g.type === 'Polygon' ? g.coordinates[0]
                     : g.type === 'MultiPolygon' ? g.coordinates[0][0]
                     : null;
            if (!ring) continue;
            for (var j = 0; j < ring.length; j++) {
                sumLng += ring[j][0]; sumLat += ring[j][1]; n++;
            }
        }
        if (n === 0) {
            appendMessage('error', 'No polygon geometry to render in 3D.');
            return;
        }
        var centerLng = sumLng / n, centerLat = sumLat / n;

        var overlay = document.createElement('div');
        overlay.className = 'chat-3d-modal-overlay';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);'
            + 'z-index:9000;display:flex;align-items:center;justify-content:center;';

        var panel = document.createElement('div');
        panel.style.cssText = 'position:relative;width:90vw;max-width:1100px;'
            + 'height:80vh;background:#1a1a2e;border-radius:8px;overflow:hidden;'
            + 'box-shadow:0 10px 40px rgba(0,0,0,0.5);';
        overlay.appendChild(panel);

        var canvas = document.createElement('div');
        canvas.id = 'deck-3d-canvas';
        canvas.style.cssText = 'position:absolute;inset:0;';
        panel.appendChild(canvas);

        var closeBtn = document.createElement('button');
        closeBtn.textContent = '✕ Close';
        closeBtn.style.cssText = 'position:absolute;top:10px;right:10px;z-index:10;'
            + 'padding:6px 14px;cursor:pointer;border:none;border-radius:4px;'
            + 'background:#fff;color:#333;font-weight:bold;';
        closeBtn.addEventListener('click', function() {
            try { deckInstance && deckInstance.finalize(); } catch (_e) {}
            document.body.removeChild(overlay);
        });
        panel.appendChild(closeBtn);

        var legend = document.createElement('div');
        legend.style.cssText = 'position:absolute;bottom:10px;left:10px;z-index:10;'
            + 'padding:6px 10px;background:rgba(255,255,255,0.85);border-radius:4px;'
            + 'font-size:12px;color:#333;';
        legend.textContent = spec.feature_count + ' buildings · '
            + 'height_attr=' + (spec.height_attribute || 'height')
            + (spec.used_default_count
                ? ' · ' + spec.used_default_count + ' used default height'
                : '');
        panel.appendChild(legend);

        document.body.appendChild(overlay);

        var deckInstance = null;
        try {
            // Color ramp: short = blue, medium = green, tall = red.
            function _heightColor(h) {
                if (h < 20) return [40, 110, 200];
                if (h < 50) return [40, 180, 100];
                if (h < 100) return [240, 180, 50];
                return [220, 60, 60];
            }
            var polygonLayer = new deck.PolygonLayer({
                id: 'extruded-buildings',
                data: feats,
                getPolygon: function(f) {
                    if (!f.geometry) return [];
                    if (f.geometry.type === 'Polygon') return f.geometry.coordinates[0];
                    if (f.geometry.type === 'MultiPolygon') return f.geometry.coordinates[0][0];
                    return [];
                },
                getElevation: function(f) {
                    return (f.properties && f.properties._height_m) || 10;
                },
                getFillColor: function(f) {
                    return _heightColor((f.properties && f.properties._height_m) || 10);
                },
                getLineColor: [80, 80, 80],
                lineWidthMinPixels: 1,
                extruded: true,
                pickable: true,
                wireframe: true,
            });

            // OSM raster basemap as a deck.gl TileLayer.
            var tileLayer = new deck.TileLayer({
                id: 'basemap',
                data: 'https://a.tile.openstreetmap.org/{z}/{x}/{y}.png',
                minZoom: 0,
                maxZoom: 19,
                tileSize: 256,
                renderSubLayers: function(props) {
                    var bbox = props.tile.bbox || props.tile.boundingBox;
                    var west = bbox.west !== undefined ? bbox.west : bbox[0][0];
                    var south = bbox.south !== undefined ? bbox.south : bbox[0][1];
                    var east = bbox.east !== undefined ? bbox.east : bbox[1][0];
                    var north = bbox.north !== undefined ? bbox.north : bbox[1][1];
                    return new deck.BitmapLayer(props, {
                        data: null,
                        image: props.data,
                        bounds: [west, south, east, north],
                    });
                },
            });

            deckInstance = new deck.DeckGL({
                container: canvas,
                initialViewState: {
                    longitude: centerLng,
                    latitude: centerLat,
                    zoom: 16,
                    pitch: 50,
                    bearing: 0,
                },
                controller: true,
                layers: [tileLayer, polygonLayer],
            });
        } catch (e) {
            console.warn('deck.gl 3D render failed:', e);
            appendMessage('error', '3D view failed: ' + e.message);
            try { document.body.removeChild(overlay); } catch (_e) {}
        }
    }

    function renderChartIntoStep(stepId, spec) {
        // `spec` matches handle_chart's return: {action, chart_type,
        // labels, datasets, title, ...}. Chart.js doesn't have a native
        // 'histogram' type so we render it as a bar chart with the
        // pre-binned data the backend produced.
        if (!stepId || !spec || !window.Chart) return;
        var hostStep = document.getElementById(stepId);
        if (!hostStep) return;

        var canvas = document.createElement('canvas');
        canvas.className = 'chat-chart-canvas';
        canvas.style.cssText = 'max-width: 480px; max-height: 320px; margin-top: 8px;';
        hostStep.appendChild(canvas);

        var jsType = spec.chart_type === 'histogram' ? 'bar' : spec.chart_type;
        try {
            new Chart(canvas.getContext('2d'), {
                type: jsType,
                data: {
                    labels: spec.labels || [],
                    datasets: spec.datasets || [],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        title: { display: !!spec.title, text: spec.title || '' },
                        legend: { display: spec.chart_type === 'pie' },
                    },
                },
            });
        } catch (e) {
            console.warn('Chart render failed:', e);
        }
    }

    function renderChoroplethLegend(stepId, legendData) {
        // N31: legendData = {type, title, entries: [{color, min, max, count, label}]}
        // The handler always emits entries; defensive checks below guard
        // against an upstream change to the contract rather than runtime
        // breakage.
        if (!stepId || !legendData || !legendData.entries) return;
        var hostStep = document.getElementById(stepId);
        if (!hostStep) return;
        var legend = document.createElement('div');
        legend.className = 'choropleth-legend';
        legend.style.cssText = 'margin-top:8px;padding:8px;background:#f4f4f4;'
            + 'border-radius:4px;font-size:11px;line-height:1.4;'
            + 'max-width:280px;';
        var html = '';
        if (legendData.title) {
            html += '<div style="font-weight:600;margin-bottom:4px;">'
                  + escapeHtml(legendData.title) + '</div>';
        }
        legendData.entries.forEach(function(entry) {
            html += '<div class="choropleth-legend-row" '
                  + 'style="display:flex;align-items:center;margin:2px 0;">'
                  + '<span style="display:inline-block;width:14px;height:14px;'
                  + 'background:' + escapeHtml(String(entry.color || '#ccc'))
                  + ';margin-right:6px;border:1px solid #999;flex-shrink:0;">'
                  + '</span>'
                  + '<span>' + escapeHtml(String(entry.label || ''))
                  + ' <span style="color:#666;">(' + (entry.count || 0)
                  + ')</span></span>'
                  + '</div>';
        });
        legend.innerHTML = html;
        hostStep.appendChild(legend);
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
        currentAbortController = null;
        $('#chatInput').prop('disabled', false);
        $('#chatSendBtn').prop('disabled', false).text('Send');
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

    function displayPlan(steps, summary) {
        _pendingPlan = steps;
        var container = document.createElement('div');
        container.className = 'chat-msg chat-msg-assistant';

        var content = document.createElement('div');
        content.className = 'chat-msg-content chat-plan';

        var summaryP = document.createElement('p');
        summaryP.innerHTML = '<strong>Plan:</strong> ' + escapeHtml(summary || '');
        content.appendChild(summaryP);

        var ol = document.createElement('ol');
        for (var i = 0; i < steps.length; i++) {
            var li = document.createElement('li');
            li.textContent = steps[i].tool + ': ' + (steps[i].reason || '');
            ol.appendChild(li);
        }
        content.appendChild(ol);

        var btnContainer = document.createElement('div');
        btnContainer.style.cssText = 'margin-top:8px;display:flex;gap:8px;';

        var approveBtn = document.createElement('button');
        approveBtn.className = 'plan-approve';
        approveBtn.textContent = 'Execute Plan';
        approveBtn.style.cssText = 'padding:6px 16px;background:#27ae60;color:#fff;border:none;border-radius:4px;cursor:pointer;font-weight:bold;';
        approveBtn.addEventListener('click', function() {
            btnContainer.remove();
            executePlan();
        });

        var rejectBtn = document.createElement('button');
        rejectBtn.className = 'plan-reject';
        rejectBtn.textContent = 'Cancel';
        rejectBtn.style.cssText = 'padding:6px 16px;background:#e74c3c;color:#fff;border:none;border-radius:4px;cursor:pointer;';
        rejectBtn.addEventListener('click', function() {
            btnContainer.remove();
            rejectPlan();
        });

        btnContainer.appendChild(approveBtn);
        btnContainer.appendChild(rejectBtn);
        content.appendChild(btnContainer);
        container.appendChild(content);
        document.getElementById('chatMessages').appendChild(container);
        scrollToBottom();
    }

    function executePlan() {
        if (!_pendingPlan || _pendingPlan.length === 0) {
            appendMessage('error', 'No plan to execute.');
            return;
        }

        var planSteps = _pendingPlan;
        _pendingPlan = null;

        // Disable input while executing
        $('#chatInput').prop('disabled', true);
        $('#chatSendBtn').text('Stop');

        var typingId = showTyping();

        // Audit H1+M2: use centralized authedFetch and thread an
        // AbortController so the Stop button can cancel plan execution
        // (was missing — Stop only aborted SSE chat).
        if (currentAbortController) {
            try { currentAbortController.abort(); } catch (_e) {}
        }
        currentAbortController = new AbortController();

        (window.authedFetch || fetch)('/api/chat/execute-plan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: currentAbortController.signal,
            body: JSON.stringify({
                plan_steps: planSteps,
                session_id: sessionId
            })
        }).then(function(response) {
            if (!response.ok) {
                throw new Error('Plan execution request failed: ' + response.status);
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
                                handleEvent(currentEvent || data.type, data, _map, _layerManager);
                            } catch (e) {
                                if (i === lines.length - 1) {
                                    buffer = lines[i];
                                    break;
                                }
                            }
                            currentEvent = null;
                        } else if (line === '') {
                            currentEvent = null;
                        } else {
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
            appendMessage('error', 'Plan execution failed: ' + err.message);
        });
    }

    function rejectPlan() {
        _pendingPlan = null;
        appendMessage('assistant', 'Plan cancelled.');
    }

    return { init: init };
})();
