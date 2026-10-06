import 'json_utils.dart';

/// `GET /weather/current`.
///
/// The provider is reported by the API and may be the demo provider; the screen
/// shows [isDemo] and [demoNotice] verbatim rather than passing synthetic values
/// off as an observation.
class WeatherNow {
  const WeatherNow({
    required this.latitude,
    required this.longitude,
    required this.provider,
    this.placeLabel,
    this.temperatureC,
    this.feelsLikeC,
    this.humidityPercent,
    this.rainfallMm,
    this.windSpeedKmh,
    this.windDirectionDeg,
    this.pressureHpa,
    this.conditionCode,
    this.conditionText,
    this.observedAt,
    this.source,
    this.isDemo = false,
    this.demoNotice,
    this.retrievedAt,
    this.cached = false,
    this.ageSeconds,
    this.farmingNote,
    this.dataClass,
  });

  factory WeatherNow.fromJson(Map<String, dynamic> json) => WeatherNow(
        latitude: asDouble(json['latitude']),
        longitude: asDouble(json['longitude']),
        provider: asString(json['provider'], fallback: 'unknown'),
        placeLabel: asStringOrNull(json['place_label']),
        temperatureC: asDoubleOrNull(json['temperature_c']),
        feelsLikeC: asDoubleOrNull(json['feels_like_c']),
        humidityPercent: asDoubleOrNull(json['humidity_percent']),
        rainfallMm: asDoubleOrNull(json['rainfall_mm']),
        windSpeedKmh: asDoubleOrNull(json['wind_speed_kmh']),
        windDirectionDeg: asDoubleOrNull(json['wind_direction_deg']),
        pressureHpa: asDoubleOrNull(json['pressure_hpa']),
        conditionCode: asStringOrNull(json['condition_code']),
        conditionText: asStringOrNull(json['condition_text']),
        observedAt: asDateTimeOrNull(json['observed_at']),
        source: asStringOrNull(json['source']),
        isDemo: asBool(json['is_demo']),
        demoNotice: asStringOrNull(json['demo_notice']),
        retrievedAt: asDateTimeOrNull(json['retrieved_at']),
        cached: asBool(json['cached']),
        ageSeconds: asIntOrNull(json['age_seconds']),
        farmingNote: asStringOrNull(json['farming_note']),
        dataClass: asStringOrNull(json['data_class']),
      );

  final double latitude;
  final double longitude;
  final String provider;
  final String? placeLabel;
  final double? temperatureC;
  final double? feelsLikeC;
  final double? humidityPercent;
  final double? rainfallMm;
  final double? windSpeedKmh;
  final double? windDirectionDeg;
  final double? pressureHpa;
  final String? conditionCode;
  final String? conditionText;
  final DateTime? observedAt;
  final String? source;
  final bool isDemo;
  final String? demoNotice;
  final DateTime? retrievedAt;
  final bool cached;
  final int? ageSeconds;
  final String? farmingNote;
  final String? dataClass;
}

class ForecastDay {
  const ForecastDay({
    required this.forecastFor,
    this.tempMinC,
    this.tempMaxC,
    this.humidityPercent,
    this.rainfallMm,
    this.rainfallProbabilityPercent,
    this.windSpeedKmh,
    this.conditionCode,
    this.conditionText,
  });

  factory ForecastDay.fromJson(Map<String, dynamic> json) => ForecastDay(
        forecastFor: asDateOnlyOrNull(json['forecast_for']),
        tempMinC: asDoubleOrNull(json['temp_min_c']),
        tempMaxC: asDoubleOrNull(json['temp_max_c']),
        humidityPercent: asDoubleOrNull(json['humidity_percent']),
        rainfallMm: asDoubleOrNull(json['rainfall_mm']),
        rainfallProbabilityPercent:
            asDoubleOrNull(json['rainfall_probability_percent']),
        windSpeedKmh: asDoubleOrNull(json['wind_speed_kmh']),
        conditionCode: asStringOrNull(json['condition_code']),
        conditionText: asStringOrNull(json['condition_text']),
      );

  final DateTime? forecastFor;
  final double? tempMinC;
  final double? tempMaxC;
  final double? humidityPercent;
  final double? rainfallMm;
  final double? rainfallProbabilityPercent;
  final double? windSpeedKmh;
  final String? conditionCode;
  final String? conditionText;
}

/// `GET /weather/forecast`.
class WeatherForecast {
  const WeatherForecast({
    required this.days,
    required this.provider,
    required this.advisories,
    required this.isDemo,
    this.latitude,
    this.longitude,
    this.source,
    this.demoNotice,
    this.retrievedAt,
    this.cached = false,
    this.advisoriesDataClass,
  });

  factory WeatherForecast.fromJson(Map<String, dynamic> json) =>
      WeatherForecast(
        days: asMapList(json['days']).map(ForecastDay.fromJson).toList(),
        provider: asString(json['provider'], fallback: 'unknown'),
        advisories: asStringList(json['advisories']),
        isDemo: asBool(json['is_demo']),
        latitude: asDoubleOrNull(json['latitude']),
        longitude: asDoubleOrNull(json['longitude']),
        source: asStringOrNull(json['source']),
        demoNotice: asStringOrNull(json['demo_notice']),
        retrievedAt: asDateTimeOrNull(json['retrieved_at']),
        cached: asBool(json['cached']),
        advisoriesDataClass: asStringOrNull(json['advisories_data_class']),
      );

  final List<ForecastDay> days;
  final String provider;
  final List<String> advisories;
  final bool isDemo;
  final double? latitude;
  final double? longitude;
  final String? source;
  final String? demoNotice;
  final DateTime? retrievedAt;
  final bool cached;
  final String? advisoriesDataClass;
}

/// A weather alert (`GET /weather/alerts`). Alerts are usually issued by an
/// official agency, so the source URL is carried through untranslated.
class WeatherAlert {
  const WeatherAlert({
    required this.event,
    required this.severity,
    required this.headline,
    required this.provider,
    this.description,
    this.instruction,
    this.validFrom,
    this.validTo,
    this.sourceUrl,
    this.isDemo = false,
  });

  factory WeatherAlert.fromJson(Map<String, dynamic> json) => WeatherAlert(
        event: asString(json['event'], fallback: 'weather'),
        severity: asString(json['severity'], fallback: 'unknown'),
        headline: asString(json['headline']),
        provider: asString(json['provider'], fallback: 'unknown'),
        description: asStringOrNull(json['description']),
        instruction: asStringOrNull(json['instruction']),
        validFrom: asDateTimeOrNull(json['valid_from']),
        validTo: asDateTimeOrNull(json['valid_to']),
        sourceUrl: asStringOrNull(json['source_url']),
        isDemo: asBool(json['is_demo']),
      );

  final String event;
  final String severity;
  final String headline;
  final String provider;
  final String? description;
  final String? instruction;
  final DateTime? validFrom;
  final DateTime? validTo;
  final String? sourceUrl;
  final bool isDemo;
}
