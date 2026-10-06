/// Defensive JSON helpers.
///
/// Every model in the app parses through these instead of casting directly. The
/// reason is that a crash on a missing key is the worst possible failure mode for
/// a farmer in a field: the API may add, rename or omit a field (an optional
/// profile column that was never filled in comes back as `null`), and a single
/// `as String` on a null would take down the whole screen. A missing value
/// therefore reads as `null`/`''`/`0`, and only genuinely required identifiers
/// throw.
library;

class JsonException implements Exception {
  JsonException(this.message);

  final String message;

  @override
  String toString() => 'JsonException: $message';
}

Map<String, dynamic> asMap(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) return value.map((k, v) => MapEntry(k.toString(), v));
  return const <String, dynamic>{};
}

List<Map<String, dynamic>> asMapList(Object? value) {
  if (value is! List) return const [];
  return value.whereType<Object>().map(asMap).toList();
}

String asString(Object? value, {String fallback = ''}) {
  if (value == null) return fallback;
  return value.toString();
}

String? asStringOrNull(Object? value) {
  if (value == null) return null;
  final text = value.toString().trim();
  return text.isEmpty ? null : text;
}

int asInt(Object? value, {int fallback = 0}) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  if (value is String) return int.tryParse(value) ?? fallback;
  return fallback;
}

int? asIntOrNull(Object? value) {
  if (value == null) return null;
  if (value is int) return value;
  if (value is num) return value.toInt();
  if (value is String) return int.tryParse(value);
  return null;
}

double asDouble(Object? value, {double fallback = 0}) {
  if (value is double) return value;
  if (value is num) return value.toDouble();
  if (value is String) return double.tryParse(value) ?? fallback;
  return fallback;
}

double? asDoubleOrNull(Object? value) {
  if (value == null) return null;
  if (value is num) return value.toDouble();
  if (value is String) return double.tryParse(value);
  return null;
}

bool asBool(Object? value, {bool fallback = false}) {
  if (value is bool) return value;
  if (value is num) return value != 0;
  if (value is String) {
    final lower = value.toLowerCase();
    if (lower == 'true' || lower == '1') return true;
    if (lower == 'false' || lower == '0') return false;
  }
  return fallback;
}

/// Parses an ISO-8601 timestamp. The backend always sends UTC (often with a
/// trailing `Z` on some fields and `+00:00` on others), and the app converts to
/// local time for display.
DateTime? asDateTimeOrNull(Object? value) {
  final text = asStringOrNull(value);
  if (text == null) return null;
  return DateTime.tryParse(text);
}

DateTime asDateTime(Object? value) =>
    asDateTimeOrNull(value) ?? DateTime.fromMillisecondsSinceEpoch(0);

DateTime? asDateOnlyOrNull(Object? value) {
  final parsed = asDateTimeOrNull(value);
  if (parsed == null) return null;
  return DateTime(parsed.year, parsed.month, parsed.day);
}

List<String> asStringList(Object? value) {
  if (value is! List) return const [];
  return value
      .map((item) => item?.toString() ?? '')
      .where((s) => s.isNotEmpty)
      .toList();
}

/// A required opaque identifier (uuid or slug). Throws when absent, because a
/// model without an id cannot be opened, reacted to or reported.
String requiredId(Object? value, String what) {
  final text = asStringOrNull(value);
  if (text == null) {
    throw JsonException('$what is missing its identifier');
  }
  return text;
}
