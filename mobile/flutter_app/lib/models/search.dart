import 'json_utils.dart';

/// One hit of `GET /search`.
///
/// `method` says whether the hit came from keyword matching, semantic search or
/// the hybrid fusion, and `trustLabel` carries the same trust vocabulary as the
/// community feed — so a search result is never shown without its provenance.
class SearchHit {
  const SearchHit({
    required this.sourceType,
    required this.id,
    required this.title,
    this.snippet,
    this.language,
    this.category,
    this.trustLabel,
    this.cropCode,
    this.state,
    this.reactionCount = 0,
    this.commentCount = 0,
    this.isDemo = false,
    this.score,
    this.method,
  });

  factory SearchHit.fromJson(Map<String, dynamic> json) => SearchHit(
        sourceType: asString(json['source_type'], fallback: 'unknown'),
        id: asString(json['id']),
        title: asString(json['title']),
        snippet: asStringOrNull(json['snippet']),
        language: asStringOrNull(json['language']),
        category: asStringOrNull(json['category']),
        trustLabel: asStringOrNull(json['trust_label']),
        cropCode: asStringOrNull(json['crop_code']),
        state: asStringOrNull(json['state']),
        reactionCount: asInt(json['reaction_count']),
        commentCount: asInt(json['comment_count']),
        isDemo: asBool(json['is_demo']),
        score: asDoubleOrNull(json['score']),
        method: asStringOrNull(json['method']),
      );

  final String sourceType;
  final String id;
  final String title;
  final String? snippet;
  final String? language;
  final String? category;
  final String? trustLabel;
  final String? cropCode;
  final String? state;
  final int reactionCount;
  final int commentCount;
  final bool isDemo;
  final double? score;
  final String? method;
}

class SearchCounts {
  const SearchCounts({
    required this.total,
    required this.keywordCandidates,
    required this.semanticCandidates,
    this.byType = const {},
  });

  factory SearchCounts.fromJson(Map<String, dynamic> json) => SearchCounts(
        total: asInt(json['total']),
        keywordCandidates: asInt(json['keyword_candidates']),
        semanticCandidates: asInt(json['semantic_candidates']),
        byType: asMap(json['by_type']).map((k, v) => MapEntry(k, asInt(v))),
      );

  final int total;
  final int keywordCandidates;
  final int semanticCandidates;
  final Map<String, int> byType;
}

/// `GET /search` response, including the notices that explain an empty result
/// set and the mode/method used.
class SearchResults {
  const SearchResults({
    required this.query,
    required this.mode,
    required this.method,
    required this.items,
    required this.counts,
    required this.notices,
    required this.warnings,
    this.language,
    this.embeddingIsDemo = false,
    this.latencyMs,
  });

  factory SearchResults.fromJson(Map<String, dynamic> json) => SearchResults(
        query: asString(json['query']),
        mode: asString(json['mode'], fallback: 'keyword'),
        method: asString(json['method']),
        items: asMapList(json['items']).map(SearchHit.fromJson).toList(),
        counts: SearchCounts.fromJson(asMap(json['counts'])),
        notices: asStringList(json['notices']),
        warnings: asStringList(json['warnings']),
        language: asStringOrNull(json['language']),
        embeddingIsDemo: asBool(asMap(json['semantic'])['embedding_is_demo']),
        latencyMs: asIntOrNull(json['latency_ms']),
      );

  final String query;
  final String mode;
  final String method;
  final List<SearchHit> items;
  final SearchCounts counts;
  final List<String> notices;
  final List<String> warnings;
  final String? language;
  final bool embeddingIsDemo;
  final int? latencyMs;

  bool get isEmpty => items.isEmpty;
}
