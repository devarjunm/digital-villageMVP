import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/api_exception.dart';
import '../core/formatters.dart';
import '../core/l10n.dart';
import '../core/theme.dart';

/// Loads a future and renders loading / error / empty / data states consistently.
///
/// One widget for this instead of a `FutureBuilder` per screen, because the app
/// must handle three things everywhere: a readable error (with the backend's
/// request id, which makes a support conversation possible), a retry that
/// actually re-runs the request, and an empty state that explains itself.
class AsyncSection<T> extends StatefulWidget {
  const AsyncSection({
    super.key,
    required this.load,
    required this.builder,
    this.emptyBuilder,
    this.isEmpty,
    this.refreshTick = 0,
    this.silentRefresh = false,
    this.padding = const EdgeInsets.fromLTRB(16, 12, 16, 24),
  });

  final Future<T> Function() load;
  final Widget Function(
      BuildContext context, T data, Future<void> Function() reload) builder;
  final Widget Function(BuildContext context, Future<void> Function() reload)?
      emptyBuilder;
  final bool Function(T data)? isEmpty;
  final int refreshTick;
  final bool silentRefresh;
  final EdgeInsets padding;

  @override
  State<AsyncSection<T>> createState() => _AsyncSectionState<T>();
}

class _AsyncSectionState<T> extends State<AsyncSection<T>> {
  Future<T>? _future;

  @override
  void initState() {
    super.initState();
    _future = widget.load();
  }

  @override
  void didUpdateWidget(covariant AsyncSection<T> oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.refreshTick != oldWidget.refreshTick) {
      _reload();
    }
  }

  Future<void> _reload() async {
    final future = widget.load();
    setState(() {
      _future = future;
    });
    try {
      await future;
    } catch (_) {
      // The FutureBuilder renders snapshot.error; a manual refresh must not
      // throw into the framework.
    }
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<T>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting &&
            !snapshot.hasData) {
          return const Padding(
            padding: EdgeInsets.symmetric(vertical: 48),
            child: LoadingState(),
          );
        }
        if (snapshot.hasError) {
          return Padding(
            padding: widget.padding,
            child: ErrorState.fromError(
              snapshot.error,
              onRetry: _reload,
            ),
          );
        }
        final data = snapshot.data;
        if (data == null) {
          return Padding(
            padding: widget.padding,
            child: const LoadingState(),
          );
        }
        final isEmpty = widget.isEmpty?.call(data) ?? false;
        if (isEmpty && widget.emptyBuilder != null) {
          return Padding(
            padding: widget.padding,
            child: widget.emptyBuilder!(context, _reload),
          );
        }
        return widget.builder(context, data, _reload);
      },
    );
  }
}

class LoadingState extends StatelessWidget {
  const LoadingState({super.key, this.label});

  final String? label;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const SizedBox(
            width: 26,
            height: 26,
            child: CircularProgressIndicator(strokeWidth: 2.4),
          ),
          if (label != null) ...[
            const SizedBox(height: 12),
            Text(label!, style: Theme.of(context).textTheme.bodySmall),
          ],
        ],
      ),
    );
  }
}

/// Error display that always tells the user what happened and offers a retry.
class ErrorState extends StatelessWidget {
  const ErrorState(
      {super.key, required this.message, this.detail, this.onRetry});

  factory ErrorState.fromError(Object? error,
      {Future<void> Function()? onRetry}) {
    if (error is ApiException) {
      final bits = <String>[];
      if (error.requestId != null) {
        bits.add(
            'request ${error.requestId!.substring(0, math.min(8, error.requestId!.length))}');
      }
      if (error.fieldErrors.isNotEmpty) {
        bits.add(
          error.fieldErrors.entries
              .map((e) => '${Fmt.humanize(e.key)}: ${e.value}')
              .join('\n'),
        );
      }
      return ErrorState(
        message: error.userMessage,
        detail: bits.isEmpty ? null : bits.join('\n'),
        onRetry: onRetry,
      );
    }
    return ErrorState(
      message: error?.toString() ?? 'Unexpected error',
      detail: null,
      onRetry: onRetry,
    );
  }

  final String message;
  final String? detail;
  final Future<void> Function()? onRetry;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: scheme.errorContainer.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: scheme.error.withValues(alpha: 0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.error_outline, color: scheme.error, size: 20),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  message,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                ),
              ),
            ],
          ),
          if (detail != null) ...[
            const SizedBox(height: 8),
            SelectableText(
              detail!,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: scheme.onErrorContainer,
                  ),
            ),
          ],
          if (onRetry != null) ...[
            const SizedBox(height: 12),
            Align(
              alignment: Alignment.centerLeft,
              child: OutlinedButton.icon(
                onPressed: () => onRetry!(),
                icon: const Icon(Icons.refresh, size: 18),
                label: Text(context.t('retry')),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    required this.title,
    this.message,
    this.icon = Icons.inbox_outlined,
    this.action,
  });

  final String title;
  final String? message;
  final IconData icon;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: scheme.outlineVariant),
        color: scheme.surfaceContainerHighest.withValues(alpha: 0.25),
      ),
      child: Column(
        children: [
          Icon(icon, size: 30, color: scheme.onSurfaceVariant),
          const SizedBox(height: 10),
          Text(
            title,
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.titleSmall,
          ),
          if (message != null) ...[
            const SizedBox(height: 6),
            Text(
              message!,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: scheme.onSurfaceVariant,
                  ),
            ),
          ],
          if (action != null) ...[const SizedBox(height: 14), action!],
        ],
      ),
    );
  }
}

enum NoticeKind { info, success, warning, danger, ai, demo }

/// A banner for disclosures: provider notices, disclaimers, data-class labels,
/// and the demo-data flags the backend sends. The app shows these verbatim —
/// rewriting a provider warning into friendlier marketing copy would defeat it.
class Notice extends StatelessWidget {
  const Notice({
    super.key,
    required this.message,
    this.title,
    this.kind = NoticeKind.info,
    this.items = const [],
    this.icon,
  });

  final String message;
  final String? title;
  final NoticeKind kind;
  final List<String> items;
  final IconData? icon;

  (Color, Color, IconData) _style(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return switch (kind) {
      NoticeKind.info => (
          scheme.surfaceContainerHighest,
          scheme.onSurfaceVariant,
          Icons.info_outline
        ),
      NoticeKind.success => (
          const Color(0xFFE3F3E6),
          const Color(0xFF1F6F3F),
          Icons.check_circle_outline,
        ),
      NoticeKind.warning => (
          const Color(0xFFFFF3E0),
          const Color(0xFF9A5B00),
          Icons.warning_amber_outlined,
        ),
      NoticeKind.danger => (
          scheme.errorContainer,
          scheme.error,
          Icons.error_outline
        ),
      NoticeKind.ai => (
          const Color(0xFFF1E9FF),
          const Color(0xFF5B3FA0),
          Icons.auto_awesome_outlined,
        ),
      NoticeKind.demo => (
          const Color(0xFFEDEDED),
          const Color(0xFF4A4A4A),
          Icons.science_outlined,
        ),
    };
  }

  @override
  Widget build(BuildContext context) {
    final (background, foreground, defaultIcon) = _style(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: foreground.withValues(alpha: 0.25)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon ?? defaultIcon, size: 18, color: foreground),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (title != null)
                  Text(
                    title!,
                    style: Theme.of(context).textTheme.labelLarge?.copyWith(
                          color: foreground,
                          fontWeight: FontWeight.w700,
                        ),
                  ),
                if (title != null) const SizedBox(height: 3),
                Text(
                  message,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: foreground,
                        height: 1.35,
                      ),
                ),
                if (items.isNotEmpty) ...[
                  const SizedBox(height: 6),
                  ...items.map(
                    (item) => Padding(
                      padding: const EdgeInsets.only(bottom: 3),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('• ', style: TextStyle(color: foreground)),
                          Expanded(
                            child: Text(
                              item,
                              style: Theme.of(context)
                                  .textTheme
                                  .bodySmall
                                  ?.copyWith(
                                    color: foreground,
                                  ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Marks data the backend flagged as demonstration/synthetic.
class DemoChip extends StatelessWidget {
  const DemoChip({super.key, this.notice});

  final String? notice;

  @override
  Widget build(BuildContext context) {
    final chip = Chip(
      avatar: const Icon(Icons.science_outlined, size: 15),
      label: Text(context.t('demo_data')),
      visualDensity: VisualDensity.compact,
      backgroundColor: const Color(0xFFEDEDED),
      side: const BorderSide(color: Color(0xFFBDBDBD)),
    );
    if (notice == null || notice!.isEmpty) return chip;
    return Tooltip(message: notice!, child: chip);
  }
}

/// The community/judgement label vocabulary. Colour is per-label and the tooltip
/// carries the API's own description, so the meaning is never colour-only.
class TrustChip extends StatelessWidget {
  const TrustChip(
      {super.key, required this.label, this.description, this.compact = false});

  final String label;
  final String? description;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final color =
        AppTheme.trustColors[label] ?? Theme.of(context).colorScheme.primary;
    final text = Fmt.humanize(label);
    final content = Container(
      padding: EdgeInsets.symmetric(
          horizontal: compact ? 8 : 10, vertical: compact ? 3 : 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(_iconFor(label), size: compact ? 12 : 14, color: color),
          const SizedBox(width: 5),
          Text(
            text,
            style: TextStyle(
              color: color,
              fontSize: compact ? 11 : 12,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
    if (description == null || description!.isEmpty) return content;
    return Tooltip(message: description!, child: content);
  }

  static IconData _iconFor(String label) => switch (label) {
        'expert_information' => Icons.verified_outlined,
        'official_information' => Icons.account_balance_outlined,
        'ai_prediction' => Icons.auto_awesome_outlined,
        'community_supported' => Icons.groups_outlined,
        _ => Icons.person_outline,
      };
}

/// Shows whether a value is a measured observation, an official figure or a
/// model output. The distinction matters more than any styling.
class DataClassChip extends StatelessWidget {
  const DataClassChip({super.key, required this.value, this.label});

  final String? value;
  final String? label;

  @override
  Widget build(BuildContext context) {
    final dataClass = value;
    if (dataClass == null || dataClass.isEmpty) return const SizedBox.shrink();
    final color = DataClassColors.forValue(dataClass) ??
        Theme.of(context).colorScheme.outline;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Text(
        label ?? Fmt.humanize(dataClass),
        style: TextStyle(
            color: color, fontSize: 11.5, fontWeight: FontWeight.w600),
      ),
    );
  }
}

/// A source line: name, url and a copy action. URLs are shown as text because
/// opening them requires a browser intent the app deliberately does not add a
/// dependency for; the user can copy and open it themselves.
class SourceLine extends StatelessWidget {
  const SourceLine(
      {super.key, required this.title, this.subtitle, this.url, this.trailing});

  final String title;
  final String? subtitle;
  final String? url;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.link, size: 16, color: scheme.onSurfaceVariant),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: Theme.of(context).textTheme.bodyMedium),
                if (subtitle != null)
                  Text(
                    subtitle!,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: scheme.onSurfaceVariant,
                        ),
                  ),
                if (url != null && url!.isNotEmpty)
                  SelectableText(
                    url!,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: scheme.primary,
                        ),
                  ),
              ],
            ),
          ),
          if (url != null && url!.isNotEmpty)
            IconButton(
              tooltip: context.t('copy'),
              iconSize: 18,
              onPressed: () async {
                await Clipboard.setData(ClipboardData(text: url!));
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text(context.t('copied'))),
                  );
                }
              },
              icon: const Icon(Icons.copy_all_outlined),
            ),
          if (trailing != null) trailing!,
        ],
      ),
    );
  }
}

class SectionCard extends StatelessWidget {
  const SectionCard({
    super.key,
    this.title,
    this.subtitle,
    this.trailing,
    required this.child,
    this.padding = const EdgeInsets.all(14),
    this.dense = false,
  });

  final String? title;
  final String? subtitle;
  final Widget? trailing;
  final Widget child;
  final EdgeInsets padding;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: padding,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (title != null)
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          title!,
                          style:
                              Theme.of(context).textTheme.titleSmall?.copyWith(
                                    fontWeight: FontWeight.w700,
                                  ),
                        ),
                        if (subtitle != null)
                          Padding(
                            padding: const EdgeInsets.only(top: 2),
                            child: Text(
                              subtitle!,
                              style: Theme.of(context)
                                  .textTheme
                                  .bodySmall
                                  ?.copyWith(
                                    color: Theme.of(context)
                                        .colorScheme
                                        .onSurfaceVariant,
                                  ),
                            ),
                          ),
                      ],
                    ),
                  ),
                  if (trailing != null) trailing!,
                ],
              ),
            if (title != null) SizedBox(height: dense ? 8 : 12),
            child,
          ],
        ),
      ),
    );
  }
}

class InfoRow extends StatelessWidget {
  const InfoRow(
      {super.key, required this.label, required this.value, this.wrap = true});

  final String label;
  final String value;
  final bool wrap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 132,
            child: Text(
              label,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: scheme.onSurfaceVariant,
                  ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: Theme.of(context).textTheme.bodyMedium,
              softWrap: wrap,
            ),
          ),
        ],
      ),
    );
  }
}

class StatTile extends StatelessWidget {
  const StatTile({
    super.key,
    required this.label,
    required this.value,
    this.hint,
    this.icon,
  });

  final String label;
  final String value;
  final String? hint;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: scheme.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              if (icon != null) ...[
                Icon(icon, size: 16, color: scheme.primary),
                const SizedBox(width: 6),
              ],
              Expanded(
                child: Text(
                  label,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: scheme.onSurfaceVariant,
                      ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            value,
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
          ),
          if (hint != null)
            Padding(
              padding: const EdgeInsets.only(top: 3),
              child: Text(
                hint!,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: scheme.onSurfaceVariant,
                    ),
              ),
            ),
        ],
      ),
    );
  }
}

/// A labelled text field with consistent spacing and error styling.
class FormTextField extends StatelessWidget {
  const FormTextField({
    super.key,
    required this.label,
    required this.controller,
    this.hint,
    this.helper,
    this.keyboardType,
    this.maxLines = 1,
    this.obscure = false,
    this.required = false,
    this.suffix,
    this.onChanged,
    this.enabled = true,
    this.textInputAction,
  });

  final String label;
  final TextEditingController controller;
  final String? hint;
  final String? helper;
  final TextInputType? keyboardType;
  final int maxLines;
  final bool obscure;
  final bool required;
  final Widget? suffix;
  final ValueChanged<String>? onChanged;
  final bool enabled;
  final TextInputAction? textInputAction;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(label, style: Theme.of(context).textTheme.labelLarge),
              if (required)
                Text(
                  ' *',
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
            ],
          ),
          const SizedBox(height: 6),
          TextField(
            controller: controller,
            keyboardType: keyboardType,
            maxLines: obscure ? 1 : maxLines,
            obscureText: obscure,
            enabled: enabled,
            onChanged: onChanged,
            textInputAction: textInputAction,
            decoration: InputDecoration(hintText: hint, suffixIcon: suffix),
          ),
          if (helper != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                helper!,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
            ),
        ],
      ),
    );
  }
}

/// Dropdown over a list of API-provided string values.
class DropdownField<T> extends StatelessWidget {
  const DropdownField({
    super.key,
    required this.label,
    required this.value,
    required this.items,
    required this.onChanged,
    this.labelBuilder,
    this.helper,
    this.allowNull = true,
    this.enabled = true,
  });

  final String label;
  final T? value;
  final List<T> items;
  final ValueChanged<T?> onChanged;
  final String Function(T item)? labelBuilder;
  final String? helper;
  final bool allowNull;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: Theme.of(context).textTheme.labelLarge),
          const SizedBox(height: 6),
          DropdownButtonFormField<T>(
            initialValue: value,
            isExpanded: true,
            items: [
              if (allowNull)
                DropdownMenuItem<T>(
                  value: null,
                  child: Text(context.t('all'),
                      style: const TextStyle(fontSize: 14)),
                ),
              ...items.map(
                (item) => DropdownMenuItem<T>(
                  value: item,
                  child: Text(
                    labelBuilder?.call(item) ?? Fmt.humanize(item.toString()),
                    style: const TextStyle(fontSize: 14),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ),
            ],
            onChanged: enabled ? onChanged : null,
          ),
          if (helper != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                helper!,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
            ),
        ],
      ),
    );
  }
}

class ChoiceChipRow<T> extends StatelessWidget {
  const ChoiceChipRow({
    super.key,
    required this.options,
    required this.selected,
    required this.onSelected,
    this.labelBuilder,
  });

  final List<T> options;
  final T? selected;
  final ValueChanged<T?> onSelected;
  final String Function(T option)? labelBuilder;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: options.map((option) {
        final isSelected = option == selected;
        return ChoiceChip(
          label: Text(
              labelBuilder?.call(option) ?? Fmt.humanize(option.toString())),
          selected: isSelected,
          onSelected: (value) => onSelected(value ? option : null),
        );
      }).toList(),
    );
  }
}

/// Submit button that disables itself while the request is in flight, so a
/// double tap cannot create two farms or two posts.
class BusyButton extends StatelessWidget {
  const BusyButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.busy = false,
    this.icon,
    this.expand = true,
  });

  final String label;
  final VoidCallback? onPressed;
  final bool busy;
  final IconData? icon;
  final bool expand;

  @override
  Widget build(BuildContext context) {
    final button = FilledButton.icon(
      onPressed: busy ? null : onPressed,
      icon: busy
          ? const SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : Icon(icon ?? Icons.check, size: 18),
      label: Text(busy ? context.t('loading') : label),
    );
    return expand ? SizedBox(width: double.infinity, child: button) : button;
  }
}

/// A score bar used for model output. The caption always states what the number
/// is, so a bar chart cannot be mistaken for a probability.
class ScoreBar extends StatelessWidget {
  const ScoreBar({
    super.key,
    required this.label,
    required this.value,
    required this.maxValue,
    this.caption,
    this.highlight = false,
  });

  final String label;
  final double value;
  final double maxValue;
  final String? caption;
  final bool highlight;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final fraction = maxValue <= 0 ? 0.0 : (value / maxValue).clamp(0.0, 1.0);
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  label,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        fontWeight:
                            highlight ? FontWeight.w700 : FontWeight.w500,
                      ),
                ),
              ),
              Text(
                Fmt.score(value),
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  fontFeatures: const [FontFeature.tabularFigures()],
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: LinearProgressIndicator(
              value: fraction,
              minHeight: 8,
              backgroundColor: scheme.surfaceContainerHighest,
            ),
          ),
          if (caption != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                caption!,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: scheme.onSurfaceVariant,
                    ),
              ),
            ),
        ],
      ),
    );
  }
}

/// Collapses long post/answer bodies to a few lines with a "more" affordance.
class ExpandableText extends StatefulWidget {
  const ExpandableText(this.text, {super.key, this.maxLines = 6, this.style});

  final String text;
  final int maxLines;
  final TextStyle? style;

  @override
  State<ExpandableText> createState() => _ExpandableTextState();
}

class _ExpandableTextState extends State<ExpandableText> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final painter = TextPainter(
          text: TextSpan(
              text: widget.text,
              style: widget.style ?? DefaultTextStyle.of(context).style),
          maxLines: widget.maxLines,
          textDirection: Directionality.of(context),
        )..layout(maxWidth: constraints.maxWidth);
        final overflows = painter.didExceedMaxLines;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              widget.text,
              style: widget.style,
              maxLines: _expanded ? null : widget.maxLines,
              overflow:
                  _expanded ? TextOverflow.visible : TextOverflow.ellipsis,
            ),
            if (overflows)
              TextButton(
                style: TextButton.styleFrom(
                  padding: EdgeInsets.zero,
                  minimumSize: const Size(0, 32),
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                ),
                onPressed: () => setState(() => _expanded = !_expanded),
                child: Text(
                    _expanded ? context.t('close') : context.t('view_all')),
              ),
          ],
        );
      },
    );
  }
}

/// Minimal price sparkline: observed prices as a solid line, model estimates as
/// a dotted line, so the two are never mixed up. Written by hand to avoid adding
/// a charting dependency for one widget.
class PriceSparkline extends StatelessWidget {
  const PriceSparkline({
    super.key,
    required this.values,
    required this.labels,
    this.height = 150,
    this.estimatesFrom,
  });

  final List<double?> values;
  final List<String> labels;
  final double height;

  /// Index from which points are estimates (drawn dotted).
  final int? estimatesFrom;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    if (values.where((v) => v != null).isEmpty) {
      return SizedBox(
        height: height,
        child: Center(
          child: Text(
            context.t('no_prices'),
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
      );
    }
    return SizedBox(
      height: height,
      child: CustomPaint(
        painter: _SparklinePainter(
          values: values,
          labels: labels,
          lineColor: scheme.primary,
          estimateColor: const Color(0xFF9A5B00),
          gridColor: scheme.outlineVariant,
          textColor: scheme.onSurfaceVariant,
          estimatesFrom: estimatesFrom,
        ),
        size: Size.infinite,
      ),
    );
  }
}

class _SparklinePainter extends CustomPainter {
  _SparklinePainter({
    required this.values,
    required this.labels,
    required this.lineColor,
    required this.estimateColor,
    required this.gridColor,
    required this.textColor,
    this.estimatesFrom,
  });

  final List<double?> values;
  final List<String> labels;
  final Color lineColor;
  final Color estimateColor;
  final Color gridColor;
  final Color textColor;
  final int? estimatesFrom;

  @override
  void paint(Canvas canvas, Size size) {
    const leftPad = 8.0;
    const rightPad = 8.0;
    const topPad = 10.0;
    const bottomPad = 26.0;
    final chartWidth = size.width - leftPad - rightPad;
    final chartHeight = size.height - topPad - bottomPad;

    final present = values.whereType<double>().toList();
    if (present.isEmpty) return;
    var minValue = present.reduce(math.min);
    var maxValue = present.reduce(math.max);
    if (minValue == maxValue) {
      minValue -= 1;
      maxValue += 1;
    }
    final range = maxValue - minValue;

    Offset pointAt(int index, double value) {
      final denominator = math.max(values.length - 1, 1);
      final x = leftPad + chartWidth * (index / denominator);
      final y = topPad + chartHeight * (1 - (value - minValue) / range);
      return Offset(x, y);
    }

    // Grid: min and max reference lines.
    final gridPaint = Paint()
      ..color = gridColor
      ..strokeWidth = 1;
    canvas.drawLine(
      const Offset(leftPad, topPad),
      Offset(leftPad + chartWidth, topPad),
      gridPaint,
    );
    canvas.drawLine(
      Offset(leftPad, topPad + chartHeight),
      Offset(leftPad + chartWidth, topPad + chartHeight),
      gridPaint,
    );

    final splitIndex = estimatesFrom ?? values.length;

    void paintSeries(int from, int to, Color color, bool dotted) {
      final paint = Paint()
        ..color = color
        ..strokeWidth = 2.2
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round;
      Offset? previous;
      for (var index = from; index < to && index < values.length; index++) {
        final value = values[index];
        if (value == null) continue;
        final current = pointAt(index, value);
        if (previous != null) {
          if (dotted) {
            _dashedLine(canvas, previous, current, paint);
          } else {
            canvas.drawLine(previous, current, paint);
          }
        }
        canvas.drawCircle(current, 2.6, Paint()..color = color);
        previous = current;
      }
    }

    paintSeries(0, math.min(splitIndex + 1, values.length), lineColor, false);
    if (splitIndex < values.length) {
      paintSeries(splitIndex, values.length, estimateColor, true);
    }

    // Value labels: first, last and extremes, to keep the chart readable.
    void drawLabel(String text, Offset at,
        {TextAlign align = TextAlign.center}) {
      final painter = TextPainter(
        text: TextSpan(
          text: text,
          style: TextStyle(color: textColor, fontSize: 10.5),
        ),
        textDirection: TextDirection.ltr,
        textAlign: align,
      )..layout();
      var dx = at.dx - painter.width / 2;
      dx = dx.clamp(0.0, size.width - painter.width);
      painter.paint(canvas, Offset(dx, at.dy));
    }

    final lastIndex = values.lastIndexWhere((value) => value != null);
    if (lastIndex >= 0) {
      drawLabel(
        '₹${Fmt.number(values[lastIndex], decimals: 0)}',
        pointAt(lastIndex, values[lastIndex]!) - const Offset(0, 18),
      );
    }
    final firstIndex = values.indexWhere((value) => value != null);
    if (firstIndex >= 0 && firstIndex != lastIndex) {
      drawLabel(
        '₹${Fmt.number(values[firstIndex], decimals: 0)}',
        pointAt(firstIndex, values[firstIndex]!) + const Offset(0, 8),
      );
    }
    // X labels: first and last only, because the chart is narrow on a phone.
    if (labels.isNotEmpty && firstIndex >= 0) {
      drawLabel(labels[firstIndex],
          Offset(pointAt(firstIndex, minValue).dx, size.height - 18));
      drawLabel(labels[labels.length - 1],
          Offset(pointAt(lastIndex, minValue).dx, size.height - 18));
    }
  }

  void _dashedLine(Canvas canvas, Offset from, Offset to, Paint paint) {
    const dash = 6.0;
    const gap = 4.0;
    final total = (to - from).distance;
    if (total == 0) return;
    final direction = (to - from) / total;
    var travelled = 0.0;
    while (travelled < total) {
      final start = from + direction * travelled;
      final end = from + direction * math.min(travelled + dash, total);
      canvas.drawLine(start, end, paint);
      travelled += dash + gap;
    }
  }

  @override
  bool shouldRepaint(covariant _SparklinePainter oldDelegate) =>
      oldDelegate.values != values ||
      oldDelegate.estimatesFrom != estimatesFrom ||
      oldDelegate.lineColor != lineColor;
}

/// Small pill for enum-ish metadata (season, stage, status).
class MetaPill extends StatelessWidget {
  const MetaPill({super.key, required this.text, this.icon, this.color});

  final String text;
  final IconData? icon;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final effective = color ?? scheme.onSurfaceVariant;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
      decoration: BoxDecoration(
        color: effective.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: effective.withValues(alpha: 0.25)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 12, color: effective),
            const SizedBox(width: 4),
          ],
          Text(
            text,
            style: TextStyle(
                fontSize: 11.5, color: effective, fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }
}
