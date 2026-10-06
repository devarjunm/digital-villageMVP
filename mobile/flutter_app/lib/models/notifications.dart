import 'json_utils.dart';

class AppNotification {
  const AppNotification({
    required this.id,
    required this.type,
    required this.title,
    required this.body,
    required this.language,
    required this.read,
    this.subjectType,
    this.subjectId,
    this.deepLink,
    this.payload = const {},
    this.readAt,
    this.pushSentAt,
    this.pushError,
    this.createdAt,
  });

  factory AppNotification.fromJson(Map<String, dynamic> json) =>
      AppNotification(
        id: requiredId(json['id'], 'notification'),
        type: asString(json['type'], fallback: 'system'),
        title: asString(json['title']),
        body: asString(json['body']),
        language: asString(json['language'], fallback: 'en'),
        read: asBool(json['read']),
        subjectType: asStringOrNull(json['subject_type']),
        subjectId: asStringOrNull(json['subject_id']),
        deepLink: asStringOrNull(json['deep_link']),
        payload: asMap(json['payload']),
        readAt: asDateTimeOrNull(json['read_at']),
        pushSentAt: asDateTimeOrNull(json['push_sent_at']),
        pushError: asStringOrNull(json['push_error']),
        createdAt: asDateTimeOrNull(json['created_at']),
      );

  final String id;
  final String type;
  final String title;
  final String body;
  final String language;
  final bool read;
  final String? subjectType;
  final String? subjectId;
  final String? deepLink;
  final Map<String, dynamic> payload;
  final DateTime? readAt;
  final DateTime? pushSentAt;
  final String? pushError;
  final DateTime? createdAt;

  String get key => '$id:$read';
}

class NotificationPage {
  const NotificationPage({
    required this.items,
    required this.page,
    required this.pageSize,
    required this.total,
    required this.totalPages,
    required this.hasNext,
    required this.unreadCount,
  });

  factory NotificationPage.fromJson(Map<String, dynamic> json) =>
      NotificationPage(
        items: asMapList(json['items']).map(AppNotification.fromJson).toList(),
        page: asInt(json['page'], fallback: 1),
        pageSize: asInt(json['page_size'], fallback: 20),
        total: asInt(json['total']),
        totalPages: asInt(json['total_pages'], fallback: 1),
        hasNext: asBool(json['has_next']),
        unreadCount: asInt(json['unread_count']),
      );

  final List<AppNotification> items;
  final int page;
  final int pageSize;
  final int total;
  final int totalPages;
  final bool hasNext;
  final int unreadCount;
}

/// `GET /notifications/preferences`.
class NotificationPreferences {
  const NotificationPreferences({
    required this.inAppEnabled,
    required this.pushEnabled,
    required this.weatherAlerts,
    required this.marketUpdates,
    required this.cropReminders,
    required this.communityActivity,
    required this.schemeUpdates,
    required this.aiJobUpdates,
    required this.digestOnly,
    required this.maxPerDay,
    this.quietHoursStart,
    this.quietHoursEnd,
  });

  factory NotificationPreferences.fromJson(Map<String, dynamic> json) =>
      NotificationPreferences(
        inAppEnabled: asBool(json['in_app_enabled'], fallback: true),
        pushEnabled: asBool(json['push_enabled']),
        weatherAlerts: asBool(json['weather_alerts'], fallback: true),
        marketUpdates: asBool(json['market_updates'], fallback: true),
        cropReminders: asBool(json['crop_reminders'], fallback: true),
        communityActivity: asBool(json['community_activity'], fallback: true),
        schemeUpdates: asBool(json['scheme_updates']),
        aiJobUpdates: asBool(json['ai_job_updates'], fallback: true),
        digestOnly: asBool(json['digest_only']),
        maxPerDay: asInt(json['max_per_day'], fallback: 20),
        quietHoursStart: asStringOrNull(json['quiet_hours_start']),
        quietHoursEnd: asStringOrNull(json['quiet_hours_end']),
      );

  final bool inAppEnabled;
  final bool pushEnabled;
  final bool weatherAlerts;
  final bool marketUpdates;
  final bool cropReminders;
  final bool communityActivity;
  final bool schemeUpdates;
  final bool aiJobUpdates;
  final bool digestOnly;
  final int maxPerDay;
  final String? quietHoursStart;
  final String? quietHoursEnd;
}

/// `GET /notifications/unread-count`.
class UnreadCount {
  const UnreadCount({
    required this.unreadCount,
    this.maxPerDay,
    this.createdLast24h,
  });

  factory UnreadCount.fromJson(Map<String, dynamic> json) => UnreadCount(
        unreadCount: asInt(json['unread_count']),
        maxPerDay: asIntOrNull(json['max_per_day']),
        createdLast24h: asIntOrNull(json['created_last_24h']),
      );

  final int unreadCount;
  final int? maxPerDay;
  final int? createdLast24h;
}
