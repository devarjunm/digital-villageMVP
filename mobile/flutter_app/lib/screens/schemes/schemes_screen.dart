import 'package:flutter/material.dart';

import '../../app.dart';
import '../../core/api_exception.dart';
import '../../core/formatters.dart';
import '../../models/schemes.dart';
import '../../widgets/common.dart';

/// Government schemes: list, details, recommendations and the eligibility check.
///
/// Every scheme keeps its official source visible, and the eligibility result is
/// presented as "likely / likely not / needs more information" with the rules
/// that passed, failed and could not be evaluated listed separately — never as a
/// promise of approval.
class SchemesScreen extends StatefulWidget {
  const SchemesScreen({super.key});

  @override
  State<SchemesScreen> createState() => _SchemesScreenState();
}

class _SchemesScreenState extends State<SchemesScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabs = TabController(length: 3, vsync: this);
  int _tick = 0;
  String? _query;
  String? _category;
  List<String> _categories = const [];
  final _searchController = TextEditingController();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      try {
        final categories = await context.repos.schemes.categories();
        if (mounted) setState(() => _categories = categories);
      } on ApiException {
        // The category filter is optional.
      }
    });
  }

  @override
  void dispose() {
    _tabs.dispose();
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('schemes_title')),
        bottom: TabBar(
          controller: _tabs,
          tabs: [
            Tab(text: context.t('all')),
            Tab(text: context.t('recommended_schemes')),
            Tab(text: context.t('eligibility')),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tabs,
        children: [
          _AllSchemesTab(
            tick: _tick,
            query: _query,
            category: _category,
            categories: _categories,
            searchController: _searchController,
            onQueryChanged: (value) => setState(() {
              _query = value;
              _tick++;
            }),
            onCategoryChanged: (value) => setState(() {
              _category = value;
              _tick++;
            }),
          ),
          _RecommendedTab(tick: _tick),
          _EligibilityTab(tick: _tick),
        ],
      ),
    );
  }
}

class _AllSchemesTab extends StatelessWidget {
  const _AllSchemesTab({
    required this.tick,
    required this.query,
    required this.category,
    required this.categories,
    required this.searchController,
    required this.onQueryChanged,
    required this.onCategoryChanged,
  });

  final int tick;
  final String? query;
  final String? category;
  final List<String> categories;
  final TextEditingController searchController;
  final ValueChanged<String?> onQueryChanged;
  final ValueChanged<String?> onCategoryChanged;

  @override
  Widget build(BuildContext context) {
    return AsyncSection<SchemePage>(
      refreshTick: tick,
      load: () => context.repos.schemes.list(q: query, category: category),
      isEmpty: (page) => page.items.isEmpty,
      emptyBuilder: (context, reload) => ListView(
        padding: const EdgeInsets.all(20),
        children: [
          EmptyState(
            title: context.t('no_schemes'),
            message: query == null ? null : context.t('search_schemes'),
            icon: Icons.account_balance_outlined,
          ),
        ],
      ),
      builder: (context, page, reload) => ListView(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 32),
        children: [
          TextField(
            controller: searchController,
            textInputAction: TextInputAction.search,
            onSubmitted: (value) =>
                onQueryChanged(value.trim().isEmpty ? null : value.trim()),
            decoration: InputDecoration(
              hintText: context.t('search_schemes'),
              prefixIcon: const Icon(Icons.search, size: 20),
            ),
          ),
          if (categories.isNotEmpty) ...[
            const SizedBox(height: 10),
            SizedBox(
              height: 40,
              child: ListView(
                scrollDirection: Axis.horizontal,
                children: [
                  Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: FilterChip(
                      label: Text(context.t('all')),
                      selected: category == null,
                      onSelected: (_) => onCategoryChanged(null),
                    ),
                  ),
                  ...categories.map(
                    (item) => Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: FilterChip(
                        label: Text(Fmt.humanize(item)),
                        selected: category == item,
                        onSelected: (_) => onCategoryChanged(item),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
          const SizedBox(height: 12),
          ...page.items.map((scheme) => _SchemeCard(scheme: scheme)),
          const SizedBox(height: 8),
          Text(
            '${page.total} ${context.t('results_count')}',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

class _SchemeCard extends StatelessWidget {
  const _SchemeCard({required this.scheme});

  final Scheme scheme;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Card(
        child: ExpansionTile(
          tilePadding: const EdgeInsets.symmetric(horizontal: 14),
          childrenPadding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
          title: Text(
            scheme.name,
            style: Theme.of(context)
                .textTheme
                .titleSmall
                ?.copyWith(fontWeight: FontWeight.w700),
          ),
          subtitle: Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                MetaPill(text: Fmt.humanize(scheme.category)),
                MetaPill(text: Fmt.humanize(scheme.level)),
                MetaPill(
                  text: Fmt.humanize(scheme.verificationStatus),
                  icon: switch (scheme.verificationStatus) {
                    'official' => Icons.account_balance_outlined,
                    'expert_reviewed' => Icons.verified_outlined,
                    _ => Icons.help_outline,
                  },
                ),
                if (scheme.isDemo) const DemoChip(),
              ],
            ),
          ),
          children: [
            Align(
              alignment: Alignment.centerLeft,
              child: Text(scheme.description,
                  style: Theme.of(context).textTheme.bodyMedium),
            ),
            const SizedBox(height: 10),
            if (scheme.benefits != null)
              _Block(title: context.t('benefits'), body: scheme.benefits!),
            if (scheme.eligibilitySummary != null)
              _Block(
                  title: context.t('eligibility'),
                  body: scheme.eligibilitySummary!),
            if (scheme.applicationProcess != null)
              _Block(
                  title: context.t('application_process'),
                  body: scheme.applicationProcess!),
            if (scheme.documentsRequired.isNotEmpty)
              _Block(
                title: context.t('documents_required'),
                body:
                    scheme.documentsRequired.map((doc) => '• $doc').join('\n'),
              ),
            if (scheme.contentNotice != null) ...[
              const SizedBox(height: 8),
              Notice(kind: NoticeKind.warning, message: scheme.contentNotice!),
            ],
            const SizedBox(height: 8),
            Notice(
              kind: NoticeKind.info,
              title: context.t('official_source'),
              message:
                  'Scheme details change. Confirm the current rules and amounts at the official page below.',
            ),
            SourceLine(
              title: scheme.officialSourceName,
              subtitle: scheme.lastVerifiedOn == null
                  ? context.t('last_verified')
                  : '${context.t('last_verified')}: ${Fmt.date(scheme.lastVerifiedOn)}',
              url: scheme.officialSourceUrl,
            ),
            if (scheme.applicationUrl != null)
              SourceLine(
                  title: context.t('apply_at'), url: scheme.applicationUrl),
            if (scheme.helpline != null)
              InfoRow(label: context.t('helpline'), value: scheme.helpline!),
          ],
        ),
      ),
    );
  }
}

class _Block extends StatelessWidget {
  const _Block({required this.title, required this.body});

  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: Theme.of(context).textTheme.labelLarge),
          const SizedBox(height: 3),
          Text(body, style: Theme.of(context).textTheme.bodyMedium),
        ],
      ),
    );
  }
}

class _RecommendedTab extends StatelessWidget {
  const _RecommendedTab({required this.tick});

  final int tick;

  @override
  Widget build(BuildContext context) {
    return AsyncSection<SchemeRecommendations>(
      refreshTick: tick,
      load: () => context.repos.schemes.recommended(),
      isEmpty: (data) => data.items.isEmpty,
      emptyBuilder: (context, reload) => EmptyState(
        title: context.t('no_schemes'),
        icon: Icons.recommend_outlined,
      ),
      builder: (context, data, reload) => ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
        children: [
          Notice(
            kind: NoticeKind.warning,
            title: context.t('match_score'),
            message: data.note,
          ),
          const SizedBox(height: 6),
          Text(
            '${data.evaluatedSchemes} ${context.t('results_count')}',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 12),
          ...data.items.map(
            (item) => Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              item.scheme.name,
                              style: Theme.of(context)
                                  .textTheme
                                  .titleSmall
                                  ?.copyWith(
                                    fontWeight: FontWeight.w700,
                                  ),
                            ),
                          ),
                          MetaPill(
                            text:
                                '${item.matchScore}% ${context.t('match_score')}',
                            color: item.matchScore >= 70
                                ? const Color(0xFF1F6F3F)
                                : Theme.of(context).colorScheme.outline,
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Text(
                        Fmt.humanize(item.status),
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                      if (item.reasons.isNotEmpty) ...[
                        const SizedBox(height: 6),
                        ...item.reasons.map(
                          (reason) => Text(
                            '• $reason',
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                        ),
                      ],
                      if (item.missingInputs.isNotEmpty) ...[
                        const SizedBox(height: 8),
                        Notice(
                          kind: NoticeKind.info,
                          title: context.t('missing_inputs'),
                          message:
                              '${context.t('eligibility_inputs_note')}\n${item.missingInputs.join(', ')}',
                        ),
                      ],
                      const SizedBox(height: 8),
                      SourceLine(
                        title: item.scheme.officialSourceName,
                        url: item.scheme.officialSourceUrl,
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Eligibility check for a chosen scheme, using the documented factor inputs.
class _EligibilityTab extends StatefulWidget {
  const _EligibilityTab({required this.tick});

  final int tick;

  @override
  State<_EligibilityTab> createState() => _EligibilityTabState();
}

class _EligibilityTabState extends State<_EligibilityTab> {
  final _age = TextEditingController();
  final _income = TextEditingController();
  final _caste = TextEditingController();
  bool? _hasKcc;
  bool? _tenant;
  String? _slug;
  List<Scheme> _schemes = const [];
  EligibilityResult? _result;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadSchemes());
  }

  @override
  void dispose() {
    _age.dispose();
    _income.dispose();
    _caste.dispose();
    super.dispose();
  }

  Future<void> _loadSchemes() async {
    try {
      final page = await context.repos.schemes.list(pageSize: 50);
      if (!mounted) return;
      setState(() {
        _schemes = page.items;
        _slug ??= page.items.isNotEmpty ? page.items.first.slug : null;
      });
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.userMessage);
    }
  }

  Future<void> _check() async {
    final slug = _slug;
    if (slug == null) return;
    setState(() {
      _busy = true;
      _error = null;
      _result = null;
    });
    try {
      final result = await context.repos.schemes.checkEligibility(
        slug,
        ageYears: int.tryParse(_age.text.trim()),
        annualIncomeInr: double.tryParse(_income.text.trim()),
        hasKcc: _hasKcc,
        isTenantFarmer: _tenant,
        categoryCaste: _caste.text.trim().isEmpty ? null : _caste.text.trim(),
      );
      if (!mounted) return;
      setState(() {
        _result = result;
        _busy = false;
      });
    } on ApiException catch (error) {
      setState(() {
        _busy = false;
        _error = error.userFieldsOrMessage;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
      children: [
        SectionCard(
          title: context.t('check_eligibility'),
          subtitle: context.t('eligibility_inputs_note'),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              DropdownField<String>(
                label: context.t('schemes_title'),
                value: _slug,
                items: _schemes.map((scheme) => scheme.slug).toList(),
                allowNull: false,
                labelBuilder: (slug) => _schemes
                    .firstWhere(
                      (scheme) => scheme.slug == slug,
                      orElse: () => Scheme(
                        id: '',
                        slug: slug,
                        name: slug,
                        description: '',
                        category: '',
                        level: '',
                        officialSourceName: '',
                        officialSourceUrl: '',
                        verificationStatus: 'unverified',
                      ),
                    )
                    .name,
                onChanged: (value) => setState(() => _slug = value),
              ),
              FormTextField(
                label: context.t('age_days'),
                controller: _age,
                keyboardType: TextInputType.number,
                helper: context.t('age_days'),
              ),
              FormTextField(
                label: context.t('annual_income'),
                controller: _income,
                keyboardType:
                    const TextInputType.numberWithOptions(decimal: true),
              ),
              FormTextField(
                  label: context.t('category_caste'), controller: _caste),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                value: _hasKcc ?? false,
                onChanged: (value) => setState(() => _hasKcc = value),
                title: Text(context.t('has_kcc')),
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                value: _tenant ?? false,
                onChanged: (value) => setState(() => _tenant = value),
                title: Text(context.t('tenant_farmer')),
              ),
              const SizedBox(height: 8),
              BusyButton(
                label: context.t('check_eligibility'),
                busy: _busy,
                icon: Icons.fact_check_outlined,
                onPressed: _slug == null ? null : _check,
              ),
            ],
          ),
        ),
        if (_error != null) ...[
          const SizedBox(height: 14),
          ErrorState(message: _error!, onRetry: _check),
        ],
        if (_result != null) ...[
          const SizedBox(height: 14),
          SectionCard(
            title: context.t('eligibility_result'),
            subtitle: _result!.schemeName,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                MetaPill(
                  text: switch (_result!.status) {
                    'likely_eligible' => context.t('likely_eligible'),
                    'likely_not_eligible' => context.t('likely_not_eligible'),
                    _ => context.t('needs_more_information'),
                  },
                  color: switch (_result!.status) {
                    'likely_eligible' => const Color(0xFF1F6F3F),
                    'likely_not_eligible' => const Color(0xFFB3261E),
                    _ => const Color(0xFF9A5B00),
                  },
                ),
                const SizedBox(height: 10),
                Text(_result!.explanation),
                const SizedBox(height: 12),
                if (_result!.passed.isNotEmpty) ...[
                  Text(context.t('passed_rules'),
                      style: Theme.of(context).textTheme.labelLarge),
                  ..._result!.passed.map(
                    (rule) => Text('• ${rule.message}',
                        style: Theme.of(context).textTheme.bodySmall),
                  ),
                  const SizedBox(height: 8),
                ],
                if (_result!.failed.isNotEmpty) ...[
                  Text(context.t('failed_rules'),
                      style: Theme.of(context).textTheme.labelLarge),
                  ..._result!.failed.map(
                    (rule) => Text('• ${rule.message}',
                        style: Theme.of(context).textTheme.bodySmall),
                  ),
                  const SizedBox(height: 8),
                ],
                if (_result!.unknown.isNotEmpty) ...[
                  Text(context.t('unknown_rules'),
                      style: Theme.of(context).textTheme.labelLarge),
                  ..._result!.unknown.map(
                    (rule) => Text('• ${rule.message}',
                        style: Theme.of(context).textTheme.bodySmall),
                  ),
                  const SizedBox(height: 8),
                ],
                if (_result!.configurationWarnings.isNotEmpty) ...[
                  Notice(
                    kind: NoticeKind.warning,
                    message: _result!.configurationWarnings.join('\n'),
                  ),
                  const SizedBox(height: 8),
                ],
                if (_result!.missingInputs.isNotEmpty)
                  Notice(
                    kind: NoticeKind.info,
                    title: context.t('missing_inputs'),
                    message: _result!.missingInputs.join(', '),
                  ),
                const SizedBox(height: 10),
                Notice(kind: NoticeKind.warning, message: _result!.disclaimer),
                SourceLine(
                  title: _result!.officialSourceName,
                  url: _result!.officialSourceUrl,
                ),
              ],
            ),
          ),
        ],
      ],
    );
  }
}
