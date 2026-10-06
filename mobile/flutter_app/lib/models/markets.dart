import 'json_utils.dart';

/// One mandi price row (`GET /markets/prices`).
///
/// `source` and `sourceUrl` are preserved so a farmer can check the price at its
/// origin. Nothing in the app recomputes or "smooths" these numbers.
class MarketPrice {
  const MarketPrice({
    required this.marketCode,
    required this.marketName,
    required this.cropCode,
    required this.cropName,
    this.state,
    this.district,
    this.priceDate,
    this.minPrice,
    this.maxPrice,
    this.modalPrice,
    this.unit,
    this.arrivalsTonnes,
    this.source,
    this.sourceUrl,
    this.isEstimate = false,
  });

  factory MarketPrice.fromJson(Map<String, dynamic> json) => MarketPrice(
        marketCode: asString(json['market_code']),
        marketName: asString(json['market_name'],
            fallback: asString(json['market_code'])),
        cropCode: asString(json['crop_code']),
        cropName:
            asString(json['crop_name'], fallback: asString(json['crop_code'])),
        state: asStringOrNull(json['state']),
        district: asStringOrNull(json['district']),
        priceDate: asDateOnlyOrNull(json['price_date']),
        minPrice: asDoubleOrNull(json['min_price']),
        maxPrice: asDoubleOrNull(json['max_price']),
        modalPrice: asDoubleOrNull(json['modal_price']),
        unit: asStringOrNull(json['unit']),
        arrivalsTonnes: asDoubleOrNull(json['arrivals_tonnes']),
        source: asStringOrNull(json['source']),
        sourceUrl: asStringOrNull(json['source_url']),
        isEstimate: asBool(json['is_estimate']),
      );

  final String marketCode;
  final String marketName;
  final String cropCode;
  final String cropName;
  final String? state;
  final String? district;
  final DateTime? priceDate;
  final double? minPrice;
  final double? maxPrice;
  final double? modalPrice;
  final String? unit;
  final double? arrivalsTonnes;
  final String? source;
  final String? sourceUrl;
  final bool isEstimate;
}

/// Envelope of `GET /markets/prices`, including the provider disclosure.
class MarketPricePage {
  const MarketPricePage({
    required this.items,
    required this.provider,
    required this.isDemo,
    required this.notices,
    required this.disclaimer,
    this.source,
    this.sourceUrl,
    this.retrievedAt,
    this.count = 0,
    this.cached = false,
  });

  factory MarketPricePage.fromJson(Map<String, dynamic> json) =>
      MarketPricePage(
        items: asMapList(json['items']).map(MarketPrice.fromJson).toList(),
        provider: asString(json['provider'], fallback: 'unknown'),
        isDemo: asBool(json['is_demo']),
        notices: asStringList(json['notices']),
        disclaimer: asString(json['disclaimer']),
        source: asStringOrNull(json['source']),
        sourceUrl: asStringOrNull(json['source_url']),
        retrievedAt: asDateTimeOrNull(json['retrieved_at']),
        count: asInt(json['count'], fallback: asMapList(json['items']).length),
        cached: asBool(json['cached']),
      );

  final List<MarketPrice> items;
  final String provider;
  final bool isDemo;
  final List<String> notices;
  final String disclaimer;
  final String? source;
  final String? sourceUrl;
  final DateTime? retrievedAt;
  final int count;
  final bool cached;
}

class TrendPoint {
  const TrendPoint({
    required this.priceDate,
    this.modalPrice,
    this.minPrice,
    this.maxPrice,
    this.isEstimate = false,
  });

  factory TrendPoint.fromJson(Map<String, dynamic> json) => TrendPoint(
        priceDate: asDateOnlyOrNull(json['price_date']),
        modalPrice: asDoubleOrNull(json['modal_price']),
        minPrice: asDoubleOrNull(json['min_price']),
        maxPrice: asDoubleOrNull(json['max_price']),
        isEstimate: asBool(json['is_estimate']),
      );

  final DateTime? priceDate;
  final double? modalPrice;
  final double? minPrice;
  final double? maxPrice;
  final bool isEstimate;
}

/// `GET /markets/prices/trend` — observed history, with estimates flagged
/// per point so the chart can render them differently.
class PriceTrend {
  const PriceTrend({
    required this.cropCode,
    required this.unit,
    required this.points,
    required this.provider,
    required this.isDemo,
    required this.direction,
    required this.notices,
    this.marketCode,
    this.source,
    this.retrievedAt,
    this.changePercent,
    this.methodNote,
  });

  factory PriceTrend.fromJson(Map<String, dynamic> json) => PriceTrend(
        cropCode: asString(json['crop_code']),
        unit: asString(json['unit'], fallback: 'quintal'),
        points: asMapList(json['points']).map(TrendPoint.fromJson).toList(),
        provider: asString(json['provider'], fallback: 'unknown'),
        isDemo: asBool(json['is_demo']),
        direction: asString(json['direction'], fallback: 'unknown'),
        notices: asStringList(json['notices']),
        marketCode: asStringOrNull(json['market_code']),
        source: asStringOrNull(json['source']),
        retrievedAt: asDateTimeOrNull(json['retrieved_at']),
        changePercent: asDoubleOrNull(json['change_percent']),
        methodNote: asStringOrNull(json['method_note']),
      );

  final String cropCode;
  final String unit;
  final List<TrendPoint> points;
  final String provider;
  final bool isDemo;
  final String direction;
  final List<String> notices;
  final String? marketCode;
  final String? source;
  final DateTime? retrievedAt;
  final double? changePercent;
  final String? methodNote;

  bool get hasObservations =>
      points.any((p) => !p.isEstimate && p.modalPrice != null);
}

/// A market that the backend knows about (`GET /markets/markets`).
class MarketInfo {
  const MarketInfo({
    required this.code,
    required this.name,
    this.state,
    this.district,
    this.marketType,
    this.sourceName,
    this.sourceUrl,
    this.isDemo = false,
  });

  factory MarketInfo.fromJson(Map<String, dynamic> json) => MarketInfo(
        code: asString(json['code']),
        name: asString(json['name'], fallback: asString(json['code'])),
        state: asStringOrNull(json['state']),
        district: asStringOrNull(json['district']),
        marketType: asStringOrNull(json['market_type']),
        sourceName: asStringOrNull(json['source_name']),
        sourceUrl: asStringOrNull(json['source_url']),
        isDemo: asBool(json['is_demo']),
      );

  final String code;
  final String name;
  final String? state;
  final String? district;
  final String? marketType;
  final String? sourceName;
  final String? sourceUrl;
  final bool isDemo;
}

/// A crop that has price data (`GET /markets/crops`).
class MarketCrop {
  const MarketCrop({
    required this.cropCode,
    required this.name,
    required this.unit,
    this.hasDemoPrices = false,
  });

  factory MarketCrop.fromJson(Map<String, dynamic> json) => MarketCrop(
        cropCode: asString(json['crop_code']),
        name: asString(json['name'], fallback: asString(json['crop_code'])),
        unit: asString(json['unit'], fallback: 'quintal'),
        hasDemoPrices: asBool(json['has_demo_prices']),
      );

  final String cropCode;
  final String name;
  final String unit;
  final bool hasDemoPrices;
}

/// An arrivals row (`GET /markets/arrivals`). Parsed defensively because the
/// provider may publish a subset of the columns for a given market.
class ArrivalRow {
  const ArrivalRow({required this.raw});

  factory ArrivalRow.fromJson(Map<String, dynamic> json) =>
      ArrivalRow(raw: json);

  final Map<String, dynamic> raw;

  String? get marketName =>
      asStringOrNull(raw['market_name']) ?? asStringOrNull(raw['market_code']);
  String? get cropName =>
      asStringOrNull(raw['crop_name']) ?? asStringOrNull(raw['crop_code']);
  String? get unit => asStringOrNull(raw['unit']);
  DateTime? get date =>
      asDateOnlyOrNull(raw['arrival_date']) ??
      asDateOnlyOrNull(raw['price_date']) ??
      asDateOnlyOrNull(raw['date']);
  double? get arrivalsTonnes =>
      asDoubleOrNull(raw['arrivals_tonnes']) ?? asDoubleOrNull(raw['arrivals']);
  double? get modalPrice => asDoubleOrNull(raw['modal_price']);
  bool get isEstimate => asBool(raw['is_estimate']);
}

class ArrivalsPage {
  const ArrivalsPage({
    required this.rows,
    required this.provider,
    required this.isDemo,
    required this.notices,
    this.cropCode,
    this.source,
    this.retrievedAt,
    this.count = 0,
    this.note,
  });

  factory ArrivalsPage.fromJson(Map<String, dynamic> json) => ArrivalsPage(
        rows: asMapList(json['items']).map(ArrivalRow.fromJson).toList(),
        provider: asString(json['provider'], fallback: 'unknown'),
        isDemo: asBool(json['is_demo']),
        notices: asStringList(json['notices']),
        cropCode: asStringOrNull(json['crop_code']),
        source: asStringOrNull(json['source']),
        retrievedAt: asDateTimeOrNull(json['retrieved_at']),
        count: asInt(json['count']),
        note: asStringOrNull(json['note']),
      );

  final List<ArrivalRow> rows;
  final String provider;
  final bool isDemo;
  final List<String> notices;
  final String? cropCode;
  final String? source;
  final DateTime? retrievedAt;
  final int count;
  final String? note;
}

/// Response of `POST /markets/prices/estimate` (`available: false` is a normal,
/// honest answer when the price model has no data for that crop/market).
class PriceEstimate {
  const PriceEstimate({
    required this.cropCode,
    required this.available,
    required this.horizonDays,
    required this.confidenceInterpretation,
    required this.disclaimer,
    this.marketCode,
    this.unit,
    this.points = const [],
    this.history = const [],
    this.modelName,
    this.modelVersion,
    this.reason,
  });

  factory PriceEstimate.fromJson(Map<String, dynamic> json) => PriceEstimate(
        cropCode: asString(json['crop_code']),
        available: asBool(json['available']),
        horizonDays: asInt(json['horizon_days']),
        confidenceInterpretation: asString(json['confidence_interpretation']),
        disclaimer: asString(json['disclaimer']),
        marketCode: asStringOrNull(json['market_code']),
        unit: asStringOrNull(json['unit']),
        points: asMapList(json['points']).map(EstimatePoint.fromJson).toList(),
        history: asMapList(json['history']).map(TrendPoint.fromJson).toList(),
        modelName: asStringOrNull(json['model_name']),
        modelVersion: asStringOrNull(json['model_version']),
        reason: asStringOrNull(json['reason']),
      );

  final String cropCode;
  final bool available;
  final int horizonDays;
  final String confidenceInterpretation;
  final String disclaimer;
  final String? marketCode;
  final String? unit;
  final List<EstimatePoint> points;
  final List<TrendPoint> history;
  final String? modelName;
  final String? modelVersion;
  final String? reason;
}

class EstimatePoint {
  const EstimatePoint({
    required this.dayOffset,
    this.estimatedPrice,
    this.lowerBound,
    this.upperBound,
    this.date,
  });

  factory EstimatePoint.fromJson(Map<String, dynamic> json) => EstimatePoint(
        dayOffset:
            asInt(json['day_offset'], fallback: asInt(json['horizon_day'])),
        estimatedPrice:
            asDoubleOrNull(json['estimated_price'] ?? json['price']),
        lowerBound: asDoubleOrNull(json['lower_bound']),
        upperBound: asDoubleOrNull(json['upper_bound']),
        date: asDateOnlyOrNull(json['date'] ?? json['price_date']),
      );

  final int dayOffset;
  final double? estimatedPrice;
  final double? lowerBound;
  final double? upperBound;
  final DateTime? date;
}
