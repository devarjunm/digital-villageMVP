import 'package:flutter/material.dart';

import '../../app.dart';
import '../../core/api_exception.dart';
import '../../core/formatters.dart';
import '../../models/ai.dart';
import '../../models/farm.dart';
import '../../widgets/common.dart';

/// Crop recommendation (`POST /ai/crop-recommendation`).
///
/// Two things this screen refuses to do: present the ranked scores as
/// probabilities (the serving model reports `relative_model_score`), and invent
/// missing inputs. If the API reports inputs it had to default, they are listed
/// under "Inputs used" with their source.
class CropRecommendationScreen extends StatefulWidget {
  const CropRecommendationScreen({super.key});

  @override
  State<CropRecommendationScreen> createState() =>
      _CropRecommendationScreenState();
}

class _CropRecommendationScreenState extends State<CropRecommendationScreen> {
  final _nitrogen = TextEditingController();
  final _phosphorus = TextEditingController();
  final _potassium = TextEditingController();
  final _temperature = TextEditingController();
  final _humidity = TextEditingController();
  final _ph = TextEditingController();
  final _rainfall = TextEditingController();

  String? _farmId;
  String _season = 'kharif';
  String _soilType = 'unknown';
  int _topK = 3;

  List<Farm> _farms = const [];
  bool _farmsLoading = true;
  String? _prefillNote;
  bool _busy = false;
  CropRecommendation? _result;
  String? _error;
  String? _feedbackSent;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadFarms());
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final arguments = ModalRoute.of(context)?.settings.arguments;
    if (arguments is Map && arguments['farmId'] is String && _farmId == null) {
      _farmId = arguments['farmId'] as String;
      WidgetsBinding.instance
          .addPostFrameCallback((_) => _prefillFromFarm(_farmId!));
    }
  }

  @override
  void dispose() {
    _nitrogen.dispose();
    _phosphorus.dispose();
    _potassium.dispose();
    _temperature.dispose();
    _humidity.dispose();
    _ph.dispose();
    _rainfall.dispose();
    super.dispose();
  }

  Future<void> _loadFarms() async {
    if (!context.session.isSignedIn) {
      setState(() => _farmsLoading = false);
      return;
    }
    try {
      final farms = await context.repos.farms.list();
      if (!mounted) return;
      setState(() {
        _farms = farms;
        _farmsLoading = false;
        _farmId ??= farms.isNotEmpty ? farms.first.id : null;
      });
      if (_farmId != null) await _prefillFromFarm(_farmId!);
    } on ApiException {
      if (mounted) setState(() => _farmsLoading = false);
    }
  }

  /// Copies the newest soil test and the farm's own soil type/pH into the form.
  /// Values are only filled when the farm actually has them.
  Future<void> _prefillFromFarm(String farmId) async {
    try {
      final summary = await context.repos.farms.summary(farmId);
      if (!mounted) return;
      final test = summary.latestSoilTest;
      final notes = <String>[];
      if (test != null) {
        if (test.nitrogen != null) {
          _nitrogen.text = test.nitrogen!.toStringAsFixed(1);
        }
        if (test.phosphorus != null) {
          _phosphorus.text = test.phosphorus!.toStringAsFixed(1);
        }
        if (test.potassium != null) {
          _potassium.text = test.potassium!.toStringAsFixed(1);
        }
        if (test.ph != null) _ph.text = test.ph!.toStringAsFixed(2);
        notes.add(
            '${context.t('latest_soil_test')}: ${Fmt.date(test.testedOn)}');
      }
      if (summary.farm.soilPh != null && _ph.text.isEmpty) {
        _ph.text = summary.farm.soilPh!.toStringAsFixed(2);
      }
      setState(() {
        _soilType = summary.farm.soilType;
        _prefillNote = notes.isEmpty ? null : notes.join(' · ');
      });
    } on ApiException {
      // Prefill is a convenience; the form stays usable without it.
    }
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
      _result = null;
      _feedbackSent = null;
    });
    try {
      final body = <String, dynamic>{
        'nitrogen': double.tryParse(_nitrogen.text.trim()),
        'phosphorus': double.tryParse(_phosphorus.text.trim()),
        'potassium': double.tryParse(_potassium.text.trim()),
        'temperature_c': double.tryParse(_temperature.text.trim()),
        'humidity_percent': double.tryParse(_humidity.text.trim()),
        'ph': double.tryParse(_ph.text.trim()),
        'rainfall_mm': double.tryParse(_rainfall.text.trim()),
        'soil_type': _soilType == 'unknown' ? null : _soilType,
        'season': _season,
        'top_k': _topK,
        if (_farmId != null) 'farm_id': _farmId,
      }..removeWhere((key, value) => value == null);

      final result = await context.repos.ai.cropRecommendation(body);
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
    final languageCode = context.session.languageCode;
    return Scaffold(
      appBar: AppBar(title: Text(context.t('crop_recommendation'))),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
        children: [
          Notice(
            kind: NoticeKind.ai,
            title: context.t('ai_assisted'),
            message: context.t('crop_recommendation_hint'),
          ),
          const SizedBox(height: 14),
          SectionCard(
            title: context.t('inputs_used'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (_farmsLoading)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 12),
                    child: LoadingState(),
                  )
                else if (_farms.isNotEmpty)
                  DropdownField<String>(
                    label: context.t('nav_farm'),
                    value: _farmId,
                    items: _farms.map((farm) => farm.id).toList(),
                    labelBuilder: (id) =>
                        _farms.firstWhere((farm) => farm.id == id).name,
                    allowNull: false,
                    onChanged: (value) {
                      setState(() => _farmId = value);
                      if (value != null) _prefillFromFarm(value);
                    },
                  ),
                if (_prefillNote != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: Notice(
                      kind: NoticeKind.info,
                      message:
                          '${context.t('use_soil_test_values')} — $_prefillNote',
                    ),
                  ),
                Row(
                  children: [
                    Expanded(
                      child: _NumberInput(
                        label: '${context.t('nitrogen')} (kg/ha)',
                        controller: _nitrogen,
                        hint: '90',
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: _NumberInput(
                        label: '${context.t('phosphorus')} (kg/ha)',
                        controller: _phosphorus,
                        hint: '42',
                      ),
                    ),
                  ],
                ),
                Row(
                  children: [
                    Expanded(
                      child: _NumberInput(
                        label: '${context.t('potassium')} (kg/ha)',
                        controller: _potassium,
                        hint: '43',
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: _NumberInput(
                        label: context.t('soil_ph'),
                        controller: _ph,
                        hint: '6.5',
                      ),
                    ),
                  ],
                ),
                Row(
                  children: [
                    Expanded(
                      child: _NumberInput(
                        label: '${context.t('temperature')} (°C)',
                        controller: _temperature,
                        hint: '26.5',
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: _NumberInput(
                        label: '${context.t('humidity')} (%)',
                        controller: _humidity,
                        hint: '82',
                      ),
                    ),
                  ],
                ),
                Row(
                  children: [
                    Expanded(
                      child: _NumberInput(
                        label: '${context.t('rainfall')} (mm)',
                        controller: _rainfall,
                        hint: '180',
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: DropdownField<int>(
                        label: 'Top K',
                        value: _topK,
                        items: const [3, 5, 10],
                        allowNull: false,
                        labelBuilder: (value) => '$value',
                        onChanged: (value) =>
                            setState(() => _topK = value ?? 3),
                      ),
                    ),
                  ],
                ),
                DropdownField<String>(
                  label: context.t('season'),
                  value: _season,
                  items: const ['kharif', 'rabi', 'zaid', 'perennial'],
                  allowNull: true,
                  onChanged: (value) =>
                      setState(() => _season = value ?? 'kharif'),
                ),
                DropdownField<String>(
                  label: context.t('soil_type'),
                  value: _soilType,
                  items: const [
                    'unknown',
                    'alluvial',
                    'black_cotton',
                    'red',
                    'laterite',
                    'sandy',
                    'clay',
                    'loamy',
                    'saline',
                    'mixed',
                  ],
                  allowNull: false,
                  onChanged: (value) =>
                      setState(() => _soilType = value ?? 'unknown'),
                ),
                Text(
                  'Leave a value empty if you do not know it — the API reports which inputs it had to default instead of inventing them.',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                ),
                const SizedBox(height: 14),
                BusyButton(
                  label: context.t('submit'),
                  busy: _busy,
                  icon: Icons.auto_awesome,
                  onPressed: _submit,
                ),
              ],
            ),
          ),
          if (_error != null) ...[
            const SizedBox(height: 14),
            ErrorState(message: _error!, onRetry: _submit),
          ],
          if (_result != null) ...[
            const SizedBox(height: 14),
            _RecommendationView(
              result: _result!,
              languageCode: languageCode,
              feedbackSent: _feedbackSent,
              onFeedback: (verdict) async {
                await context.repos.ai.feedback(
                  aiRequestId: _result!.requestId ?? _result!.modelVersion,
                  verdict: verdict,
                );
                if (mounted) setState(() => _feedbackSent = verdict);
              },
            ),
          ],
        ],
      ),
    );
  }
}

class _NumberInput extends StatelessWidget {
  const _NumberInput(
      {required this.label, required this.controller, this.hint});

  final String label;
  final TextEditingController controller;
  final String? hint;

  @override
  Widget build(BuildContext context) {
    return FormTextField(
      label: label,
      controller: controller,
      hint: hint,
      keyboardType: const TextInputType.numberWithOptions(decimal: true),
    );
  }
}

class _RecommendationView extends StatelessWidget {
  const _RecommendationView({
    required this.result,
    required this.languageCode,
    required this.onFeedback,
    this.feedbackSent,
  });

  final CropRecommendation result;
  final String languageCode;
  final Future<void> Function(String verdict) onFeedback;
  final String? feedbackSent;

  @override
  Widget build(BuildContext context) {
    final topScore = result.ranked.isEmpty
        ? 1.0
        : result.ranked
            .map((crop) => crop.score)
            .reduce((a, b) => a > b ? a : b);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionCard(
          title: context.t('predicted_labels'),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: result.ranked
                .map(
                  (crop) => ScoreBar(
                    label: '${crop.rank}. ${crop.localizedName(languageCode)}',
                    value: crop.score,
                    maxValue: topScore,
                    highlight: crop.rank == 1,
                    caption:
                        crop.envelopeNote.isEmpty ? null : crop.envelopeNote,
                  ),
                )
                .toList(),
          ),
        ),
        const SizedBox(height: 14),
        SectionCard(
          title: context.t('how_it_was_produced'),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              InfoRow(label: context.t('model_used'), value: result.modelName),
              InfoRow(
                  label: context.t('model_version'),
                  value: result.modelVersion),
              InfoRow(label: context.t('score_type'), value: result.scoreType),
              const SizedBox(height: 6),
              Notice(
                kind: result.scoreIsProbability
                    ? NoticeKind.info
                    : NoticeKind.warning,
                message: result.scoreTypeNote,
              ),
              const SizedBox(height: 8),
              Text(result.confidenceInterpretation,
                  style: Theme.of(context).textTheme.bodySmall),
              const SizedBox(height: 10),
              Text(
                context.t('inputs_used'),
                style: Theme.of(context).textTheme.labelLarge,
              ),
              const SizedBox(height: 4),
              ...result.inputsUsed.entries.map(
                (entry) => InfoRow(
                  label: Fmt.humanize(entry.key),
                  value:
                      '${entry.value}${_unitSuffix(result.inputUnits[entry.key])}',
                ),
              ),
              if (result.inputSources.isNotEmpty) ...[
                const SizedBox(height: 10),
                Text(
                  context.t('input_sources'),
                  style: Theme.of(context).textTheme.labelLarge,
                ),
                const SizedBox(height: 4),
                ...result.inputSources.entries.map(
                  (entry) => InfoRow(
                    label: Fmt.humanize(entry.key),
                    value: entry.value.toString(),
                  ),
                ),
              ],
              if (result.isDemoDataset) ...[
                const SizedBox(height: 10),
                const DemoChip(
                  notice:
                      'The model behind this result was trained on the development dataset.',
                ),
              ],
            ],
          ),
        ),
        if (result.warnings.isNotEmpty) ...[
          const SizedBox(height: 14),
          Notice(
            kind: NoticeKind.warning,
            title: context.t('warnings'),
            message: result.warnings.first,
            items: result.warnings.length > 1
                ? result.warnings.sublist(1)
                : const [],
          ),
        ],
        if (result.limitations.isNotEmpty) ...[
          const SizedBox(height: 14),
          Notice(
            kind: NoticeKind.info,
            title: context.t('limitations'),
            message: result.limitations.first,
            items: result.limitations.length > 1
                ? result.limitations.sublist(1)
                : const [],
          ),
        ],
        const SizedBox(height: 14),
        Notice(kind: NoticeKind.ai, message: result.disclaimer),
        const SizedBox(height: 10),
        _FeedbackRow(
          sent: feedbackSent,
          onFeedback: onFeedback,
          extraInfo: [
            if (result.latencyMs != null)
              '${context.t('latency')}: ${result.latencyMs} ms',
            if (result.requestId != null)
              '${context.t('request_id')}: ${result.requestId}',
          ].join(' · '),
        ),
      ],
    );
  }

  static String _unitSuffix(Object? unit) {
    if (unit == null) return '';
    final text = unit.toString();
    return text.isEmpty ? '' : ' $text';
  }
}

class _FeedbackRow extends StatelessWidget {
  const _FeedbackRow(
      {required this.sent, required this.onFeedback, this.extraInfo});

  final String? sent;
  final Future<void> Function(String verdict) onFeedback;
  final String? extraInfo;

  @override
  Widget build(BuildContext context) {
    if (sent != null) {
      return Notice(
          kind: NoticeKind.success, message: context.t('feedback_thanks'));
    }
    return SectionCard(
      title: context.t('how_it_was_produced'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            context.t('feedback_consent_note'),
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              OutlinedButton.icon(
                onPressed: () => onFeedback('helpful'),
                icon: const Icon(Icons.thumb_up_outlined, size: 16),
                label: Text(context.t('feedback_helpful')),
              ),
              OutlinedButton.icon(
                onPressed: () => onFeedback('not_helpful'),
                icon: const Icon(Icons.thumb_down_outlined, size: 16),
                label: Text(context.t('feedback_not_helpful')),
              ),
              OutlinedButton.icon(
                onPressed: () => onFeedback('incorrect'),
                icon: const Icon(Icons.report_gmailerrorred_outlined, size: 16),
                label: Text(context.t('feedback_incorrect')),
              ),
            ],
          ),
          if (extraInfo != null && extraInfo!.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(
              extraInfo!,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
          ],
        ],
      ),
    );
  }
}
