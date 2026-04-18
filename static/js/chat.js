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
            if (currentAbortController && $(this).text() === 'Stop') {
                currentAbortController.abort();
                currentAbortController = null;
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

        // Send via fetch + SSE
        var csrfToken = document.querySelector('meta[name="csrf-token"]');
        fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken ? csrfToken.getAttribute('content') : ''
            },
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
        var csrfToken = document.querySelector('meta[name="csrf-token"]');

        fetch('/api/chat/execute-plan', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken ? csrfToken.getAttribute('content') : ''
            },
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
