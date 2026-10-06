import 'package:flutter/material.dart';

import '../../app.dart';
import '../../core/api_exception.dart';
import '../../core/formatters.dart';
import '../../models/farm.dart';
import '../../widgets/common.dart';

/// One farm: `GET /farms/{id}/summary`, plus crops, soil tests and the
/// farm-scoped AI entry points.
///
/// The crop-recommendation button passes this farm's id, so the model can read
/// the soil test the farmer already recorded instead of asking for it again.
class FarmDetailScreen extends StatefulWidget {
  const FarmDetailScreen({super.key, required this.farmId});

  final String farmId;

  @override
  State<FarmDetailScreen> createState() => _FarmDetailScreenState();
}

class _FarmDetailScreenState extends State<FarmDetailScreen> {
  int _tick = 0;

  Future<void> _refresh() async => setState(() => _tick++);

  Future<void> _deleteFarm(Farm farm) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(context.t('delete')),
        content: Text(context.t('delete_farm_confirm')),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: Text(context.t('cancel')),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: Text(context.t('delete')),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    try {
      await context.repos.farms.delete(farm.id);
      if (!mounted) return;
      Navigator.of(context).pop();
    } on ApiException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(error.userMessage)));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('farm_details')),
        actions: [
          AsyncSection<FarmSummary>(
            refreshTick: -1,
            load: () => context.repos.farms.summary(widget.farmId),
            padding: EdgeInsets.zero,
            builder: (context, summary, reload) => IconButton(
              tooltip: context.t('delete'),
              icon: const Icon(Icons.delete_outline),
              onPressed: () => _deleteFarm(summary.farm),
            ),
          ),
        ],
      ),
      body: AsyncSection<FarmSummary>(
        refreshTick: _tick,
        load: () => context.repos.farms.summary(widget.farmId),
        builder: (context, summary, reload) {
          final farm = summary.farm;
          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
            children: [
              SectionCard(
                title: farm.name,
                subtitle: farm.placeLabel,
                trailing: farm.isDemo ? const DemoChip() : null,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    InfoRow(
                      label: context.t('area'),
                      value:
                          '${Fmt.area(farm.areaValue, farm.areaUnit)} (${Fmt.hectares(farm.areaHectares)})',
                    ),
                    InfoRow(
                        label: context.t('soil_type'),
                        value: Fmt.humanize(farm.soilType)),
                    InfoRow(
                      label: context.t('soil_ph'),
                      value: farm.soilPh?.toStringAsFixed(1) ??
                          context.t('not_recorded'),
                    ),
                    InfoRow(
                      label: context.t('irrigation'),
                      value: Fmt.humanize(farm.irrigationType),
                    ),
                    InfoRow(
                      label: context.t('ownership'),
                      value: Fmt.humanize(farm.ownershipType),
                    ),
                    if (farm.hasCoordinates)
                      InfoRow(
                        label: context.t('coordinates'),
                        value:
                            '${Fmt.coord(farm.latitude)}, ${Fmt.coord(farm.longitude)}',
                      ),
                    if (farm.waterSourceNotes != null)
                      InfoRow(
                          label: 'Water source', value: farm.waterSourceNotes!),
                    if (farm.notes != null)
                      InfoRow(label: context.t('notes'), value: farm.notes!),
                  ],
                ),
              ),
              const SizedBox(height: 14),
              SectionCard(
                title: context.t('latest_soil_test'),
                trailing: TextButton(
                  onPressed: () => _showSoilTestSheet(context),
                  child: Text(context.t('add_soil_test')),
                ),
                child: summary.latestSoilTest == null
                    ? Text(
                        context.t('no_soil_test'),
                        style: Theme.of(context).textTheme.bodySmall,
                      )
                    : _SoilTestView(test: summary.latestSoilTest!),
              ),
              const SizedBox(height: 14),
              if (summary.aiNotes.isNotEmpty) ...[
                const SizedBox(height: 0),
                Notice(
                  kind: NoticeKind.info,
                  title: context.t('how_it_was_produced'),
                  message: summary.aiNotes.first,
                  items: summary.aiNotes.length > 1
                      ? summary.aiNotes.sublist(1)
                      : const [],
                ),
                const SizedBox(height: 14),
              ],
              SectionCard(
                title: context.t('crops'),
                trailing: TextButton.icon(
                  onPressed: _showAddCropSheet,
                  icon: const Icon(Icons.add, size: 16),
                  label: Text(context.t('add_crop')),
                ),
                child: summary.crops.isEmpty
                    ? Text(
                        context.t('no_active_crops'),
                        style: Theme.of(context).textTheme.bodySmall,
                      )
                    : Column(
                        children: summary.crops
                            .map((crop) =>
                                _CropTile(crop: crop, onChanged: reload))
                            .toList(),
                      ),
              ),
              const SizedBox(height: 14),
              SectionCard(
                title: context.t('ai_tools'),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      context.t('ai_tools_intro'),
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                    const SizedBox(height: 12),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        ActionChip(
                          avatar: const Icon(Icons.eco_outlined, size: 16),
                          label: Text(context.t('crop_recommendation')),
                          onPressed: () => Navigator.of(context).pushNamed(
                            Routes.cropRecommendation,
                            arguments: {'farmId': farm.id},
                          ),
                        ),
                        ActionChip(
                          avatar:
                              const Icon(Icons.photo_camera_outlined, size: 16),
                          label: Text(context.t('disease_detection')),
                          onPressed: () => Navigator.of(context).pushNamed(
                            Routes.diseaseDetection,
                            arguments: {'farmId': farm.id},
                          ),
                        ),
                        ActionChip(
                          avatar: const Icon(Icons.insights_outlined, size: 16),
                          label: Text(context.t('yield_prediction')),
                          onPressed: () => Navigator.of(context).pushNamed(
                            Routes.yieldPrediction,
                            arguments: {'farmId': farm.id},
                          ),
                        ),
                        ActionChip(
                          avatar: const Icon(Icons.cloud_outlined, size: 16),
                          label: Text(context.t('more_weather')),
                          onPressed: () => Navigator.of(context).pushNamed(
                            Routes.weather,
                            arguments: {'farmId': farm.id},
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  Future<void> _showAddCropSheet() async {
    final catalog = await context.repos.crops.catalog();
    if (!mounted) return;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => _AddCropSheet(
        farmId: widget.farmId,
        catalog: catalog,
        onCreated: _refresh,
      ),
    );
  }

  Future<void> _showSoilTestSheet(BuildContext context) async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => _AddSoilTestSheet(
        farmId: widget.farmId,
        onCreated: _refresh,
      ),
    );
  }
}

class _SoilTestView extends StatelessWidget {
  const _SoilTestView({required this.test});

  final SoilTest test;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        InfoRow(label: context.t('tested_on'), value: Fmt.date(test.testedOn)),
        InfoRow(
          label: '${context.t('nitrogen')} (kg/ha)',
          value: test.nitrogen?.toStringAsFixed(1) ?? context.t('not_recorded'),
        ),
        InfoRow(
          label: '${context.t('phosphorus')} (kg/ha)',
          value:
              test.phosphorus?.toStringAsFixed(1) ?? context.t('not_recorded'),
        ),
        InfoRow(
          label: '${context.t('potassium')} (kg/ha)',
          value:
              test.potassium?.toStringAsFixed(1) ?? context.t('not_recorded'),
        ),
        InfoRow(
            label: context.t('soil_ph'),
            value: test.ph?.toStringAsFixed(2) ?? '—'),
        InfoRow(
          label: context.t('organic_carbon'),
          value: test.organicCarbonPercent == null
              ? '—'
              : '${test.organicCarbonPercent!.toStringAsFixed(2)} %',
        ),
        if (test.labName != null)
          InfoRow(label: context.t('lab_name'), value: test.labName!),
      ],
    );
  }
}

class _CropTile extends StatelessWidget {
  const _CropTile({required this.crop, required this.onChanged});

  final Crop crop;
  final Future<void> Function() onChanged;

  @override
  Widget build(BuildContext context) {
    return ExpansionTile(
      tilePadding: EdgeInsets.zero,
      childrenPadding: const EdgeInsets.only(bottom: 10),
      title: Text('${crop.displayName} ${crop.variety ?? ''}'.trim()),
      subtitle: Text(
        [
          Fmt.humanize(crop.stage),
          Fmt.humanize(crop.status),
          crop.areaValue == null
              ? null
              : Fmt.area(crop.areaValue, crop.areaUnit),
        ].whereType<String>().join(' · '),
      ),
      children: [
        InfoRow(label: context.t('season'), value: Fmt.humanize(crop.season)),
        InfoRow(
            label: context.t('sowing_date'), value: Fmt.date(crop.sowingDate)),
        InfoRow(
          label: context.t('expected_harvest'),
          value: Fmt.date(crop.expectedHarvestDate),
        ),
        InfoRow(
          label: context.t('days_since_sowing'),
          value: crop.daysSinceSowing?.toString() ?? '—',
        ),
        InfoRow(
          label: context.t('days_to_harvest'),
          value: crop.daysToExpectedHarvest?.toString() ?? '—',
        ),
        if (crop.seedSource != null)
          InfoRow(label: context.t('seed_source'), value: crop.seedSource!),
        if (crop.notes != null)
          InfoRow(label: context.t('notes'), value: crop.notes!),
        const SizedBox(height: 6),
        _StageGuidanceBlock(cropId: crop.id),
      ],
    );
  }
}

/// Advisory text for the crop's current stage, straight from
/// `GET /crops/{id}/stage-guidance`, including its citation.
class _StageGuidanceBlock extends StatefulWidget {
  const _StageGuidanceBlock({required this.cropId});

  final String cropId;

  @override
  State<_StageGuidanceBlock> createState() => _StageGuidanceBlockState();
}

class _StageGuidanceBlockState extends State<_StageGuidanceBlock> {
  late Future<StageGuidance> _future;

  @override
  void initState() {
    super.initState();
    _future = context.repos.crops.stageGuidance(widget.cropId);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<StageGuidance>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Padding(
            padding: EdgeInsets.all(12),
            child: LoadingState(),
          );
        }
        if (snapshot.hasError) {
          return ErrorState.fromError(snapshot.error);
        }
        final guidance = snapshot.data;
        if (guidance == null) return const SizedBox.shrink();
        return Container(
          width: double.infinity,
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            color: Theme.of(context)
                .colorScheme
                .surfaceContainerHighest
                .withValues(alpha: 0.3),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Text(
                    context.t('stage_guidance'),
                    style: Theme.of(context).textTheme.labelLarge,
                  ),
                  const SizedBox(width: 8),
                  DataClassChip(value: guidance.dataClass),
                ],
              ),
              const SizedBox(height: 6),
              ...guidance.actions.map(
                (action) => Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('• '),
                      Expanded(
                        child: Text(action,
                            style: Theme.of(context).textTheme.bodySmall),
                      ),
                    ],
                  ),
                ),
              ),
              if (guidance.sourceUrl != null)
                SourceLine(
                  title: guidance.sourceName ?? context.t('source'),
                  url: guidance.sourceUrl,
                ),
              if (guidance.note != null)
                Text(
                  guidance.note!,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                ),
            ],
          ),
        );
      },
    );
  }
}

class _AddCropSheet extends StatefulWidget {
  const _AddCropSheet({
    required this.farmId,
    required this.catalog,
    required this.onCreated,
  });

  final String farmId;
  final List<CropCatalogEntry> catalog;
  final Future<void> Function() onCreated;

  @override
  State<_AddCropSheet> createState() => _AddCropSheetState();
}

class _AddCropSheetState extends State<_AddCropSheet> {
  late String _cropCode =
      widget.catalog.isNotEmpty ? widget.catalog.first.code : '';
  String _season = 'kharif';
  String _stage = 'sowing';
  String _areaUnit = 'acre';
  final _variety = TextEditingController();
  final _area = TextEditingController();
  final _seedSource = TextEditingController();
  final _notes = TextEditingController();
  DateTime? _sowingDate;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _variety.dispose();
    _area.dispose();
    _seedSource.dispose();
    _notes.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await context.repos.farms.addCrop(widget.farmId, {
        'crop_code': _cropCode,
        'variety': _variety.text.trim().isEmpty ? null : _variety.text.trim(),
        'season': _season,
        'stage': _stage,
        'area_unit': _areaUnit,
        'area_value': double.tryParse(_area.text.trim()),
        'sowing_date': _sowingDate?.toIso8601String().split('T').first,
        'seed_source':
            _seedSource.text.trim().isEmpty ? null : _seedSource.text.trim(),
        'notes': _notes.text.trim().isEmpty ? null : _notes.text.trim(),
      });
      if (!mounted) return;
      Navigator.of(context).pop();
      await widget.onCreated();
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
    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(context.t('add_crop'),
                style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 16),
            if (_error != null) ...[
              Notice(kind: NoticeKind.danger, message: _error!),
              const SizedBox(height: 14),
            ],
            DropdownField<String>(
              label: context.t('crop'),
              value: _cropCode.isEmpty ? null : _cropCode,
              items: widget.catalog.map((entry) => entry.code).toList(),
              allowNull: false,
              labelBuilder: (code) {
                final entry = widget.catalog.firstWhere(
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
              onChanged: (value) =>
                  setState(() => _cropCode = value ?? _cropCode),
            ),
            FormTextField(label: context.t('variety'), controller: _variety),
            DropdownField<String>(
              label: context.t('season'),
              value: _season,
              items: const ['kharif', 'rabi', 'zaid', 'perennial', 'any'],
              allowNull: false,
              onChanged: (value) => setState(() => _season = value ?? 'kharif'),
            ),
            DropdownField<String>(
              label: context.t('stage'),
              value: _stage,
              items: const [
                'planned',
                'land_preparation',
                'sowing',
                'germination',
                'vegetative',
                'flowering',
                'fruiting',
                'maturity',
                'harvest',
                'post_harvest',
              ],
              allowNull: false,
              onChanged: (value) => setState(() => _stage = value ?? 'sowing'),
            ),
            Row(
              children: [
                Expanded(
                  child: FormTextField(
                    label: context.t('area'),
                    controller: _area,
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: DropdownField<String>(
                    label: context.t('area_unit'),
                    value: _areaUnit,
                    items: const [
                      'acre',
                      'hectare',
                      'guntha',
                      'bigha',
                      'square_metre'
                    ],
                    allowNull: false,
                    onChanged: (value) =>
                        setState(() => _areaUnit = value ?? 'acre'),
                  ),
                ),
              ],
            ),
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      '${context.t('sowing_date')}: ${_sowingDate == null ? context.t('not_recorded') : Fmt.date(_sowingDate)}',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ),
                  OutlinedButton.icon(
                    onPressed: () async {
                      final picked = await showDatePicker(
                        context: context,
                        firstDate: DateTime(DateTime.now().year - 3),
                        lastDate: DateTime(DateTime.now().year + 1),
                        initialDate: _sowingDate ?? DateTime.now(),
                      );
                      if (picked != null) setState(() => _sowingDate = picked);
                    },
                    icon: const Icon(Icons.calendar_today_outlined, size: 16),
                    label: Text(context.t('sowing_date')),
                  ),
                ],
              ),
            ),
            FormTextField(
                label: context.t('seed_source'), controller: _seedSource),
            FormTextField(
                label: context.t('notes'), controller: _notes, maxLines: 3),
            BusyButton(
              label: context.t('save'),
              busy: _busy,
              onPressed: _cropCode.isEmpty ? null : _submit,
            ),
            const SizedBox(height: 8),
            OutlinedButton(
              onPressed: _busy ? null : () => Navigator.of(context).pop(),
              child: Text(context.t('cancel')),
            ),
          ],
        ),
      ),
    );
  }
}

class _AddSoilTestSheet extends StatefulWidget {
  const _AddSoilTestSheet({required this.farmId, required this.onCreated});

  final String farmId;
  final Future<void> Function() onCreated;

  @override
  State<_AddSoilTestSheet> createState() => _AddSoilTestSheetState();
}

class _AddSoilTestSheetState extends State<_AddSoilTestSheet> {
  final _ph = TextEditingController();
  final _nitrogen = TextEditingController();
  final _phosphorus = TextEditingController();
  final _potassium = TextEditingController();
  final _carbon = TextEditingController();
  final _lab = TextEditingController();
  final _notes = TextEditingController();
  DateTime _testedOn = DateTime.now();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _ph.dispose();
    _nitrogen.dispose();
    _phosphorus.dispose();
    _potassium.dispose();
    _carbon.dispose();
    _lab.dispose();
    _notes.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await context.repos.farms.addSoilTest(widget.farmId, {
        'tested_on': _testedOn.toIso8601String().split('T').first,
        'ph': double.tryParse(_ph.text.trim()),
        'nitrogen_kg_per_ha': double.tryParse(_nitrogen.text.trim()),
        'phosphorus_kg_per_ha': double.tryParse(_phosphorus.text.trim()),
        'potassium_kg_per_ha': double.tryParse(_potassium.text.trim()),
        'organic_carbon_percent': double.tryParse(_carbon.text.trim()),
        'lab_name': _lab.text.trim().isEmpty ? null : _lab.text.trim(),
        'notes': _notes.text.trim().isEmpty ? null : _notes.text.trim(),
      });
      if (!mounted) return;
      Navigator.of(context).pop();
      await widget.onCreated();
    } on ApiException catch (error) {
      setState(() {
        _busy = false;
        _error = error.userFieldsOrMessage;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(context.t('add_soil_test'),
                style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 6),
            Text(
              context.t('use_soil_test_values'),
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 16),
            if (_error != null) ...[
              Notice(kind: NoticeKind.danger, message: _error!),
              const SizedBox(height: 14),
            ],
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      '${context.t('tested_on')}: ${Fmt.date(_testedOn)}',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ),
                  OutlinedButton.icon(
                    onPressed: () async {
                      final picked = await showDatePicker(
                        context: context,
                        firstDate: DateTime(DateTime.now().year - 5),
                        lastDate: DateTime.now(),
                        initialDate: _testedOn,
                      );
                      if (picked != null) setState(() => _testedOn = picked);
                    },
                    icon: const Icon(Icons.calendar_today_outlined, size: 16),
                    label: Text(context.t('tested_on')),
                  ),
                ],
              ),
            ),
            FormTextField(
              label: context.t('soil_ph'),
              controller: _ph,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
            ),
            Row(
              children: [
                Expanded(
                  child: FormTextField(
                    label: '${context.t('nitrogen')} (kg/ha)',
                    controller: _nitrogen,
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FormTextField(
                    label: '${context.t('phosphorus')} (kg/ha)',
                    controller: _phosphorus,
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
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
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FormTextField(
                    label: '${context.t('organic_carbon')} (%)',
                    controller: _carbon,
                    keyboardType:
                        const TextInputType.numberWithOptions(decimal: true),
                  ),
                ),
              ],
            ),
            FormTextField(label: context.t('lab_name'), controller: _lab),
            FormTextField(
                label: context.t('notes'), controller: _notes, maxLines: 2),
            BusyButton(
              label: context.t('save'),
              busy: _busy,
              onPressed: _submit,
            ),
            const SizedBox(height: 8),
            OutlinedButton(
              onPressed: _busy ? null : () => Navigator.of(context).pop(),
              child: Text(context.t('cancel')),
            ),
          ],
        ),
      ),
    );
  }
}
