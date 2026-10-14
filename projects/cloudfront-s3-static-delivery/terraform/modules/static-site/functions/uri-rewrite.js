// CloudFront Function (cloudfront-js-2.0), viewer-request event.
//
// Specification: scripts/rewrite.py is the reference implementation and is
// unit tested. This file is reviewed against it, branch for branch, and
// tests/test_cloudfront_function.py runs both on the same events when node
// is installed. Change the Python first, then mirror the change here.
//
//   1. URI ends with "/"           -> rewrite to URI + "index.html"
//   2. last segment has a "."      -> a file: pass through unchanged
//   3. otherwise (no extension)    -> 301 redirect to URI + "/", keeping
//                                     the query string
//
// The URI is matched as CloudFront delivers it (percent-encoded form); it
// is never decoded here, so "%2F" is not a slash and "%2E" is not a dot.

function buildQueryString(querystring) {
    var parts = [];
    for (var name in querystring) {
        var entry = querystring[name];
        var values = entry.multiValue ? entry.multiValue : [entry];
        for (var i = 0; i < values.length; i++) {
            var value = values[i].value;
            parts.push(value === '' ? name : name + '=' + value);
        }
    }
    return parts.length > 0 ? '?' + parts.join('&') : '';
}

function handler(event) {
    var request = event.request;
    var uri = request.uri;

    // Branch 1: directory request.
    if (uri.endsWith('/')) {
        request.uri = uri + 'index.html';
        return request;
    }

    // Branch 2: the last path segment looks like a file name.
    var lastSegment = uri.substring(uri.lastIndexOf('/') + 1);
    if (lastSegment.indexOf('.') !== -1) {
        return request;
    }

    // Branch 3: extensionless path without a trailing slash. Redirect so the
    // browser's base URL is the directory and relative links resolve.
    return {
        statusCode: 301,
        statusDescription: 'Moved Permanently',
        headers: {
            'location': { value: uri + '/' + buildQueryString(request.querystring || {}) },
            'cache-control': { value: 'public, max-age=3600' }
        }
    };
}
