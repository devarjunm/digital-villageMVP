import 'package:flutter/material.dart';

import '../../app.dart';
import '../../core/config.dart';
import '../../core/formatters.dart';
import '../../models/weather.dart';
import '../../widgets/common.dart';
import 'home_shell.dart';

/// The "More" tab: remaining modules plus the account summary.
///
/// Each row leads to a screen backed by real endpoints. The weather summary is
/// fetched live for the saved profile location, and shows the provider and the
/// demo flag from the response rather than a hard-coded label.
class MoreScreen extends StatefulWidget {
  const MoreScreen(
      {super.key, required this.unreadCount, required this.onUnreadChanged});

  final int unreadCount;
  final Future<void> Function() onUnreadChanged;

  @override
  State<MoreScreen> createState() => _MoreScreenState();
}

class _MoreScreenState extends State<MoreScreen> {
  WeatherNow? _weather;
  bool _loadingWeather = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadWeather());
  }

  Future<void> _loadWeather() async {
    final session = context.session;
    final repos = context.repos;
    if (!session.isSignedIn) {
      setState(() => _loadingWeather = false);
      return;
    }
    try {
      final profile = session.profile ?? await repos.farmer.me();
      final weather = await repos.weather.current(
        latitude: profile.latitude,
        longitude: profile.longitude,
      );
      if (!mounted) return;
      setState(() {
        _weather = weather;
        _loadingWeather = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loadingWeather = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = context.session;
    final user = session.user;

    return EmbeddedScreenScaffold(
      title: context.t('nav_more'),
      onRefresh: _loadWeather,
      actions: [
        IconButton(
          tooltip: context.t('notifications_title'),
          icon: Badge(
            isLabelVisible: widget.unreadCount > 0,
            label: Text('${widget.unreadCount}'),
            child: const Icon(Icons.notifications_outlined),
          ),
          onPressed: () async {
            await Navigator.of(context).pushNamed(Routes.notifications);
            await widget.onUnreadChanged();
          },
        ),
      ],
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
        children: [
          Card(
            child: ListTile(
              leading: CircleAvatar(
                child: Text(
                  (user?.fullName.isNotEmpty ?? false)
                      ? user!.fullName.characters.first.toUpperCase()
                      : '?',
                ),
              ),
              title: Text(user?.fullName ?? context.t('sign_in')),
              subtitle: Text(
                [
                  if (user != null) Fmt.humanize(user.primaryRole),
                  if (user?.phoneMasked != null) user!.phoneMasked!,
                  if (session.profile?.placeLabel != null)
                    session.profile!.placeLabel,
                ].join(' · '),
              ),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context).pushNamed(Routes.profile),
            ),
          ),
          const SizedBox(height: 14),
          SectionCard(
            title: context.t('weather_title'),
            trailing: TextButton(
              onPressed: () => Navigator.of(context).pushNamed(Routes.weather),
              child: Text(context.t('view_all')),
            ),
            child: _loadingWeather
                ? const Padding(
                    padding: EdgeInsets.symmetric(vertical: 12),
                    child: LoadingState(),
                  )
                : _weather == null
                    ? Text(context.t('not_available'),
                        style: Theme.of(context).textTheme.bodySmall)
                    : Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Text(
                                Fmt.temp(_weather!.temperatureC),
                                style: Theme.of(context)
                                    .textTheme
                                    .headlineSmall
                                    ?.copyWith(
                                      fontWeight: FontWeight.w700,
                                    ),
                              ),
                              const SizedBox(width: 10),
                              Expanded(
                                child: Text(
                                  _weather!.conditionText ??
                                      Fmt.humanize(_weather!.conditionCode),
                                  style: Theme.of(context).textTheme.bodyMedium,
                                ),
                              ),
                              if (_weather!.isDemo) const DemoChip(),
                            ],
                          ),
                          const SizedBox(height: 6),
                          Text(
                            [
                              '${context.t('humidity')}: ${Fmt.percent(_weather!.humidityPercent, decimals: 0)}',
                              '${context.t('rainfall')}: ${Fmt.mm(_weather!.rainfallMm)}',
                              '${context.t('wind')}: ${Fmt.wind(_weather!.windSpeedKmh)}',
                            ].join(' · '),
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                          if (_weather!.farmingNote != null) ...[
                            const SizedBox(height: 8),
                            Notice(
                                kind: NoticeKind.info,
                                message: _weather!.farmingNote!),
                          ],
                        ],
                      ),
          ),
          const SizedBox(height: 14),
          _MenuTile(
            icon: Icons.storefront_outlined,
            title: context.t('more_markets'),
            subtitle: context.t('prices'),
            route: Routes.markets,
          ),
          _MenuTile(
            icon: Icons.cloud_outlined,
            title: context.t('more_weather'),
            subtitle: context.t('forecast'),
            route: Routes.weather,
          ),
          _MenuTile(
            icon: Icons.account_balance_outlined,
            title: context.t('more_schemes'),
            subtitle: context.t('eligibility'),
            route: Routes.schemes,
          ),
          _MenuTile(
            icon: Icons.search,
            title: context.t('more_search'),
            subtitle: context.t('search_hint'),
            route: Routes.search,
          ),
          _MenuTile(
            icon: Icons.notifications_outlined,
            title: context.t('notifications_title'),
            subtitle: widget.unreadCount > 0
                ? '${widget.unreadCount} ${context.t('unread')}'
                : context.t('no_notifications'),
            onTap: () async {
              await Navigator.of(context).pushNamed(Routes.notifications);
              await widget.onUnreadChanged();
            },
          ),
          _MenuTile(
            icon: Icons.question_answer_outlined,
            title: context.t('more_assistant'),
            subtitle: context.t('assistant_hint'),
            route: Routes.assistant,
          ),
          _MenuTile(
            icon: Icons.person_outline,
            title: context.t('more_profile'),
            subtitle: context.t('more_data_sources'),
            route: Routes.profile,
          ),
          _MenuTile(
            icon: Icons.info_outline,
            title: context.t('more_about'),
            subtitle: 'v${AppConfig.appVersion}',
            route: Routes.about,
          ),
          const SizedBox(height: 16),
          if (session.isSignedIn)
            OutlinedButton.icon(
              onPressed: () async {
                await session.signOut();
                if (context.mounted) {
                  Navigator.of(context)
                      .pushNamedAndRemoveUntil(Routes.auth, (route) => false);
                }
              },
              icon: const Icon(Icons.logout, size: 18),
              label: Text(context.t('sign_out')),
            ),
        ],
      ),
    );
  }
}

class _MenuTile extends StatelessWidget {
  const _MenuTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    this.route,
    this.onTap,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final String? route;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Card(
        child: ListTile(
          leading: Icon(icon),
          title: Text(title),
          subtitle: Text(
            subtitle,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.bodySmall,
          ),
          trailing: const Icon(Icons.chevron_right),
          onTap: onTap ??
              (route == null
                  ? null
                  : () => Navigator.of(context).pushNamed(route!)),
        ),
      ),
    );
  }
}
