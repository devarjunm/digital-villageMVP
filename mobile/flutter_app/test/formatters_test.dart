import 'package:digital_village_app/core/config.dart';
import 'package:digital_village_app/core/formatters.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('Fmt.number — Indian digit grouping', () {
    test('groups thousands the way mandi prices are written', () {
      expect(Fmt.number(999), '999');
      expect(Fmt.number(1000), '1,000');
      expect(Fmt.number(45000), '45,000');
      expect(Fmt.number(123456), '1,23,456');
      expect(Fmt.number(1234567), '12,34,567');
      expect(Fmt.number(12345678), '1,23,45,678');
    });

    test('keeps the sign and the requested decimals', () {
      expect(Fmt.number(-1234567), '-12,34,567');
      expect(Fmt.number(2450.5, decimals: 2), '2,450.50');
      expect(Fmt.number(0.5, decimals: 2), '0.50');
      expect(Fmt.number(1, decimals: 3), '1.000');
    });

    test('renders an em dash for a missing value instead of 0', () {
      expect(Fmt.number(null), '—');
      expect(Fmt.inr(null), '—');
      expect(Fmt.temp(null), '—');
    });
  });

  group('money and units', () {
    test('rupee amounts, per-unit prices and areas', () {
      expect(Fmt.inr(2450), '₹2,450');
      expect(Fmt.inr(2450.5, decimals: 2), '₹2,450.50');
      expect(Fmt.pricePerUnit(2450, 'quintal'), '₹2,450 / quintal');
      expect(Fmt.pricePerUnit(2450, null), '₹2,450');
      expect(Fmt.pricePerUnit(null, 'quintal'), '—');
      expect(Fmt.area(2.5, 'hectare'), '2.50 hectare');
      expect(Fmt.area(3, 'acre'), '3 acre');
      expect(Fmt.hectares(1.25), '1.25 ha');
      expect(Fmt.mm(12.34), '12.3 mm');
      expect(Fmt.temp(31.44), '31.4 °C');
      expect(Fmt.wind(12.6), '13 km/h');
    });
  });

  group('model scores', () {
    test('a score is a bare number — never presented as a probability', () {
      expect(Fmt.score(0.12345), '0.123');
      expect(Fmt.score(1.0), '1.000');
      expect(Fmt.score(0.5, decimals: 2), '0.50');
      expect(Fmt.score(0.123), isNot(contains('%')));
      expect(Fmt.score(null), '—');
    });

    test('percent is explicit about the unit', () {
      expect(Fmt.percent(78.44), '78.4%');
      expect(Fmt.percent(78.44, decimals: 0), '78%');
    });
  });

  group('dates', () {
    test('English, Marathi and Hindi month names', () {
      final date = DateTime(2026, 3, 12, 9, 5);
      expect(Fmt.date(date), '12 Mar 2026');
      expect(Fmt.date(date, language: 'mr'), startsWith('12 मार्च'));
      expect(Fmt.date(date, language: 'hi'), startsWith('12 मार्च'));
    });

    test('date with weekday and 12-hour clock', () {
      final date = DateTime(2026, 3, 12, 16, 35);
      expect(Fmt.dateWithWeekday(date), startsWith('Thu, 12 Mar 2026'));
      expect(Fmt.dateTime(date), '12 Mar 2026, 4:35 pm');
      expect(
          Fmt.dateTime(DateTime(2026, 3, 12, 0, 5)), '12 Mar 2026, 12:05 am');
    });

    test('relative times read naturally in each language', () {
      final now = DateTime.now();
      expect(
          Fmt.relative(now.subtract(const Duration(seconds: 5))), 'just now');
      expect(
          Fmt.relative(now.subtract(const Duration(minutes: 5))), '5 min ago');
      expect(Fmt.relative(now.subtract(const Duration(hours: 3))), '3 h ago');
      expect(Fmt.relative(now.subtract(const Duration(days: 1))), 'yesterday');
      expect(
        Fmt.relative(now.subtract(const Duration(hours: 3)), language: 'mr'),
        '3 तासांपूर्वी',
      );
      expect(
        Fmt.relative(now.subtract(const Duration(hours: 3)), language: 'hi'),
        '3 घंटे पहले',
      );
      // A timestamp in the future is not "in -2 hours".
      expect(Fmt.relative(now.add(const Duration(hours: 2))), 'just now');
    });
  });

  group('Fmt.humanize — API enum values', () {
    test('turns snake_case into a readable label', () {
      expect(Fmt.humanize('official_information'), 'Official Information');
      expect(Fmt.humanize('black_cotton'), 'Black Cotton');
      expect(Fmt.humanize('model_output'), 'Model Output');
      expect(Fmt.humanize('a_b'), 'A B');
      expect(Fmt.humanize(''), '—');
      expect(Fmt.humanize(null), '—');
    });

    test('capitalize and bytes', () {
      expect(Fmt.capitalize('onion'), 'Onion');
      expect(Fmt.capitalize(null), '');
      expect(Fmt.bytes(512), '512 B');
      expect(Fmt.bytes(2048), '2 KB');
      expect(Fmt.bytes(3 * 1024 * 1024), '3.0 MB');
    });
  });

  group('AppConfig.tryNormalizeBaseUrl', () {
    test('accepts what a person types on a phone, and repairs the scheme', () {
      // The trap this exists for: without a scheme Dart reads "192.168.1.5" as
      // the scheme, the request never leaves the app, and the panel can only
      // report "no answer".
      expect(AppConfig.tryNormalizeBaseUrl('192.168.1.5:8000'),
          'http://192.168.1.5:8000');
      expect(AppConfig.tryNormalizeBaseUrl(' 10.0.2.2:8000 '),
          'http://10.0.2.2:8000');
      expect(AppConfig.tryNormalizeBaseUrl('localhost:8000'),
          'http://localhost:8000');
      expect(AppConfig.tryNormalizeBaseUrl('127.0.0.1'), 'http://127.0.0.1');
    });

    test('keeps an explicit scheme, and never downgrades https', () {
      expect(AppConfig.tryNormalizeBaseUrl('http://192.168.1.5:8000/'),
          'http://192.168.1.5:8000');
      expect(AppConfig.tryNormalizeBaseUrl('https://api.example.org'),
          'https://api.example.org');
      // A public host must be typed with a scheme: guessing http:// here would
      // silently send real traffic in the clear.
      expect(AppConfig.tryNormalizeBaseUrl('api.example.org'), isNull);
    });

    test('drops a path, because requests add /api/v1 themselves', () {
      expect(AppConfig.tryNormalizeBaseUrl('http://192.168.1.5:8000/api/v1'),
          'http://192.168.1.5:8000');
    });

    test('refuses what cannot be a base URL', () {
      for (final bad in ['', '   ', 'not a url', 'ftp://192.168.1.5']) {
        expect(AppConfig.tryNormalizeBaseUrl(bad), isNull, reason: bad);
      }
    });

    test('tells a phone on a foreign subnet from one on the same network', () {
      // The single most common cause of "no answer": the address is right but
      // this device is on a different network.
      expect(
        AppConfig.isProbablyForeignSubnet(
            'http://192.168.1.5:8000', ['10.0.0.7']),
        isTrue,
      );
      expect(
        AppConfig.isProbablyForeignSubnet(
            'http://192.168.1.5:8000', ['192.168.1.42', '10.0.0.7']),
        isFalse,
      );
      // Unknown is not a claim: no IPv4 on either side, no verdict.
      expect(AppConfig.isProbablyForeignSubnet('http://10.0.2.2:8000', []),
          isFalse);
      expect(
        AppConfig.isProbablyForeignSubnet(
            'https://api.example.org', ['192.168.1.42']),
        isFalse,
      );
    });

    test('reports the /24 of an IPv4 literal for the network comparison', () {
      expect(AppConfig.ipv4Subnet('192.168.1.42'), '192.168.1');
      expect(AppConfig.ipv4Subnet('10.0.2.2'), '10.0.2');
      expect(AppConfig.ipv4Subnet('api.example.org'), isNull);
      expect(AppConfig.ipv4Subnet('999.1.1.1'), isNull);
    });
  });
}
