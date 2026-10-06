/// A failed API call, carrying the backend's error envelope.
///
/// The backend answers every failure with
/// `{"error": {"code", "message", "details", "request_id"}}`. Keeping that shape
/// (instead of flattening it to a string) lets the UI react to *specific* causes
/// — show the field errors of a 422, offer a retry on a 429 and mention the
/// request id when a 500 happens — and lets tests assert on codes.
class ApiException implements Exception {
  ApiException({
    required this.message,
    this.statusCode,
    this.code = 'unknown_error',
    this.details,
    this.requestId,
    this.isNetworkError = false,
    this.retryAfterSeconds,
  });

  /// A network-level failure (no response at all): DNS, refused connection,
  /// timeout. Distinct from a 5xx, because the fix for the user is different.
  factory ApiException.network(String message) => ApiException(
      message: message, code: 'network_error', isNetworkError: true);

  final String message;
  final int? statusCode;
  final String code;
  final Map<String, dynamic>? details;
  final String? requestId;
  final bool isNetworkError;
  final int? retryAfterSeconds;

  /// Field-level errors of a validation failure, e.g. `{'area_value': 'must be > 0'}`.
  Map<String, String> get fieldErrors {
    final fields = details?['fields'];
    if (fields is! List) return const {};
    final out = <String, String>{};
    for (final entry in fields) {
      if (entry is Map) {
        final loc = entry['loc'];
        final msg = entry['msg']?.toString() ?? 'invalid';
        if (loc is String) {
          // `body.field_name` / `query.page` -> `field_name` / `page`
          final parts = loc.split('.');
          out[parts.length > 1 ? parts.last : loc] = msg;
        }
      }
    }
    return out;
  }

  /// [userMessage] plus any field-level validation messages, for forms.
  String get userFieldsOrMessage {
    final errors = fieldErrors;
    if (errors.isEmpty) return userMessage;
    return '$userMessage\n${errors.entries.map((entry) => '• ${entry.key}: ${entry.value}').join('\n')}';
  }

  bool get isUnauthenticated => statusCode == 401;
  bool get isForbidden => statusCode == 403;
  bool get isNotFound => statusCode == 404;
  bool get isRateLimited => statusCode == 429 || code == 'rate_limited';

  /// A short, user-facing line. Never contains a stack trace, SQL or a token:
  /// the backend is responsible for not putting internals in `message`, and the
  /// client does not invent extra detail.
  String get userMessage {
    if (isNetworkError) {
      return message;
    }
    if (isRateLimited) {
      final wait = retryAfterSeconds;
      return wait == null
          ? 'Too many requests. Please wait a moment and try again.'
          : 'Too many requests. Please try again in $wait seconds.';
    }
    return message;
  }

  @override
  String toString() => 'ApiException($statusCode $code): $message';
}
