import 'package:digital_village_app/core/api_exception.dart';
import 'package:digital_village_app/core/formatters.dart';
import 'package:digital_village_app/core/l10n.dart';
import 'package:digital_village_app/core/theme.dart';
import 'package:digital_village_app/widgets/common.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

const _strings = AppLocalizations(Locale('en'));

Future<void> _pump(WidgetTester tester, Widget child) async {
  // One frame only: a widget under test may legitimately contain a spinner, and
  // pumpAndSettle would time out on it. Tests that await data settle themselves.
  await tester.pumpWidget(
    MaterialApp(theme: AppTheme.light(), home: Scaffold(body: child)),
  );
  await tester.pump();
}

void main() {
  group('DemoChip', () {
    testWidgets(
        'always says the data is demo data, and shows the backend notice',
        (tester) async {
      await _pump(
          tester, const DemoChip(notice: 'Synthetic values for development.'));
      expect(find.text(_strings.t('demo_data')), findsOneWidget);
      expect(
        find.byTooltip('Synthetic values for development.'),
        findsOneWidget,
        reason:
            'the provider\'s own explanation must be reachable, not just a generic chip',
      );
    });

    testWidgets('renders without a notice too', (tester) async {
      await _pump(tester, const DemoChip());
      expect(find.text(_strings.t('demo_data')), findsOneWidget);
    });
  });

  group('Notice', () {
    testWidgets('renders title, message and bullet items', (tester) async {
      await _pump(
        tester,
        const Notice(
          kind: NoticeKind.warning,
          title: 'No evidence found',
          message: 'The knowledge base has nothing relevant.',
          items: ['Try a different wording', 'Ask your local officer'],
        ),
      );
      expect(find.text('No evidence found'), findsOneWidget);
      expect(find.text('The knowledge base has nothing relevant.'),
          findsOneWidget);
      expect(find.text('Try a different wording'), findsOneWidget);
      expect(find.text('Ask your local officer'), findsOneWidget);
    });

    testWidgets('the AI notice is visually distinct from a success notice',
        (tester) async {
      await _pump(tester,
          const Notice(kind: NoticeKind.ai, message: 'AI-assisted result.'));
      final container = tester.widget<Container>(
        find
            .ancestor(
                of: find.text('AI-assisted result.'),
                matching: find.byType(Container))
            .first,
      );
      final decoration = container.decoration! as BoxDecoration;
      expect(decoration.color, isNotNull);
      expect(decoration.color, isNot(equals(Colors.transparent)));
    });
  });

  group('TrustChip', () {
    testWidgets('every trust label renders with its meaning', (tester) async {
      for (final entry in AppTheme.trustColors.keys) {
        await _pump(
            tester, TrustChip(label: entry, description: 'meaning of $entry'));
        expect(find.text('meaning of $entry'),
            findsNothing); // it is a tooltip, not a label
        expect(find.byTooltip('meaning of $entry'), findsOneWidget);
        expect(find.text(Fmt.humanize(entry)), findsOneWidget);
      }
    });
  });

  group('DataClassChip', () {
    testWidgets(
        'labels model output, and hides itself when there is nothing to say',
        (tester) async {
      await _pump(tester, const DataClassChip(value: 'model_output'));
      expect(find.text('Model Output'), findsOneWidget);

      await _pump(tester, const DataClassChip(value: null));
      expect(find.byType(Text), findsNothing);
    });
  });

  group('ScoreBar', () {
    testWidgets(
        'shows the raw score with three decimals and never a percent sign',
        (tester) async {
      await _pump(
        tester,
        const ScoreBar(
          label: 'Onion',
          value: 0.8123,
          maxValue: 1,
          caption: 'Relative model score (not a probability)',
          highlight: true,
        ),
      );
      expect(find.text('Onion'), findsOneWidget);
      expect(find.text('0.812'), findsOneWidget);
      expect(find.textContaining('%'), findsNothing);
      expect(find.text('Relative model score (not a probability)'),
          findsOneWidget);
    });
  });

  group('ErrorState', () {
    testWidgets('maps an API error envelope to the message plus the request id',
        (tester) async {
      await _pump(
        tester,
        ErrorState.fromError(
          ApiException(
            message: 'Internal server error',
            statusCode: 500,
            code: 'internal_error',
            requestId: 'abcdef1234567890',
          ),
          onRetry: () async {},
        ),
      );
      expect(find.text('Internal server error'), findsOneWidget);
      expect(find.textContaining('request abcdef12'), findsOneWidget);
      expect(find.text(_strings.t('retry')), findsOneWidget);
    });

    testWidgets('a rate limit explains how long to wait', (tester) async {
      await _pump(
        tester,
        ErrorState.fromError(
          ApiException(
              message: 'slow down',
              statusCode: 429,
              code: 'rate_limited',
              retryAfterSeconds: 30),
        ),
      );
      expect(find.textContaining('30 seconds'), findsOneWidget);
    });

    testWidgets('field errors are listed for forms', (tester) async {
      await _pump(
        tester,
        ErrorState.fromError(
          ApiException(
            message: 'Validation failed',
            statusCode: 422,
            code: 'validation_error',
            details: {
              'fields': [
                {'loc': 'body.area_hectares', 'msg': 'must be greater than 0'},
              ],
            },
          ),
        ),
      );
      expect(find.textContaining('must be greater than 0'), findsOneWidget);
    });
  });

  group('AsyncSection', () {
    testWidgets('shows a loader, then the data', (tester) async {
      var calls = 0;
      await _pump(
        tester,
        AsyncSection<String>(
          load: () async {
            calls++;
            return 'loaded value';
          },
          builder: (context, data, reload) => Text(data),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('loaded value'), findsOneWidget);
      expect(calls, 1);
    });

    testWidgets('shows the error state with a working retry', (tester) async {
      var calls = 0;
      await _pump(
        tester,
        AsyncSection<String>(
          load: () async {
            calls++;
            if (calls == 1) {
              throw ApiException(
                  message: 'Backend unreachable', code: 'network_error');
            }
            return 'second try';
          },
          builder: (context, data, reload) => Text(data),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Backend unreachable'), findsOneWidget);

      await tester.tap(find.text(_strings.t('retry')));
      await tester.pumpAndSettle();
      expect(find.text('second try'), findsOneWidget);
    });

    testWidgets('an empty result uses its own builder, not a blank screen',
        (tester) async {
      await _pump(
        tester,
        AsyncSection<List<String>>(
          load: () async => <String>[],
          isEmpty: (data) => data.isEmpty,
          emptyBuilder: (context, reload) => const Text('nothing here'),
          builder: (context, data, reload) => Text('${data.length} rows'),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('nothing here'), findsOneWidget);
    });
  });

  group('BusyButton', () {
    testWidgets('is disabled while busy and reports the loading label',
        (tester) async {
      var taps = 0;
      await _pump(
        tester,
        BusyButton(
          label: 'Check eligibility',
          busy: true,
          onPressed: () => taps++,
        ),
      );
      expect(find.text(_strings.t('loading')), findsOneWidget);
      await tester.tap(find.byType(FilledButton), warnIfMissed: false);
      expect(taps, 0);
    });

    testWidgets('calls back when idle', (tester) async {
      var taps = 0;
      await _pump(
        tester,
        BusyButton(label: 'Ask', onPressed: () => taps++),
      );
      await tester.tap(find.text('Ask'));
      await tester.pump();
      expect(taps, 1);
    });
  });

  group('InfoRow and StatTile', () {
    testWidgets('render label and value', (tester) async {
      await _pump(
        tester,
        const Column(
          children: [
            InfoRow(label: 'District', value: 'Nashik'),
            StatTile(
                label: 'Modal price', value: '₹2,200', hint: 'per quintal'),
          ],
        ),
      );
      expect(find.text('District'), findsOneWidget);
      expect(find.text('Nashik'), findsOneWidget);
      expect(find.text('Modal price'), findsOneWidget);
      expect(find.text('₹2,200'), findsOneWidget);
    });
  });

  group('localisation plumbing', () {
    testWidgets('context.t resolves through the delegate', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.light(),
          locale: const Locale('mr'),
          localizationsDelegates: const [
            AppLocalizations.delegate,
            GlobalMaterialLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
            GlobalCupertinoLocalizations.delegate,
          ],
          supportedLocales: AppLocalizations.supportedLocales,
          home: Builder(
            builder: (context) => Scaffold(body: Text(context.t('save'))),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('जतन करा'), findsOneWidget);
    });
  });
}
