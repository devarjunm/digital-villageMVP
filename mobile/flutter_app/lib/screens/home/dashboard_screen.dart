import 'package:flutter/material.dart';

import '../../app.dart';
import '../../core/formatters.dart';
import '../../models/identity.dart';
import '../../widgets/common.dart';
import 'home_shell.dart';

/// Home screen: `GET /farmers/me/dashboard`.
///
/// Everything here is real: farm counts come from the database, the freshness
/// note is the backend's own sentence about when the profile was last updated,
/// and the reminder list is empty when there is genuinely nothing to remind.
class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  int _tick = 0;

  Future<void> _refresh() async {
    setState(() => _tick++);
    await context.session.refreshProfile();
  }

  @override
  Widget build(BuildContext context) {
    final session = context.session;
    final name = session.profile?.displayName ?? session.user?.fullName ?? '';

    return EmbeddedScreenScaffold(
      title: context.t('dashboard_title'),
      onRefresh: _refresh,
      actions: [
        IconButton(
          tooltip: context.t('search_everything'),
          icon: const Icon(Icons.search),
          onPressed: () => Navigator.of(context).pushNamed(Routes.search),
        ),
        IconButton(
          tooltip: context.t('notifications_title'),
          icon: const Icon(Icons.notifications_outlined),
          onPressed: () =>
              Navigator.of(context).pushNamed(Routes.notifications),
        ),
      ],
      child: AsyncSection<FarmerDashboard>(
        refreshTick: _tick,
        load: () => context.repos.farmer.dashboard(),
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
        builder: (context, dashboard, reload) {
          final profile = dashboard.profile;
          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
            children: [
              Text(
                '${context.t('welcome_back')}, ${name.isEmpty ? profile.displayName : name}',
                style: Theme.of(context).textTheme.titleLarge?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
              ),
              const SizedBox(height: 2),
              Text(
                profile.placeLabel,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
              const SizedBox(height: 16),
              if (profile.profileCompleteness < 100) ...[
                SectionCard(
                  title: context.t('complete_profile'),
                  subtitle: context.t('complete_profile_hint'),
                  trailing: Text(
                    '${profile.profileCompleteness}%',
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      ClipRRect(
                        borderRadius: BorderRadius.circular(6),
                        child: LinearProgressIndicator(
                          value: profile.profileCompleteness / 100,
                          minHeight: 8,
                        ),
                      ),
                      const SizedBox(height: 12),
                      OutlinedButton.icon(
                        onPressed: () =>
                            Navigator.of(context).pushNamed(Routes.profile),
                        icon: const Icon(Icons.edit_outlined, size: 18),
                        label: Text(context.t('edit_profile')),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 14),
              ],
              SectionCard(
                title: context.t('land_summary'),
                child: Column(
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: StatTile(
                            label: context.t('total_farms'),
                            value: '${dashboard.landSummary.totalFarms}',
                            icon: Icons.grass_outlined,
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: StatTile(
                            label: context.t('total_area'),
                            value: Fmt.hectares(
                                dashboard.landSummary.totalAreaHectares),
                            hint:
                                '${Fmt.number(dashboard.landSummary.totalAreaAcres, decimals: 2)} acre',
                            icon: Icons.straighten,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    Row(
                      children: [
                        Expanded(
                          child: StatTile(
                            label: context.t('active_crops'),
                            value: '${dashboard.landSummary.activeCropCount}',
                            icon: Icons.eco_outlined,
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: StatTile(
                            label: context.t('harvested_crops'),
                            value:
                                '${dashboard.landSummary.harvestedCropCount}',
                            icon: Icons.inventory_2_outlined,
                          ),
                        ),
                      ],
                    ),
                    if (dashboard.cropStageCounts.isNotEmpty) ...[
                      const SizedBox(height: 14),
                      Align(
                        alignment: Alignment.centerLeft,
                        child: Text(
                          context.t('crop_stage_counts'),
                          style: Theme.of(context).textTheme.labelLarge,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: dashboard.cropStageCounts.entries
                            .map(
                              (entry) => MetaPill(
                                text:
                                    '${Fmt.humanize(entry.key)}: ${entry.value}',
                              ),
                            )
                            .toList(),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: 14),
              SectionCard(
                title: context.t('active_crops'),
                trailing: TextButton(
                  onPressed: () =>
                      Navigator.of(context).pushNamed(Routes.farms),
                  child: Text(context.t('view_all')),
                ),
                child: dashboard.activeCrops.isEmpty
                    ? Padding(
                        padding: const EdgeInsets.symmetric(vertical: 8),
                        child: Text(
                          context.t('no_active_crops'),
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      )
                    : Column(
                        children: dashboard.activeCrops
                            .map(
                              (crop) => _ActiveCropTile(
                                crop: crop,
                                onTap: () => Navigator.of(context).push(
                                  Routes.farm(crop.farmId),
                                ),
                              ),
                            )
                            .toList(),
                      ),
              ),
              const SizedBox(height: 14),
              SectionCard(
                title: context.t('reminders'),
                child: dashboard.reminders.isEmpty
                    ? Padding(
                        padding: const EdgeInsets.symmetric(vertical: 8),
                        child: Text(
                          context.t('no_reminders'),
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      )
                    : Column(
                        children: dashboard.reminders
                            .map(
                              (reminder) => ListTile(
                                dense: true,
                                contentPadding: EdgeInsets.zero,
                                leading:
                                    const Icon(Icons.alarm_outlined, size: 18),
                                title: Text(reminder.title),
                                subtitle: reminder.body == null
                                    ? null
                                    : Text(reminder.body!),
                                trailing: reminder.dueOn == null
                                    ? null
                                    : Text(
                                        Fmt.date(reminder.dueOn),
                                        style: Theme.of(context)
                                            .textTheme
                                            .bodySmall,
                                      ),
                              ),
                            )
                            .toList(),
                      ),
              ),
              const SizedBox(height: 14),
              SectionCard(
                title: context.t('quick_actions'),
                child: Column(
                  children: [
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        ActionChip(
                          avatar:
                              const Icon(Icons.auto_awesome_outlined, size: 16),
                          label: Text(context.t('ask_ai')),
                          onPressed: () =>
                              Navigator.of(context).pushNamed(Routes.assistant),
                        ),
                        ActionChip(
                          avatar: const Icon(Icons.eco_outlined, size: 16),
                          label: Text(context.t('crop_recommendation')),
                          onPressed: () => Navigator.of(context)
                              .pushNamed(Routes.cropRecommendation),
                        ),
                        ActionChip(
                          avatar:
                              const Icon(Icons.storefront_outlined, size: 16),
                          label: Text(context.t('more_markets')),
                          onPressed: () =>
                              Navigator.of(context).pushNamed(Routes.markets),
                        ),
                        ActionChip(
                          avatar: const Icon(Icons.cloud_outlined, size: 16),
                          label: Text(context.t('more_weather')),
                          onPressed: () =>
                              Navigator.of(context).pushNamed(Routes.weather),
                        ),
                        ActionChip(
                          avatar: const Icon(Icons.account_balance_outlined,
                              size: 16),
                          label: Text(context.t('more_schemes')),
                          onPressed: () =>
                              Navigator.of(context).pushNamed(Routes.schemes),
                        ),
                        ActionChip(
                          avatar: const Icon(Icons.forum_outlined, size: 16),
                          label: Text(context.t('nav_community')),
                          onPressed: () =>
                              Navigator.of(context).pushNamed(Routes.community),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 14),
              SectionCard(
                title: context.t('data_freshness'),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      dashboard.dataFreshness.note,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                    const SizedBox(height: 8),
                    InfoRow(
                      label: context.t('member_since'),
                      value: Fmt.dateTime(
                          dashboard.dataFreshness.profileUpdatedAt),
                    ),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _ActiveCropTile extends StatelessWidget {
  const _ActiveCropTile({required this.crop, required this.onTap});

  final ActiveCrop crop;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final days = crop.daysToExpectedHarvest;
    return ListTile(
      dense: true,
      contentPadding: EdgeInsets.zero,
      onTap: onTap,
      leading: const Icon(Icons.eco_outlined, size: 18),
      title: Text('${crop.cropName} · ${crop.variety ?? ''}'.trim()),
      subtitle: Text(
        [
          Fmt.humanize(crop.stage),
          crop.farmName,
          crop.areaValue == null
              ? null
              : Fmt.area(crop.areaValue, crop.areaUnit),
          crop.sowingDate == null
              ? null
              : '${context.t('sowing_date')}: ${Fmt.date(crop.sowingDate)}',
        ].whereType<String>().join(' · '),
      ),
      trailing: days == null
          ? null
          : Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text('$days', style: Theme.of(context).textTheme.titleSmall),
                Text(
                  context.t('days_to_harvest'),
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(fontSize: 10),
                ),
              ],
            ),
    );
  }
}
