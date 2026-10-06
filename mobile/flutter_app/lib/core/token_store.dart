import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Credential storage backed by the platform keystore (Android Keystore).
///
/// Tokens are bearer credentials: if they leak, the account is compromised, so
/// they are never written to SharedPreferences, logs or crash reports. Only
/// non-secret preferences (language, base-URL override) share this store because
/// it is the only key-value store the app already has — they are not sensitive,
/// and keeping them here avoids a second dependency.
class TokenStore {
  TokenStore({FlutterSecureStorage? storage})
      : _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
            );

  final FlutterSecureStorage _storage;

  static const _accessKey = 'dv.access_token';
  static const _refreshKey = 'dv.refresh_token';
  static const _accessExpiryKey = 'dv.access_expires_at';
  static const _userKey = 'dv.user_json';
  static const _localeKey = 'dv.locale';
  static const _baseUrlKey = 'dv.api_base_url';

  String? _cachedAccessToken;

  Future<String?> accessToken() async {
    _cachedAccessToken ??= await _storage.read(key: _accessKey);
    return _cachedAccessToken;
  }

  Future<String?> refreshToken() => _storage.read(key: _refreshKey);

  Future<DateTime?> accessExpiry() async {
    final raw = await _storage.read(key: _accessExpiryKey);
    return raw == null ? null : DateTime.tryParse(raw);
  }

  /// True when the access token is missing or within [skew] of expiry, so the
  /// client can refresh proactively instead of waiting for a 401.
  Future<bool> accessTokenNeedsRefresh(
      {Duration skew = const Duration(seconds: 60)}) async {
    final expiry = await accessExpiry();
    if (expiry == null) return false; // unknown expiry: let the server decide
    return DateTime.now().toUtc().isAfter(expiry.toUtc().subtract(skew));
  }

  Future<void> saveTokens({
    required String accessToken,
    String? refreshToken,
    DateTime? accessExpiresAt,
  }) async {
    _cachedAccessToken = accessToken;
    await _storage.write(key: _accessKey, value: accessToken);
    if (refreshToken != null) {
      await _storage.write(key: _refreshKey, value: refreshToken);
    }
    if (accessExpiresAt != null) {
      await _storage.write(
        key: _accessExpiryKey,
        value: accessExpiresAt.toUtc().toIso8601String(),
      );
    }
  }

  Future<void> saveUser(Map<String, dynamic> user) =>
      _storage.write(key: _userKey, value: jsonEncode(user));

  Future<Map<String, dynamic>?> readUser() async {
    final raw = await _storage.read(key: _userKey);
    if (raw == null) return null;
    try {
      final decoded = jsonDecode(raw);
      return decoded is Map<String, dynamic> ? decoded : null;
    } on FormatException {
      // Corrupt cache: drop it rather than crash the splash screen.
      await _storage.delete(key: _userKey);
      return null;
    }
  }

  /// Clears credentials. Called on logout and whenever the server rejects a
  /// refresh token — a half-cleared session is worse than no session.
  Future<void> clearSession() async {
    _cachedAccessToken = null;
    await Future.wait([
      _storage.delete(key: _accessKey),
      _storage.delete(key: _refreshKey),
      _storage.delete(key: _accessExpiryKey),
      _storage.delete(key: _userKey),
    ]);
  }

  Future<String?> readLocale() => _storage.read(key: _localeKey);

  Future<void> saveLocale(String code) =>
      _storage.write(key: _localeKey, value: code);

  Future<String?> readBaseUrl() => _storage.read(key: _baseUrlKey);

  Future<void> saveBaseUrl(String? value) async {
    if (value == null || value.isEmpty) {
      await _storage.delete(key: _baseUrlKey);
    } else {
      await _storage.write(key: _baseUrlKey, value: value);
    }
  }
}
