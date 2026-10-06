import 'package:flutter/material.dart';

import '../../app.dart';
import '../../core/api_exception.dart';
import '../../core/config.dart';
import '../../core/formatters.dart';
import '../../models/ai.dart';
import '../../widgets/common.dart';

/// About screen: what the app does, which providers are configured, and what is
/// explicitly *not* claimed.
///
/// The provider status is read live from `GET /weather/provider`,
/// `GET /markets/provider` and `GET /ai/health` where the caller is allowed to
/// see it, so this page cannot drift from the running configuration.
class AboutScreen extends StatefulWidget {
  const AboutScreen({super.key});

  @override
  State<AboutScreen> createState() => _AboutScreenState();
}

class _AboutScreenState extends State<AboutScreen> {
  Map<String, dynamic>? _weatherProvider;
  Map<String, dynamic>? _marketProvider;
  List<Map<String, dynamic>> _notices = const [];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadProviders());
  }

  Future<void> _loadProviders() async {
    // Captured before the first await: the provider calls outlive no widget tree.
    final repos = context.repos;
    final notices = <Map<String, dynamic>>[];
    Map<String, dynamic>? weather;
    Map<String, dynamic>? market;
    try {
      weather = await repos.weather.provider();
      if (weather['is_demo'] == true) {
        notices.add({
          'kind': 'demo',
          'text':
              'Weather uses the ${weather['provider']} provider: values are development data, '
                  'not a real forecast. Configure WEATHER_PROVIDER for live data.',
        });
      }
    } on ApiException {
      weather = null;
    }
    try {
      market = await repos.markets.provider();
      if (market['is_demo'] == true) {
        notices.add({
          'kind': 'demo',
          'text':
              'Market prices use the ${market['provider']} provider: rows are development data. '
                  'Configure MARKET_PROVIDER for live mandi data.',
        });
      }
    } on ApiException {
      market = null;
    }
    try {
      final health = await repos.ai.aiHealth();
      for (final entry in (health.entries)) {
        if (entry.value is Map && (entry.value as Map)['is_demo'] == true) {
          notices.add({
            'kind': 'demo',
            'text':
                'AI provider "${entry.key}" is running in demonstration mode '
                    '(${(entry.value as Map)['provider']}).',
          });
        }
      }
    } on ApiException {
      // /ai/health is staff-only; a normal account cannot read it.
    }
    if (!mounted) return;
    setState(() {
      _weatherProvider = weather;
      _marketProvider = market;
      _notices = notices;
    });
  }

  @override
  Widget build(BuildContext context) {
    final languageCode = context.session.languageCode;
    return Scaffold(
      appBar: AppBar(title: Text(context.t('about_app'))),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
        children: [
          SectionCard(
            title: AppConfig.appName,
            subtitle: '${context.t('version_label')} ${AppConfig.appVersion}',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(context.t('about_body')),
                const SizedBox(height: 10),
                InfoRow(
                    label: context.t('api_base_url'),
                    value: context.session.api.baseUrl),
                InfoRow(
                  label: 'Package id',
                  value: 'com.digitalvillage.digital_village_app',
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),
          SectionCard(
            title: context.t('more_data_sources'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (_weatherProvider != null)
                  InfoRow(
                    label: context.t('weather_provider'),
                    value:
                        '${_weatherProvider!['provider']}${_weatherProvider!['is_demo'] == true ? ' (${context.t('demo_provider')})' : ''}',
                  ),
                if (_marketProvider != null)
                  InfoRow(
                    label: context.t('market_provider'),
                    value:
                        '${_marketProvider!['provider']}${_marketProvider!['is_demo'] == true ? ' (${context.t('demo_provider')})' : ''}',
                  ),
                InfoRow(
                  label: 'Knowledge base',
                  value: 'Platform documents with source names and links',
                ),
                InfoRow(
                  label: 'Community',
                  value: 'Posts written by registered users',
                ),
                InfoRow(
                    label: 'Schemes',
                    value: 'Official sources, link on every scheme'),
              ],
            ),
          ),
          if (_notices.isNotEmpty) ...[
            const SizedBox(height: 14),
            Notice(
              kind: NoticeKind.demo,
              title: context.t('limitations_title'),
              message: _notices.first['text'] as String,
              items: _notices
                  .skip(1)
                  .map((notice) => notice['text'] as String)
                  .toList(),
            ),
          ],
          const SizedBox(height: 14),
          SectionCard(
            title: context.t('limitations_title'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(context.t('limitations_body')),
                const SizedBox(height: 10),
                Text(
                  context.t('rule_based_note'),
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),
          SectionCard(
            title: context.t('ai_models'),
            child: AsyncSection<ModelRegistry>(
              load: () => context.repos.ai.models(),
              padding: EdgeInsets.zero,
              builder: (context, registry, reload) => Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  ...registry.models.map(
                    (model) => InfoRow(
                      label: model.displayName ?? model.name,
                      value: [
                        model.version,
                        Fmt.humanize(model.stage),
                        if (!model.installedOnDisk) 'not installed',
                      ].join(' · '),
                    ),
                  ),
                  if (registry.registryNote != null) ...[
                    const SizedBox(height: 8),
                    Text(
                      registry.registryNote!,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color:
                                Theme.of(context).colorScheme.onSurfaceVariant,
                          ),
                    ),
                  ],
                ],
              ),
            ),
          ),
          const SizedBox(height: 14),
          SectionCard(
            title: 'Legal',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(context.t('policy_placeholder')),
                const SizedBox(height: 10),
                InfoRow(label: context.t('privacy_policy'), value: '—'),
                InfoRow(label: context.t('terms_of_service'), value: '—'),
                const SizedBox(height: 8),
                Text(
                  'Language: ${switch (languageCode) {
                    'mr' => 'मराठी',
                    'hi' => 'हिंदी',
                    _ => 'English',
                  }}',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
