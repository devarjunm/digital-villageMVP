import 'package:flutter/material.dart';

import '../../app.dart';
import '../../core/formatters.dart';
import '../../models/ai.dart';
import '../../widgets/common.dart';
import '../home/home_shell.dart';

/// Entry point to the AI features, each of which calls a real endpoint.
///
/// The hub also shows the model registry summary (`GET /ai/models`) so a farmer
/// can see which models exist, which version is serving, and whether the model
/// files are actually installed — the difference between "the feature exists"
/// and "the feature has a trained model behind it today".
class AiHubScreen extends StatefulWidget {
  const AiHubScreen({super.key, this.embedded = false});

  final bool embedded;

  @override
  State<AiHubScreen> createState() => _AiHubScreenState();
}

class _AiHubScreenState extends State<AiHubScreen> {
  int _tick = 0;

  @override
  Widget build(BuildContext context) {
    return EmbeddedScreenScaffold(
      title: context.t('ai_tools'),
      embedded: widget.embedded,
      onRefresh: () async => setState(() => _tick++),
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
        children: [
          Notice(
            kind: NoticeKind.ai,
            title: context.t('ai_assisted'),
            message: context.t('ai_tools_intro'),
          ),
          const SizedBox(height: 14),
          _ToolTile(
            icon: Icons.eco_outlined,
            title: context.t('crop_recommendation'),
            subtitle: context.t('crop_recommendation_hint'),
            route: Routes.cropRecommendation,
          ),
          _ToolTile(
            icon: Icons.photo_camera_outlined,
            title: context.t('disease_detection'),
            subtitle: context.t('disease_detection_hint'),
            route: Routes.diseaseDetection,
          ),
          _ToolTile(
            icon: Icons.insights_outlined,
            title: context.t('yield_prediction'),
            subtitle: context.t('yield_hint'),
            route: Routes.yieldPrediction,
          ),
          _ToolTile(
            icon: Icons.question_answer_outlined,
            title: context.t('assistant'),
            subtitle: context.t('assistant_hint'),
            route: Routes.assistant,
          ),
          _ToolTile(
            icon: Icons.history_outlined,
            title: context.t('ai_history'),
            subtitle: context.t('ai_models'),
            route: null,
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute<void>(builder: (_) => const AiActivityScreen()),
            ),
          ),
          const SizedBox(height: 18),
          SectionCard(
            title: context.t('ai_models'),
            child: AsyncSection<ModelRegistry>(
              refreshTick: _tick,
              load: () => context.repos.ai.models(),
              padding: EdgeInsets.zero,
              builder: (context, registry, reload) {
                if (registry.models.isEmpty) {
                  return Text(
                    context.t('not_available'),
                    style: Theme.of(context).textTheme.bodySmall,
                  );
                }
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    ...registry.models.map((model) => _ModelRow(model: model)),
                    if (registry.registryNote != null) ...[
                      const SizedBox(height: 8),
                      Text(
                        registry.registryNote!,
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color: Theme.of(context)
                                  .colorScheme
                                  .onSurfaceVariant,
                            ),
                      ),
                    ],
                  ],
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _ToolTile extends StatelessWidget {
  const _ToolTile({
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
      padding: const EdgeInsets.only(bottom: 10),
      child: Card(
        child: ListTile(
          leading: Icon(icon),
          title:
              Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
          subtitle:
              Text(subtitle, style: Theme.of(context).textTheme.bodySmall),
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

class _ModelRow extends StatelessWidget {
  const _ModelRow({required this.model});

  final ModelCard model;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final validation = model.validationMetrics;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  model.displayName ?? model.name,
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
              ),
              MetaPill(
                text: Fmt.humanize(model.stage),
                color: model.isActive ? scheme.primary : scheme.outline,
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            [
              '${context.t('model_version')}: ${model.version}',
              if (model.task != null) Fmt.humanize(model.task),
              if (model.framework != null) model.framework!,
            ].join(' · '),
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 4),
          Row(
            children: [
              Icon(
                model.installedOnDisk
                    ? Icons.check_circle_outline
                    : Icons.error_outline,
                size: 14,
                color: model.installedOnDisk ? scheme.primary : scheme.error,
              ),
              const SizedBox(width: 6),
              Text(
                model.installedOnDisk
                    ? 'installed'
                    : 'not installed on this server',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ),
          if (validation.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              '${context.t('data_class')}: validation metrics — '
              '${validation.entries.map((e) => '${Fmt.humanize(e.key)}: ${e.value}').join(', ')}',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: scheme.onSurfaceVariant,
                  ),
            ),
          ],
        ],
      ),
    );
  }
}

/// AI history and the model registry, side by side.
///
/// History comes from `GET /ai/history` (with the backend's own retention note)
/// and can be deleted entry by entry, because the record of what a farmer asked
/// is their own data.
class AiActivityScreen extends StatefulWidget {
  const AiActivityScreen({super.key});

  @override
  State<AiActivityScreen> createState() => _AiActivityScreenState();
}

class _AiActivityScreenState extends State<AiActivityScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabs = TabController(length: 2, vsync: this);
  // Refreshes are driven by AsyncSection.reload(); the tick only forces a new
  // key on the first build after a delete.
  final int _tick = 0;

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('ai_history')),
        bottom: TabBar(
          controller: _tabs,
          tabs: [
            Tab(text: context.t('ai_history')),
            Tab(text: context.t('ai_models')),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tabs,
        children: [
          AsyncSection<AiHistoryPage>(
            refreshTick: _tick,
            load: () => context.repos.ai.history(),
            isEmpty: (page) => page.items.isEmpty,
            emptyBuilder: (context, reload) => EmptyState(
              title: context.t('empty_title'),
              message: context.t('ai_history'),
              icon: Icons.history_outlined,
            ),
            builder: (context, page, reload) => ListView(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
              children: [
                Notice(kind: NoticeKind.info, message: page.retentionNote),
                const SizedBox(height: 12),
                ...page.items.map(
                  (entry) => Card(
                    child: ListTile(
                      title: Text(Fmt.humanize(entry.kind)),
                      subtitle: Text(
                        [
                          Fmt.dateTime(entry.createdAt),
                          if (entry.modelName != null) entry.modelName!,
                          if (entry.modelVersion != null) entry.modelVersion!,
                          if (entry.dataClass != null)
                            Fmt.humanize(entry.dataClass!),
                        ].join(' · '),
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                      trailing: IconButton(
                        tooltip: context.t('delete'),
                        icon: const Icon(Icons.delete_outline, size: 20),
                        onPressed: () async {
                          final repos = context.repos;
                          final confirmed = await showDialog<bool>(
                            context: context,
                            builder: (dialogContext) => AlertDialog(
                              content:
                                  Text(context.t('delete_history_confirm')),
                              actions: [
                                TextButton(
                                  onPressed: () =>
                                      Navigator.of(dialogContext).pop(false),
                                  child: Text(context.t('cancel')),
                                ),
                                FilledButton(
                                  onPressed: () =>
                                      Navigator.of(dialogContext).pop(true),
                                  child: Text(context.t('delete')),
                                ),
                              ],
                            ),
                          );
                          if (confirmed != true) return;
                          await repos.ai.deleteHistoryEntry(entry.id);
                          await reload();
                        },
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
          AsyncSection<ModelRegistry>(
            refreshTick: _tick,
            load: () => context.repos.ai.models(),
            builder: (context, registry, reload) => ListView(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
              children: [
                if (registry.registryNote != null)
                  Notice(
                      kind: NoticeKind.info, message: registry.registryNote!),
                const SizedBox(height: 12),
                ...registry.models.map(
                  (model) => Card(
                    child: Padding(
                      padding: const EdgeInsets.all(14),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            model.displayName ?? model.name,
                            style: Theme.of(context).textTheme.titleSmall,
                          ),
                          const SizedBox(height: 6),
                          InfoRow(
                              label: context.t('model_version'),
                              value: model.version),
                          InfoRow(label: 'Task', value: model.task ?? '—'),
                          InfoRow(
                              label: 'Framework',
                              value: model.framework ?? '—'),
                          InfoRow(
                              label: 'Stage', value: Fmt.humanize(model.stage)),
                          InfoRow(
                            label: 'Serving',
                            value: model.isActive
                                ? context.t('yes')
                                : context.t('no'),
                          ),
                          InfoRow(
                            label: 'Installed',
                            value: model.installedOnDisk
                                ? context.t('yes')
                                : context.t('no'),
                          ),
                          if (model.trainedAt != null)
                            InfoRow(
                              label: 'Trained',
                              value: Fmt.dateTime(model.trainedAt),
                            ),
                          if (model.validationMetrics.isNotEmpty) ...[
                            const SizedBox(height: 8),
                            Text(
                              'Validation metrics (as reported by training):',
                              style: Theme.of(context).textTheme.labelMedium,
                            ),
                            ...model.validationMetrics.entries.map(
                              (entry) => InfoRow(
                                label: Fmt.humanize(entry.key),
                                value: entry.value.toString(),
                              ),
                            ),
                          ],
                          if (model.notes != null) ...[
                            const SizedBox(height: 8),
                            Text(
                              model.notes!,
                              style: Theme.of(context)
                                  .textTheme
                                  .bodySmall
                                  ?.copyWith(
                                    color: Theme.of(context)
                                        .colorScheme
                                        .onSurfaceVariant,
                                  ),
                            ),
                          ],
                        ],
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
