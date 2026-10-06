import 'json_utils.dart';

/// A government scheme (`GET /schemes`, `GET /schemes/{slug}`).
///
/// The official source name and URL are required by the API schema and are shown
/// on every scheme screen: scheme details change, and the farmer must be able to
/// read the current version at the government's own page. `verificationStatus`
/// and `contentNotice` are surfaced too, so an unverified entry is not presented
/// as confirmed.
class Scheme {
  const Scheme({
    required this.id,
    required this.slug,
    required this.name,
    required this.description,
    required this.category,
    required this.level,
    required this.officialSourceName,
    required this.officialSourceUrl,
    required this.verificationStatus,
    this.benefits,
    this.eligibilitySummary,
    this.applicationProcess,
    this.documentsRequired = const [],
    this.stateCodes = const [],
    this.cropCodes = const [],
    this.applicationUrl,
    this.helpline,
    this.lastVerifiedOn,
    this.isDemo = false,
    this.contentNotice,
    this.updatedAt,
  });

  factory Scheme.fromJson(Map<String, dynamic> json) => Scheme(
        id: asString(json['id']),
        slug: requiredId(json['slug'], 'scheme'),
        name: asString(json['name'], fallback: asString(json['slug'])),
        description: asString(json['description']),
        category: asString(json['category']),
        level: asString(json['level']),
        officialSourceName: asString(json['official_source_name']),
        officialSourceUrl: asString(json['official_source_url']),
        verificationStatus:
            asString(json['verification_status'], fallback: 'unverified'),
        benefits: asStringOrNull(json['benefits']),
        eligibilitySummary: asStringOrNull(json['eligibility_summary']),
        applicationProcess: asStringOrNull(json['application_process']),
        documentsRequired: asStringList(json['documents_required']),
        stateCodes: asStringList(json['state_codes']),
        cropCodes: asStringList(json['crop_codes']),
        applicationUrl: asStringOrNull(json['application_url']),
        helpline: asStringOrNull(json['helpline']),
        lastVerifiedOn: asDateOnlyOrNull(json['last_verified_on']),
        isDemo: asBool(json['is_demo']),
        contentNotice: asStringOrNull(json['content_notice']),
        updatedAt: asDateTimeOrNull(json['updated_at']),
      );

  final String id;
  final String slug;
  final String name;
  final String description;
  final String category;
  final String level;
  final String officialSourceName;
  final String officialSourceUrl;
  final String verificationStatus;
  final String? benefits;
  final String? eligibilitySummary;
  final String? applicationProcess;
  final List<String> documentsRequired;
  final List<String> stateCodes;
  final List<String> cropCodes;
  final String? applicationUrl;
  final String? helpline;
  final DateTime? lastVerifiedOn;
  final bool isDemo;
  final String? contentNotice;
  final DateTime? updatedAt;
}

class SchemePage {
  const SchemePage({
    required this.items,
    required this.page,
    required this.pageSize,
    required this.total,
    required this.totalPages,
    required this.hasNext,
  });

  factory SchemePage.fromJson(Map<String, dynamic> json) => SchemePage(
        items: asMapList(json['items']).map(Scheme.fromJson).toList(),
        page: asInt(json['page'], fallback: 1),
        pageSize: asInt(json['page_size'], fallback: 20),
        total: asInt(json['total']),
        totalPages: asInt(json['total_pages'], fallback: 1),
        hasNext: asBool(json['has_next']),
      );

  final List<Scheme> items;
  final int page;
  final int pageSize;
  final int total;
  final int totalPages;
  final bool hasNext;
}

/// A recommendation row from `GET /schemes/recommended`.
///
/// `matchScore` is the API's *rule-based* match percentage, not a probability,
/// and the app labels it as such. `missingInputs` is shown so a farmer can
/// complete their profile and get a better answer.
class SchemeRecommendation {
  const SchemeRecommendation({
    required this.scheme,
    required this.matchScore,
    required this.status,
    required this.reasons,
    required this.missingInputs,
  });

  factory SchemeRecommendation.fromJson(Map<String, dynamic> json) =>
      SchemeRecommendation(
        scheme: Scheme.fromJson(asMap(json['scheme'])),
        matchScore: asInt(json['match_score']),
        status: asString(json['status'], fallback: 'unknown'),
        reasons: asStringList(json['reasons']),
        missingInputs: asStringList(json['missing_inputs']),
      );

  final Scheme scheme;
  final int matchScore;
  final String status;
  final List<String> reasons;
  final List<String> missingInputs;
}

class SchemeRecommendations {
  const SchemeRecommendations({
    required this.items,
    required this.evaluatedSchemes,
    required this.note,
    this.dataClass,
  });

  factory SchemeRecommendations.fromJson(Map<String, dynamic> json) =>
      SchemeRecommendations(
        items: asMapList(json['items'])
            .map(SchemeRecommendation.fromJson)
            .toList(),
        evaluatedSchemes: asInt(json['evaluated_schemes']),
        note: asString(json['note']),
        dataClass: asStringOrNull(json['data_class']),
      );

  final List<SchemeRecommendation> items;
  final int evaluatedSchemes;
  final String note;
  final String? dataClass;
}

/// One rule evaluated by `POST /schemes/{slug}/eligibility-check`.
class RuleOutcome {
  const RuleOutcome(
      {required this.field, required this.message, this.expected});

  factory RuleOutcome.fromJson(Map<String, dynamic> json) => RuleOutcome(
        field: asString(json['field']),
        message: asString(json['message']),
        expected: json['expected']?.toString(),
      );

  final String field;
  final String message;
  final String? expected;
}

/// Result of an eligibility check.
///
/// `status` is one of `likely_eligible` / `likely_not_eligible` /
/// `needs_more_information`; `unknown` lists rules whose data is missing. The
/// app never turns this into "you will receive the money".
class EligibilityResult {
  const EligibilityResult({
    required this.schemeSlug,
    required this.schemeName,
    required this.status,
    required this.confidence,
    required this.passed,
    required this.failed,
    required this.unknown,
    required this.missingInputs,
    required this.configurationWarnings,
    required this.explanation,
    required this.officialSourceName,
    required this.officialSourceUrl,
    required this.verificationStatus,
    required this.disclaimer,
    this.lastVerifiedOn,
    this.dataClass,
  });

  factory EligibilityResult.fromJson(Map<String, dynamic> json) =>
      EligibilityResult(
        schemeSlug: asString(json['scheme_slug']),
        schemeName: asString(json['scheme_name']),
        status: asString(json['status']),
        confidence: asString(json['confidence']),
        passed: asMapList(json['passed']).map(RuleOutcome.fromJson).toList(),
        failed: asMapList(json['failed']).map(RuleOutcome.fromJson).toList(),
        unknown: asMapList(json['unknown']).map(RuleOutcome.fromJson).toList(),
        missingInputs: asStringList(json['missing_inputs']),
        configurationWarnings: asStringList(json['configuration_warnings']),
        explanation: asString(json['explanation']),
        officialSourceName: asString(json['official_source_name']),
        officialSourceUrl: asString(json['official_source_url']),
        verificationStatus: asString(json['verification_status']),
        disclaimer: asString(json['disclaimer']),
        lastVerifiedOn: asDateOnlyOrNull(json['last_verified_on']),
        dataClass: asStringOrNull(json['data_class']),
      );

  final String schemeSlug;
  final String schemeName;
  final String status;
  final String confidence;
  final List<RuleOutcome> passed;
  final List<RuleOutcome> failed;
  final List<RuleOutcome> unknown;
  final List<String> missingInputs;
  final List<String> configurationWarnings;
  final String explanation;
  final String officialSourceName;
  final String officialSourceUrl;
  final String verificationStatus;
  final String disclaimer;
  final DateTime? lastVerifiedOn;
  final String? dataClass;
}
