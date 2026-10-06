import '../core/api_client.dart';
import '../core/config.dart';
import '../models/ai.dart';
import '../models/community.dart';
import '../models/farm.dart';
import '../models/identity.dart';
import '../models/json_utils.dart';
import '../models/markets.dart';
import '../models/notifications.dart';
import '../models/schemes.dart';
import '../models/search.dart';
import '../models/weather.dart';

/// Repositories map one backend area to typed Dart methods.
///
/// Rules followed throughout:
/// * a method exists only when the endpoint exists — no speculative wrappers;
/// * responses are parsed into models, so a renamed field surfaces as a missing
///   value in one place instead of a runtime crash in a widget;
/// * nothing is cached or defaulted here: if the API says "not available", the
///   repository returns that fact and the UI renders it.
class AuthRepository {
  AuthRepository(this._api);

  final ApiClient _api;

  Future<LoginResult> login(
      {required String identifier, required String password}) async {
    final data = await _api.post(
      '/auth/login',
      body: {'identifier': identifier, 'password': password},
      auth: false,
    );
    return LoginResult.fromJson(asMap(data));
  }

  Future<LoginResult> register({
    required String fullName,
    String? phone,
    String? email,
    String? password,
    String preferredLanguage = 'en',
    String roleIntent = 'farmer',
  }) async {
    final data = await _api.post(
      '/auth/register',
      body: {
        'full_name': fullName,
        if (phone != null && phone.isNotEmpty) 'phone': phone,
        if (email != null && email.isNotEmpty) 'email': email,
        if (password != null && password.isNotEmpty) 'password': password,
        'preferred_language': preferredLanguage,
        'role_intent': roleIntent,
      },
      auth: false,
    );
    return LoginResult.fromJson(asMap(data));
  }

  /// Requests an OTP. `purpose` must be one of register/login/password_reset/phone_verify.
  Future<OtpChallenge> requestOtp({
    required String identifier,
    String purpose = 'login',
  }) async {
    final data = await _api.post(
      '/auth/otp/request',
      body: {'identifier': identifier, 'purpose': purpose},
      auth: false,
    );
    return OtpChallenge.fromJson(asMap(data));
  }

  Future<LoginResult> verifyOtp({
    required String identifier,
    required String code,
    String purpose = 'login',
    String? fullName,
    String? preferredLanguage,
  }) async {
    final data = await _api.post(
      '/auth/otp/verify',
      body: {
        'identifier': identifier,
        'code': code,
        'purpose': purpose,
        if (fullName != null && fullName.isNotEmpty) 'full_name': fullName,
        if (preferredLanguage != null) 'preferred_language': preferredLanguage,
      },
      auth: false,
    );
    return LoginResult.fromJson(asMap(data));
  }

  Future<AppUser> me() async {
    final data = await _api.get('/auth/me');
    return AppUser.fromJson(asMap(data));
  }

  Future<void> logout() => _api.post('/auth/logout');

  Future<void> changePassword({
    required String currentPassword,
    required String newPassword,
  }) =>
      _api.post(
        '/auth/password/change',
        body: {
          'current_password': currentPassword,
          'new_password': newPassword
        },
      );

  Future<void> requestPasswordReset(String identifier) =>
      _api.post('/auth/password/reset/request',
          body: {'identifier': identifier}, auth: false);

  Future<void> confirmPasswordReset({
    required String identifier,
    required String code,
    required String newPassword,
  }) =>
      _api.post(
        '/auth/password/reset/confirm',
        body: {
          'identifier': identifier,
          'code': code,
          'new_password': newPassword
        },
        auth: false,
      );
}

class AccountRepository {
  AccountRepository(this._api);

  final ApiClient _api;

  Future<AppUser> me() async =>
      AppUser.fromJson(asMap(await _api.get('/users/me')));

  Future<AppUser> updateMe(
      {String? fullName, String? preferredLanguage}) async {
    final data = await _api.patch(
      '/users/me',
      body: {
        if (fullName != null) 'full_name': fullName,
        if (preferredLanguage != null) 'preferred_language': preferredLanguage,
      },
    );
    return AppUser.fromJson(asMap(data));
  }

  Future<ConsentOverview> consents() async =>
      ConsentOverview.fromJson(asMap(await _api.get('/users/me/consents')));

  Future<ConsentOverview> updateConsents(
    List<Map<String, dynamic>> decisions,
  ) async {
    final data =
        await _api.patch('/users/me/consents', body: {'decisions': decisions});
    return ConsentOverview.fromJson(asMap(data));
  }

  Future<Map<String, dynamic>> dataExportStatus() async =>
      asMap(await _api.get('/users/me/data-export'));

  /// Requests a copy of the account's own data. The API requires the literal
  /// string `EXPORT` so a request cannot be fired by accident.
  Future<Map<String, dynamic>> requestDataExport(
          {String confirm = 'EXPORT'}) async =>
      asMap(await _api
          .post('/users/me/data-export/request', body: {'confirm': confirm}));

  /// `DELETE /users/me` — erases personal data, closes the account and returns a
  /// receipt of what was erased and what was retained. The API requires the
  /// literal string `DELETE`, which the confirmation dialog makes the user type.
  Future<Map<String, dynamic>> deleteAccount(
          {String confirm = 'DELETE'}) async =>
      asMap(await _api.delete('/users/me', body: {'confirm': confirm}));
}

class FarmerRepository {
  FarmerRepository(this._api);

  final ApiClient _api;

  Future<FarmerProfile> me() async =>
      FarmerProfile.fromJson(asMap(await _api.get('/farmers/me')));

  Future<FarmerProfile> update(Map<String, dynamic> patch) async =>
      FarmerProfile.fromJson(
          asMap(await _api.patch('/farmers/me', body: patch)));

  Future<FarmerDashboard> dashboard() async =>
      FarmerDashboard.fromJson(asMap(await _api.get('/farmers/me/dashboard')));
}

class FarmRepository {
  FarmRepository(this._api);

  final ApiClient _api;

  Future<List<Farm>> list() async {
    final data = await _api.get('/farms');
    if (data is! List) return const [];
    return data.map((item) => Farm.fromJson(asMap(item))).toList();
  }

  Future<Farm> get(String farmId) async =>
      Farm.fromJson(asMap(await _api.get('/farms/$farmId')));

  Future<Farm> create(Map<String, dynamic> body) async =>
      Farm.fromJson(asMap(await _api.post('/farms', body: body)));

  Future<Farm> update(String farmId, Map<String, dynamic> patch) async =>
      Farm.fromJson(asMap(await _api.patch('/farms/$farmId', body: patch)));

  Future<void> delete(String farmId) => _api.delete('/farms/$farmId');

  Future<FarmSummary> summary(String farmId) async =>
      FarmSummary.fromJson(asMap(await _api.get('/farms/$farmId/summary')));

  Future<List<Crop>> crops(String farmId) async {
    final data = await _api.get('/farms/$farmId/crops');
    if (data is! List) return const [];
    return data.map((item) => Crop.fromJson(asMap(item))).toList();
  }

  Future<Crop> addCrop(String farmId, Map<String, dynamic> body) async =>
      Crop.fromJson(asMap(await _api.post('/farms/$farmId/crops', body: body)));

  Future<SoilTest> addSoilTest(
          String farmId, Map<String, dynamic> body) async =>
      SoilTest.fromJson(
          asMap(await _api.post('/farms/$farmId/soil-tests', body: body)));
}

class CropRepository {
  CropRepository(this._api);

  final ApiClient _api;

  Future<List<Crop>> list({String? farmId, String? status}) async {
    final data = await _api.get(
      '/crops',
      query: {'farm_id': farmId, 'status': status},
    );
    if (data is! List) return const [];
    return data.map((item) => Crop.fromJson(asMap(item))).toList();
  }

  Future<List<CropCatalogEntry>> catalog() async {
    final data = await _api.get('/crops/catalog');
    if (data is! List) return const [];
    return data.map((item) => CropCatalogEntry.fromJson(asMap(item))).toList();
  }

  Future<Crop> get(String cropId) async =>
      Crop.fromJson(asMap(await _api.get('/crops/$cropId')));

  Future<Crop> update(String cropId, Map<String, dynamic> patch) async =>
      Crop.fromJson(asMap(await _api.patch('/crops/$cropId', body: patch)));

  Future<void> delete(String cropId) => _api.delete('/crops/$cropId');

  Future<List<CropEvent>> events(String cropId) async {
    final data = await _api.get('/crops/$cropId/events');
    if (data is! List) return const [];
    return data.map((item) => CropEvent.fromJson(asMap(item))).toList();
  }

  Future<CropEvent> addEvent(String cropId, Map<String, dynamic> body) async =>
      CropEvent.fromJson(
          asMap(await _api.post('/crops/$cropId/events', body: body)));

  Future<StageGuidance> stageGuidance(String cropId) async =>
      StageGuidance.fromJson(
          asMap(await _api.get('/crops/$cropId/stage-guidance')));
}

class CommunityRepository {
  CommunityRepository(this._api);

  final ApiClient _api;

  Future<CommunityMeta> meta() async => CommunityMeta.fromJson(
      asMap(await _api.get('/community/meta', auth: false)));

  Future<PostPage> feed({
    int page = 1,
    int pageSize = AppConfig.defaultPageSize,
    String? category,
    String? cropCode,
    String? state,
    String? query,
    bool followingOnly = false,
    bool savedOnly = false,
    bool unansweredOnly = false,
    String? sort,
  }) async {
    final data = await _api.get(
      '/community/feed',
      query: {
        'page': page,
        'page_size': pageSize,
        'category': category,
        'crop_code': cropCode,
        'state': state,
        'query': query,
        if (followingOnly) 'following_only': true,
        if (savedOnly) 'saved_only': true,
        if (unansweredOnly) 'unanswered_only': true,
        'sort': sort,
      },
    );
    return PostPage.fromJson(asMap(data));
  }

  Future<PostPage> saved({int page = 1}) async {
    final data = await _api.get('/community/me/saved', query: {'page': page});
    return PostPage.fromJson(asMap(data));
  }

  Future<CommunityPost> post(String postId) async =>
      CommunityPost.fromJson(asMap(await _api.get('/community/posts/$postId')));

  Future<CommunityPost> createPost(Map<String, dynamic> body) async =>
      CommunityPost.fromJson(
          asMap(await _api.post('/community/posts', body: body)));

  Future<CommunityPost> updatePost(
          String postId, Map<String, dynamic> patch) async =>
      CommunityPost.fromJson(
          asMap(await _api.patch('/community/posts/$postId', body: patch)));

  Future<void> deletePost(String postId) =>
      _api.delete('/community/posts/$postId');

  Future<List<Comment>> comments(String postId) async {
    final data = await _api.get('/community/posts/$postId/comments');
    if (data is List) {
      return data.map((item) => Comment.fromJson(asMap(item))).toList();
    }
    // Some endpoints paginate; accept the envelope form too.
    return asMapList(asMap(data)['items']).map(Comment.fromJson).toList();
  }

  Future<Comment> addComment(
    String postId,
    String body, {
    String? parentId,
    List<String> sourceUrls = const [],
  }) async =>
      Comment.fromJson(
        asMap(
          await _api.post(
            '/community/posts/$postId/comments',
            body: {
              'body': body,
              if (parentId != null) 'parent_id': parentId,
              'source_urls': sourceUrls,
            },
          ),
        ),
      );

  /// Adds a reaction. `kind` is one of support/helpful/insightful (from meta).
  Future<int> react(String postId, String kind) async {
    final data = asMap(
      await _api
          .post('/community/posts/$postId/reactions', body: {'kind': kind}),
    );
    return asInt(data['reaction_count'], fallback: asInt(data['count']));
  }

  Future<int> removeReaction(String postId) async {
    final data = asMap(await _api.delete('/community/posts/$postId/reactions'));
    return asInt(data['reaction_count'], fallback: asInt(data['count']));
  }

  Future<bool> toggleSave(String postId) async {
    final data = asMap(await _api.post('/community/posts/$postId/save'));
    return asBool(data['saved'], fallback: asBool(data['is_saved']));
  }

  Future<void> follow(String userId, {required bool follow}) => follow
      ? _api.post('/community/users/$userId/follow')
      : _api.delete('/community/users/$userId/follow');

  /// Reports content. Reasons come from `/community/meta` so the app cannot
  /// invent a category the moderation queue does not understand.
  Future<Map<String, dynamic>> report({
    required String targetType,
    required String targetId,
    required String reason,
    String? details,
  }) async =>
      asMap(
        await _api.post(
          '/community/reports',
          body: {
            'target_type': targetType,
            'target_id': targetId,
            'reason': reason,
            if (details != null && details.isNotEmpty) 'details': details,
          },
        ),
      );
}

class MarketRepository {
  MarketRepository(this._api);

  final ApiClient _api;

  Future<MarketPricePage> prices({
    String? crop,
    String? market,
    String? state,
    String? district,
    String? date,
    int page = 1,
    int pageSize = AppConfig.defaultPageSize,
  }) async {
    final data = await _api.get(
      '/markets/prices',
      query: {
        'crop': crop,
        'market': market,
        'state': state,
        'district': district,
        'date': date,
        'page': page,
        'page_size': pageSize,
      },
    );
    return MarketPricePage.fromJson(asMap(data));
  }

  Future<PriceTrend> trend({
    required String crop,
    String? market,
    int days = 30,
  }) async {
    final data = await _api.get(
      '/markets/prices/trend',
      query: {'crop': crop, 'market': market, 'days': days},
    );
    return PriceTrend.fromJson(asMap(data));
  }

  Future<List<MarketInfo>> markets(
      {String? state, String? district, String? q}) async {
    final data = await _api.get(
      '/markets/markets',
      query: {'state': state, 'district': district, 'q': q},
    );
    if (data is! List) return const [];
    return data.map((item) => MarketInfo.fromJson(asMap(item))).toList();
  }

  Future<List<MarketCrop>> crops() async {
    final data = await _api.get('/markets/crops');
    if (data is! List) return const [];
    return data.map((item) => MarketCrop.fromJson(asMap(item))).toList();
  }

  Future<ArrivalsPage> arrivals(
          {String? crop, String? market, String? state}) async =>
      ArrivalsPage.fromJson(
        asMap(
          await _api.get(
            '/markets/arrivals',
            query: {'crop': crop, 'market': market, 'state': state},
          ),
        ),
      );

  /// Price outlook. A response with `available: false` is a valid answer and is
  /// rendered as "no estimate available", never replaced by a guess.
  Future<PriceEstimate> estimate({
    required String crop,
    String? market,
    int horizonDays = 7,
  }) async =>
      PriceEstimate.fromJson(
        asMap(
          await _api.post(
            '/markets/prices/estimate',
            body: {
              'crop_code': crop,
              if (market != null && market.isNotEmpty) 'market_code': market,
              'horizon_days': horizonDays,
            },
            timeout: AppConfig.aiRequestTimeout,
          ),
        ),
      );

  Future<Map<String, dynamic>> provider() async =>
      asMap(await _api.get('/markets/provider'));
}

class WeatherRepository {
  WeatherRepository(this._api);

  final ApiClient _api;

  Future<WeatherNow> current({double? latitude, double? longitude}) async {
    final data = await _api.get(
      '/weather/current',
      query: {'latitude': latitude, 'longitude': longitude},
    );
    return WeatherNow.fromJson(asMap(data));
  }

  Future<WeatherForecast> forecast({
    double? latitude,
    double? longitude,
    int days = 5,
  }) async {
    final data = await _api.get(
      '/weather/forecast',
      query: {'latitude': latitude, 'longitude': longitude, 'days': days},
    );
    return WeatherForecast.fromJson(asMap(data));
  }

  /// Weather for a farm's own coordinates — the API resolves them server-side so
  /// the client never sends a stale cached location.
  Future<WeatherNow> forFarm(String farmId) async =>
      WeatherNow.fromJson(asMap(await _api.get('/weather/farm/$farmId')));

  Future<List<WeatherAlert>> alerts(
      {double? latitude, double? longitude}) async {
    final data = await _api.get(
      '/weather/alerts',
      query: {'latitude': latitude, 'longitude': longitude},
    );
    final list =
        data is List ? asMapList(data) : asMapList(asMap(data)['items']);
    return list.map(WeatherAlert.fromJson).toList();
  }

  Future<Map<String, dynamic>> provider() async =>
      asMap(await _api.get('/weather/provider'));
}

class SchemeRepository {
  SchemeRepository(this._api);

  final ApiClient _api;

  Future<SchemePage> list({
    String? category,
    String? level,
    String? state,
    String? crop,
    String? q,
    int page = 1,
    int pageSize = AppConfig.defaultPageSize,
  }) async {
    final data = await _api.get(
      '/schemes',
      query: {
        'category': category,
        'level': level,
        'state': state,
        'crop': crop,
        'q': q,
        'page': page,
        'page_size': pageSize,
      },
    );
    return SchemePage.fromJson(asMap(data));
  }

  Future<Scheme> detail(String slug) async =>
      Scheme.fromJson(asMap(await _api.get('/schemes/$slug')));

  Future<SchemeRecommendations> recommended({String? state}) async =>
      SchemeRecommendations.fromJson(
        asMap(await _api.get('/schemes/recommended', query: {'state': state})),
      );

  Future<List<String>> categories() async {
    final data = await _api.get('/schemes/categories');
    if (data is List) return asStringList(data);
    return asStringList(asMap(data)['items']);
  }

  /// Rule-based eligibility check. The inputs are the factors the rules use; any
  /// the user does not provide are reported back in `missingInputs`.
  Future<EligibilityResult> checkEligibility(
    String slug, {
    bool? hasKcc,
    int? ageYears,
    double? annualIncomeInr,
    bool? isTenantFarmer,
    String? categoryCaste,
  }) async =>
      EligibilityResult.fromJson(
        asMap(
          await _api.post(
            '/schemes/$slug/eligibility-check',
            body: {
              if (hasKcc != null) 'has_kcc': hasKcc,
              if (ageYears != null) 'age_years': ageYears,
              if (annualIncomeInr != null) 'annual_income_inr': annualIncomeInr,
              if (isTenantFarmer != null) 'is_tenant_farmer': isTenantFarmer,
              if (categoryCaste != null && categoryCaste.isNotEmpty)
                'category_caste': categoryCaste,
            },
          ),
        ),
      );
}

class NotificationRepository {
  NotificationRepository(this._api);

  final ApiClient _api;

  Future<NotificationPage> list({
    int page = 1,
    int pageSize = AppConfig.defaultPageSize,
    bool unreadOnly = false,
  }) async =>
      NotificationPage.fromJson(
        asMap(
          await _api.get(
            '/notifications',
            query: {
              'page': page,
              'page_size': pageSize,
              if (unreadOnly) 'unread_only': true
            },
          ),
        ),
      );

  Future<UnreadCount> unreadCount() async => UnreadCount.fromJson(
      asMap(await _api.get('/notifications/unread-count')));

  Future<void> markRead(String notificationId) =>
      _api.post('/notifications/$notificationId/read');

  Future<void> markAllRead() => _api.post('/notifications/read-all');

  Future<void> remove(String notificationId) =>
      _api.delete('/notifications/$notificationId');

  Future<NotificationPreferences> preferences() async =>
      NotificationPreferences.fromJson(
          asMap(await _api.get('/notifications/preferences')));

  Future<NotificationPreferences> updatePreferences(
          Map<String, dynamic> patch) async =>
      NotificationPreferences.fromJson(
        asMap(await _api.patch('/notifications/preferences', body: patch)),
      );

  /// Registers a push token. Called only when the app has one — the app does not
  /// invent a token to appear "push enabled" when no push service is configured.
  Future<void> registerDevice(
          {required String token, String platform = 'android'}) =>
      _api.post('/notifications/devices',
          body: {'token': token, 'platform': platform});

  Future<void> unregisterDevice(String token) =>
      _api.delete('/notifications/devices', query: {'token': token});
}

class AiRepository {
  AiRepository(this._api);

  final ApiClient _api;

  Future<CropRecommendation> cropRecommendation(
          Map<String, dynamic> body) async =>
      CropRecommendation.fromJson(
        asMap(
          await _api.post(
            '/ai/crop-recommendation',
            body: body,
            timeout: AppConfig.aiRequestTimeout,
          ),
        ),
      );

  Future<DiseaseObservation> diseaseDetection(
          Map<String, dynamic> body) async =>
      DiseaseObservation.fromJson(
        asMap(
          await _api.post(
            '/ai/disease-detection',
            body: body,
            timeout: AppConfig.aiRequestTimeout,
          ),
        ),
      );

  Future<YieldPrediction> yieldPrediction(Map<String, dynamic> body) async =>
      YieldPrediction.fromJson(
        asMap(
          await _api.post(
            '/ai/yield-prediction',
            body: body,
            timeout: AppConfig.aiRequestTimeout,
          ),
        ),
      );

  Future<Map<String, dynamic>> riskAssessment({
    String? farmId,
    String? cropId,
    String language = 'en',
  }) async =>
      asMap(
        await _api.post(
          '/ai/risk-assessment',
          body: {
            if (farmId != null) 'farm_id': farmId,
            if (cropId != null) 'crop_id': cropId,
            'language': language,
          },
          timeout: AppConfig.aiRequestTimeout,
        ),
      );

  Future<Map<String, dynamic>> seasonPlan({
    required String farmId,
    required String season,
    bool includeRisk = true,
  }) async =>
      asMap(
        await _api.post(
          '/ai/season-plan',
          body: {
            'farm_id': farmId,
            'season': season,
            'include_risk': includeRisk
          },
          timeout: AppConfig.aiRequestTimeout,
        ),
      );

  /// RAG assistant. Farm context is only sent as a flag — the server builds it
  /// from the authenticated profile, so a stale client-side copy cannot leak in.
  Future<AssistantAnswer> ask({
    required String question,
    String? language,
    int topK = 5,
    bool useFarmContext = true,
    String? cropCode,
  }) async =>
      AssistantAnswer.fromJson(
        asMap(
          await _api.post(
            '/knowledge/ask',
            body: {
              'question': question,
              if (language != null) 'language': language,
              'top_k': topK,
              'use_farm_context': useFarmContext,
              if (cropCode != null) 'filters': {'crop_code': cropCode},
            },
            timeout: AppConfig.aiRequestTimeout,
          ),
        ),
      );

  Future<Map<String, dynamic>> retrieve({
    required String query,
    int topK = 5,
    String? cropCode,
  }) async =>
      asMap(
        await _api.post(
          '/knowledge/retrieve',
          body: {
            'query': query,
            'top_k': topK,
            if (cropCode != null) 'filters': {'crop_code': cropCode},
          },
          timeout: AppConfig.aiRequestTimeout,
        ),
      );

  /// Uploads an observation photo. `purpose` must be one the API allows —
  /// `disease_scan` for the disease tool, `post_image` for a community post.
  Future<MediaAsset> uploadImage({
    required List<int> bytes,
    required String filename,
    required String purpose,
  }) async =>
      MediaAsset.fromJson(
        asMap(
          await _api.uploadImage(
            path: '/media/upload',
            bytes: bytes,
            filename: filename,
            fields: {'purpose': purpose},
          ),
        ),
      );

  Future<ModelRegistry> models() async =>
      ModelRegistry.fromJson(asMap(await _api.get('/ai/models', auth: false)));

  Future<AiHistoryPage> history({int page = 1, int pageSize = 20}) async =>
      AiHistoryPage.fromJson(
        asMap(await _api
            .get('/ai/history', query: {'page': page, 'page_size': pageSize})),
      );

  Future<void> deleteHistoryEntry(String predictionId) =>
      _api.delete('/ai/history/$predictionId');

  /// Feedback on an AI result. `consentToTrain` defaults to false: using a
  /// farmer's correction for training requires explicit consent.
  Future<void> feedback({
    required String aiRequestId,
    required String verdict,
    String? comment,
    String? correctedLabel,
    bool consentToTrain = false,
  }) =>
      _api.post(
        '/ai/feedback',
        body: {
          'ai_request_id': aiRequestId,
          'verdict': verdict,
          if (comment != null && comment.isNotEmpty) 'comment': comment,
          if (correctedLabel != null && correctedLabel.isNotEmpty)
            'corrected_label': correctedLabel,
          'consent_to_train': consentToTrain,
        },
      );

  Future<Map<String, dynamic>> aiHealth() async =>
      asMap(await _api.get('/ai/health'));
}

class SearchRepository {
  SearchRepository(this._api);

  final ApiClient _api;

  Future<SearchResults> search({
    required String q,
    String? mode,
    String? crop,
    String? state,
    String? docType,
    String? category,
    int limit = 20,
  }) async =>
      SearchResults.fromJson(
        asMap(
          await _api.get(
            '/search',
            query: {
              'q': q,
              'mode': mode,
              'crop': crop,
              'state': state,
              'doc_type': docType,
              'category': category,
              'limit': limit,
            },
          ),
        ),
      );

  Future<List<String>> suggest(String q, {int limit = 8}) async {
    final data =
        await _api.get('/search/suggest', query: {'q': q, 'limit': limit});
    if (data is List) return asStringList(data);
    return asStringList(asMap(data)['items']);
  }
}

/// Holds one instance of each repository so screens receive them together.
class Repositories {
  Repositories(ApiClient api)
      : auth = AuthRepository(api),
        account = AccountRepository(api),
        farmer = FarmerRepository(api),
        farms = FarmRepository(api),
        crops = CropRepository(api),
        community = CommunityRepository(api),
        markets = MarketRepository(api),
        weather = WeatherRepository(api),
        schemes = SchemeRepository(api),
        notifications = NotificationRepository(api),
        ai = AiRepository(api),
        search = SearchRepository(api);

  final AuthRepository auth;
  final AccountRepository account;
  final FarmerRepository farmer;
  final FarmRepository farms;
  final CropRepository crops;
  final CommunityRepository community;
  final MarketRepository markets;
  final WeatherRepository weather;
  final SchemeRepository schemes;
  final NotificationRepository notifications;
  final AiRepository ai;
  final SearchRepository search;
}
