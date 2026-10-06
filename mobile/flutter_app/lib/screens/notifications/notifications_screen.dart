import 'package:flutter/material.dart';

import '../../app.dart';
import '../../core/api_exception.dart';
import '../../core/formatters.dart';
import '../../models/notifications.dart';
import '../../widgets/common.dart';

/// Notifications list, preferences and device registration.
///
/// Tapping a notification opens the screen its `deep_link`/`subject` refers to
/// (`DeepLinks.open`) and marks it read. The preferences screen writes the real
/// `PATCH /notifications/preferences` fields, and the push section states plainly
/// that push delivery needs a configured provider and a device token.
class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key});

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  int _tick = 0;
  bool _unreadOnly = false;

  Future<void> _refresh() async => setState(() => _tick++);

  Future<void> _markAllRead() async {
    try {
      await context.repos.notifications.markAllRead();
      await _refresh();
    } on ApiException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(error.userMessage)));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('notifications_title')),
        actions: [
          IconButton(
            tooltip: context.t('notification_preferences'),
            icon: const Icon(Icons.settings_outlined),
            onPressed: () async {
              await Navigator.of(context).push(
                MaterialPageRoute<void>(
                    builder: (_) => const NotificationPrefsScreen()),
              );
              await _refresh();
            },
          ),
          IconButton(
            tooltip: context.t('mark_all_read'),
            icon: const Icon(Icons.done_all),
            onPressed: _markAllRead,
          ),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: Row(
              children: [
                FilterChip(
                  label: Text(context.t('unread')),
                  selected: _unreadOnly,
                  onSelected: (value) => setState(() {
                    _unreadOnly = value;
                    _tick++;
                  }),
                ),
              ],
            ),
          ),
          Expanded(
            child: AsyncSection<NotificationPage>(
              refreshTick: _tick,
              load: () =>
                  context.repos.notifications.list(unreadOnly: _unreadOnly),
              isEmpty: (page) => page.items.isEmpty,
              emptyBuilder: (context, reload) => EmptyState(
                title: context.t('no_notifications'),
                icon: Icons.notifications_none,
              ),
              builder: (context, page, reload) => RefreshIndicator(
                onRefresh: reload,
                child: ListView.separated(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
                  itemCount: page.items.length + 1,
                  separatorBuilder: (_, __) => const SizedBox(height: 8),
                  itemBuilder: (context, index) {
                    if (index == page.items.length) {
                      return Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: Text(
                          '${page.total} ${context.t('results_count')} · ${page.unreadCount} ${context.t('unread')}',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      );
                    }
                    final notification = page.items[index];
                    return Card(
                      child: ListTile(
                        leading: Icon(_iconFor(notification.type)),
                        title: Text(
                          notification.title,
                          style: TextStyle(
                            fontWeight: notification.read
                                ? FontWeight.w400
                                : FontWeight.w700,
                          ),
                        ),
                        subtitle: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(notification.body),
                            const SizedBox(height: 4),
                            Text(
                              [
                                Fmt.relative(
                                  notification.createdAt,
                                  language: context.session.languageCode,
                                ),
                                Fmt.humanize(notification.type),
                                if (notification.pushError != null)
                                  'push failed',
                              ].join(' · '),
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                          ],
                        ),
                        isThreeLine: true,
                        onTap: () async {
                          if (!notification.read) {
                            try {
                              await context.repos.notifications
                                  .markRead(notification.id);
                            } on ApiException {
                              // Opening the target matters more than the flag.
                            }
                          }
                          if (!context.mounted) return;
                          DeepLinks.open(
                            context,
                            link: notification.deepLink,
                            subjectType: notification.subjectType,
                            subjectId: notification.subjectId,
                          );
                          await reload();
                        },
                        trailing: IconButton(
                          tooltip: context.t('delete'),
                          icon: const Icon(Icons.close, size: 18),
                          onPressed: () async {
                            await context.repos.notifications
                                .remove(notification.id);
                            await reload();
                          },
                        ),
                      ),
                    );
                  },
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  static IconData _iconFor(String type) => switch (type) {
        'weather_alert' => Icons.cloud_outlined,
        'market_update' => Icons.storefront_outlined,
        'crop_reminder' => Icons.alarm_outlined,
        'scheme_update' => Icons.account_balance_outlined,
        'ai_job_complete' => Icons.auto_awesome_outlined,
        'comment_reply' || 'mention' => Icons.mode_comment_outlined,
        'moderation_action' => Icons.gavel_outlined,
        _ => Icons.notifications_none,
      };
}

/// Notification preferences (`GET`/`PATCH /notifications/preferences`).
class NotificationPrefsScreen extends StatefulWidget {
  const NotificationPrefsScreen({super.key});

  @override
  State<NotificationPrefsScreen> createState() =>
      _NotificationPrefsScreenState();
}

class _NotificationPrefsScreenState extends State<NotificationPrefsScreen> {
  NotificationPreferences? _preferences;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    try {
      final preferences = await context.repos.notifications.preferences();
      if (mounted) setState(() => _preferences = preferences);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.userMessage);
    }
  }

  Future<void> _update(Map<String, dynamic> patch) async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final updated =
          await context.repos.notifications.updatePreferences(patch);
      if (mounted) setState(() => _preferences = updated);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.userMessage);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final preferences = _preferences;
    return Scaffold(
      appBar: AppBar(title: Text(context.t('notification_preferences'))),
      body: preferences == null
          ? Padding(
              padding: const EdgeInsets.all(16),
              child: _error != null
                  ? ErrorState(message: _error!, onRetry: _load)
                  : const LoadingState(),
            )
          : ListView(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
              children: [
                if (_error != null) ...[
                  Notice(kind: NoticeKind.danger, message: _error!),
                  const SizedBox(height: 12),
                ],
                SectionCard(
                  title: context.t('notification_preferences'),
                  child: Column(
                    children: [
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        value: preferences.inAppEnabled,
                        onChanged: _saving
                            ? null
                            : (value) => _update({'in_app_enabled': value}),
                        title: Text(context.t('pref_in_app')),
                      ),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        value: preferences.pushEnabled,
                        onChanged: _saving
                            ? null
                            : (value) => _update({'push_enabled': value}),
                        title: Text(context.t('pref_push')),
                      ),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        value: preferences.weatherAlerts,
                        onChanged: _saving
                            ? null
                            : (value) => _update({'weather_alerts': value}),
                        title: Text(context.t('pref_weather')),
                      ),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        value: preferences.marketUpdates,
                        onChanged: _saving
                            ? null
                            : (value) => _update({'market_updates': value}),
                        title: Text(context.t('pref_market')),
                      ),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        value: preferences.cropReminders,
                        onChanged: _saving
                            ? null
                            : (value) => _update({'crop_reminders': value}),
                        title: Text(context.t('pref_crop')),
                      ),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        value: preferences.communityActivity,
                        onChanged: _saving
                            ? null
                            : (value) => _update({'community_activity': value}),
                        title: Text(context.t('pref_community')),
                      ),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        value: preferences.schemeUpdates,
                        onChanged: _saving
                            ? null
                            : (value) => _update({'scheme_updates': value}),
                        title: Text(context.t('pref_schemes')),
                      ),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        value: preferences.aiJobUpdates,
                        onChanged: _saving
                            ? null
                            : (value) => _update({'ai_job_updates': value}),
                        title: Text(context.t('pref_ai')),
                      ),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        value: preferences.digestOnly,
                        onChanged: _saving
                            ? null
                            : (value) => _update({'digest_only': value}),
                        title: Text(context.t('pref_digest_only')),
                      ),
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        title: Text(context.t('max_per_day')),
                        trailing: DropdownButton<int>(
                          value: preferences.maxPerDay.clamp(1, 200),
                          items: const [5, 10, 20, 50, 100]
                              .map(
                                (value) => DropdownMenuItem(
                                    value: value, child: Text('$value')),
                              )
                              .toList(),
                          onChanged: _saving
                              ? null
                              : (value) => value == null
                                  ? null
                                  : _update({'max_per_day': value}),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 14),
                Notice(
                  kind: NoticeKind.warning,
                  title: context.t('pref_push'),
                  message: context.t('push_note'),
                ),
                const SizedBox(height: 14),
                SectionCard(
                  title: context.t('quiet_hours_start'),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Quiet hours prevent alerts at night. They are stored on the server as '
                        'HH:MM values and applied by the notification worker.',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                      const SizedBox(height: 8),
                      OutlinedButton(
                        onPressed: _saving
                            ? null
                            : () => _update({
                                  'quiet_hours_start': '22:00',
                                  'quiet_hours_end': '06:00'
                                }),
                        child: const Text('22:00 – 06:00'),
                      ),
                    ],
                  ),
                ),
              ],
            ),
    );
  }
}
