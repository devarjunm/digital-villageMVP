import 'package:flutter/material.dart';

import '../../app.dart';
import '../../core/api_exception.dart';
import '../../core/formatters.dart';
import '../../models/farm.dart';
import '../../widgets/common.dart';
import '../home/home_shell.dart';
import 'farm_detail_screen.dart';

/// Farm list and farm creation (`GET /farms`, `POST /farms`).
class FarmsScreen extends StatefulWidget {
  const FarmsScreen({super.key, this.embedded = false});

  final bool embedded;

  @override
  State<FarmsScreen> createState() => _FarmsScreenState();
}

class _FarmsScreenState extends State<FarmsScreen> {
  int _tick = 0;

  Future<void> _refresh() async => setState(() => _tick++);

  @override
  Widget build(BuildContext context) {
    return EmbeddedScreenScaffold(
      title: context.t('my_farms'),
      embedded: widget.embedded,
      onRefresh: _refresh,
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => showAddFarmSheet(context, onCreated: _refresh),
        icon: const Icon(Icons.add),
        label: Text(context.t('add_farm')),
      ),
      child: AsyncSection<List<Farm>>(
        refreshTick: _tick,
        load: () => context.repos.farms.list(),
        isEmpty: (farms) => farms.isEmpty,
        emptyBuilder: (context, reload) => ListView(
          padding: const EdgeInsets.all(20),
          children: [
            EmptyState(
              title: context.t('no_farms'),
              message: context.t('no_farms_hint'),
              icon: Icons.grass_outlined,
              action: FilledButton.icon(
                onPressed: () => showAddFarmSheet(context, onCreated: reload),
                icon: const Icon(Icons.add),
                label: Text(context.t('add_farm')),
              ),
            ),
          ],
        ),
        builder: (context, farms, reload) => ListView.separated(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 96),
          itemCount: farms.length,
          separatorBuilder: (_, __) => const SizedBox(height: 12),
          itemBuilder: (context, index) {
            final farm = farms[index];
            return _FarmCard(
              farm: farm,
              onTap: () async {
                await Navigator.of(context).push(Routes.farm(farm.id));
                reload();
              },
            );
          },
        ),
      ),
    );
  }
}

class _FarmCard extends StatelessWidget {
  const _FarmCard({required this.farm, required this.onTap});

  final Farm farm;
  final Future<void> Function() onTap;

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
                      farm.name,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                    ),
                  ),
                  if (farm.isDemo) const DemoChip(),
                  const Icon(Icons.chevron_right),
                ],
              ),
              const SizedBox(height: 6),
              Text(
                farm.placeLabel,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
              const SizedBox(height: 10),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  MetaPill(
                      text: Fmt.area(farm.areaValue, farm.areaUnit),
                      icon: Icons.straighten),
                  if (farm.areaHectares > 0)
                    MetaPill(
                        text: Fmt.hectares(farm.areaHectares),
                        icon: Icons.square_foot),
                  MetaPill(
                    text: Fmt.humanize(farm.soilType),
                    icon: Icons.landscape_outlined,
                  ),
                  MetaPill(
                    text: Fmt.humanize(farm.irrigationType),
                    icon: Icons.water_drop_outlined,
                  ),
                  MetaPill(
                    text:
                        '${context.t('crops')}: ${farm.activeCropCount}/${farm.cropCount}',
                    icon: Icons.eco_outlined,
                  ),
                  if (farm.soilPh != null)
                    MetaPill(text: 'pH ${farm.soilPh!.toStringAsFixed(1)}'),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Bottom-sheet form for creating a farm. Field values mirror `FarmCreate`
/// exactly, including the enum members the API accepts.
Future<void> showAddFarmSheet(
  BuildContext context, {
  required Future<void> Function() onCreated,
}) async {
  final name = TextEditingController();
  final area = TextEditingController(text: '1');
  final village = TextEditingController();
  final taluka = TextEditingController();
  final district = TextEditingController();
  final state = TextEditingController();
  final pincode = TextEditingController();
  final soilPh = TextEditingController();
  final latitude = TextEditingController();
  final longitude = TextEditingController();
  final notes = TextEditingController();

  var areaUnit = 'acre';
  var soilType = 'unknown';
  var irrigation = 'rainfed';
  var ownership = 'owned';
  var busy = false;
  String? error;

  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (sheetContext) => StatefulBuilder(
      builder: (sheetContext, setState) {
        Future<void> submit() async {
          setState(() {
            busy = true;
            error = null;
          });
          try {
            await context.repos.farms.create({
              'name': name.text.trim(),
              'area_value': double.tryParse(area.text.trim()) ?? 0,
              'area_unit': areaUnit,
              'village': _nullIfEmpty(village.text),
              'taluka': _nullIfEmpty(taluka.text),
              'district': _nullIfEmpty(district.text),
              'state': _nullIfEmpty(state.text),
              'pincode': _nullIfEmpty(pincode.text),
              'soil_type': soilType,
              'soil_ph': double.tryParse(soilPh.text.trim()),
              'irrigation_type': irrigation,
              'ownership_type': ownership,
              'latitude': double.tryParse(latitude.text.trim()),
              'longitude': double.tryParse(longitude.text.trim()),
              'notes': _nullIfEmpty(notes.text),
            });
            if (!sheetContext.mounted) return;
            Navigator.of(sheetContext).pop();
            await onCreated();
            if (context.mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(content: Text(context.t('saved'))),
              );
            }
          } on ApiException catch (apiError) {
            setState(() {
              busy = false;
              final fields = apiError.fieldErrors;
              error = fields.isEmpty
                  ? apiError.userMessage
                  : fields.entries
                      .map((e) => '${Fmt.humanize(e.key)}: ${e.value}')
                      .join('\n');
            });
          }
        }

        return Padding(
          padding: EdgeInsets.only(
            left: 20,
            right: 20,
            top: 20,
            bottom: MediaQuery.of(sheetContext).viewInsets.bottom + 24,
          ),
          child: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  context.t('add_farm'),
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 16),
                if (error != null) ...[
                  Notice(
                    kind: NoticeKind.danger,
                    title: context.t('error_title'),
                    message: error!,
                  ),
                  const SizedBox(height: 14),
                ],
                FormTextField(
                  label: context.t('farm_name'),
                  controller: name,
                  required: true,
                  hint: 'e.g. Field near the canal',
                ),
                Row(
                  children: [
                    Expanded(
                      child: FormTextField(
                        label: context.t('area'),
                        controller: area,
                        keyboardType: const TextInputType.numberWithOptions(
                            decimal: true),
                        required: true,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: DropdownField<String>(
                        label: context.t('area_unit'),
                        value: areaUnit,
                        items: const [
                          'acre',
                          'hectare',
                          'guntha',
                          'bigha',
                          'square_metre'
                        ],
                        allowNull: false,
                        onChanged: (value) =>
                            setState(() => areaUnit = value ?? 'acre'),
                      ),
                    ),
                  ],
                ),
                Row(
                  children: [
                    Expanded(
                      child: FormTextField(
                          label: context.t('village'), controller: village),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: FormTextField(
                          label: context.t('taluka'), controller: taluka),
                    ),
                  ],
                ),
                Row(
                  children: [
                    Expanded(
                      child: FormTextField(
                          label: context.t('district'), controller: district),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: FormTextField(
                          label: context.t('state'), controller: state),
                    ),
                  ],
                ),
                Row(
                  children: [
                    Expanded(
                      child: FormTextField(
                        label: context.t('pincode'),
                        controller: pincode,
                        keyboardType: TextInputType.number,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: FormTextField(
                        label: context.t('soil_ph'),
                        controller: soilPh,
                        keyboardType: const TextInputType.numberWithOptions(
                            decimal: true),
                      ),
                    ),
                  ],
                ),
                DropdownField<String>(
                  label: context.t('soil_type'),
                  value: soilType,
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
                      setState(() => soilType = value ?? 'unknown'),
                ),
                DropdownField<String>(
                  label: context.t('irrigation'),
                  value: irrigation,
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
                      setState(() => irrigation = value ?? 'rainfed'),
                ),
                DropdownField<String>(
                  label: context.t('ownership'),
                  value: ownership,
                  items: const [
                    'owned',
                    'leased',
                    'shared',
                    'government_leased'
                  ],
                  allowNull: false,
                  onChanged: (value) =>
                      setState(() => ownership = value ?? 'owned'),
                ),
                Row(
                  children: [
                    Expanded(
                      child: FormTextField(
                        label: 'Latitude',
                        controller: latitude,
                        keyboardType: const TextInputType.numberWithOptions(
                            decimal: true, signed: true),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: FormTextField(
                        label: 'Longitude',
                        controller: longitude,
                        keyboardType: const TextInputType.numberWithOptions(
                            decimal: true, signed: true),
                      ),
                    ),
                  ],
                ),
                FormTextField(
                    label: context.t('notes'), controller: notes, maxLines: 3),
                const SizedBox(height: 8),
                BusyButton(
                  label: context.t('save'),
                  busy: busy,
                  onPressed: name.text.trim().isEmpty ? null : submit,
                ),
                const SizedBox(height: 8),
                OutlinedButton(
                  onPressed:
                      busy ? null : () => Navigator.of(sheetContext).pop(),
                  child: Text(context.t('cancel')),
                ),
              ],
            ),
          ),
        );
      },
    ),
  );
}

String? _nullIfEmpty(String value) {
  final trimmed = value.trim();
  return trimmed.isEmpty ? null : trimmed;
}

/// Opens a farm, or the add-farm sheet when the id is unknown. Kept public so
/// deep links from notifications and search can reuse it.
Future<void> openFarm(BuildContext context, String farmId) =>
    Navigator.of(context).push(
      MaterialPageRoute<void>(builder: (_) => FarmDetailScreen(farmId: farmId)),
    );
