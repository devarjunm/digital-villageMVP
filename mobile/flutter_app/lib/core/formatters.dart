/// Number, money, date and unit formatting.
///
/// Written by hand rather than pulled from `intl` for one reason: the app must
/// format Marathi and Hindi dates and rupee amounts correctly *without* loading
/// locale data at startup, and the three locales it supports have fixed, known
/// conventions.
///
/// Money uses the Indian digit grouping (1,23,456 rather than 123,456), because
/// that is how prices are written in the market.
class Fmt {
  Fmt._();

  static const _months = <String, List<String>>{
    'en': [
      'Jan',
      'Feb',
      'Mar',
      'Apr',
      'May',
      'Jun',
      'Jul',
      'Aug',
      'Sep',
      'Oct',
      'Nov',
      'Dec',
    ],
    'mr': [
      'जाने',
      'फेब्रु',
      'मार्च',
      'एप्रि',
      'मे',
      'जून',
      'जुलै',
      'ऑग',
      'सप्टें',
      'ऑक्टो',
      'नोव्हें',
      'डिसें',
    ],
    'hi': [
      'जन',
      'फ़र',
      'मार्च',
      'अप्रैल',
      'मई',
      'जून',
      'जुल',
      'अग',
      'सित',
      'अक्तू',
      'नव',
      'दिस',
    ],
  };

  static const _weekdays = <String, List<String>>{
    'en': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
    'mr': ['सोम', 'मंगळ', 'बुध', 'गुरु', 'शुक्र', 'शनि', 'रवि'],
    'hi': ['सोम', 'मंगल', 'बुध', 'गुरु', 'शुक्र', 'शनि', 'रवि'],
  };

  /// `1,23,456` — Indian grouping, with optional decimals.
  static String number(num? value, {int decimals = 0, String dash = '—'}) {
    if (value == null) return dash;
    final negative = value < 0;
    final absolute = value.abs();
    final whole = absolute.truncate();
    var fraction = '';
    if (decimals > 0) {
      final micros = ((absolute - whole) * _pow10(decimals)).round();
      fraction = '.${micros.toString().padLeft(decimals, '0')}';
    }
    final digits = whole.toString();
    String grouped;
    if (digits.length <= 3) {
      grouped = digits;
    } else {
      final last3 = digits.substring(digits.length - 3);
      var rest = digits.substring(0, digits.length - 3);
      final parts = <String>[];
      while (rest.length > 2) {
        parts.insert(0, rest.substring(rest.length - 2));
        rest = rest.substring(0, rest.length - 2);
      }
      if (rest.isNotEmpty) parts.insert(0, rest);
      grouped = '${parts.join(',')},$last3';
    }
    return '${negative ? '-' : ''}$grouped$fraction';
  }

  static int _pow10(int exponent) {
    var result = 1;
    for (var i = 0; i < exponent; i++) {
      result *= 10;
    }
    return result;
  }

  /// Rupee amount, e.g. `₹2,450` or `₹2,450.50`.
  static String inr(num? value, {int decimals = 0, String dash = '—'}) =>
      value == null ? dash : '₹${number(value, decimals: decimals)}';

  /// Per-unit price, e.g. `₹2,450 / quintal`.
  static String pricePerUnit(num? value, String? unit, {int decimals = 0}) {
    if (value == null) return '—';
    return unit == null || unit.isEmpty
        ? inr(value, decimals: decimals)
        : '${inr(value, decimals: decimals)} / $unit';
  }

  /// Decimal degrees, used for coordinates.
  static String coord(double? value, {int decimals = 4}) =>
      value == null ? '—' : value.toStringAsFixed(decimals);

  static String area(num? value, String? unit, {String dash = '—'}) {
    if (value == null || unit == null) return dash;
    final decimals = value == value.roundToDouble() ? 0 : 2;
    return '${number(value, decimals: decimals)} $unit';
  }

  static String hectares(num? value) =>
      value == null ? '—' : '${number(value, decimals: 2)} ha';

  /// `12 Mar 2026`.
  static String date(DateTime? value,
      {String language = 'en', String dash = '—'}) {
    if (value == null) return dash;
    final local = value.toLocal();
    final months = _months[language] ?? _months['en']!;
    return '${local.day} ${months[local.month - 1]} ${local.year}';
  }

  /// `Mon, 12 Mar 2026`.
  static String dateWithWeekday(DateTime? value, {String language = 'en'}) {
    if (value == null) return '—';
    final local = value.toLocal();
    final names = _weekdays[language] ?? _weekdays['en']!;
    return '${names[local.weekday - 1]}, ${date(local, language: language)}';
  }

  /// `Mon 12 Oct` — short enough for a forecast row.
  static String weekdayShort(DateTime? value, {String language = 'en'}) {
    if (value == null) return '—';
    final local = value.toLocal();
    final names = _weekdays[language] ?? _weekdays['en']!;
    final months = _months[language] ?? _months['en']!;
    return '${names[local.weekday - 1]} ${local.day} ${months[local.month - 1]}';
  }

  /// `12 Mar 2026, 4:35 pm`.
  static String dateTime(DateTime? value,
      {String language = 'en', String dash = '—'}) {
    if (value == null) return dash;
    final local = value.toLocal();
    final hour24 = local.hour;
    final hour12 = hour24 % 12 == 0 ? 12 : hour24 % 12;
    final suffix = hour24 < 12 ? 'am' : 'pm';
    final minute = local.minute.toString().padLeft(2, '0');
    return '${date(local, language: language)}, $hour12:$minute $suffix';
  }

  /// `3 hours ago` / `just now`, localised for the three supported languages.
  static String relative(DateTime? value,
      {String language = 'en', String dash = '—'}) {
    if (value == null) return dash;
    final difference = DateTime.now().difference(value.toLocal());
    if (difference.isNegative) return _now(language);
    if (difference.inSeconds < 60) return _now(language);
    if (difference.inMinutes < 60) {
      return _minutes(difference.inMinutes, language);
    }
    if (difference.inHours < 24) return _hours(difference.inHours, language);
    if (difference.inDays == 1) return _yesterday(language);
    if (difference.inDays < 30) return _days(difference.inDays, language);
    return date(value, language: language);
  }

  static String _now(String language) => switch (language) {
        'mr' => 'आत्ताच',
        'hi' => 'अभी',
        _ => 'just now',
      };

  static String _minutes(int count, String language) => switch (language) {
        'mr' => '$count मिनिटांपूर्वी',
        'hi' => '$count मिनट पहले',
        _ => '$count min ago',
      };

  static String _hours(int count, String language) => switch (language) {
        'mr' => '$count तासांपूर्वी',
        'hi' => '$count घंटे पहले',
        _ => '$count h ago',
      };

  static String _yesterday(String language) => switch (language) {
        'mr' => 'काल',
        'hi' => 'कल',
        _ => 'yesterday',
      };

  static String _days(int count, String language) => switch (language) {
        'mr' => '$count दिवसांपूर्वी',
        'hi' => '$count दिन पहले',
        _ => '$count days ago',
      };

  /// A model score. Deliberately not called a probability anywhere in the UI:
  /// the crop model reports `relative_model_score`, which is a ranking value.
  static String score(num? value, {int decimals = 3}) =>
      value == null ? '—' : value.toStringAsFixed(decimals);

  static String percent(num? value, {int decimals = 1}) =>
      value == null ? '—' : '${value.toStringAsFixed(decimals)}%';

  /// Bare degrees for compact rows: `21.0°`.
  static String degrees(num? value) =>
      value == null ? '—' : '${value.toStringAsFixed(1)}°';

  static String temp(num? value) =>
      value == null ? '—' : '${value.toStringAsFixed(1)} °C';

  static String wind(num? value) =>
      value == null ? '—' : '${value.toStringAsFixed(0)} km/h';

  static String mm(num? value) =>
      value == null ? '—' : '${value.toStringAsFixed(1)} mm';

  /// Human name for an enum-ish API value: `black_cotton` -> `Black cotton`.
  static String humanize(String? value) {
    if (value == null || value.isEmpty) return '—';
    final words = value.split(RegExp(r'[_\s]+')).where((w) => w.isNotEmpty);
    return words
        .map((w) => w.length == 1
            ? w.toUpperCase()
            : '${w[0].toUpperCase()}${w.substring(1)}')
        .join(' ');
  }

  static String capitalize(String? value) {
    if (value == null || value.isEmpty) return '';
    return value[0].toUpperCase() + value.substring(1);
  }

  static String bytes(int? value) {
    if (value == null) return '—';
    if (value < 1024) return '$value B';
    if (value < 1024 * 1024) return '${(value / 1024).toStringAsFixed(0)} KB';
    return '${(value / (1024 * 1024)).toStringAsFixed(1)} MB';
  }
}
