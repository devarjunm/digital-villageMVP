import 'package:flutter/material.dart';

import '../../app.dart';
import '../../core/api_exception.dart';
import '../../core/formatters.dart';
import '../../models/community.dart';
import '../../widgets/common.dart';
import '../home/home_shell.dart';

/// Community feed (`GET /community/feed`, vocabulary from `/community/meta`).
///
/// The category list, the reaction kinds and the ranking weights all come from
/// the backend, so the app cannot drift from what moderation and ranking
/// actually use. The ranking disclosure is shown in the filter sheet.
class CommunityScreen extends StatefulWidget {
  const CommunityScreen({super.key, this.embedded = false});

  final bool embedded;

  @override
  State<CommunityScreen> createState() => _CommunityScreenState();
}

class _CommunityScreenState extends State<CommunityScreen> {
  int _tick = 0;
  int _page = 1;
  String? _category;
  String? _cropCode;
  String? _query;
  String? _sort;
  bool _followingOnly = false;
  bool _savedOnly = false;
  bool _unansweredOnly = false;
  final _searchController = TextEditingController();

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    setState(() {
      _page = 1;
      _tick++;
    });
  }

  @override
  Widget build(BuildContext context) {
    return EmbeddedScreenScaffold(
      title: context.t('community_feed'),
      embedded: widget.embedded,
      onRefresh: _refresh,
      actions: [
        IconButton(
          tooltip: context.t('filters'),
          icon: const Icon(Icons.tune),
          onPressed: _openFilters,
        ),
        if (context.session.isSignedIn)
          IconButton(
            tooltip: context.t('create_post'),
            icon: const Icon(Icons.edit_outlined),
            onPressed: () async {
              await Navigator.of(context).pushNamed(Routes.createPost);
              await _refresh();
            },
          ),
      ],
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
            child: TextField(
              controller: _searchController,
              textInputAction: TextInputAction.search,
              onSubmitted: (value) {
                setState(() {
                  _query = value.trim().isEmpty ? null : value.trim();
                  _page = 1;
                  _tick++;
                });
              },
              decoration: InputDecoration(
                hintText: context.t('search_hint'),
                prefixIcon: const Icon(Icons.search, size: 20),
                suffixIcon: _query == null
                    ? null
                    : IconButton(
                        icon: const Icon(Icons.close, size: 18),
                        onPressed: () {
                          _searchController.clear();
                          setState(() {
                            _query = null;
                            _page = 1;
                            _tick++;
                          });
                        },
                      ),
              ),
            ),
          ),
          if (_category != null ||
              _followingOnly ||
              _savedOnly ||
              _unansweredOnly)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Wrap(
                spacing: 8,
                children: [
                  if (_category != null)
                    Chip(
                      label: Text(Fmt.humanize(_category!)),
                      onDeleted: () => setState(() {
                        _category = null;
                        _page = 1;
                        _tick++;
                      }),
                    ),
                  if (_followingOnly)
                    Chip(
                      label: Text(context.t('following_only')),
                      onDeleted: () => setState(() {
                        _followingOnly = false;
                        _page = 1;
                        _tick++;
                      }),
                    ),
                  if (_savedOnly)
                    Chip(
                      label: Text(context.t('saved_only')),
                      onDeleted: () => setState(() {
                        _savedOnly = false;
                        _page = 1;
                        _tick++;
                      }),
                    ),
                  if (_unansweredOnly)
                    Chip(
                      label: Text(context.t('unanswered_only')),
                      onDeleted: () => setState(() {
                        _unansweredOnly = false;
                        _page = 1;
                        _tick++;
                      }),
                    ),
                ],
              ),
            ),
          Expanded(
            child: AsyncSection<PostPage>(
              refreshTick: _tick,
              load: () => context.repos.community.feed(
                page: _page,
                category: _category,
                cropCode: _cropCode,
                query: _query,
                followingOnly: _followingOnly,
                savedOnly: _savedOnly,
                unansweredOnly: _unansweredOnly,
                sort: _sort,
              ),
              isEmpty: (page) => page.items.isEmpty,
              emptyBuilder: (context, reload) => ListView(
                padding: const EdgeInsets.all(20),
                children: [
                  EmptyState(
                    title: context.t('no_posts'),
                    message: _savedOnly
                        ? context.t('saved_only')
                        : context.t('demo_accounts_note'),
                    icon: Icons.forum_outlined,
                  ),
                ],
              ),
              builder: (context, page, reload) => ListView.separated(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                itemCount: page.items.length + 1,
                separatorBuilder: (_, __) => const SizedBox(height: 12),
                itemBuilder: (context, index) {
                  if (index == page.items.length) {
                    return _FeedFooter(
                        page: page,
                        onLoadMore: () async {
                          setState(() {
                            _page += 1;
                            _tick++;
                          });
                        },
                        onRankingInfo: () =>
                            _showRanking(context, page.ranking));
                  }
                  final post = page.items[index];
                  return PostCard(
                    post: post,
                    onTap: () async {
                      await Navigator.of(context).push(Routes.post(post.id));
                      await reload();
                    },
                    onChanged: reload,
                  );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _openFilters() async {
    final repos = context.repos;
    CommunityMeta? meta;
    try {
      meta = await repos.community.meta();
    } on ApiException {
      meta = null;
    }
    if (!mounted) return;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => StatefulBuilder(
        builder: (sheetContext, setSheetState) => Padding(
          padding: const EdgeInsets.fromLTRB(20, 20, 20, 28),
          child: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(context.t('filters'),
                    style: Theme.of(context).textTheme.titleLarge),
                const SizedBox(height: 16),
                if (meta != null && meta.categories.isNotEmpty) ...[
                  Text(context.t('category'),
                      style: Theme.of(context).textTheme.labelLarge),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: meta.categories
                        .map(
                          (option) => FilterChip(
                            label: Text(option.label),
                            selected: _category == option.value,
                            onSelected: (selected) {
                              setState(() {
                                _category = selected ? option.value : null;
                                _page = 1;
                                _tick++;
                              });
                              setSheetState(() {});
                            },
                          ),
                        )
                        .toList(),
                  ),
                  const SizedBox(height: 16),
                ],
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  value: _followingOnly,
                  onChanged: context.session.isSignedIn
                      ? (value) {
                          setState(() {
                            _followingOnly = value;
                            _page = 1;
                            _tick++;
                          });
                          setSheetState(() {});
                        }
                      : null,
                  title: Text(context.t('following_only')),
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  value: _savedOnly,
                  onChanged: context.session.isSignedIn
                      ? (value) {
                          setState(() {
                            _savedOnly = value;
                            _page = 1;
                            _tick++;
                          });
                          setSheetState(() {});
                        }
                      : null,
                  title: Text(context.t('saved_only')),
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  value: _unansweredOnly,
                  onChanged: (value) {
                    setState(() {
                      _unansweredOnly = value;
                      _page = 1;
                      _tick++;
                    });
                    setSheetState(() {});
                  },
                  title: Text(context.t('unanswered_only')),
                ),
                const SizedBox(height: 8),
                Text(context.t('sort_recent'),
                    style: Theme.of(context).textTheme.labelLarge),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  children: [
                    ChoiceChip(
                      label: Text(context.t('sort_recent')),
                      selected: _sort == null || _sort == 'recent',
                      onSelected: (_) {
                        setState(() {
                          _sort = 'recent';
                          _page = 1;
                          _tick++;
                        });
                        setSheetState(() {});
                      },
                    ),
                    ChoiceChip(
                      label: Text(context.t('sort_relevance')),
                      selected: _sort == 'relevance',
                      onSelected: (_) {
                        setState(() {
                          _sort = 'relevance';
                          _page = 1;
                          _tick++;
                        });
                        setSheetState(() {});
                      },
                    ),
                  ],
                ),
                if (meta?.whatTrustLabelsMean != null) ...[
                  const SizedBox(height: 18),
                  Notice(
                    kind: NoticeKind.info,
                    title: context.t('trust_label'),
                    message: meta!.whatTrustLabelsMean!,
                    items: meta.trustLabels
                        .map((label) =>
                            '${Fmt.humanize(label.value)} — ${label.description ?? ''}')
                        .toList(),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  void _showRanking(BuildContext context, FeedRanking? ranking) {
    if (ranking == null) return;
    showModalBottomSheet<void>(
      context: context,
      builder: (sheetContext) => Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(context.t('ranking_method'),
                style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            InfoRow(label: 'Method', value: Fmt.humanize(ranking.method)),
            InfoRow(
              label: 'Learned ranking model',
              value: ranking.isMlModel ? context.t('yes') : context.t('no'),
            ),
            if (ranking.weights.isNotEmpty)
              InfoRow(
                label: 'Weights',
                value: ranking.weights.entries
                    .map((e) =>
                        '${Fmt.humanize(e.key)} ${e.value.toStringAsFixed(2)}')
                    .join(', '),
              ),
            if (ranking.activeTerms.isNotEmpty)
              InfoRow(
                  label: 'Active terms', value: ranking.activeTerms.join(', ')),
            const SizedBox(height: 12),
            Notice(
                kind: NoticeKind.warning, message: context.t('ranking_note')),
            if (ranking.note != null) ...[
              const SizedBox(height: 10),
              Text(ranking.note!, style: Theme.of(context).textTheme.bodySmall),
            ],
          ],
        ),
      ),
    );
  }
}

class _FeedFooter extends StatelessWidget {
  const _FeedFooter({
    required this.page,
    required this.onLoadMore,
    required this.onRankingInfo,
  });

  final PostPage page;
  final Future<void> Function() onLoadMore;
  final VoidCallback onRankingInfo;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Column(
        children: [
          Text(
            '${page.total} ${context.t('results_count')}',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 8),
          if (page.hasNext)
            OutlinedButton(
              onPressed: () => onLoadMore(),
              child: Text(context.t('view_all')),
            ),
          TextButton.icon(
            onPressed: onRankingInfo,
            icon: const Icon(Icons.info_outline, size: 16),
            label: Text(context.t('ranking_method')),
          ),
        ],
      ),
    );
  }
}

/// Post card with the trust label, reactions and save/report actions.
class PostCard extends StatelessWidget {
  const PostCard({
    super.key,
    required this.post,
    required this.onTap,
    required this.onChanged,
    this.showBody = true,
  });

  final CommunityPost post;
  final Future<void> Function() onTap;
  final Future<void> Function() onChanged;
  final bool showBody;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: InkWell(
        onTap: () => onTap(),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      post.author.displayName,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                            fontWeight: FontWeight.w600,
                          ),
                    ),
                  ),
                  if (post.author.verifiedExpert)
                    const MetaPill(
                        text: 'Verified expert', icon: Icons.verified_outlined),
                  const SizedBox(width: 6),
                  Text(
                    Fmt.relative(post.createdAt,
                        language: context.session.languageCode),
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Text(
                post.title,
                style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
              ),
              if (showBody) ...[
                const SizedBox(height: 6),
                ExpandableText(post.body, maxLines: 4),
              ],
              const SizedBox(height: 10),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  TrustChip(label: post.trustLabel, compact: true),
                  if (post.cropCode != null)
                    MetaPill(
                        text: Fmt.humanize(post.cropCode),
                        icon: Icons.eco_outlined),
                  MetaPill(
                      text: Fmt.humanize(post.category),
                      icon: Icons.label_outline),
                  if (post.district != null)
                    MetaPill(text: post.district!, icon: Icons.place_outlined),
                  if (post.isDemo) const DemoChip(),
                ],
              ),
              const SizedBox(height: 6),
              Row(
                children: [
                  Text(
                    '${post.reactionCount} · ${post.commentCount}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                  const Spacer(),
                  TextButton(
                    onPressed: () => onTap(),
                    child: Text(context.t('comments')),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
