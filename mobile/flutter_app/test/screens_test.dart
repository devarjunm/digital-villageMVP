import 'package:digital_village_app/core/l10n.dart';
import 'package:digital_village_app/screens/ai/assistant_screen.dart';
import 'package:digital_village_app/screens/auth/auth_screen.dart';
import 'package:digital_village_app/screens/notifications/notifications_screen.dart';
import 'package:digital_village_app/screens/schemes/schemes_screen.dart';
import 'package:digital_village_app/screens/weather/weather_screen.dart';
import 'package:digital_village_app/widgets/common.dart';
import 'package:digital_village_app/widgets/server_settings.dart';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fakes.dart';

const _strings = AppLocalizations(Locale('en'));

void main() {
  group('WeatherScreen', () {
    testWidgets('signed out, it refuses to invent a location', (tester) async {
      final harness = await buildHarness();
      await pumpHarness(tester, harness, const WeatherScreen());

      expect(find.text(_strings.t('no_location_note')), findsOneWidget);
      expect(
        harness.paths.where((path) => path.contains('/weather/')).toList(),
        isEmpty,
        reason:
            'no weather may be requested for a place the farmer does not farm',
      );
    });

    testWidgets(
        'signed in, it renders the provider, the demo flag and the values',
        (tester) async {
      final harness = await buildHarness(
        signedIn: true,
        routes: {
          '/api/v1/farms': (request) => jsonResponse([
                {
                  'id': 'farm-1',
                  'name': 'Ozar plot',
                  'area_value': 2,
                  'area_unit': 'acre',
                  'area_hectares': 0.81,
                  'soil_type': 'black',
                  'irrigation_type': 'drip',
                  'village': 'Ozar',
                  'district': 'Nashik',
                  'latitude': 19.9975,
                  'longitude': 73.7898,
                },
              ]),
          '/api/v1/farmers/me': (request) => jsonResponse({
                'id': 'farmer-1',
                'display_name': 'Demo Farmer',
                'profile_completeness': 80,
                'latitude': 19.9975,
                'longitude': 73.7898,
                'village': 'Ozar',
                'district': 'Nashik',
                'state': 'Maharashtra',
              }),
          '/api/v1/weather/current': (request) => jsonResponse({
                'latitude': 19.9975,
                'longitude': 73.7898,
                'provider': 'mock',
                'temperature_c': 31.4,
                'feels_like_c': 34.0,
                'humidity_percent': 62,
                'rainfall_mm': 0.0,
                'wind_speed_kmh': 12.6,
                'condition_text': 'Partly cloudy',
                'observed_at': '2026-10-06T04:30:00Z',
                'is_demo': true,
                'demo_notice': 'Synthetic weather values for development.',
                'data_class': 'demo',
              }),
          '/api/v1/weather/forecast': (request) => jsonResponse({
                'provider': 'mock',
                'is_demo': true,
                'advisories': ['Delay irrigation: rain expected in 48 hours.'],
                'advisories_data_class': 'model_output',
                'days': [
                  {
                    'forecast_for': '2026-10-07',
                    'temp_min_c': 21.0,
                    'temp_max_c': 33.5,
                    'rainfall_probability_percent': 60,
                    'condition_text': 'Light rain',
                  },
                ],
              }),
          '/api/v1/weather/alerts': (request) => jsonResponse([]),
        },
      );
      await pumpHarness(tester, harness, const WeatherScreen());

      expect(find.text('31.4 °C'), findsOneWidget);
      expect(find.text('Partly cloudy'), findsOneWidget);
      expect(find.textContaining('mock'), findsWidgets);
      expect(find.text(_strings.t('demo_data')), findsWidgets);
      expect(find.textContaining('Delay irrigation'), findsOneWidget);
    });
  });

  group('SchemesScreen', () {
    testWidgets('lists real schemes with their official source and demo flag',
        (tester) async {
      final harness = await buildHarness(
        routes: {
          '/api/v1/schemes/categories': (request) =>
              jsonResponse(['income_support', 'credit']),
          '/api/v1/schemes': (request) => jsonResponse({
                'items': [
                  {
                    'slug': 'pm-kisan',
                    'name': 'PM-KISAN',
                    'description': 'Income support for landholding farmers.',
                    'category': 'income_support',
                    'level': 'central',
                    'official_source_name': 'PM-KISAN portal',
                    'official_source_url': 'https://pmkisan.gov.in',
                    'verification_status': 'official',
                    'benefits': '₹6,000 per year in three instalments.',
                    'documents_required': ['Aadhaar', 'Land records'],
                    'is_demo': true,
                  },
                ],
                'page': 1,
                'page_size': 20,
                'total': 1,
                'total_pages': 1,
                'has_next': false,
              }),
        },
      );
      await pumpHarness(tester, harness, const SchemesScreen());

      expect(find.text('PM-KISAN'), findsOneWidget);
      expect(find.text('Income Support'), findsWidgets);
      expect(find.text('Central'), findsOneWidget);
      expect(find.text(_strings.t('demo_data')), findsOneWidget);

      // The details live behind the expansion: opening it must reveal the
      // official link a farmer can verify, not just the app's own summary.
      await tester.tap(find.text('PM-KISAN'));
      await tester.pumpAndSettle();
      expect(find.textContaining('pmkisan.gov.in'), findsOneWidget);
      expect(find.textContaining('₹6,000 per year'), findsOneWidget);
    });

    testWidgets('an empty result shows the empty state, not a spinner',
        (tester) async {
      final harness = await buildHarness(
        routes: {
          '/api/v1/schemes/categories': (request) => jsonResponse([]),
          '/api/v1/schemes': (request) => jsonResponse({
                'items': [],
                'page': 1,
                'page_size': 20,
                'total': 0,
                'total_pages': 0,
                'has_next': false,
              }),
        },
      );
      await pumpHarness(tester, harness, const SchemesScreen());
      expect(find.text(_strings.t('no_schemes')), findsOneWidget);
    });
  });

  group('NotificationsScreen', () {
    testWidgets(
        'renders the notification as delivered, including the unread state',
        (tester) async {
      final harness = await buildHarness(
        signedIn: true,
        routes: {
          '/api/v1/notifications': (request) => jsonResponse({
                'items': [
                  {
                    'id': '11111111-2222-3333-4444-555555555555',
                    'type': 'weather_alert',
                    'title': 'Heavy rain expected',
                    'body': 'Delay spraying for 48 hours.',
                    'language': 'en',
                    'read': false,
                    'deep_link': '/weather',
                    'created_at': '2026-10-06T04:00:00Z',
                  },
                ],
                'page': 1,
                'page_size': 20,
                'total': 1,
                'total_pages': 1,
                'has_next': false,
                'unread_count': 1,
              }),
        },
      );
      await pumpHarness(tester, harness, const NotificationsScreen());

      expect(find.text('Heavy rain expected'), findsOneWidget);
      expect(find.text('Delay spraying for 48 hours.'), findsOneWidget);

      // Unread state is a property of the row, not a word on the screen: the
      // title is bold until the notification is opened.
      final title = tester.widget<Text>(find.text('Heavy rain expected'));
      expect(title.style?.fontWeight, FontWeight.w700);
    });
  });

  group('AssistantScreen', () {
    testWidgets('insufficient evidence is shown as a warning, never hidden',
        (tester) async {
      final harness = await buildHarness(
        signedIn: true,
        routes: {
          '/api/v1/knowledge/ask': (request) => jsonResponse({
                'answer':
                    'I could not find anything in the knowledge base about this.',
                'citations': [],
                'insufficient_evidence': true,
                'insufficient_reason':
                    'No document scored above the minimum relevance.',
                'notices': [
                  'Answers are generated from platform documents only.'
                ],
                'disclaimer':
                    'AI-assisted answer — verify with your local agriculture officer.',
                'llm': {
                  'provider': 'mock',
                  'model': 'demo-llm',
                  'is_demo': true
                },
                'retrieval': {
                  'method': 'pgvector_cosine',
                  'embedding_provider': 'mock',
                  'embedding_is_demo': true,
                },
                'guardrails': {
                  'grounded': false,
                  'flags': [],
                  'answer_modified': false
                },
              }),
        },
      );
      await pumpHarness(tester, harness, const AssistantScreen());

      await tester.enterText(find.byType(TextField), 'how much urea for onion');
      await tester.tap(find.byIcon(Icons.send));
      await tester.pumpAndSettle();

      expect(find.text(_strings.t('insufficient_evidence')), findsOneWidget);
      expect(find.text('No document scored above the minimum relevance.'),
          findsOneWidget);
      expect(find.textContaining('knowledge base'), findsWidgets);
      expect(
        find.text(_strings.t('no_sources')),
        findsNothing,
        reason:
            'the insufficient-evidence branch replaces the "no sources" hint',
      );
    });

    testWidgets(
        'a grounded answer shows the provider disclosure and its citations',
        (tester) async {
      final harness = await buildHarness(
        signedIn: true,
        routes: {
          '/api/v1/knowledge/ask': (request) => jsonResponse({
                'answer': 'Apply potassium sulphate as per the package label.',
                'citations': [
                  {
                    'kind': 'knowledge_chunk',
                    'ref_id': 'chunk-1',
                    'title': 'Onion nutrient management',
                    'source_name': 'Maharashtra agriculture department',
                    'source_url': 'https://example.org/onion',
                    'score': 0.8123,
                    'verification_status': 'official',
                  },
                ],
                'insufficient_evidence': false,
                'notices': [],
                'disclaimer':
                    'AI-assisted answer — verify with your local agriculture officer.',
                'llm': {
                  'provider': 'mock',
                  'model': 'demo-llm',
                  'is_demo': true
                },
                'retrieval': {
                  'method': 'pgvector_cosine',
                  'embedding_provider': 'mock',
                  'embedding_is_demo': true,
                },
                'guardrails': {
                  'grounded': true,
                  'flags': [],
                  'answer_modified': false
                },
              }),
        },
      );
      await pumpHarness(tester, harness, const AssistantScreen());

      await tester.enterText(find.byType(TextField), 'urea dose for onion');
      await tester.tap(find.byIcon(Icons.send));
      await tester.pumpAndSettle();

      expect(find.text(_strings.t('sources')), findsOneWidget);
      expect(find.text('Onion nutrient management'), findsOneWidget);
      expect(find.textContaining('example.org/onion'), findsOneWidget);
      expect(find.textContaining('mock'), findsWidgets);
      expect(find.textContaining('AI-assisted'), findsWidgets);
    });
  });

  group('AuthScreen — server settings', () {
    testWidgets('an unreachable backend is explained and can be re-pointed',
        (tester) async {
      final harness = await buildHarness(
        routes: {
          // The probes (and the login) fail: nothing is listening on this address.
          '/health': (request) => errorResponse(500, 'down', 'nope'),
        },
      );
      await pumpHarness(tester, harness, const AuthScreen());

      // The address is visible before signing in, with a way in.
      expect(find.textContaining(_strings.t('server_address')), findsOneWidget);
      await tester.tap(find.byTooltip(_strings.t('server_settings')));
      await tester.pumpAndSettle();

      expect(find.text(_strings.t('server_help')), findsOneWidget);

      // Point it at a different host and test the connection for real.
      await tester.enterText(
        find.descendant(
          of: find.byType(ServerSettingsSheet),
          matching: find.byType(FormTextField),
        ),
        'http://192.168.1.7:8000',
      );
      await tester.tap(find.byIcon(Icons.network_check));
      await tester.pumpAndSettle();

      expect(
        harness.paths.where((path) => path == '/health').length,
        1,
        reason: 'the panel must probe the API it is configured to use',
      );
      expect(find.text('/health'), findsOneWidget);
      expect(find.text(_strings.t('connection_not_ready')), findsWidgets);
      expect(harness.store.values['base_url'], 'http://192.168.1.7:8000');
    });

    testWidgets('a healthy backend is reported as reachable, with version',
        (tester) async {
      final harness = await buildHarness(
        routes: {
          '/health': (request) => jsonResponse({
                'status': 'ok',
                'service': 'Digital Village API',
                'version': '0.1.0',
                'environment': 'development',
              }),
          '/ready': (request) => jsonResponse({
                'status': 'ready',
                'checks': {'database': 'ok', 'cache': 'ok'},
              }),
        },
      );
      await pumpHarness(tester, harness, const AuthScreen());

      await tester.tap(find.byTooltip(_strings.t('server_settings')));
      await tester.pumpAndSettle();
      await tester.tap(find.byIcon(Icons.network_check));
      await tester.pumpAndSettle();

      expect(find.text(_strings.t('connection_reachable')), findsWidgets);
      expect(find.textContaining('Digital Village API 0.1.0'), findsOneWidget);
      expect(find.textContaining('database: ok'), findsOneWidget);
    });
  });

  group('AuthScreen — server panel diagnostics', () {
    testWidgets('a socket failure names the reason and the next step',
        (tester) async {
      final harness = await buildHarness(
        routes: {
          '/health': (request) =>
              throw const SocketException('Connection refused'),
        },
      );
      await pumpHarness(tester, harness, const AuthScreen());

      await tester.tap(find.byTooltip(_strings.t('server_settings')));
      await tester.pumpAndSettle();
      await tester.tap(find.byIcon(Icons.network_check));
      await tester.pumpAndSettle();

      expect(find.text(_strings.t('connection_unreachable')), findsWidgets);
      // The reason, not a code: the OS message is passed through.
      expect(find.textContaining('Connection refused'), findsWidgets);
      // And the next step, which for this cause is "start the API on 0.0.0.0".
      expect(find.textContaining(_strings.t('advice_refused')), findsOneWidget);
      // And the documented place to look next.
      expect(
        find.textContaining('docs/mobile_release.md'),
        findsOneWidget,
        reason: 'a dead end must point at the checklist',
      );
    });

    testWidgets('an unusable address is not saved, and says why',
        (tester) async {
      final harness = await buildHarness();
      await pumpHarness(tester, harness, const AuthScreen());

      await tester.tap(find.byTooltip(_strings.t('server_settings')));
      await tester.pumpAndSettle();

      final field = find.descendant(
        of: find.byType(ServerSettingsSheet),
        matching: find.byType(FormTextField),
      );
      await tester.enterText(field, 'not a url');
      await tester.tap(find.byIcon(Icons.network_check));
      await tester.pumpAndSettle();

      expect(find.text(_strings.t('server_invalid')), findsOneWidget);
      expect(harness.paths, isEmpty,
          reason:
              'nothing may be probed with an address that was not accepted');
      expect(harness.store.values.containsKey('base_url'), isFalse,
          reason: 'the rejected address must not be persisted either');
    });

    testWidgets('a typed address without a scheme is repaired and shown',
        (tester) async {
      final harness = await buildHarness(
        routes: {
          '/health': (request) => errorResponse(500, 'down', 'nope'),
        },
      );
      await pumpHarness(tester, harness, const AuthScreen());

      await tester.tap(find.byTooltip(_strings.t('server_settings')));
      await tester.pumpAndSettle();
      final field = find.descendant(
        of: find.byType(ServerSettingsSheet),
        matching: find.byType(FormTextField),
      );
      await tester.enterText(field, '10.0.0.7:8000');
      await tester.tap(find.byIcon(Icons.network_check));
      await tester.pumpAndSettle();

      expect(harness.store.values['base_url'], 'http://10.0.0.7:8000');
      expect(find.textContaining('http://10.0.0.7:8000'), findsWidgets);
      expect(find.textContaining(_strings.t('server_saved')), findsOneWidget);
    });
  });
}
