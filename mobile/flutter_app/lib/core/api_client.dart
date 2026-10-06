import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart' show MediaType;

import 'api_exception.dart';
import 'config.dart';
import 'token_store.dart';

/// Result of probing an observability endpoint (`/health`, `/ready`).
///
/// These endpoints live *outside* the `/api/v1` prefix by design, so they are
/// reached by a dedicated method rather than through the repository layer. They
/// are how the app answers "is the address I typed actually a Digital Village
/// backend?" without needing a signed-in session.
class ServerProbe {
  const ServerProbe({
    required this.url,
    required this.reachable,
    required this.ok,
    this.statusCode,
    this.latencyMs,
    this.detail,
    this.body,
  });

  /// The exact URL that was called.
  final String url;

  /// True when the host answered at all (any HTTP status).
  final bool reachable;

  /// True when it answered with a success status. `/ready` answers 503 when a
  /// dependency (database, cache) is down: reachable but not ok.
  final bool ok;

  final int? statusCode;
  final int? latencyMs;

  /// A human-readable reason, present only when the probe did not succeed.
  final String? detail;

  /// The decoded JSON body, when the server sent one.
  final Map<String, dynamic>? body;
}

/// Thin, typed wrapper around the Digital Village REST API.
///
/// Responsibilities kept here (and nowhere else) so that screens never deal with
/// transport concerns:
///
/// * building URLs against the configured base URL and `/api/v1` prefix;
/// * attaching the bearer token and refreshing it **once** on a 401 (a
///   single-flight refresh: ten concurrent 401s must not trigger ten refreshes);
/// * turning the backend's error envelope into [ApiException];
/// * keeping AI calls on a longer timeout than CRUD calls.
///
/// It deliberately does not cache responses. Private data (profile, farms,
/// notifications) is fetched per screen, and the only caching in the system is
/// server-side where it is keyed and invalidated correctly.
class ApiClient {
  ApiClient({required this.store, http.Client? httpClient})
      : _http = httpClient ?? http.Client();

  final TokenStore store;
  final http.Client _http;

  /// Set by [Session]; falls back to the platform default until then.
  String baseUrl = AppConfig.builtInBaseUrl;

  /// Called when a request fails with 401 and refreshing did not help. The
  /// session uses it to drop the user back to the login screen.
  void Function()? onUnauthenticated;

  /// Refreshes credentials. Supplied by [Session], which owns the token store.
  /// Returns true when a new access token is available.
  Future<bool> Function()? refreshHandler;

  Future<bool>? _inFlightRefresh;

  Uri _uri(String path, [Map<String, dynamic>? query]) {
    final normalized = path.startsWith('/') ? path : '/$path';
    final base = Uri.parse('$baseUrl${AppConfig.apiPrefix}$normalized');
    if (query == null || query.isEmpty) return base;

    final params = <String, dynamic>{};
    query.forEach((key, value) {
      if (value == null) return;
      if (value is String && value.isEmpty) return;
      if (value is Iterable) {
        final kept = value.where((v) => v != null && v.toString().isNotEmpty);
        if (kept.isEmpty) return;
        params[key] = kept.map((v) => v.toString()).toList();
      } else {
        params[key] = value.toString();
      }
    });
    if (params.isEmpty) return base;
    return base.replace(queryParameters: {...base.queryParameters, ...params});
  }

  Map<String, String> _headers({bool auth = true, bool json = true}) {
    final headers = AppConfig.baseHeaders();
    if (json) headers['Content-Type'] = 'application/json; charset=utf-8';
    final token = _accessToken;
    if (auth && token != null && token.isNotEmpty) {
      headers['Authorization'] = 'Bearer $token';
    }
    return headers;
  }

  String? _accessToken;

  /// Kept in memory so every request does not hit the keystore.
  void setAccessToken(String? token) => _accessToken = token;

  Future<String?> loadAccessToken() async {
    _accessToken ??= await store.accessToken();
    return _accessToken;
  }

  // ------------------------------------------------------------------ verbs
  Future<dynamic> get(
    String path, {
    Map<String, dynamic>? query,
    bool auth = true,
    Duration? timeout,
  }) =>
      _send(
        'GET',
        path,
        query: query,
        auth: auth,
        timeout: timeout,
      );

  Future<dynamic> post(
    String path, {
    Object? body,
    Map<String, dynamic>? query,
    bool auth = true,
    Duration? timeout,
  }) =>
      _send(
        'POST',
        path,
        body: body,
        query: query,
        auth: auth,
        timeout: timeout,
      );

  Future<dynamic> patch(
    String path, {
    Object? body,
    bool auth = true,
    Duration? timeout,
  }) =>
      _send('PATCH', path, body: body, auth: auth, timeout: timeout);

  Future<dynamic> delete(
    String path, {
    Object? body,
    Map<String, dynamic>? query,
    bool auth = true,
    Duration? timeout,
  }) =>
      _send('DELETE', path,
          body: body, query: query, auth: auth, timeout: timeout);

  /// Uploads one image (multipart/form-data).
  ///
  /// The bytes come from `image_picker`; the MIME type is sent explicitly because
  /// the backend validates it, and a missing content type would be rejected.
  Future<dynamic> uploadImage({
    required String path,
    required List<int> bytes,
    required String filename,
    String field = 'file',
    Map<String, String>? fields,
  }) async {
    await _prepareAuth();
    final request = http.MultipartRequest('POST', _uri(path));
    request.headers.addAll(_headers(auth: true, json: false));
    request.fields.addAll(fields ?? const {});
    request.files.add(
      http.MultipartFile.fromBytes(
        field,
        bytes,
        filename: filename,
        contentType: _mediaTypeFor(filename),
      ),
    );
    return _dispatch(request, timeout: AppConfig.aiRequestTimeout);
  }

  static MediaType _mediaTypeFor(String filename) {
    final ext = filename.toLowerCase().split('.').last;
    switch (ext) {
      case 'png':
        return MediaType('image', 'png');
      case 'webp':
        return MediaType('image', 'webp');
      case 'heic':
        return MediaType('image', 'heic');
      default:
        return MediaType('image', 'jpeg');
    }
  }

  /// Probes an observability endpoint outside the `/api/v1` prefix.
  ///
  /// Never throws: a failed probe is a result to display, not an exception to
  /// crash on. This is the call the sign-in screen uses so a user can find out
  /// *why* the app cannot reach the backend before they have an account.
  Future<ServerProbe> probe(
    String path, {
    Duration timeout = const Duration(seconds: 8),
  }) async {
    final trimmed = baseUrl.replaceAll(RegExp(r'/+$'), '');
    Uri uri;
    try {
      uri = Uri.parse('$trimmed$path');
    } on FormatException {
      return ServerProbe(
          url: '$trimmed$path',
          reachable: false,
          ok: false,
          detail: 'not_a_url');
    }
    final started = DateTime.now();
    try {
      final response = await _http
          .get(uri, headers: _headers(auth: false, json: false))
          .timeout(timeout);
      final latency = DateTime.now().difference(started).inMilliseconds;
      Map<String, dynamic>? body;
      final text = utf8.decode(response.bodyBytes, allowMalformed: true);
      try {
        final decoded = jsonDecode(text);
        if (decoded is Map<String, dynamic>) body = decoded;
      } on FormatException {
        // A non-JSON answer (a proxy error page, say) is still a reachable host.
      }
      return ServerProbe(
        url: uri.toString(),
        reachable: true,
        ok: response.statusCode >= 200 && response.statusCode < 300,
        statusCode: response.statusCode,
        latencyMs: latency,
        body: body,
      );
    } on TimeoutException {
      return ServerProbe(
        url: uri.toString(),
        reachable: false,
        ok: false,
        detail: 'timeout',
      );
    } on SocketException catch (error) {
      return ServerProbe(
        url: uri.toString(),
        reachable: false,
        ok: false,
        detail: error.osError?.message ?? error.message,
      );
    } on http.ClientException catch (error) {
      return ServerProbe(
        url: uri.toString(),
        reachable: false,
        ok: false,
        detail: error.message,
      );
    }
  }

  // ----------------------------------------------------------- request flow
  Future<void> _prepareAuth() async {
    await loadAccessToken();
    if (_inFlightRefresh == null && await store.accessTokenNeedsRefresh()) {
      // Proactive refresh: avoids a guaranteed 401 round-trip after the app has
      // been in the background past the access-token lifetime.
      await _refreshOnce();
    }
  }

  Future<dynamic> _send(
    String method,
    String path, {
    Object? body,
    Map<String, dynamic>? query,
    bool auth = true,
    Duration? timeout,
    bool retried = false,
  }) async {
    if (auth) {
      await _prepareAuth();
    }
    final uri = _uri(path, query);

    late http.Response response;
    try {
      final headers = _headers(auth: auth);
      final encoded = body == null ? null : jsonEncode(body);
      response = switch (method) {
        'GET' => await _http
            .get(uri, headers: headers)
            .timeout(timeout ?? AppConfig.requestTimeout),
        'POST' => await _http
            .post(uri, headers: headers, body: encoded)
            .timeout(timeout ?? AppConfig.requestTimeout),
        'PATCH' => await _http
            .patch(uri, headers: headers, body: encoded)
            .timeout(timeout ?? AppConfig.requestTimeout),
        'DELETE' => await _http
            .delete(uri, headers: headers, body: encoded)
            .timeout(timeout ?? AppConfig.requestTimeout),
        _ => throw ArgumentError('Unsupported method $method'),
      };
    } on TimeoutException {
      throw ApiException.network(
        'The server took too long to answer. Check your connection and try again.',
      );
    } on SocketException {
      throw ApiException.network(
        'Cannot reach the server at $baseUrl. Check that the backend is running'
        ' and that the API address in Settings is correct.',
      );
    } on http.ClientException catch (error) {
      throw ApiException.network('Network error: ${error.message}');
    }

    if (response.statusCode == 401 && auth && !retried) {
      final refreshed = await _refreshOnce();
      if (refreshed) {
        return _send(
          method,
          path,
          body: body,
          query: query,
          auth: auth,
          timeout: timeout,
          retried: true,
        );
      }
      onUnauthenticated?.call();
    }
    return _decode(response);
  }

  /// One refresh attempt shared by all callers currently waiting on it.
  Future<bool> _refreshOnce() {
    final existing = _inFlightRefresh;
    if (existing != null) return existing;

    final handler = refreshHandler;
    if (handler == null) return Future.value(false);

    final future = handler().whenComplete(() => _inFlightRefresh = null);
    _inFlightRefresh = future;
    return future;
  }

  Future<dynamic> _dispatch(
    http.MultipartRequest request, {
    required Duration timeout,
    bool retried = false,
  }) async {
    try {
      final streamed = await _http.send(request).timeout(timeout);
      final response = await http.Response.fromStream(streamed);
      if (response.statusCode == 401 && !retried && await _refreshOnce()) {
        return await _dispatch(request, timeout: timeout, retried: true);
      }
      return _decode(response);
    } on TimeoutException {
      throw ApiException.network('The upload timed out. Try a smaller photo.');
    } on SocketException {
      throw ApiException.network('Cannot reach the server at $baseUrl.');
    } on http.ClientException catch (error) {
      throw ApiException.network('Network error: ${error.message}');
    }
  }

  dynamic _decode(http.Response response) {
    final status = response.statusCode;
    dynamic decoded;
    final text = utf8.decode(response.bodyBytes, allowMalformed: true);
    if (text.isNotEmpty) {
      try {
        decoded = jsonDecode(text);
      } on FormatException {
        decoded = null;
      }
    }

    if (status >= 200 && status < 300) {
      return decoded;
    }

    final envelope = decoded is Map<String, dynamic> ? decoded['error'] : null;
    if (envelope is Map<String, dynamic>) {
      return throw ApiException(
        message: (envelope['message'] ?? 'The request failed.').toString(),
        code: (envelope['code'] ?? 'error').toString(),
        statusCode: status,
        details: envelope['details'] is Map<String, dynamic>
            ? envelope['details'] as Map<String, dynamic>
            : null,
        requestId: envelope['request_id']?.toString(),
        retryAfterSeconds: _retryAfter(response),
      );
    }

    throw ApiException(
      message: status >= 500
          ? 'The server reported a problem (HTTP $status). Please try again.'
          : 'Unexpected response from the server (HTTP $status).',
      code: 'http_$status',
      statusCode: status,
      retryAfterSeconds: _retryAfter(response),
    );
  }

  static int? _retryAfter(http.Response response) {
    final raw = response.headers['retry-after'];
    if (raw == null) return null;
    return int.tryParse(raw.trim());
  }

  void dispose() => _http.close();
}
