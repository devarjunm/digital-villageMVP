import 'package:flutter/material.dart';

import '../../app.dart';
import '../../core/api_exception.dart';
import '../../core/formatters.dart';
import '../../models/ai.dart';
import '../../models/farm.dart';
import '../../widgets/common.dart';

/// Yield estimate (`POST /ai/yield-prediction`).
///
/// The API returns the estimate together with `rangeBasis` (what the range means)
/// and `limitations`; both are displayed, because a single number without its
/// basis invites over-confidence.
class YieldPredictionScreen extends StatefulWidget {
  const YieldPredictionScreen({super.key});

  @override
  State<YieldPredictionScreen> createState() => _YieldPredictionScreenState();
}

class _YieldPredictionScreenState extends State<YieldPredictionScreen> {
  final _area = TextEditingController(text: '1');
  final _ph = TextEditingController();
  final _nitrogen = TextEditingController();
  final _phosphorus = TextEditingController();
  final _potassium = TextEditingController();
  final _rainfall = TextEditingController();
  final _temperature = TextEditingController();

  String? _cropCode;
  String? _farmId;
  String _irrigation = 'rainfed';
  List<CropCatalogEntry> _catalog = const [];
  List<Farm> _farms = const [];
  bool _busy = false;
  String? _error;
  YieldPrediction? _result;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _bootstrap());
  }

  @override
  void dispose() {
    _area.dispose();
    _ph.dispose();
    _nitrogen.dispose();
    _phosphorus.dispose();
    _potassium.dispose();
    _rainfall.dispose();
    _temperature.dispose();
    super.dispose();
  }

  Future<void> _bootstrap() async {
    try {
      final catalog = await context.repos.crops.catalog();
      if (!mounted) return;
      setState(() {
        _catalog = catalog;
        _cropCode ??= catalog.isNotEmpty ? catalog.first.code : null;
      });
      if (context.session.isSignedIn) {
        final farms = await context.repos.farms.list();
        if (!mounted) return;
        setState(() => _farms = farms);
        final arguments = ModalRoute.of(context)?.settings.arguments;
        if (arguments is Map && arguments['farmId'] is String) {
          await _applyFarm(arguments['farmId'] as String);
        }
      }
    } on ApiException {
      // Manual entry remains available.
    }
  }

  Future<void> _applyFarm(String farmId) async {
    setState(() {
      _farmId = farmId;
      _irrigation = _farms
              .where((farm) => farm.id == farmId)
              .map((farm) => farm.irrigationType)
              .firstOrNull ??
          _irrigation;
    });
    try {
      final summary = await context.repos.farms.summary(farmId);
      if (!mounted) return;
      final test = summary.latestSoilTest;
      setState(() {
        if (summary.farm.soilPh != null) {
          _ph.text = summary.farm.soilPh!.toStringAsFixed(2);
        }
        if (test?.ph != null) _ph.text = test!.ph!.toStringAsFixed(2);
        if (test?.nitrogen != null) {
          _nitrogen.text = test!.nitrogen!.toStringAsFixed(1);
        }
        if (test?.phosphorus != null) {
          _phosphorus.text = test!.phosphorus!.toStringAsFixed(1);
        }
        if (test?.potassium != null) {
          _potassium.text = test!.potassium!.toStringAsFixed(1);
        }
      });
    } on ApiException {
      // ignore prefill failures
    }
  }

  Future<void> _submit() async {
    final crop = _cropCode;
    final area = double.tryParse(_area.text.trim());
    if (crop == null || area == null || area <= 0) {
      setState(() => _error = 'Choose a crop and enter a positive area.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _result = null;
    });
    try {
      final result = await context.repos.ai.yieldPrediction({
        'crop_code': crop,
        'area_hectares': area,
        'soil_ph': double.tryParse(_ph.text.trim()),
        'nitrogen': double.tryParse(_nitrogen.text.trim()),
        'phosphorus': double.tryParse(_phosphorus.text.trim()),
        'potassium': double.tryParse(_potassium.text.trim()),
        'rainfall_mm': double.tryParse(_rainfall.text.trim()),
        'temperature_mean_c': double.tryParse(_temperature.text.trim()),
        'irrigation_type': _irrigation,
        if (_farmId != null) 'farm_id': _farmId,
      }..removeWhere((key, value) => value == null));
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
    final result = _result;
    return Scaffold(
      appBar: AppBar(title: Text(context.t('yield_prediction'))),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
        children: [
          Notice(
            kind: NoticeKind.ai,
            title: context.t('ai_assisted'),
            message: context.t('yield_hint'),
          ),
          const SizedBox(height: 14),
          SectionCard(
            title: context.t('inputs_used'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
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
                        _applyFarm(value);
                      }
                    },
                  ),
                DropdownField<String>(
                  label: context.t('crop'),
                  value: _cropCode,
                  items: _catalog.map((entry) => entry.code).toList(),
                  allowNull: false,
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
                    return entry.localizedName(languageCode);
                  },
                  onChanged: (value) => setState(() => _cropCode = value),
                ),
                FormTextField(
                  label: 'Area (hectares)',
                  controller: _area,
                  keyboardType:
                      const TextInputType.numberWithOptions(decimal: true),
                  required: true,
                ),
                Row(
                  children: [
                    Expanded(
                      child: FormTextField(
                        label: context.t('soil_ph'),
                        controller: _ph,
                        keyboardType: const TextInputType.numberWithOptions(
                            decimal: true),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: FormTextField(
                        label: '${context.t('temperature')} (°C)',
                        controller: _temperature,
                        keyboardType: const TextInputType.numberWithOptions(
                            decimal: true),
                      ),
                    ),
                  ],
                ),
                Row(
                  children: [
                    Expanded(
                      child: FormTextField(
                        label: '${context.t('nitrogen')} (kg/ha)',
                        controller: _nitrogen,
                        keyboardType: const TextInputType.numberWithOptions(
                            decimal: true),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: FormTextField(
                        label: '${context.t('phosphorus')} (kg/ha)',
                        controller: _phosphorus,
                        keyboardType: const TextInputType.numberWithOptions(
                            decimal: true),
                      ),
                    ),
                  ],
                ),
                Row(
                  children: [
                    Expanded(
                      child: FormTextField(
                        label: '${context.t('potassium')} (kg/ha)',
                        controller: _potassium,
                        keyboardType: const TextInputType.numberWithOptions(
                            decimal: true),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: FormTextField(
                        label: '${context.t('rainfall')} (mm)',
                        controller: _rainfall,
                        keyboardType: const TextInputType.numberWithOptions(
                            decimal: true),
                      ),
                    ),
                  ],
                ),
                DropdownField<String>(
                  label: context.t('irrigation'),
                  value: _irrigation,
                  items: const [
                    'rainfed',
                    'canal',
                    'borewell',
                    'open_well',
                    'drip',
                    'sprinkler',
                    'tank',
                    'other',
                  ],
                  allowNull: false,
                  onChanged: (value) =>
                      setState(() => _irrigation = value ?? 'rainfed'),
                ),
                const SizedBox(height: 6),
                BusyButton(
                  label: context.t('submit'),
                  busy: _busy,
                  icon: Icons.insights_outlined,
                  onPressed: _submit,
                ),
              ],
            ),
          ),
          if (_error != null) ...[
            const SizedBox(height: 14),
            ErrorState(message: _error!, onRetry: _submit),
          ],
          if (result != null) ...[
            const SizedBox(height: 14),
            SectionCard(
              title: context.t('yield_prediction'),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${Fmt.number(result.estimate, decimals: 2)} ${result.unit}',
                    style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                  ),
                  const SizedBox(height: 6),
                  if (result.range != null)
                    Text(
                      result.range!.entries
                          .map((e) => '${Fmt.humanize(e.key)}: ${e.value}')
                          .join(' · '),
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  const SizedBox(height: 6),
                  Text(result.rangeBasis,
                      style: Theme.of(context).textTheme.bodySmall),
                  const SizedBox(height: 10),
                  InfoRow(
                      label: context.t('model_used'), value: result.modelName),
                  InfoRow(
                      label: context.t('model_version'),
                      value: result.modelVersion),
                  InfoRow(
                      label: context.t('score_type'), value: result.scoreType),
                  const SizedBox(height: 8),
                  Text(
                    result.confidenceInterpretation,
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
              ),
            ),
            const SizedBox(height: 14),
            SectionCard(
              title: context.t('inputs_used'),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: result.inputsUsed.entries
                    .map(
                      (entry) => InfoRow(
                        label: Fmt.humanize(entry.key),
                        value: entry.value.toString(),
                      ),
                    )
                    .toList(),
              ),
            ),
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
          ],
        ],
      ),
    );
  }
}
