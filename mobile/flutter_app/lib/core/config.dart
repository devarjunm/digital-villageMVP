/// Build-time and runtime configuration.
///
/// The API base URL is resolved in this order:
///
/// 1. `--dart-define=API_BASE_URL=...` at build time (used by CI and release
///    builds; this is how a real deployment points the app at HTTPS).
/// 2. A value the user saved in the in-app settings screen, which is needed
///    because a physical test device cannot reach the developer machine at
///    `10.0.2.2` (that address is the emulator's alias for the host loopback).
/// 3. A platform default: Android emulator -> `http://10.0.2.2:8000`, otherwise
///    `http://localhost:8000`.
///
/// Plain HTTP is a development-only transport; see `docs/mobile.md`. The Android
/// manifest allows cleartext traffic only so that a locally running backend can
/// be reached — a production build must sit behind HTTPS.
library;

import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kIsWeb;

class AppConfig {
  AppConfig._();

  static const String appName = 'Digital Village';
  static const String appVersion = '0.1.0';

  /// Set with `flutter build apk --dart-define=API_BASE_URL=https://api.example.org`.
  static const String _buildTimeBaseUrl =
      String.fromEnvironment('API_BASE_URL');

  static const String apiPrefix = '/api/v1';

  /// How long a normal request may take.
  static const Duration requestTimeout = Duration(seconds: 30);

  /// AI endpoints run models (and, for the assistant, retrieval + generation),
  /// so they are given a longer budget than ordinary CRUD calls.
  static const Duration aiRequestTimeout = Duration(seconds: 120);

  static const int defaultPageSize = 20;

  static String get platformDefaultBaseUrl {
    if (kIsWeb) return 'http://localhost:8000';
    if (Platform.isAndroid) {
      // 10.0.2.2 is the Android emulator's alias for the host machine's loopback.
      // It is *not* reachable from a physical device — use the settings screen to
      // enter the developer machine's LAN address there.
      return 'http://10.0.2.2:8000';
    }
    return 'http://localhost:8000';
  }

  /// The base URL in use, before any runtime override is loaded.
  static String get builtInBaseUrl =>
      _buildTimeBaseUrl.isNotEmpty ? _buildTimeBaseUrl : platformDefaultBaseUrl;

  /// Repairs what a person actually types into the server panel.
  ///
  /// `192.168.1.5:8000` is not a URL: Dart reads `192.168.1.5` as the *scheme*,
  /// so the request never leaves the app and the panel can only say "no answer".
  /// A missing scheme is therefore filled in as `http://`, but only for addresses
  /// that can only be a development machine (loopback, the private IPv4 ranges,
  /// link-local). A public host must be typed with its scheme, so the app can
  /// never silently downgrade real traffic to plaintext.
  ///
  /// Any path or trailing slash is dropped: requests add `/api/v1` themselves, so
  /// `http://10.0.0.5:8000/api/v1` would otherwise become `/api/v1/api/v1`.
  ///
  /// Returns null when the input cannot be used as a base URL.
  static String? tryNormalizeBaseUrl(String raw) {
    final trimmed = raw.trim().replaceAll(RegExp(r'/+$'), '');
    if (trimmed.isEmpty) return null;
    final hasScheme = RegExp(r'^[a-zA-Z][a-zA-Z0-9+.-]*://').hasMatch(trimmed);
    if (!hasScheme && !_looksLikeDeveloperHost(trimmed)) return null;
    final uri = Uri.tryParse(hasScheme ? trimmed : 'http://$trimmed');
    if (uri == null || uri.host.isEmpty) return null;
    if (uri.scheme != 'http' && uri.scheme != 'https') return null;
    final port = uri.hasPort ? ':${uri.port}' : '';
    return '${uri.scheme}://${uri.host}$port';
  }

  /// True for `localhost` and the IPv4 ranges that are never a public server.
  static bool _looksLikeDeveloperHost(String value) {
    final host = value.split('/').first.split(':').first;
    if (host == 'localhost') return true;
    final octets = host.split('.');
    if (octets.length != 4) return false;
    final values = <int>[];
    for (final octet in octets) {
      final parsed = int.tryParse(octet);
      if (parsed == null || parsed < 0 || parsed > 255) return false;
      values.add(parsed);
    }
    if (values[0] == 127 || values[0] == 10) return true;
    if (values[0] == 192 && values[1] == 168) return true;
    if (values[0] == 172 && values[1] >= 16 && values[1] <= 31) return true;
    if (values[0] == 169 && values[1] == 254) return true;
    return false;
  }

  /// True when every address in [localIPv4] sits on a different /24 than the
  /// host in [baseUrl] — i.e. the phone is probably not on the backend's
  /// network at all. False when either side is not an IPv4 literal: an unknown
  /// answer must not produce a confident claim.
  static bool isProbablyForeignSubnet(String baseUrl, List<String> localIPv4) {
    final target = ipv4Subnet(Uri.tryParse(baseUrl)?.host ?? '');
    if (target == null || localIPv4.isEmpty) return false;
    return !localIPv4.map(ipv4Subnet).contains(target);
  }

  /// The /24 an IPv4 literal belongs to (`192.168.1.42` -> `192.168.1`), so the
  /// server panel can say whether the address typed is even on the phone's own
  /// network. Null for anything that is not an IPv4 literal.
  static String? ipv4Subnet(String host) {
    final octets = host.split('.');
    if (octets.length != 4) return null;
    for (final octet in octets) {
      final parsed = int.tryParse(octet);
      if (parsed == null || parsed < 0 || parsed > 255) return null;
    }
    return octets.take(3).join('.');
  }

  static const Map<String, String> _headers = {
    'Accept': 'application/json',
    'X-Client': 'digital-village-mobile/$appVersion',
  };

  static Map<String, String> baseHeaders() =>
      Map<String, String>.from(_headers);
}
