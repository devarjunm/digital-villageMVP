import 'json_utils.dart';

/// The signed-in account (`GET /auth/me`, and the `user` object of a login
/// response).
///
/// Only masked contact details are sent by the API — the full phone number and
/// email address never leave the server, so the app cannot leak them.
class AppUser {
  const AppUser({
    required this.id,
    required this.fullName,
    required this.primaryRole,
    required this.roles,
    required this.preferredLanguage,
    required this.status,
    this.phoneMasked,
    this.emailMasked,
    this.phoneVerified = false,
    this.emailVerified = false,
    this.createdAt,
    this.isDemo = false,
  });

  factory AppUser.fromJson(Map<String, dynamic> json) => AppUser(
        id: requiredId(json['id'], 'account'),
        fullName: asString(json['full_name'], fallback: 'Farmer'),
        primaryRole: asString(json['primary_role'], fallback: 'farmer'),
        roles: asStringList(json['roles']),
        preferredLanguage: asString(json['preferred_language'], fallback: 'en'),
        status: asString(json['status'], fallback: 'active'),
        phoneMasked: asStringOrNull(json['phone_masked']),
        emailMasked: asStringOrNull(json['email_masked']),
        phoneVerified: asBool(json['phone_verified']),
        emailVerified: asBool(json['email_verified']),
        createdAt: asDateTimeOrNull(json['created_at']),
        isDemo: asBool(json['is_demo']),
      );

  final String id;
  final String fullName;
  final String primaryRole;
  final List<String> roles;
  final String preferredLanguage;
  final String status;
  final String? phoneMasked;
  final String? emailMasked;
  final bool phoneVerified;
  final bool emailVerified;
  final DateTime? createdAt;
  final bool isDemo;

  bool get isExpert => roles.contains('expert') || primaryRole == 'expert';
  bool get isModerator =>
      roles.contains('moderator') || primaryRole == 'moderator';
  bool get isAdmin => roles.contains('admin') || primaryRole == 'admin';

  Map<String, dynamic> toJson() => {
        'id': id,
        'full_name': fullName,
        'primary_role': primaryRole,
        'roles': roles,
        'preferred_language': preferredLanguage,
        'status': status,
        'phone_masked': phoneMasked,
        'email_masked': emailMasked,
        'phone_verified': phoneVerified,
        'email_verified': emailVerified,
        'created_at': createdAt?.toIso8601String(),
        'is_demo': isDemo,
      };
}

/// Tokens returned by `/auth/login`, `/auth/otp/verify` and `/auth/refresh`.
class AuthTokens {
  const AuthTokens({
    required this.accessToken,
    this.refreshToken,
    this.expiresIn,
    this.accessExpiresAt,
    this.refreshExpiresAt,
  });

  factory AuthTokens.fromJson(Map<String, dynamic> json) => AuthTokens(
        accessToken: requiredId(json['access_token'], 'access token'),
        refreshToken: asStringOrNull(json['refresh_token']),
        expiresIn: asIntOrNull(json['expires_in']),
        accessExpiresAt: asDateTimeOrNull(json['access_expires_at']),
        refreshExpiresAt: asDateTimeOrNull(json['refresh_expires_at']),
      );

  final String accessToken;
  final String? refreshToken;
  final int? expiresIn;
  final DateTime? accessExpiresAt;
  final DateTime? refreshExpiresAt;
}

class LoginResult {
  const LoginResult({required this.user, required this.tokens});

  factory LoginResult.fromJson(Map<String, dynamic> json) => LoginResult(
        user: AppUser.fromJson(asMap(json['user'])),
        tokens: AuthTokens.fromJson(asMap(json['tokens'])),
      );

  final AppUser user;
  final AuthTokens tokens;
}

/// Result of `/auth/otp/request`.
///
/// `devOtp` is only present while the development console OTP provider is
/// configured. It is shown in the UI behind an explicit "development provider"
/// warning, never as if a real SMS had been verified.
class OtpChallenge {
  const OtpChallenge({
    required this.status,
    required this.message,
    this.expiresInSeconds,
    this.channel,
    this.provider,
    this.isDemoProvider = false,
    this.devOtp,
  });

  factory OtpChallenge.fromJson(Map<String, dynamic> json) => OtpChallenge(
        status: asString(json['status'], fallback: 'sent'),
        message: asString(json['message']),
        expiresInSeconds: asIntOrNull(json['expires_in_seconds']),
        channel: asStringOrNull(json['channel']),
        provider: asStringOrNull(json['provider']),
        isDemoProvider: asBool(json['is_demo_provider']),
        devOtp: asStringOrNull(json['dev_otp']),
      );

  final String status;
  final String message;
  final int? expiresInSeconds;
  final String? channel;
  final String? provider;
  final bool isDemoProvider;
  final String? devOtp;
}

/// `GET /farmers/me` — the farm profile. `profileCompleteness` and
/// `preferredLanguage` are computed server-side.
class FarmerProfile {
  const FarmerProfile({
    required this.id,
    required this.userId,
    required this.displayName,
    this.village,
    this.taluka,
    this.district,
    this.state,
    this.pincode,
    this.latitude,
    this.longitude,
    this.farmingExperienceYears,
    this.primaryCrops = const [],
    this.interests = const [],
    this.totalLandArea,
    this.totalLandUnit,
    this.bio,
    this.organisation,
    this.isPublic = true,
    this.preferredLanguage = 'en',
    this.profileCompleteness = 0,
  });

  factory FarmerProfile.fromJson(Map<String, dynamic> json) => FarmerProfile(
        id: requiredId(json['id'], 'farmer profile'),
        userId: asString(json['user_id']),
        displayName: asString(json['display_name'], fallback: 'Farmer'),
        village: asStringOrNull(json['village']),
        taluka: asStringOrNull(json['taluka']),
        district: asStringOrNull(json['district']),
        state: asStringOrNull(json['state']),
        pincode: asStringOrNull(json['pincode']),
        latitude: asDoubleOrNull(json['latitude']),
        longitude: asDoubleOrNull(json['longitude']),
        farmingExperienceYears: asIntOrNull(json['farming_experience_years']),
        primaryCrops: asStringList(json['primary_crops']),
        interests: asStringList(json['interests']),
        totalLandArea: asDoubleOrNull(json['total_land_area']),
        totalLandUnit: asStringOrNull(json['total_land_unit']),
        bio: asStringOrNull(json['bio']),
        organisation: asStringOrNull(json['organisation']),
        isPublic: asBool(json['is_public'], fallback: true),
        preferredLanguage: asString(json['preferred_language'], fallback: 'en'),
        profileCompleteness: asInt(json['profile_completeness']),
      );

  final String id;
  final String userId;
  final String displayName;
  final String? village;
  final String? taluka;
  final String? district;
  final String? state;
  final String? pincode;
  final double? latitude;
  final double? longitude;
  final int? farmingExperienceYears;
  final List<String> primaryCrops;
  final List<String> interests;
  final double? totalLandArea;
  final String? totalLandUnit;
  final String? bio;
  final String? organisation;
  final bool isPublic;
  final String preferredLanguage;
  final int profileCompleteness;

  bool get hasCoordinates => latitude != null && longitude != null;

  String get placeLabel {
    final parts = [
      village,
      taluka,
      district,
      state,
    ].where((p) => p != null && p.isNotEmpty).cast<String>();
    return parts.isEmpty ? 'Location not recorded' : parts.join(', ');
  }
}

class LandSummary {
  const LandSummary({
    required this.totalFarms,
    required this.totalAreaHectares,
    required this.totalAreaAcres,
    required this.activeCropCount,
    required this.harvestedCropCount,
  });

  factory LandSummary.fromJson(Map<String, dynamic> json) => LandSummary(
        totalFarms: asInt(json['total_farms']),
        totalAreaHectares: asDouble(json['total_area_hectares']),
        totalAreaAcres: asDouble(json['total_area_acres']),
        activeCropCount: asInt(json['active_crop_count']),
        harvestedCropCount: asInt(json['harvested_crop_count']),
      );

  final int totalFarms;
  final double totalAreaHectares;
  final double totalAreaAcres;
  final int activeCropCount;
  final int harvestedCropCount;
}

/// A crop currently in the ground, as reported by the dashboard.
class ActiveCrop {
  const ActiveCrop({
    required this.cropId,
    required this.cropCode,
    required this.cropName,
    required this.farmId,
    required this.farmName,
    required this.stage,
    required this.status,
    this.variety,
    this.sowingDate,
    this.expectedHarvestDate,
    this.daysToExpectedHarvest,
    this.areaValue,
    this.areaUnit,
    this.irrigationMethod,
    this.diseaseModelSupported = false,
  });

  factory ActiveCrop.fromJson(Map<String, dynamic> json) => ActiveCrop(
        cropId: requiredId(json['crop_id'], 'crop'),
        cropCode: asString(json['crop_code']),
        cropName:
            asString(json['crop_name'], fallback: asString(json['crop_code'])),
        farmId: asString(json['farm_id']),
        farmName: asString(json['farm_name']),
        stage: asString(json['stage']),
        status: asString(json['status']),
        variety: asStringOrNull(json['variety']),
        sowingDate: asDateOnlyOrNull(json['sowing_date']),
        expectedHarvestDate: asDateOnlyOrNull(json['expected_harvest_date']),
        daysToExpectedHarvest: asIntOrNull(json['days_to_expected_harvest']),
        areaValue: asDoubleOrNull(json['area_value']),
        areaUnit: asStringOrNull(json['area_unit']),
        irrigationMethod: asStringOrNull(json['irrigation_method']),
        diseaseModelSupported: asBool(json['disease_model_supported']),
      );

  final String cropId;
  final String cropCode;
  final String cropName;
  final String farmId;
  final String farmName;
  final String stage;
  final String status;
  final String? variety;
  final DateTime? sowingDate;
  final DateTime? expectedHarvestDate;
  final int? daysToExpectedHarvest;
  final double? areaValue;
  final String? areaUnit;
  final String? irrigationMethod;

  /// Whether a trained disease model covers this crop. False means the app must
  /// say the photo tool cannot assess it, instead of guessing.
  final bool diseaseModelSupported;
}

class DashboardReminder {
  const DashboardReminder({
    required this.title,
    this.body,
    this.kind,
    this.dueOn,
    this.cropId,
    this.farmId,
  });

  factory DashboardReminder.fromJson(Map<String, dynamic> json) =>
      DashboardReminder(
        title: asString(json['title'], fallback: 'Reminder'),
        body: asStringOrNull(json['body']),
        kind: asStringOrNull(json['kind']),
        dueOn: asDateOnlyOrNull(json['due_on']),
        cropId: asStringOrNull(json['crop_id']),
        farmId: asStringOrNull(json['farm_id']),
      );

  final String title;
  final String? body;
  final String? kind;
  final DateTime? dueOn;
  final String? cropId;
  final String? farmId;
}

class DataFreshness {
  const DataFreshness({this.profileUpdatedAt, required this.note});

  factory DataFreshness.fromJson(Map<String, dynamic> json) => DataFreshness(
        profileUpdatedAt: asDateTimeOrNull(json['profile_updated_at']),
        note: asString(json['note']),
      );

  final DateTime? profileUpdatedAt;
  final String note;
}

/// `GET /farmers/me/dashboard` — everything the home screen shows.
class FarmerDashboard {
  const FarmerDashboard({
    required this.profile,
    required this.landSummary,
    required this.cropStageCounts,
    required this.activeCrops,
    required this.reminders,
    required this.dataFreshness,
  });

  factory FarmerDashboard.fromJson(Map<String, dynamic> json) =>
      FarmerDashboard(
        profile: FarmerProfile.fromJson(asMap(json['profile'])),
        landSummary: LandSummary.fromJson(asMap(json['land_summary'])),
        cropStageCounts: asMap(json['crop_stage_counts']).map(
          (key, value) => MapEntry(key, asInt(value)),
        ),
        activeCrops:
            asMapList(json['active_crops']).map(ActiveCrop.fromJson).toList(),
        reminders: asMapList(json['reminders'])
            .map(DashboardReminder.fromJson)
            .toList(),
        dataFreshness: DataFreshness.fromJson(asMap(json['data_freshness'])),
      );

  final FarmerProfile profile;
  final LandSummary landSummary;
  final Map<String, int> cropStageCounts;
  final List<ActiveCrop> activeCrops;
  final List<DashboardReminder> reminders;
  final DataFreshness dataFreshness;
}

/// One consent switch on the privacy screen (`GET /users/me/consents`).
class ConsentItem {
  const ConsentItem({
    required this.kind,
    required this.title,
    required this.description,
    required this.required,
    required this.granted,
    this.decidedAt,
    this.revokedAt,
    this.source,
  });

  factory ConsentItem.fromJson(Map<String, dynamic> json) => ConsentItem(
        kind: asString(json['kind']),
        title: asString(json['title']),
        description: asString(json['description']),
        required: asBool(json['required']),
        granted: asBool(json['granted']),
        decidedAt: asDateTimeOrNull(json['decided_at']),
        revokedAt: asDateTimeOrNull(json['revoked_at']),
        source: asStringOrNull(json['source']),
      );

  final String kind;
  final String title;
  final String description;
  final bool required;
  final bool granted;
  final DateTime? decidedAt;
  final DateTime? revokedAt;
  final String? source;
}

class ConsentOverview {
  const ConsentOverview({
    required this.policyVersion,
    required this.items,
    required this.note,
  });

  factory ConsentOverview.fromJson(Map<String, dynamic> json) =>
      ConsentOverview(
        policyVersion: asString(json['policy_version']),
        items: asMapList(json['items']).map(ConsentItem.fromJson).toList(),
        note: asString(json['note']),
      );

  final String policyVersion;
  final List<ConsentItem> items;
  final String note;
}
