import 'json_utils.dart';

class AuthorBrief {
  const AuthorBrief({
    required this.id,
    required this.displayName,
    required this.primaryRole,
    this.village,
    this.district,
    this.state,
    this.verifiedExpert = false,
    this.isFollowing = false,
  });

  factory AuthorBrief.fromJson(Map<String, dynamic> json) => AuthorBrief(
        id: asString(json['id']),
        displayName: asString(json['display_name'], fallback: 'Farmer'),
        primaryRole: asString(json['primary_role'], fallback: 'farmer'),
        village: asStringOrNull(json['village']),
        district: asStringOrNull(json['district']),
        state: asStringOrNull(json['state']),
        verifiedExpert: asBool(json['verified_expert']),
        isFollowing: asBool(json['is_following']),
      );

  final String id;
  final String displayName;
  final String primaryRole;
  final String? village;
  final String? district;
  final String? state;
  final bool verifiedExpert;
  final bool isFollowing;
}

class MediaBrief {
  const MediaBrief({
    required this.id,
    required this.mimeType,
    this.url,
    this.width,
    this.height,
  });

  factory MediaBrief.fromJson(Map<String, dynamic> json) => MediaBrief(
        id: asString(json['id']),
        mimeType: asString(json['mime_type'], fallback: 'image/jpeg'),
        url: asStringOrNull(json['url']),
        width: asIntOrNull(json['width']),
        height: asIntOrNull(json['height']),
      );

  final String id;
  final String mimeType;
  final String? url;
  final int? width;
  final int? height;
}

class Engagement {
  const Engagement({
    required this.reactionCount,
    required this.commentCount,
    this.saveCount = 0,
    this.viewCount = 0,
    this.note,
  });

  factory Engagement.fromJson(Map<String, dynamic> json) => Engagement(
        reactionCount: asInt(json['reaction_count']),
        commentCount: asInt(json['comment_count']),
        saveCount: asInt(json['save_count']),
        viewCount: asInt(json['view_count']),
        note: asStringOrNull(json['note']),
      );

  final int reactionCount;
  final int commentCount;
  final int saveCount;
  final int viewCount;
  final String? note;
}

/// A community post (`GET /community/feed`, `GET /community/posts/{id}`).
///
/// [trustLabel] and [trustReasons] are produced by the backend and are shown
/// as-is: the app never upgrades a farmer's experience to "expert information"
/// and never hides the reason a label was applied.
class CommunityPost {
  const CommunityPost({
    required this.id,
    required this.title,
    required this.body,
    required this.category,
    required this.language,
    required this.author,
    required this.trustLabel,
    required this.status,
    this.cropCode,
    this.state,
    this.district,
    this.village,
    this.media = const [],
    this.sourceUrls = const [],
    this.trustReasons = const [],
    this.engagement = const Engagement(reactionCount: 0, commentCount: 0),
    this.reactionCount = 0,
    this.commentCount = 0,
    this.saveCount = 0,
    this.viewCount = 0,
    this.myReaction,
    this.isSaved = false,
    this.isDemo = false,
    this.createdAt,
    this.updatedAt,
  });

  factory CommunityPost.fromJson(Map<String, dynamic> json) => CommunityPost(
        id: requiredId(json['id'], 'post'),
        title: asString(json['title']),
        body: asString(json['body']),
        category: asString(json['category'], fallback: 'general'),
        language: asString(json['language'], fallback: 'en'),
        author: AuthorBrief.fromJson(asMap(json['author'])),
        trustLabel:
            asString(json['trust_label'], fallback: 'farmer_experience'),
        status: asString(json['status'], fallback: 'published'),
        cropCode: asStringOrNull(json['crop_code']),
        state: asStringOrNull(json['state']),
        district: asStringOrNull(json['district']),
        village: asStringOrNull(json['village']),
        media: asMapList(json['media']).map(MediaBrief.fromJson).toList(),
        sourceUrls: asStringList(json['source_urls']),
        trustReasons: asStringList(json['trust_reasons']),
        engagement: Engagement.fromJson(asMap(json['engagement'])),
        reactionCount: asInt(json['reaction_count']),
        commentCount: asInt(json['comment_count']),
        saveCount: asInt(json['save_count']),
        viewCount: asInt(json['view_count']),
        myReaction: asStringOrNull(json['my_reaction']),
        isSaved: asBool(json['is_saved']),
        isDemo: asBool(json['is_demo']),
        createdAt: asDateTimeOrNull(json['created_at']),
        updatedAt: asDateTimeOrNull(json['updated_at']),
      );

  final String id;
  final String title;
  final String body;
  final String category;
  final String language;
  final AuthorBrief author;
  final String trustLabel;
  final String status;
  final String? cropCode;
  final String? state;
  final String? district;
  final String? village;
  final List<MediaBrief> media;
  final List<String> sourceUrls;
  final List<String> trustReasons;
  final Engagement engagement;
  final int reactionCount;
  final int commentCount;
  final int saveCount;
  final int viewCount;
  final String? myReaction;
  final bool isSaved;
  final bool isDemo;
  final DateTime? createdAt;
  final DateTime? updatedAt;
}

class Comment {
  const Comment({
    required this.id,
    required this.postId,
    required this.body,
    required this.author,
    required this.trustLabel,
    required this.status,
    this.parentId,
    this.reactionCount = 0,
    this.reportCount = 0,
    this.createdAt,
    this.myReaction,
    this.replies = const [],
    this.isDemo = false,
  });

  factory Comment.fromJson(Map<String, dynamic> json) => Comment(
        id: requiredId(json['id'], 'comment'),
        postId: asString(json['post_id']),
        body: asString(json['body']),
        author: AuthorBrief.fromJson(asMap(json['author'])),
        trustLabel:
            asString(json['trust_label'], fallback: 'farmer_experience'),
        status: asString(json['status'], fallback: 'published'),
        parentId: asStringOrNull(json['parent_id']),
        reactionCount: asInt(json['reaction_count']),
        reportCount: asInt(json['report_count']),
        createdAt: asDateTimeOrNull(json['created_at']),
        myReaction: asStringOrNull(json['my_reaction']),
        replies: asMapList(json['replies']).map(Comment.fromJson).toList(),
        isDemo: asBool(json['is_demo']),
      );

  final String id;
  final String postId;
  final String body;
  final AuthorBrief author;
  final String trustLabel;
  final String status;
  final String? parentId;
  final int reactionCount;
  final int reportCount;
  final DateTime? createdAt;
  final String? myReaction;
  final List<Comment> replies;
  final bool isDemo;
}

/// The feed's ranking disclosure (`ranking` object of `GET /community/feed`).
///
/// The app shows this so a farmer can see *why* posts are ordered this way, and
/// so nobody mistakes ranking for endorsement.
class FeedRanking {
  const FeedRanking({
    required this.method,
    required this.isMlModel,
    required this.weights,
    required this.activeTerms,
    this.note,
    this.recencyHalfLifeHours,
    this.personalisationSignals,
  });

  factory FeedRanking.fromJson(Map<String, dynamic> json) => FeedRanking(
        method: asString(json['method'], fallback: 'unknown'),
        isMlModel: asBool(json['is_ml_model']),
        weights: asMap(json['weights']).map((k, v) => MapEntry(k, asDouble(v))),
        activeTerms: asStringList(json['active_terms']),
        note: asStringOrNull(json['note']),
        recencyHalfLifeHours: asDoubleOrNull(json['recency_half_life_hours']),
        personalisationSignals: json['personalisation_signals'] == null
            ? null
            : asMap(json['personalisation_signals']),
      );

  final String method;
  final bool isMlModel;
  final Map<String, double> weights;
  final List<String> activeTerms;
  final String? note;
  final double? recencyHalfLifeHours;
  final Map<String, dynamic>? personalisationSignals;
}

class PostPage {
  const PostPage({
    required this.items,
    required this.page,
    required this.pageSize,
    required this.total,
    required this.totalPages,
    required this.hasNext,
    this.ranking,
  });

  factory PostPage.fromJson(Map<String, dynamic> json) => PostPage(
        items: asMapList(json['items']).map(CommunityPost.fromJson).toList(),
        page: asInt(json['page'], fallback: 1),
        pageSize: asInt(json['page_size'], fallback: 20),
        total: asInt(json['total']),
        totalPages: asInt(json['total_pages'], fallback: 1),
        hasNext: asBool(json['has_next']),
        ranking: json['ranking'] == null
            ? null
            : FeedRanking.fromJson(asMap(json['ranking'])),
      );

  final List<CommunityPost> items;
  final int page;
  final int pageSize;
  final int total;
  final int totalPages;
  final bool hasNext;
  final FeedRanking? ranking;
}

/// One option of `GET /community/meta` (category, reaction kind, report reason).
class MetaOption {
  const MetaOption(
      {required this.value, required this.label, this.description});

  factory MetaOption.fromJson(Map<String, dynamic> json) => MetaOption(
        value: asString(json['value']),
        label: asString(json['label_en'], fallback: asString(json['value'])),
        description: asStringOrNull(json['description']),
      );

  final String value;
  final String label;
  final String? description;
}

/// `GET /community/meta` — the vocabulary the UI must use instead of hard-coding
/// its own category or report-reason lists.
class CommunityMeta {
  const CommunityMeta({
    required this.categories,
    required this.reactionKinds,
    required this.reportReasons,
    required this.trustLabels,
    required this.notes,
    this.whatTrustLabelsMean,
  });

  factory CommunityMeta.fromJson(Map<String, dynamic> json) => CommunityMeta(
        categories:
            asMapList(json['categories']).map(MetaOption.fromJson).toList(),
        reactionKinds: asStringList(json['reaction_kinds']),
        reportReasons: asStringList(json['report_reasons']),
        trustLabels:
            asMapList(json['trust_labels']).map(MetaOption.fromJson).toList(),
        notes: asStringList(json['notes']),
        whatTrustLabelsMean: asStringOrNull(json['what_trust_labels_mean']),
      );

  final List<MetaOption> categories;
  final List<String> reactionKinds;
  final List<String> reportReasons;
  final List<MetaOption> trustLabels;
  final List<String> notes;
  final String? whatTrustLabelsMean;
}
