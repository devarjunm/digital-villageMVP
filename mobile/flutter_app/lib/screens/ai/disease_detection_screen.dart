import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../../app.dart';
import '../../core/api_exception.dart';
import '../../core/formatters.dart';
import '../../models/ai.dart';
import '../../models/farm.dart';
import '../../widgets/common.dart';

/// Disease/pest observation from a photo.
///
/// Flow: pick an image → `POST /media/upload` (purpose `disease_scan`, so the
/// server's MIME/size/dimension validation and the storage abstraction are used)
/// → `POST /ai/disease-detection` with the returned media id.
///
/// The screen keeps the model's own caveats in view: the classes it was trained
/// on, whether the photo passed the quality gate, and the fact that an
/// inconclusive answer is a legitimate outcome rather than a hidden failure.
class DiseaseDetectionScreen extends StatefulWidget {
  const DiseaseDetectionScreen({super.key});

  @override
  State<DiseaseDetectionScreen> createState() => _DiseaseDetectionScreenState();
}

class _DiseaseDetectionScreenState extends State<DiseaseDetectionScreen> {
  final _note = TextEditingController();
  final _picker = ImagePicker();

  Uint8List? _bytes;
  String? _filename;
  String? _farmId;
  String _plantPart = 'leaf';
  String? _cropCode;
  List<Farm> _farms = const [];
  List<Crop> _farmCrops = const [];
  CropCatalogEntry? _selectedCropEntry;
  List<CropCatalogEntry> _catalog = const [];

  bool _busy = false;
  String? _progress;
  String? _error;
  DiseaseObservation? _result;
  String? _feedbackSent;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _bootstrap());
  }

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  Future<void> _bootstrap() async {
    try {
      final catalog = await context.repos.crops.catalog();
      if (!mounted) return;
      setState(() => _catalog = catalog);
      if (context.session.isSignedIn) {
        final farms = await context.repos.farms.list();
        if (!mounted) return;
        setState(() => _farms = farms);
        final arguments = ModalRoute.of(context)?.settings.arguments;
        if (arguments is Map && arguments['farmId'] is String) {
          await _selectFarm(arguments['farmId'] as String);
        }
      }
    } on ApiException {
      // The tool still works with a manual crop choice.
    }
  }

  Future<void> _selectFarm(String farmId) async {
    setState(() => _farmId = farmId);
    try {
      final crops = await context.repos.farms.crops(farmId);
      if (!mounted) return;
      setState(() {
        _farmCrops = crops;
        _cropCode ??= crops.isNotEmpty ? crops.first.cropCode : null;
      });
    } on ApiException {
      // Keep whatever crop was selected.
    }
  }

  Future<void> _pick(ImageSource source) async {
    setState(() {
      _error = null;
      _result = null;
    });
    try {
      final picked = await _picker.pickImage(
        source: source,
        maxWidth: 1600,
        maxHeight: 1600,
        imageQuality: 90,
      );
      if (picked == null) return;
      final bytes = await picked.readAsBytes();
      if (!mounted) return;
      setState(() {
        _bytes = bytes;
        _filename = picked.name.isEmpty ? 'observation.jpg' : picked.name;
      });
    } on Exception catch (error) {
      if (mounted) setState(() => _error = error.toString());
    }
  }

  Future<void> _analyse() async {
    final bytes = _bytes;
    if (bytes == null) {
      setState(() => _error = context.t('upload_photo'));
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _result = null;
      _feedbackSent = null;
      _progress = 'Uploading photo…';
    });
    try {
      final asset = await context.repos.ai.uploadImage(
        bytes: bytes,
        filename: _filename ?? 'observation.jpg',
        purpose: 'disease_scan',
      );
      if (!mounted) return;
      setState(() => _progress = context.t('analysing'));
      final result = await context.repos.ai.diseaseDetection({
        'media_id': asset.id,
        if (_cropCode != null) 'crop_code': _cropCode,
        if (_farmId != null) 'farm_id': _farmId,
        'plant_part': _plantPart,
        if (_note.text.trim().isNotEmpty) 'note': _note.text.trim(),
        'top_k': 3,
      });
      if (!mounted) return;
      setState(() {
        _result = result;
        _busy = false;
        _progress = null;
      });
    } on ApiException catch (error) {
      setState(() {
        _busy = false;
        _progress = null;
        _error = error.userFieldsOrMessage;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final languageCode = context.session.languageCode;
    return Scaffold(
      appBar: AppBar(title: Text(context.t('disease_detection'))),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
        children: [
          Notice(
            kind: NoticeKind.ai,
            title: context.t('ai_assisted'),
            message: context.t('disease_detection_hint'),
          ),
          const SizedBox(height: 14),
          SectionCard(
            title: context.t('upload_photo'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (_bytes != null)
                  ClipRRect(
                    borderRadius: BorderRadius.circular(12),
                    child: Image.memory(
                      _bytes!,
                      height: 180,
                      width: double.infinity,
                      fit: BoxFit.cover,
                    ),
                  ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed:
                            _busy ? null : () => _pick(ImageSource.camera),
                        icon: const Icon(Icons.photo_camera_outlined, size: 18),
                        label: Text(context.t('take_photo')),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed:
                            _busy ? null : () => _pick(ImageSource.gallery),
                        icon:
                            const Icon(Icons.photo_library_outlined, size: 18),
                        label: Text(context.t('from_gallery')),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                if (_farms.isNotEmpty)
                  DropdownField<String>(
                    label: context.t('nav_farm'),
                    value: _farmId,
                    items: _farms.map((farm) => farm.id).toList(),
                    labelBuilder: (id) =>
                        _farms.firstWhere((farm) => farm.id == id).name,
                    onChanged: (value) {
                      if (value == null) {
                        setState(() => _farmId = null);
                      } else {
                        _selectFarm(value);
                      }
                    },
                  ),
                if (_farmCrops.isNotEmpty)
                  DropdownField<String>(
                    label: context.t('crop'),
                    value: _cropCode,
                    items: _farmCrops.map((crop) => crop.cropCode).toList(),
                    labelBuilder: (code) => _catalog
                        .firstWhere(
                          (entry) => entry.code == code,
                          orElse: () => CropCatalogEntry(
                            code: code,
                            nameEn: code,
                            category: '',
                            season: '',
                            defaultAreaUnit: 'acre',
                          ),
                        )
                        .localizedName(languageCode),
                    onChanged: (value) => setState(() => _cropCode = value),
                  )
                else
                  DropdownField<String>(
                    label: context.t('crop'),
                    value: _cropCode,
                    items: _catalog.map((entry) => entry.code).toList(),
                    labelBuilder: (code) {
                      final entry = _catalog.firstWhere(
                        (item) => item.code == code,
                        orElse: () => CropCatalogEntry(
                          code: code,
                          nameEn: code,
                          category: '',
                          season: '',
                          defaultAreaUnit: 'acre',
                        ),
                      );
                      final supported = entry.diseaseModelSupported;
                      return '${entry.localizedName(languageCode)}${supported ? '' : ' — no model'}';
                    },
                    onChanged: (value) => setState(() {
                      _cropCode = value;
                      _selectedCropEntry =
                          _catalog.where((e) => e.code == value).firstOrNull;
                    }),
                  ),
                if (_selectedCropEntry != null &&
                    !_selectedCropEntry!.diseaseModelSupported) ...[
                  Notice(
                    kind: NoticeKind.warning,
                    message:
                        'The platform has no trained disease model for this crop. The request '
                        'will be refused rather than guessed at.',
                  ),
                  const SizedBox(height: 12),
                ],
                DropdownField<String>(
                  label: 'Plant part',
                  value: _plantPart,
                  items: const [
                    'leaf',
                    'stem',
                    'fruit',
                    'root',
                    'flower',
                    'whole_plant'
                  ],
                  allowNull: false,
                  onChanged: (value) =>
                      setState(() => _plantPart = value ?? 'leaf'),
                ),
                FormTextField(
                  label: '${context.t('notes')} (${context.t('optional')})',
                  controller: _note,
                  maxLines: 3,
                  helper:
                      'Symptoms, when they appeared, recent sprays — this text is shown with the result.',
                ),
                if (_progress != null)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Row(
                      children: [
                        const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                        const SizedBox(width: 10),
                        Text(_progress!,
                            style: Theme.of(context).textTheme.bodySmall),
                      ],
                    ),
                  ),
                BusyButton(
                  label: context.t('analysing'),
                  busy: _busy,
                  icon: Icons.search,
                  onPressed: _bytes == null ? null : _analyse,
                ),
              ],
            ),
          ),
          if (_error != null) ...[
            const SizedBox(height: 14),
            ErrorState(message: _error!, onRetry: _analyse),
          ],
          if (_result != null) ...[
            const SizedBox(height: 14),
            _ObservationView(
              observation: _result!,
              feedbackSent: _feedbackSent,
              onFeedback: (verdict) async {
                await context.repos.ai.feedback(
                  aiRequestId: _result!.requestId ?? _result!.modelVersion,
                  verdict: verdict,
                  correctedLabel: null,
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

class _ObservationView extends StatelessWidget {
  const _ObservationView({
    required this.observation,
    required this.onFeedback,
    this.feedbackSent,
  });

  final DiseaseObservation observation;
  final Future<void> Function(String verdict) onFeedback;
  final String? feedbackSent;

  @override
  Widget build(BuildContext context) {
    final top = observation.predictions.isEmpty
        ? 1.0
        : observation.predictions
            .map((prediction) => prediction.score)
            .reduce((a, b) => a > b ? a : b);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (!observation.cropSupported) ...[
          Notice(
            kind: NoticeKind.warning,
            title: context.t('not_available'),
            message: observation.cropCoverageNote ??
                'The model was not trained on this crop, so no assessment is shown.',
          ),
          const SizedBox(height: 14),
        ] else if (observation.qualityGateFailed) ...[
          Notice(
            kind: NoticeKind.warning,
            title: context.t('image_quality'),
            message:
                'The photo did not pass the quality checks, so no class is reported. '
                'Take another photo in better light, closer to the affected part.',
            items: observation.imageQuality
                .where((check) => !check.passed)
                .map((check) =>
                    '${Fmt.humanize(check.name)}: ${check.detail ?? 'failed'}')
                .toList(),
          ),
          const SizedBox(height: 14),
        ] else if (observation.inconclusive) ...[
          Notice(
            kind: NoticeKind.warning,
            title: context.t('inconclusive'),
            message: context.t('inconclusive_explanation'),
          ),
          const SizedBox(height: 14),
        ],
        if (observation.predictions.isNotEmpty)
          SectionCard(
            title: context.t('predicted_labels'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                ...observation.predictions.map(
                  (prediction) => ScoreBar(
                    label: prediction.displayName,
                    value: prediction.score,
                    maxValue: top,
                    highlight: prediction == observation.predictions.first,
                  ),
                ),
                Text(
                  observation.confidenceInterpretation,
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ),
        const SizedBox(height: 14),
        SectionCard(
          title: context.t('how_it_was_produced'),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              InfoRow(
                  label: context.t('model_used'), value: observation.modelName),
              InfoRow(
                  label: context.t('model_version'),
                  value: observation.modelVersion),
              if (observation.scoreType != null)
                InfoRow(
                    label: context.t('score_type'),
                    value: observation.scoreType!),
              if (observation.confidence != null)
                InfoRow(
                  label: context.t('confidence'),
                  value: observation.confidence!.toStringAsFixed(3),
                ),
              if (observation.cropCode != null)
                InfoRow(label: context.t('crop'), value: observation.cropCode!),
              if (observation.imageQuality.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(context.t('image_quality'),
                    style: Theme.of(context).textTheme.labelLarge),
                const SizedBox(height: 4),
                ...observation.imageQuality.map(
                  (check) => Row(
                    children: [
                      Icon(
                        check.passed
                            ? Icons.check_circle_outline
                            : Icons.cancel_outlined,
                        size: 14,
                        color: check.passed
                            ? Theme.of(context).colorScheme.primary
                            : Theme.of(context).colorScheme.error,
                      ),
                      const SizedBox(width: 6),
                      Expanded(
                        child: Text(
                          '${Fmt.humanize(check.name)}${check.detail == null ? '' : ': ${check.detail}'}',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
              if (observation.modelTrainedClasses.isNotEmpty) ...[
                const SizedBox(height: 10),
                Text(
                  context.t('trained_classes'),
                  style: Theme.of(context).textTheme.labelLarge,
                ),
                const SizedBox(height: 4),
                Text(
                  observation.modelTrainedClasses.join(', '),
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: 14),
        SectionCard(
          title: context.t('recommendation'),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              DataClassChip(value: observation.recommendationKind),
              const SizedBox(height: 8),
              Text(observation.recommendation),
            ],
          ),
        ),
        if (observation.relatedKnowledge.isNotEmpty ||
            observation.similarPosts.isNotEmpty) ...[
          const SizedBox(height: 14),
          SectionCard(
            title: context.t('sources'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                ...observation.relatedKnowledge.map(
                  (item) => SourceLine(
                    title: (item['title'] ?? '').toString(),
                    subtitle: (item['source_name'] ?? '').toString(),
                    url: item['source_url']?.toString(),
                  ),
                ),
                ...observation.similarPosts.map(
                  (item) => SourceLine(
                    title: (item['title'] ?? '').toString(),
                    subtitle: 'community',
                  ),
                ),
              ],
            ),
          ),
        ],
        const SizedBox(height: 14),
        Notice(kind: NoticeKind.ai, message: observation.disclaimer),
        const SizedBox(height: 10),
        if (feedbackSent != null)
          Notice(
              kind: NoticeKind.success, message: context.t('feedback_thanks'))
        else
          SectionCard(
            title: context.t('feedback_helpful'),
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
                    OutlinedButton(
                      onPressed: () => onFeedback('helpful'),
                      child: Text(context.t('feedback_helpful')),
                    ),
                    OutlinedButton(
                      onPressed: () => onFeedback('incorrect'),
                      child: Text(context.t('feedback_incorrect')),
                    ),
                  ],
                ),
                if (observation.requestId != null) ...[
                  const SizedBox(height: 10),
                  Text(
                    '${context.t('request_id')}: ${observation.requestId}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
              ],
            ),
          ),
      ],
    );
  }
}
