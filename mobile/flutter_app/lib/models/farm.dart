import 'json_utils.dart';

/// `GET /farms`, `GET /farms/{id}`.
class Farm {
  const Farm({
    required this.id,
    required this.name,
    required this.areaValue,
    required this.areaUnit,
    required this.areaHectares,
    required this.soilType,
    required this.irrigationType,
    this.village,
    this.taluka,
    this.district,
    this.state,
    this.pincode,
    this.latitude,
    this.longitude,
    this.soilPh,
    this.ownershipType,
    this.waterSourceNotes,
    this.notes,
    this.cropCount = 0,
    this.activeCropCount = 0,
    this.isDemo = false,
    this.areaUnitNote,
    this.createdAt,
    this.updatedAt,
  });

  factory Farm.fromJson(Map<String, dynamic> json) => Farm(
        id: requiredId(json['id'], 'farm'),
        name: asString(json['name'], fallback: 'Farm'),
        areaValue: asDouble(json['area_value']),
        areaUnit: asString(json['area_unit'], fallback: 'acre'),
        areaHectares: asDouble(json['area_hectares']),
        soilType: asString(json['soil_type'], fallback: 'unknown'),
        irrigationType: asString(json['irrigation_type'], fallback: 'rainfed'),
        village: asStringOrNull(json['village']),
        taluka: asStringOrNull(json['taluka']),
        district: asStringOrNull(json['district']),
        state: asStringOrNull(json['state']),
        pincode: asStringOrNull(json['pincode']),
        latitude: asDoubleOrNull(json['latitude']),
        longitude: asDoubleOrNull(json['longitude']),
        soilPh: asDoubleOrNull(json['soil_ph']),
        ownershipType: asStringOrNull(json['ownership_type']),
        waterSourceNotes: asStringOrNull(json['water_source_notes']),
        notes: asStringOrNull(json['notes']),
        cropCount: asInt(json['crop_count']),
        activeCropCount: asInt(json['active_crop_count']),
        isDemo: asBool(json['is_demo']),
        areaUnitNote: asStringOrNull(json['area_unit_note']),
        createdAt: asDateTimeOrNull(json['created_at']),
        updatedAt: asDateTimeOrNull(json['updated_at']),
      );

  final String id;
  final String name;
  final double areaValue;
  final String areaUnit;
  final double areaHectares;
  final String soilType;
  final String irrigationType;
  final String? village;
  final String? taluka;
  final String? district;
  final String? state;
  final String? pincode;
  final double? latitude;
  final double? longitude;
  final double? soilPh;
  final String? ownershipType;
  final String? waterSourceNotes;
  final String? notes;
  final int cropCount;
  final int activeCropCount;
  final bool isDemo;
  final String? areaUnitNote;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  bool get hasCoordinates => latitude != null && longitude != null;

  String get areaDisplay => '${_trim(areaValue)} $areaUnit';

  /// Location line used in lists; falls back to the district/state pair.
  String get placeLabel {
    final parts = [village, taluka, district, state]
        .where((p) => p != null && p.isNotEmpty)
        .cast<String>();
    return parts.isEmpty ? 'Location not recorded' : parts.join(', ');
  }

  static String _trim(double value) {
    if (value == value.roundToDouble()) return value.toInt().toString();
    return value.toStringAsFixed(2);
  }
}

/// A soil test result (`GET /farms/{farm_id}/summary` latest, `POST /farms/{id}/soil-tests`).
class SoilTest {
  const SoilTest({
    required this.id,
    required this.farmId,
    required this.testedOn,
    this.ph,
    this.nitrogen,
    this.phosphorus,
    this.potassium,
    this.organicCarbonPercent,
    this.electricalConductivity,
    this.labName,
    this.reportMediaId,
    this.notes,
    this.createdAt,
  });

  factory SoilTest.fromJson(Map<String, dynamic> json) => SoilTest(
        id: requiredId(json['id'], 'soil test'),
        farmId: asString(json['farm_id']),
        testedOn: asDateOnlyOrNull(json['tested_on']),
        ph: asDoubleOrNull(json['ph']),
        nitrogen: asDoubleOrNull(json['nitrogen_kg_per_ha']),
        phosphorus: asDoubleOrNull(json['phosphorus_kg_per_ha']),
        potassium: asDoubleOrNull(json['potassium_kg_per_ha']),
        organicCarbonPercent: asDoubleOrNull(json['organic_carbon_percent']),
        electricalConductivity: asDoubleOrNull(json['electrical_conductivity']),
        labName: asStringOrNull(json['lab_name']),
        reportMediaId: asStringOrNull(json['report_media_id']),
        notes: asStringOrNull(json['notes']),
        createdAt: asDateTimeOrNull(json['created_at']),
      );

  final String id;
  final String farmId;
  final DateTime? testedOn;
  final double? ph;
  final double? nitrogen;
  final double? phosphorus;
  final double? potassium;
  final double? organicCarbonPercent;
  final double? electricalConductivity;
  final String? labName;
  final String? reportMediaId;
  final String? notes;
  final DateTime? createdAt;

  /// Whether the values the crop-recommendation model needs are present, so the
  /// screen can offer "use my last soil test" only when it can actually help.
  bool get hasMacronutrients =>
      nitrogen != null && phosphorus != null && potassium != null;
}

class CropEvent {
  const CropEvent({
    required this.id,
    required this.eventType,
    required this.occurredOn,
    this.notes,
    this.quantity,
    this.unit,
    this.cost,
    this.dataClass,
  });

  factory CropEvent.fromJson(Map<String, dynamic> json) => CropEvent(
        id: asString(json['id']),
        eventType: asString(json['event_type'], fallback: 'note'),
        occurredOn: asDateOnlyOrNull(json['occurred_on']),
        notes: asStringOrNull(json['notes']),
        quantity: asDoubleOrNull(json['quantity']),
        unit: asStringOrNull(json['unit']),
        cost: asDoubleOrNull(json['cost']),
        dataClass: asStringOrNull(json['data_class']),
      );

  final String id;
  final String eventType;
  final DateTime? occurredOn;
  final String? notes;
  final double? quantity;
  final String? unit;
  final double? cost;
  final String? dataClass;
}

/// A crop cycle on a farm (`GET /farms/{id}/crops`, `GET /crops/{id}`).
class Crop {
  const Crop({
    required this.id,
    required this.farmId,
    required this.cropCode,
    required this.season,
    required this.areaUnit,
    required this.stage,
    required this.status,
    this.cropName,
    this.variety,
    this.sowingDate,
    this.expectedHarvestDate,
    this.areaValue,
    this.irrigationMethod,
    this.seedSource,
    this.notes,
    this.daysSinceSowing,
    this.daysToExpectedHarvest,
    this.events = const [],
    this.isDemo = false,
  });

  factory Crop.fromJson(Map<String, dynamic> json) => Crop(
        id: requiredId(json['id'], 'crop'),
        farmId: asString(json['farm_id']),
        cropCode: asString(json['crop_code']),
        season: asString(json['season'], fallback: 'any'),
        areaUnit: asString(json['area_unit'], fallback: 'acre'),
        stage: asString(json['stage'], fallback: 'planned'),
        status: asString(json['status'], fallback: 'active'),
        cropName: asStringOrNull(json['crop_name']),
        variety: asStringOrNull(json['variety']),
        sowingDate: asDateOnlyOrNull(json['sowing_date']),
        expectedHarvestDate: asDateOnlyOrNull(json['expected_harvest_date']),
        areaValue: asDoubleOrNull(json['area_value']),
        irrigationMethod: asStringOrNull(json['irrigation_method']),
        seedSource: asStringOrNull(json['seed_source']),
        notes: asStringOrNull(json['notes']),
        daysSinceSowing: asIntOrNull(json['days_since_sowing']),
        daysToExpectedHarvest: asIntOrNull(json['days_to_expected_harvest']),
        events: asMapList(json['events']).map(CropEvent.fromJson).toList(),
        isDemo: asBool(json['is_demo']),
      );

  final String id;
  final String farmId;
  final String cropCode;
  final String season;
  final String areaUnit;
  final String stage;
  final String status;
  final String? cropName;
  final String? variety;
  final DateTime? sowingDate;
  final DateTime? expectedHarvestDate;
  final double? areaValue;
  final String? irrigationMethod;
  final String? seedSource;
  final String? notes;
  final int? daysSinceSowing;
  final int? daysToExpectedHarvest;
  final List<CropEvent> events;
  final bool isDemo;

  String get displayName => cropName ?? cropCode;
}

/// One entry of the crop catalogue (`GET /crops/catalog`).
class CropCatalogEntry {
  const CropCatalogEntry({
    required this.code,
    required this.nameEn,
    required this.category,
    required this.season,
    required this.defaultAreaUnit,
    this.nameMr,
    this.nameHi,
    this.diseaseModelSupported = false,
    this.typicalYieldPerHectare,
    this.referenceSource,
  });

  factory CropCatalogEntry.fromJson(Map<String, dynamic> json) =>
      CropCatalogEntry(
        code: asString(json['code']),
        nameEn: asString(json['name_en'], fallback: asString(json['code'])),
        category: asString(json['category']),
        season: asString(json['season'], fallback: 'any'),
        defaultAreaUnit: asString(json['default_area_unit'], fallback: 'acre'),
        nameMr: asStringOrNull(json['name_mr']),
        nameHi: asStringOrNull(json['name_hi']),
        diseaseModelSupported: asBool(json['disease_model_supported']),
        typicalYieldPerHectare:
            asDoubleOrNull(json['typical_yield_per_hectare']),
        referenceSource: asStringOrNull(json['reference_source']),
      );

  final String code;
  final String nameEn;
  final String category;
  final String season;
  final String defaultAreaUnit;
  final String? nameMr;
  final String? nameHi;
  final bool diseaseModelSupported;
  final double? typicalYieldPerHectare;
  final String? referenceSource;

  /// Localised display name, falling back to English when a translation is absent.
  String localizedName(String languageCode) => switch (languageCode) {
        'mr' => nameMr ?? nameEn,
        'hi' => nameHi ?? nameEn,
        _ => nameEn,
      };
}

/// `GET /farms/{farm_id}/summary` — farm, its crops, stage counts, last soil test.
class FarmSummary {
  const FarmSummary({
    required this.farm,
    required this.crops,
    required this.cropStageCounts,
    required this.aiNotes,
    this.latestSoilTest,
  });

  factory FarmSummary.fromJson(Map<String, dynamic> json) => FarmSummary(
        farm: Farm.fromJson(asMap(json['farm'])),
        crops: asMapList(json['crops']).map(Crop.fromJson).toList(),
        cropStageCounts: asMap(json['crop_stage_counts'])
            .map((k, v) => MapEntry(k, asInt(v))),
        aiNotes: asStringList(json['ai_notes']),
        latestSoilTest: json['latest_soil_test'] == null
            ? null
            : SoilTest.fromJson(asMap(json['latest_soil_test'])),
      );

  final Farm farm;
  final List<Crop> crops;
  final Map<String, int> cropStageCounts;
  final List<String> aiNotes;
  final SoilTest? latestSoilTest;
}

/// `GET /crops/{crop_id}/stage-guidance` — advisory text for the current stage.
class StageGuidance {
  const StageGuidance({
    required this.cropCode,
    required this.stage,
    required this.actions,
    required this.dataClass,
    this.sourceName,
    this.sourceUrl,
    this.note,
    this.disclaimer,
  });

  factory StageGuidance.fromJson(Map<String, dynamic> json) => StageGuidance(
        cropCode: asString(json['crop_code']),
        stage: asString(json['stage']),
        actions: asStringList(json['actions']),
        dataClass: asString(json['data_class'], fallback: 'reference'),
        sourceName: asStringOrNull(json['source_name']),
        sourceUrl: asStringOrNull(json['source_url']),
        note: asStringOrNull(json['note']),
        disclaimer: asStringOrNull(json['disclaimer']),
      );

  final String cropCode;
  final String stage;
  final List<String> actions;
  final String dataClass;
  final String? sourceName;
  final String? sourceUrl;
  final String? note;
  final String? disclaimer;
}
