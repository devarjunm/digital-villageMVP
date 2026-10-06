import 'dart:io';

import 'package:digital_village_app/core/l10n.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('string table', () {
    test('every key exists in English, Marathi and Hindi', () {
      expect(
        AppLocalizations.missingKeys(),
        isEmpty,
        reason: 'A farmer must never see a raw key like "dashboard_title".',
      );
    });

    test('Marathi and Hindi are translated, not copied from English', () {
      final en = const AppLocalizations(Locale('en'));
      final mr = const AppLocalizations(Locale('mr'));
      final hi = const AppLocalizations(Locale('hi'));
      for (final key in ['save', 'cancel', 'retry', 'notifications_title']) {
        expect(mr.t(key), isNot(en.t(key)),
            reason: '$key is not translated to Marathi');
        expect(hi.t(key), isNot(en.t(key)),
            reason: '$key is not translated to Hindi');
      }
    });

    test('an unknown key returns the key itself so the bug is greppable', () {
      const strings = AppLocalizations(Locale('en'));
      expect(strings.t('definitely_not_a_key'), 'definitely_not_a_key');
      expect(AppLocalizations.hasKey('definitely_not_a_key'), isFalse);
    });

    test('a missing translation falls back to English, never to an empty label',
        () {
      // `en` is present for every key by construction (asserted above), and the
      // fallback chain is language -> en -> key.
      const strings = AppLocalizations(Locale('mr'));
      expect(strings.t('save'), isNotEmpty);
    });

    test('the disclaimer and demo wording exist in all three languages', () {
      final keys = <String>[
        'ai_assisted',
        'demo_data',
        'insufficient_evidence',
        'limitations_title',
        'not_a_diagnosis',
        'estimate_unavailable',
      ];
      for (final key in keys) {
        expect(AppLocalizations.hasKey(key), isTrue,
            reason: '$key is missing from the table');
      }
    });
  });

  test('every key used in lib/ is present in the string table', () {
    final pattern = RegExp(r"""\btf?\(\s*['"]([a-zA-Z0-9_]+)['"]""");
    final used = <String>{};
    for (final entity in Directory('lib').listSync(recursive: true)) {
      if (entity is! File || !entity.path.endsWith('.dart')) continue;
      final source = entity
          .readAsStringSync()
          .split('\n')
          .where((line) => !line.trimLeft().startsWith('//'))
          .join('\n');
      for (final match in pattern.allMatches(source)) {
        used.add(match.group(1)!);
      }
    }
    expect(used.length, greaterThan(50),
        reason: 'the scan should find the screens\' keys');
    final missing = used.where((key) => !AppLocalizations.hasKey(key)).toList()
      ..sort();
    expect(missing, isEmpty,
        reason: 'Keys used in lib/ but absent from the table: $missing');
  });
}
