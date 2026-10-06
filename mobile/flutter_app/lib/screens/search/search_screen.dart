import 'dart:async';

import 'package:flutter/material.dart';

import '../../app.dart';
import '../../core/api_exception.dart';
import '../../core/formatters.dart';
import '../../models/search.dart';
import '../../widgets/common.dart';
import '../community/post_detail_screen.dart';

/// Global search (`GET /search`, suggestions from `GET /search/suggest`).
///
/// Search spans knowledge documents, community posts, schemes, market prices and
/// weather notes. Each hit shows its own type, method (keyword/semantic/hybrid)
/// and trust label, because a semantic match is not the same kind of evidence as
/// an official document. An empty result set shows the backend's explanation
/// instead of a bare "no results".
class SearchScreen extends StatefulWidget {
  const SearchScreen({super.key});

  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> {
  final _controller = TextEditingController();
  final _focus = FocusNode();

  Timer? _debounce;
  List<String> _suggestions = const [];
  SearchResults? _results;
  bool _busy = false;
  String? _error;
  String? _crop;
  String? _state;
  String? _category;

  @override
  void dispose() {
    _debounce?.cancel();
    _controller.dispose();
    _focus.dispose();
    super.dispose();
  }

  void _onChanged(String value) {
    _debounce?.cancel();
    if (value.trim().length < 2) {
      setState(() => _suggestions = const []);
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 280), () async {
      try {
        final suggestions = await context.repos.search.suggest(value.trim());
        if (mounted) setState(() => _suggestions = suggestions);
      } on ApiException {
        if (mounted) setState(() => _suggestions = const []);
      }
    });
  }

  Future<void> _run([String? query]) async {
    final term = (query ?? _controller.text).trim();
    if (term.isEmpty) return;
    _controller.text = term;
    _focus.unfocus();
    setState(() {
      _busy = true;
      _error = null;
      _suggestions = const [];
    });
    try {
      final results = await context.repos.search.search(
        q: term,
        crop: _crop,
        state: _state,
        category: _category,
      );
      if (!mounted) return;
      setState(() {
        _results = results;
        _busy = false;
      });
    } on ApiException catch (error) {
      setState(() {
        _busy = false;
        _error = error.userMessage;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final results = _results;
    return Scaffold(
      appBar: AppBar(title: Text(context.t('search_everything'))),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
            child: TextField(
              controller: _controller,
              focusNode: _focus,
              autofocus: true,
              textInputAction: TextInputAction.search,
              onChanged: _onChanged,
              onSubmitted: (value) => _run(value),
              decoration: InputDecoration(
                hintText: context.t('search_hint'),
                prefixIcon: const Icon(Icons.search, size: 20),
                suffixIcon: IconButton(
                  icon: const Icon(Icons.arrow_forward, size: 18),
                  onPressed: () => _run(),
                ),
              ),
            ),
          ),
          if (_suggestions.isNotEmpty)
            SizedBox(
              height: 42,
              child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 16),
                children: _suggestions
                    .map(
                      (suggestion) => Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: ActionChip(
                          label: Text(suggestion),
                          onPressed: () => _run(suggestion),
                        ),
                      ),
                    )
                    .toList(),
              ),
            ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.all(16),
              child: ErrorState(message: _error!, onRetry: _run),
            ),
          if (_busy)
            const Padding(
              padding: EdgeInsets.all(24),
              child: LoadingState(),
            ),
          if (results != null && !_busy)
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
                children: [
                  Row(
                    children: [
                      Text(
                        '${results.counts.total} ${context.t('results_count')}',
                        style: Theme.of(context).textTheme.titleSmall,
                      ),
                      const Spacer(),
                      Text(
                        '${context.t('search_mode')}: ${Fmt.humanize(results.mode)}',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(
                    [
                      results.method,
                      if (results.latencyMs != null) '${results.latencyMs} ms',
                      'keyword ${results.counts.keywordCandidates}',
                      'semantic ${results.counts.semanticCandidates}',
                    ].join(' · '),
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                  ),
                  if (results.embeddingIsDemo) ...[
                    const SizedBox(height: 10),
                    const DemoChip(
                      notice:
                          'Semantic matching used the demonstration embedding provider '
                          '(lexical vectors), so "similar meaning" results are approximate.',
                    ),
                  ],
                  if (results.notices.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    Notice(
                        kind: NoticeKind.info,
                        message: results.notices.join('\n')),
                  ],
                  if (results.warnings.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    Notice(
                        kind: NoticeKind.warning,
                        message: results.warnings.join('\n')),
                  ],
                  const SizedBox(height: 12),
                  if (results.items.isEmpty)
                    EmptyState(
                      title: context.t('no_results'),
                      message: results.notices.isEmpty
                          ? context.t('search_hint')
                          : results.notices.join('\n'),
                      icon: Icons.search_off,
                    )
                  else
                    ...results.items.map((hit) => _HitCard(hit: hit)),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _HitCard extends StatelessWidget {
  const _HitCard({required this.hit});

  final SearchHit hit;

  @override
  Widget build(BuildContext context) {
    final drillable =
        hit.sourceType == 'post' || hit.sourceType == 'community_post';
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Card(
        child: InkWell(
          onTap: drillable
              ? () => Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => PostDetailScreen(postId: hit.id),
                    ),
                  )
              : null,
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    MetaPill(
                      text: Fmt.humanize(hit.sourceType),
                      icon: _iconFor(hit.sourceType),
                    ),
                    const SizedBox(width: 8),
                    if (hit.trustLabel != null)
                      TrustChip(label: hit.trustLabel!, compact: true),
                    const Spacer(),
                    Text(
                      Fmt.score(hit.score, decimals: 3),
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Text(
                  hit.title,
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                ),
                if (hit.snippet != null) ...[
                  const SizedBox(height: 4),
                  Text(hit.snippet!,
                      style: Theme.of(context).textTheme.bodySmall),
                ],
                const SizedBox(height: 8),
                Text(
                  [
                    if (hit.method != null) hit.method!,
                    if (hit.cropCode != null) Fmt.humanize(hit.cropCode!),
                    if (hit.state != null) hit.state!,
                    if (hit.category != null) Fmt.humanize(hit.category!),
                    if (hit.language != null) hit.language!,
                  ].whereType<String>().join(' · '),
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  static IconData _iconFor(String type) => switch (type) {
        'post' || 'community_post' => Icons.forum_outlined,
        'knowledge_chunk' ||
        'knowledge_document' ||
        'knowledge' =>
          Icons.menu_book_outlined,
        'scheme' => Icons.account_balance_outlined,
        'market_price' || 'market' => Icons.storefront_outlined,
        'weather' => Icons.cloud_outlined,
        'model_card' => Icons.memory_outlined,
        _ => Icons.article_outlined,
      };
}
