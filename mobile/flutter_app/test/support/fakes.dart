import 'dart:convert';

import 'package:digital_village_app/app.dart';
import 'package:digital_village_app/core/api_client.dart';
import 'package:digital_village_app/core/session.dart';
import 'package:digital_village_app/core/theme.dart';
import 'package:digital_village_app/core/token_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

/// Token store with no platform channel: a widget test must never reach for the
/// Android keystore. Every method of the real store is overridden, so a test
/// cannot silently fall through to the plugin.
class MemoryTokenStore extends TokenStore {
  MemoryTokenStore();

  final Map<String, String> values = <String, String>{};

  @override
  Future<String?> accessToken() async => values['access'];

  @override
  Future<String?> refreshToken() async => values['refresh'];

  @override
  Future<DateTime?> accessExpiry() async {
    final raw = values['access_expires_at'];
    return raw == null ? null : DateTime.tryParse(raw);
  }

  @override
  Future<bool> accessTokenNeedsRefresh(
      {Duration skew = const Duration(seconds: 60)}) async {
    final expiry = await accessExpiry();
    if (expiry == null) return false;
    return DateTime.now().toUtc().isAfter(expiry.toUtc().subtract(skew));
  }

  @override
  Future<void> saveTokens({
    required String accessToken,
    String? refreshToken,
    DateTime? accessExpiresAt,
  }) async {
    values['access'] = accessToken;
    if (refreshToken != null) values['refresh'] = refreshToken;
    if (accessExpiresAt != null) {
      values['access_expires_at'] = accessExpiresAt.toUtc().toIso8601String();
    }
  }

  @override
  Future<void> saveUser(Map<String, dynamic> user) async =>
      values['user'] = jsonEncode(user);

  @override
  Future<Map<String, dynamic>?> readUser() async {
    final raw = values['user'];
    if (raw == null) return null;
    final decoded = jsonDecode(raw);
    return decoded is Map<String, dynamic> ? decoded : null;
  }

  @override
  Future<void> clearSession() async {
    for (final key in ['access', 'refresh', 'access_expires_at', 'user']) {
      values.remove(key);
    }
  }

  @override
  Future<String?> readLocale() async => values['locale'];

  @override
  Future<void> saveLocale(String code) async => values['locale'] = code;

  @override
  Future<String?> readBaseUrl() async => values['base_url'];

  @override
  Future<void> saveBaseUrl(String? value) async {
    if (value == null || value.isEmpty) {
      values.remove('base_url');
    } else {
      values['base_url'] = value;
    }
  }
}

http.Response jsonResponse(Object body, [int status = 200]) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

/// The documented error envelope, so failure paths are exercised too.
http.Response errorResponse(int status, String code, String message) =>
    jsonResponse({
      'error': {'code': code, 'message': message},
      'detail': message,
    }, status);

Map<String, dynamic> demoUserJson({String role = 'farmer'}) => {
      'id': '11111111-1111-1111-1111-111111111111',
      'full_name': 'Demo Farmer',
      'primary_role': role,
      'roles': [role],
      'preferred_language': 'en',
      'status': 'active',
      'phone_masked': '+91******001',
      'email_masked': null,
      'phone_verified': true,
      'email_verified': false,
      'created_at': '2026-01-05T04:30:00Z',
      'is_demo': true,
    };

Map<String, dynamic> demoLoginJson({String role = 'farmer'}) => {
      'user': demoUserJson(role: role),
      'tokens': {
        'access_token': 'test-access-token',
        'refresh_token': 'test-refresh-token',
        'token_type': 'bearer',
        'expires_in': 3600,
        'access_expires_at': DateTime.now()
            .toUtc()
            .add(const Duration(hours: 1))
            .toIso8601String(),
        'refresh_expires_at': DateTime.now()
            .toUtc()
            .add(const Duration(days: 30))
            .toIso8601String(),
      },
    };

/// A session plus a stub HTTP client, with a record of what the app requested.
///
/// Requests are matched by path, so a test states exactly which endpoints the
/// screen under test is allowed to call; anything else fails loudly instead of
/// hitting the network.
class Harness {
  Harness._(this.session, this.store, this.requests, this.unmatched);

  final Session session;
  final MemoryTokenStore store;
  final List<http.Request> requests;
  final List<String> unmatched;

  List<String> get paths =>
      requests.map((request) => request.url.path).toList();

  String bodyOf(String path) {
    final match = requests.firstWhere(
      (request) => request.url.path == path,
      orElse: () => throw StateError('no request to $path; got $paths'),
    );
    return match.body;
  }
}

Future<Harness> buildHarness({
  Map<String, http.Response Function(http.Request)> routes = const {},
  bool signedIn = false,
  String role = 'farmer',
}) async {
  final store = MemoryTokenStore();
  final requests = <http.Request>[];
  final unmatched = <String>[];
  final client = MockClient((request) async {
    requests.add(request);
    final handler = routes[request.url.path];
    if (handler != null) return handler(request);
    if (request.url.path.endsWith('/auth/login')) {
      return jsonResponse(demoLoginJson(role: role));
    }
    unmatched.add('${request.method} ${request.url.path}');
    return errorResponse(
        404, 'not_found', 'no stub registered for ${request.url.path}');
  });

  final api = ApiClient(store: store, httpClient: client);
  api.baseUrl = 'http://test.local';
  final session = Session(tokenStore: store, apiClient: api);
  final harness = Harness._(session, store, requests, unmatched);
  if (signedIn) {
    await session.signInWithPassword(
        identifier: '+919000000001', password: 'DemoPass!23');
  }
  return harness;
}

/// Pumps [child] inside the app scope the screens expect.
Future<void> pumpHarness(
    WidgetTester tester, Harness harness, Widget child) async {
  tester.view.physicalSize = const Size(1200, 2600);
  tester.view.devicePixelRatio = 3.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    MaterialApp(
      theme: AppTheme.light(),
      // Mirrors the real app's localisation setup, so a screen that relies on a
      // delegate (or on Material translations for mr/hi) is exercised here too.
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: AppLocalizations.supportedLocales,
      home: AppScope(session: harness.session, child: child),
    ),
  );
  await tester.pumpAndSettle();
}
