import 'package:flutter/cupertino.dart' show CupertinoPageTransitionsBuilder;
import 'package:flutter/material.dart';

/// Material 3 theme. Green seed because it is an agriculture app, but the colour
/// is only used for structure and status — never to imply that one piece of
/// information is more trustworthy than another (trust labels carry that meaning
/// and have their own, documented colours).
class AppTheme {
  AppTheme._();

  static const Color seed = Color(0xFF2E6E3F);

  /// Colours for the trust vocabulary, so "expert information" and "farmer
  /// experience" are visually distinguishable without a legend.
  static const Map<String, Color> trustColors = {
    'farmer_experience': Color(0xFF1B7F79),
    'community_supported': Color(0xFF2E6E3F),
    'expert_information': Color(0xFF1F4E9C),
    'official_information': Color(0xFF6A3FA0),
    'ai_prediction': Color(0xFF9A5B00),
  };

  static ThemeData light() => _build(Brightness.light);

  static ThemeData dark() => _build(Brightness.dark);

  static ThemeData _build(Brightness brightness) {
    final scheme =
        ColorScheme.fromSeed(seedColor: seed, brightness: brightness);
    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      visualDensity: VisualDensity.standard,
      appBarTheme: AppBarTheme(
        centerTitle: false,
        scrolledUnderElevation: 2,
        backgroundColor: scheme.surface,
        foregroundColor: scheme.onSurface,
      ),
      cardTheme: CardThemeData(
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(14),
          side: BorderSide(color: scheme.outlineVariant),
        ),
        clipBehavior: Clip.antiAlias,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: scheme.surfaceContainerHighest.withValues(alpha: 0.35),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: scheme.outlineVariant),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: scheme.outlineVariant),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: scheme.primary, width: 1.6),
        ),
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        isDense: true,
      ),
      chipTheme: ChipThemeData(
        side: BorderSide(color: scheme.outlineVariant),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        labelStyle: const TextStyle(fontSize: 12.5),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 13),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(10))),
      ),
      navigationBarTheme: NavigationBarThemeData(
        height: 66,
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
        backgroundColor: scheme.surface,
      ),
      listTileTheme: const ListTileThemeData(
        contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 2),
      ),
      dividerTheme:
          DividerThemeData(color: scheme.outlineVariant, thickness: 1),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
      pageTransitionsTheme: PageTransitionsTheme(
        builders: {
          TargetPlatform.android: ZoomPageTransitionsBuilder(),
          TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
        },
      ),
    );
  }
}

/// Semantic colours for data classes. Used consistently so that "observed" and
/// "estimated" are never mistaken for one another.
class DataClassColors {
  DataClassColors._();

  static const Map<String, Color> map = {
    'observation': Color(0xFF1F6F3F),
    'observed': Color(0xFF1F6F3F),
    'actual': Color(0xFF1F6F3F),
    'official': Color(0xFF6A3FA0),
    'reference': Color(0xFF1F4E9C),
    'model_output': Color(0xFF9A5B00),
    'estimate': Color(0xFF9A5B00),
    'prediction': Color(0xFF9A5B00),
    'demo': Color(0xFF6B6B6B),
  };

  static Color? forValue(String? value) =>
      value == null ? null : map[value.toLowerCase()];
}
