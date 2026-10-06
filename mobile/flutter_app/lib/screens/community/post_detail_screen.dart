import 'package:flutter/material.dart';

import '../../app.dart';
import '../../core/api_exception.dart';
import '../../core/formatters.dart';
import '../../models/community.dart';
import '../../widgets/common.dart';

/// One post with its comments, reactions, saving and reporting.
///
/// Reaction kinds and report reasons are read from `/community/meta`, so the app
/// cannot offer a reaction the backend does not store or a report reason the
/// moderation queue does not understand. Reactions are labelled as social
/// signals, not as evidence of correctness.
class PostDetailScreen extends StatefulWidget {
  const PostDetailScreen({super.key, required this.postId});

  final String postId;

  @override
  State<PostDetailScreen> createState() => _PostDetailScreenState();
}

class _PostDetailScreenState extends State<PostDetailScreen> {
  int _tick = 0;
  final _commentController = TextEditingController();
  bool _sendingComment = false;
  CommunityMeta? _meta;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      try {
        final meta = await context.repos.community.meta();
        if (mounted) setState(() => _meta = meta);
      } on ApiException {
        // Fall back to an empty reaction list; the post still renders.
      }
    });
  }

  @override
  void dispose() {
    _commentController.dispose();
    super.dispose();
  }

  Future<void> _react(CommunityPost post, String kind) async {
    final repos = context.repos;
    try {
      if (post.myReaction == kind) {
        await repos.community.removeReaction(post.id);
      } else {
        await repos.community.react(post.id, kind);
      }
      if (!mounted) return;
      setState(() => _tick++);
    } on ApiException catch (error) {
      _snack(error.userMessage);
    }
  }

  Future<void> _toggleSave(CommunityPost post) async {
    final repos = context.repos;
    try {
      final saved = await repos.community.toggleSave(post.id);
      if (!mounted) return;
      _snack(saved ? context.t('saved') : context.t('unsaved'));
      setState(() => _tick++);
    } on ApiException catch (error) {
      _snack(error.userMessage);
    }
  }

  Future<void> _addComment() async {
    final body = _commentController.text.trim();
    if (body.isEmpty) return;
    setState(() => _sendingComment = true);
    try {
      await context.repos.community.addComment(widget.postId, body);
      _commentController.clear();
      setState(() => _tick++);
    } on ApiException catch (error) {
      _snack(error.userMessage);
    } finally {
      if (mounted) setState(() => _sendingComment = false);
    }
  }

  Future<void> _report(String targetType, String targetId) async {
    final reasons = _meta?.reportReasons ??
        const ['spam', 'abuse', 'misinformation', 'off_topic', 'other'];
    String? reason = reasons.first;
    final details = TextEditingController();
    final submitted = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (dialogContext, setDialogState) => AlertDialog(
          title: Text(context.t('report')),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(context.t('report_reason'),
                  style: Theme.of(context).textTheme.labelLarge),
              const SizedBox(height: 8),
              RadioGroup<String>(
                groupValue: reason,
                onChanged: (value) => setDialogState(() => reason = value),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: reasons
                      .map(
                        (option) => RadioListTile<String>(
                          dense: true,
                          contentPadding: EdgeInsets.zero,
                          value: option,
                          title: Text(Fmt.humanize(option)),
                        ),
                      )
                      .toList(),
                ),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: details,
                maxLines: 3,
                decoration:
                    InputDecoration(hintText: context.t('report_details')),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(false),
              child: Text(context.t('cancel')),
            ),
            FilledButton(
              onPressed: () => Navigator.of(dialogContext).pop(true),
              child: Text(context.t('submit')),
            ),
          ],
        ),
      ),
    );
    if (submitted != true || !mounted) return;
    final repos = context.repos;
    try {
      final result = await repos.community.report(
        targetType: targetType,
        targetId: targetId,
        reason: reason ?? 'other',
        details: details.text.trim().isEmpty ? null : details.text.trim(),
      );
      if (!mounted) return;
      _snack(
        result['already_reported'] == true
            ? context.t('report_already')
            : context.t('report_submitted'),
      );
    } on ApiException catch (error) {
      if (mounted) _snack(error.userMessage);
    } finally {
      details.dispose();
    }
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('comments')),
        actions: [
          AsyncSection<CommunityPost>(
            refreshTick: -1,
            load: () => context.repos.community.post(widget.postId),
            padding: EdgeInsets.zero,
            builder: (builderContext, post, reload) => PopupMenuButton<String>(
              onSelected: (value) async {
                final repos = builderContext.repos;
                final session = builderContext.session;
                if (value == 'report') await _report('post', post.id);
                if (value == 'delete' && session.user?.id == post.author.id) {
                  try {
                    await repos.community.deletePost(post.id);
                    if (mounted) Navigator.of(this.context).pop();
                  } on ApiException catch (error) {
                    if (mounted) _snack(error.userMessage);
                  }
                }
              },
              itemBuilder: (context) => [
                PopupMenuItem(
                    value: 'report', child: Text(context.t('report'))),
                if (context.session.user?.id == post.author.id)
                  PopupMenuItem(
                      value: 'delete', child: Text(context.t('delete'))),
              ],
            ),
          ),
        ],
      ),
      body: AsyncSection<CommunityPost>(
        refreshTick: _tick,
        load: () => context.repos.community.post(widget.postId),
        builder: (context, post, reload) => ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
          children: [
            Card(
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
                            style: Theme.of(context).textTheme.titleSmall,
                          ),
                        ),
                        if (post.author.verifiedExpert)
                          const MetaPill(
                              text: 'Verified expert',
                              icon: Icons.verified_outlined),
                      ],
                    ),
                    const SizedBox(height: 2),
                    Text(
                      [
                        Fmt.humanize(post.author.primaryRole),
                        if (post.author.district != null) post.author.district!,
                        Fmt.relative(post.createdAt,
                            language: context.session.languageCode),
                      ].join(' · '),
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                    const SizedBox(height: 12),
                    Text(
                      post.title,
                      style: Theme.of(context).textTheme.titleLarge?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                    ),
                    const SizedBox(height: 8),
                    SelectableText(post.body),
                    if (post.media.isNotEmpty) ...[
                      const SizedBox(height: 12),
                      Column(
                        children: post.media
                            .map(
                              (media) => Padding(
                                padding: const EdgeInsets.only(bottom: 8),
                                child: Notice(
                                  kind: NoticeKind.info,
                                  message: 'Attached ${media.mimeType} '
                                      '${media.width == null ? '' : '(${media.width}×${media.height})'}'
                                      '${media.url == null ? ' — stored, url not public' : ''}',
                                ),
                              ),
                            )
                            .toList(),
                      ),
                    ],
                    if (post.sourceUrls.isNotEmpty) ...[
                      const SizedBox(height: 10),
                      Text(context.t('source_links'),
                          style: Theme.of(context).textTheme.labelLarge),
                      ...post.sourceUrls
                          .map((url) => SourceLine(title: url, url: url)),
                    ],
                    const SizedBox(height: 10),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        TrustChip(label: post.trustLabel, compact: true),
                        MetaPill(text: Fmt.humanize(post.category)),
                        if (post.cropCode != null)
                          MetaPill(text: Fmt.humanize(post.cropCode)),
                        if (post.state != null) MetaPill(text: post.state!),
                      ],
                    ),
                    if (post.trustReasons.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      Text(
                        '${context.t('trust_reasons')}: ${post.trustReasons.join('; ')}',
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color: Theme.of(context)
                                  .colorScheme
                                  .onSurfaceVariant,
                            ),
                      ),
                    ],
                    const Divider(height: 24),
                    Row(
                      children: [
                        ...(_meta?.reactionKinds ??
                                const ['support', 'helpful', 'insightful'])
                            .map(
                          (kind) => Padding(
                            padding: const EdgeInsets.only(right: 6),
                            child: FilterChip(
                              avatar: Icon(_reactionIcon(kind), size: 15),
                              label: Text(_reactionLabel(context, kind)),
                              selected: post.myReaction == kind,
                              onSelected: (_) => _react(post, kind),
                            ),
                          ),
                        ),
                        const Spacer(),
                        IconButton(
                          tooltip: context.t('saved'),
                          onPressed: () => _toggleSave(post),
                          icon: Icon(
                            post.isSaved
                                ? Icons.bookmark
                                : Icons.bookmark_border,
                          ),
                        ),
                      ],
                    ),
                    Text(
                      '${post.reactionCount} · ${post.commentCount} · ${post.viewCount}',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                    const SizedBox(height: 6),
                    Text(
                      context.t('ranking_note'),
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color:
                                Theme.of(context).colorScheme.onSurfaceVariant,
                          ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),
            Text(context.t('comments'),
                style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 8),
            AsyncSection<List<Comment>>(
              refreshTick: _tick,
              load: () => context.repos.community.comments(widget.postId),
              isEmpty: (comments) => comments.isEmpty,
              emptyBuilder: (context, reload) => EmptyState(
                title: context.t('no_comments'),
                icon: Icons.mode_comment_outlined,
              ),
              builder: (context, comments, reload) => Column(
                children: comments
                    .map(
                      (comment) => _CommentTile(
                        comment: comment,
                        onReport: () => _report('comment', comment.id),
                      ),
                    )
                    .toList(),
              ),
            ),
          ],
        ),
      ),
      bottomNavigationBar: context.session.isSignedIn
          ? SafeArea(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
                child: Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _commentController,
                        minLines: 1,
                        maxLines: 4,
                        decoration: InputDecoration(
                            hintText: context.t('comment_hint')),
                      ),
                    ),
                    const SizedBox(width: 8),
                    _sendingComment
                        ? const SizedBox(
                            width: 22,
                            height: 22,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : IconButton.filled(
                            onPressed: _addComment,
                            icon: const Icon(Icons.send),
                          ),
                  ],
                ),
              ),
            )
          : null,
    );
  }

  static IconData _reactionIcon(String kind) => switch (kind) {
        'support' => Icons.volunteer_activism_outlined,
        'helpful' => Icons.thumb_up_outlined,
        'insightful' => Icons.lightbulb_outline,
        _ => Icons.circle_outlined,
      };

  static String _reactionLabel(BuildContext context, String kind) =>
      switch (kind) {
        'support' => context.t('reaction_support'),
        'helpful' => context.t('reaction_helpful'),
        'insightful' => context.t('reaction_insightful'),
        _ => Fmt.humanize(kind),
      };
}

class _CommentTile extends StatelessWidget {
  const _CommentTile({required this.comment, required this.onReport});

  final Comment comment;
  final VoidCallback onReport;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      comment.author.displayName,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                            fontWeight: FontWeight.w600,
                          ),
                    ),
                  ),
                  if (comment.author.verifiedExpert)
                    const MetaPill(
                        text: 'Expert', icon: Icons.verified_outlined),
                  const SizedBox(width: 6),
                  Text(
                    Fmt.relative(comment.createdAt,
                        language: context.session.languageCode),
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                  IconButton(
                    tooltip: context.t('report'),
                    iconSize: 18,
                    onPressed: onReport,
                    icon: const Icon(Icons.flag_outlined),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              Text(comment.body),
              const SizedBox(height: 6),
              Row(
                children: [
                  TrustChip(label: comment.trustLabel, compact: true),
                  const Spacer(),
                  if (comment.reportCount > 0)
                    Text(
                      '${comment.reportCount} ${context.t('report')}',
                      style: Theme.of(context).textTheme.bodySmall,
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
