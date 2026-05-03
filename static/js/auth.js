/* Audit H1+M1+M2 — centralized authed transport.
 *
 * Exports two helpers on window:
 *   - authedFetch(url, opts)   — fetch wrapper auto-attaching CSRF + Bearer
 *   - authedAjax(jqXhr, opts)  — jQuery $.ajax beforeSend hook
 *
 * Bearer token source: localStorage.getItem('api_token'). When absent,
 * Authorization header is omitted (server-side @require_api_token will
 * 401, which is the desired observable behavior).
 */
(function (global) {
    'use strict';

    function getCsrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    function getBearerToken() {
        try {
            return localStorage.getItem('api_token') || '';
        } catch (_e) {
            return '';
        }
    }

    function isStateMutating(method) {
        return !/^(GET|HEAD|OPTIONS|TRACE)$/i.test(method || 'GET');
    }

    function authedFetch(url, opts) {
        opts = opts || {};
        opts.headers = Object.assign({}, opts.headers || {});
        var method = (opts.method || 'GET').toUpperCase();
        if (isStateMutating(method)) {
            if (!opts.headers['X-CSRFToken']) {
                opts.headers['X-CSRFToken'] = getCsrfToken();
            }
        }
        var bearer = getBearerToken();
        if (bearer && !opts.headers['Authorization']) {
            opts.headers['Authorization'] = 'Bearer ' + bearer;
        }
        return fetch(url, opts);
    }

    function authedAjaxBeforeSend(xhr, settings) {
        if (isStateMutating(settings.type) && !settings.crossDomain) {
            xhr.setRequestHeader('X-CSRFToken', getCsrfToken());
        }
        var bearer = getBearerToken();
        if (bearer) {
            xhr.setRequestHeader('Authorization', 'Bearer ' + bearer);
        }
    }

    global.SpatialAuth = {
        getCsrfToken: getCsrfToken,
        getBearerToken: getBearerToken,
        authedFetch: authedFetch,
        authedAjaxBeforeSend: authedAjaxBeforeSend,
    };
    // Aliases for direct use.
    global.authedFetch = authedFetch;
})(typeof window !== 'undefined' ? window : this);
