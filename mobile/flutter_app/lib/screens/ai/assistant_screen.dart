import 'package:flutter/material.dart';

import '../../app.dart';
import '../../core/api_exception.dart';
import '../../core/formatters.dart';
import '../../models/ai.dart';
import '../../widgets/common.dart';

/// The RAG assistant (`POST /knowledge/ask`).
///
/// Behaviour that must not change:
/// * the answer is only shown together with its citations;
/// * `insufficientEvidence` is rendered as a prominent warning, not hidden;
/// * the provider disclosure (including "the demo provider answered this") is
///   always visible, and the guardrail flags are shown when set.
class AssistantScreen extends StatefulWidget {
  const AssistantScreen({super.key});

  @override
  State<AssistantScreen> createState() => _AssistantScreenState();
}

class _AssistantScreenState extends State<AssistantScreen> {
  final _question = TextEditingController();
  final _scrollController = ScrollController();

  bool _useFarmContext = true;
  int _topK = 5;
  bool _busy = false;
  String? _error;
  final List<_Exchange> _session = [];

  @override
  void dispose() {
    _question.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _ask() async {
    final question = _question.text.trim();
    if (question.isEmpty) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final answer = await context.repos.ai.ask(
        question: question,
        language: context.session.languageCode,
        topK: _topK,
        useFarmContext: _useFarmContext && context.session.isSignedIn,
      );
      if (!mounted) return;
      setState(() {
        _busy = false;
        _session.insert(0, _Exchange(question: question, answer: answer));
        _question.clear();
      });
      if (_scrollController.hasClients) {
        await _scrollController.animateTo(
          0,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      }
    } on ApiException catch (error) {
      setState(() {
        _busy = false;
        _error = error.userMessage;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('assistant')),
        actions: [
          if (_session.isNotEmpty)
            IconButton(
              tooltip: context.t('close'),
              icon: const Icon(Icons.delete_sweep_outlined),
              onPressed: () => setState(_session.clear),
            ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: ListView(
              controller: _scrollController,
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
              children: [
                Notice(
                  kind: NoticeKind.ai,
                  title: context.t('ai_assisted'),
                  message: context.t('assistant_hint'),
                ),
                const SizedBox(height: 12),
                if (_error != null) ...[
                  ErrorState(message: _error!, onRetry: _ask),
                  const SizedBox(height: 12),
                ],
                if (_busy)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 28),
                    child: LoadingState(),
                  ),
                for (final exchange in _session) ...[
                  _QuestionBubble(text: exchange.question),
                  const SizedBox(height: 8),
                  _AnswerView(answer: exchange.answer),
                  const SizedBox(height: 20),
                ],
                if (_session.isEmpty && !_busy)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 24),
                    child: EmptyState(
                      title: context.t('ask_question'),
                      message: context.t('question_hint'),
                      icon: Icons.question_answer_outlined,
                    ),
                  ),
              ],
            ),
          ),
          SafeArea(
            top: false,
            child: Container(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
              decoration: BoxDecoration(
                color: Theme.of(context).colorScheme.surface,
                border: Border(
                  top: BorderSide(
                      color: Theme.of(context).colorScheme.outlineVariant),
                ),
              ),
              child: Column(
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: _question,
                          maxLines: 3,
                          minLines: 1,
                          textInputAction: TextInputAction.send,
                          onSubmitted: (_) => _ask(),
                          decoration: InputDecoration(
                              hintText: context.t('question_hint')),
                        ),
                      ),
                      const SizedBox(width: 8),
                      IconButton.filled(
                        onPressed: _busy ? null : _ask,
                        icon: const Icon(Icons.send),
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      Expanded(
                        child: InkWell(
                          // A plain row, not a ListTile: this area sits on a
                          // coloured surface, where a ListTile's own background
                          // painting is asserted against in debug builds.
                          onTap: context.session.isSignedIn
                              ? () => setState(
                                  () => _useFarmContext = !_useFarmContext)
                              : null,
                          child: Row(
                            children: [
                              Checkbox(
                                value: _useFarmContext,
                                onChanged: context.session.isSignedIn
                                    ? (value) => setState(
                                        () => _useFarmContext = value ?? false)
                                    : null,
                              ),
                              Expanded(
                                child: Text(
                                  context.t('farm_context_used'),
                                  style: Theme.of(context).textTheme.bodySmall,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                      DropdownButton<int>(
                        value: _topK,
                        underline: const SizedBox.shrink(),
                        items: const [3, 5, 8, 12]
                            .map(
                              (value) => DropdownMenuItem(
                                  value: value, child: Text('top $value')),
                            )
                            .toList(),
                        onChanged: (value) =>
                            setState(() => _topK = value ?? 5),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Exchange {
  const _Exchange({required this.question, required this.answer});

  final String question;
  final AssistantAnswer answer;
}

class _QuestionBubble extends StatelessWidget {
  const _QuestionBubble({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Align(
      alignment: Alignment.centerRight,
      child: Container(
        padding: const EdgeInsets.all(12),
        constraints: const BoxConstraints(maxWidth: 320),
        decoration: BoxDecoration(
          color: scheme.primaryContainer,
          borderRadius: const BorderRadius.only(
            topLeft: Radius.circular(14),
            topRight: Radius.circular(14),
            bottomLeft: Radius.circular(14),
          ),
        ),
        child: Text(text, style: TextStyle(color: scheme.onPrimaryContainer)),
      ),
    );
  }
}

class _AnswerView extends StatelessWidget {
  const _AnswerView({required this.answer});

  final AssistantAnswer answer;

  @override
  Widget build(BuildContext context) {
    return SectionCard(
      title: context.t('assistant'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (answer.insufficientEvidence)
            Notice(
              kind: NoticeKind.warning,
              title: context.t('insufficient_evidence'),
              message: answer.insufficientReason ??
                  'The knowledge base has nothing relevant to this question.',
            )
          else
            Row(
              children: [
                TrustChip(
                  label: 'ai_prediction',
                  description:
                      'Answer assembled from retrieved documents by the configured provider.',
                  compact: true,
                ),
                const SizedBox(width: 8),
                if (!answer.grounded)
                  MetaPill(
                    text: 'ungrounded',
                    color: Theme.of(context).colorScheme.error,
                  ),
              ],
            ),
          const SizedBox(height: 10),
          SelectableText(answer.answer,
              style: Theme.of(context).textTheme.bodyMedium),
          if (answer.citations.isNotEmpty) ...[
            const SizedBox(height: 14),
            Text(context.t('sources'),
                style: Theme.of(context).textTheme.labelLarge),
            const SizedBox(height: 4),
            ...answer.citations.map(
              (citation) => SourceLine(
                title: citation.title,
                subtitle: [
                  Fmt.humanize(citation.kind),
                  if (citation.sourceName != null) citation.sourceName!,
                  if (citation.verificationStatus != null)
                    Fmt.humanize(citation.verificationStatus!),
                  if (citation.score != null)
                    'score ${Fmt.score(citation.score, decimals: 3)}',
                ].whereType<String>().join(' · '),
                url: citation.sourceUrl,
              ),
            ),
          ] else if (!answer.insufficientEvidence) ...[
            const SizedBox(height: 10),
            Text(
              context.t('no_sources'),
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
          if (answer.guardrailFlags.isNotEmpty) ...[
            const SizedBox(height: 12),
            Notice(
              kind: NoticeKind.warning,
              title: context.t('warnings'),
              message: answer.guardrailFlags.map(Fmt.humanize).join(', '),
            ),
          ],
          const SizedBox(height: 12),
          Row(
            children: [
              DataClassChip(
                  value: answer.dataClass, label: 'AI-assisted answer'),
              const SizedBox(width: 8),
              if (answer.llmIsDemo)
                const DemoChip(
                  notice:
                      'The configured language-model provider is a demonstration provider; '
                      'answers are assembled from retrieved text rather than generated.',
                ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            [
              if (answer.llmProvider != null)
                '${context.t('ai_provider_disclosure')}: ${answer.llmProvider}',
              if (answer.llmModel != null) answer.llmModel!,
              if (answer.retrievalMethod != null)
                '${context.t('method_note')}: ${answer.retrievalMethod}',
              if (answer.sourceTypes.isNotEmpty)
                'sources: ${answer.sourceTypes.map(Fmt.humanize).join(', ')}',
            ].whereType<String>().join(' · '),
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
          if (answer.notices.isNotEmpty) ...[
            const SizedBox(height: 10),
            Notice(
              kind: NoticeKind.info,
              message: answer.notices.first,
              items: answer.notices.length > 1
                  ? answer.notices.sublist(1)
                  : const [],
            ),
          ],
          const SizedBox(height: 10),
          Text(answer.disclaimer, style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }
}
