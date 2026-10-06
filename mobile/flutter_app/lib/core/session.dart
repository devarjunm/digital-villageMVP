import 'dart:async';

import 'package:flutter/foundation.dart';

import '../models/identity.dart';
import '../repositories/repositories.dart';
import 'api_client.dart';
import 'api_exception.dart';
import 'config.dart';
import 'token_store.dart';

enum SessionStatus { checking, signedOut, signedIn }

/// Owns authentication state for the whole app.
///
/// The session is the only place that writes tokens. Screens ask it to sign in,
/// sign out or change language; they never touch the keystore or the HTTP client
/// themselves. `status` is a three-state value rather than a boolean because the
/// app must not flash the login screen while it is still restoring a stored
/// session from the keystore.
class Session extends ChangeNotifier {
  Session({TokenStore? tokenStore, ApiClient? apiClient})
      : store = tokenStore ?? TokenStore() {
    api = apiClient ?? ApiClient(store: store);
    api.onUnauthenticated = _onRejected;
    api.refreshHandler = _refreshToken;
    repositories = Repositories(api);
  }

  final TokenStore store;
  late final ApiClient api;
  late final Repositories repositories;

  SessionStatus _status = SessionStatus.checking;
  AppUser? _user;
  FarmerProfile? _profile;
  String _languageCode = 'en';
  String? _lastError;

  SessionStatus get status => _status;
  AppUser? get user => _user;
  FarmerProfile? get profile => _profile;
  String get languageCode => _languageCode;
  String? get lastError => _lastError;
  bool get isSignedIn => _status == SessionStatus.signedIn;

  /// Restores a stored session on startup.
  ///
  /// The cached user object is used to render immediately, then `/auth/me`
  /// confirms it: a token revoked on another device must not keep working
  /// locally, and a display name changed elsewhere should appear.
  Future<void> restore() async {
    await api.loadAccessToken();
    final cached = await store.readUser();
    _languageCode = await store.readLocale() ?? 'en';
    final storedBaseUrl = await store.readBaseUrl();
    if (storedBaseUrl != null && storedBaseUrl.isNotEmpty) {
      api.baseUrl = storedBaseUrl;
    }

    final token = await store.accessToken();
    if (token == null || token.isEmpty) {
      _status = SessionStatus.signedOut;
      notifyListeners();
      return;
    }

    if (cached != null) {
      _user = AppUser.fromJson(cached);
      _status = SessionStatus.signedIn;
      notifyListeners();
    }

    try {
      final result = await repositories.auth.me();
      _user = result;
      await store.saveUser(result.toJson());
      _status = SessionStatus.signedIn;
      _lastError = null;
    } on ApiException {
      // The token is unusable (expired beyond refresh, revoked, or the server is
      // unreachable). Distinguish "not authorized" from "no network": a network
      // problem must not silently sign the user out and lose their draft.
      if (_user == null) {
        _status = SessionStatus.signedOut;
      }
    }
    notifyListeners();
  }

  Future<void> signInWithPassword({
    required String identifier,
    required String password,
  }) async {
    final result = await repositories.auth
        .login(identifier: identifier, password: password);
    await _adopt(result);
  }

  Future<OtpChallenge> requestOtp(
          {required String identifier, String purpose = 'login'}) =>
      repositories.auth.requestOtp(identifier: identifier, purpose: purpose);

  Future<void> signInWithOtp({
    required String identifier,
    required String code,
    String? fullName,
    String purpose = 'login',
  }) async {
    final result = await repositories.auth.verifyOtp(
      identifier: identifier,
      code: code,
      fullName: fullName,
      purpose: purpose,
      preferredLanguage: _languageCode,
    );
    await _adopt(result);
  }

  Future<void> register({
    required String fullName,
    String? phone,
    String? email,
    String? password,
  }) async {
    final result = await repositories.auth.register(
      fullName: fullName,
      phone: phone,
      email: email,
      password: password,
      preferredLanguage: _languageCode,
    );
    await _adopt(result);
  }

  Future<void> _adopt(LoginResult result) async {
    await store.saveTokens(
      accessToken: result.tokens.accessToken,
      refreshToken: result.tokens.refreshToken,
      accessExpiresAt: result.tokens.accessExpiresAt,
    );
    api.setAccessToken(result.tokens.accessToken);
    _user = result.user;
    await store.saveUser(result.user.toJson());
    _status = SessionStatus.signedIn;
    _lastError = null;
    notifyListeners();
    // Load the farm profile in the background: the home screen needs it, but a
    // failure there must not block a successful login.
    unawaited(refreshProfile());
  }

  Future<void> refreshProfile() async {
    if (!isSignedIn) return;
    try {
      _profile = await repositories.farmer.me();
      notifyListeners();
    } on ApiException {
      // Keep whatever profile we already had; the screens show their own error.
    }
  }

  Future<void> signOut() async {
    try {
      // Best effort: the local session is cleared even if the call fails, so
      // "log out" always means the tokens are gone from this device.
      await repositories.auth.logout();
    } on ApiException {
      // ignored on purpose
    }
    await _clearLocal();
  }

  /// Called when the server rejects our credentials mid-session.
  void _onRejected() {
    unawaited(_clearLocal());
  }

  Future<void> _clearLocal() async {
    await store.clearSession();
    api.setAccessToken(null);
    _user = null;
    _profile = null;
    _status = SessionStatus.signedOut;
    notifyListeners();
  }

  /// Exchanges the refresh token for a new access token. Returns false when
  /// there is nothing to refresh with — the caller then treats the request as
  /// unauthenticated instead of retrying forever.
  Future<bool> _refreshToken() async {
    final refresh = await store.refreshToken();
    if (refresh == null || refresh.isEmpty) return false;
    try {
      final data = await api.post(
        '/auth/refresh',
        body: {'refresh_token': refresh},
        auth: false,
      );
      final tokens = AuthTokens.fromJson(
        (data is Map && data['tokens'] is Map)
            ? Map<String, dynamic>.from(data['tokens'] as Map)
            : Map<String, dynamic>.from(data as Map),
      );
      await store.saveTokens(
        accessToken: tokens.accessToken,
        refreshToken: tokens.refreshToken,
        accessExpiresAt: tokens.accessExpiresAt,
      );
      api.setAccessToken(tokens.accessToken);
      return true;
    } on ApiException {
      await store.clearSession();
      api.setAccessToken(null);
      return false;
    }
  }

  Future<void> setLanguageCode(String code) async {
    _languageCode = code;
    await store.saveLocale(code);
    notifyListeners();
    if (isSignedIn) {
      try {
        await repositories.account.updateMe(preferredLanguage: code);
      } on ApiException {
        // The local choice still applies; the server keeps the previous value
        // and the next successful call will sync it.
      }
    }
  }

  /// Overrides the API base URL (physical-device testing, staging).
  ///
  /// Returns false, and changes nothing, when the address cannot be used: the
  /// server panel then says so instead of saving something that fails later.
  /// An empty string means "back to the built-in default".
  Future<bool> setBaseUrl(String? url) async {
    final trimmed = url?.trim();
    if (trimmed == null || trimmed.isEmpty) {
      api.baseUrl = AppConfig.builtInBaseUrl;
      await store.saveBaseUrl(null);
      notifyListeners();
      return true;
    }
    final normalized = AppConfig.tryNormalizeBaseUrl(trimmed);
    if (normalized == null) return false;
    api.baseUrl = normalized;
    await store.saveBaseUrl(normalized);
    notifyListeners();
    return true;
  }

  Future<String?> loadStoredBaseUrl() => store.readBaseUrl();

  @override
  void dispose() {
    api.dispose();
    super.dispose();
  }
}
