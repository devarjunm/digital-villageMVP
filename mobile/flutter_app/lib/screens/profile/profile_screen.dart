import 'package:flutter/material.dart';

import '../../app.dart';
import '../../core/api_exception.dart';
import '../../core/config.dart';
import '../../core/formatters.dart';
import '../../models/identity.dart';
import '../../widgets/common.dart';
import '../../widgets/server_settings.dart';

/// Profile, consents, language and advanced settings.
///
/// The consent switches write to `PATCH /users/me/consents`, the language choice
/// is sent to `/users/me` as well as stored locally, and the backend address is
/// editable because a physical test device cannot reach the emulator alias. The
/// data export is *requested* here — the backend prepares it; the app does not
/// pretend to have produced a file.
class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  final _baseUrl = TextEditingController();
  int _tick = 0;
  bool _savingBaseUrl = false;
  String? _baseUrlMessage;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final stored = await context.session.loadStoredBaseUrl();
      if (!mounted) return;
      setState(() => _baseUrl.text = stored ?? context.session.api.baseUrl);
    });
  }

  @override
  void dispose() {
    _baseUrl.dispose();
    super.dispose();
  }

  Future<void> _saveBaseUrl() async {
    final session = context.session;
    setState(() {
      _savingBaseUrl = true;
      _baseUrlMessage = null;
    });
    final accepted = await session.setBaseUrl(_baseUrl.text);
    if (!accepted) {
      if (mounted) {
        setState(() {
          _savingBaseUrl = false;
          _baseUrlMessage = context.t('server_invalid');
        });
      }
      return;
    }
    try {
      await session.refreshProfile();
      if (mounted) setState(() => _baseUrlMessage = context.t('saved'));
    } on ApiException catch (error) {
      if (mounted) setState(() => _baseUrlMessage = error.userMessage);
    } finally {
      if (mounted) {
        setState(() {
          _savingBaseUrl = false;
          _tick++;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = context.session;
    final user = session.user;

    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('profile_title')),
        actions: [
          IconButton(
            tooltip: context.t('refresh'),
            icon: const Icon(Icons.refresh),
            onPressed: () async {
              await session.refreshProfile();
              setState(() => _tick++);
            },
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
        children: [
          _ProfileCard(tick: _tick),
          const SizedBox(height: 14),
          SectionCard(
            title: context.t('language'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SegmentedButton<String>(
                  segments: const [
                    ButtonSegment(value: 'en', label: Text('English')),
                    ButtonSegment(value: 'mr', label: Text('मराठी')),
                    ButtonSegment(value: 'hi', label: Text('हिंदी')),
                  ],
                  selected: {session.languageCode},
                  onSelectionChanged: (selection) async {
                    await session.setLanguageCode(selection.first);
                    if (mounted) setState(() => _tick++);
                  },
                ),
                const SizedBox(height: 8),
                Text(
                  'The choice is stored on the device and saved to your account, so content the '
                  'backend generates (schemes, advisories, answers) is requested in this language.',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),
          SectionCard(
            title: context.t('account'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                InfoRow(
                    label: context.t('full_name'),
                    value: user?.fullName ?? '—'),
                InfoRow(
                    label: context.t('phone'), value: user?.phoneMasked ?? '—'),
                InfoRow(
                  label: context.t('verified'),
                  value: (user?.phoneVerified ?? false)
                      ? context.t('verified')
                      : context.t('not_verified'),
                ),
                InfoRow(
                    label: context.t('email'), value: user?.emailMasked ?? '—'),
                InfoRow(
                  label: 'Role',
                  value: user == null ? '—' : Fmt.humanize(user.primaryRole),
                ),
                InfoRow(
                  label: context.t('member_since'),
                  value:
                      Fmt.date(user?.createdAt, language: session.languageCode),
                ),
                if (user?.isDemo ?? false) ...[
                  const SizedBox(height: 8),
                  const DemoChip(
                    notice:
                        'This account was created by the development seed script.',
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 14),
          _ConsentsCard(tick: _tick),
          const SizedBox(height: 14),
          SectionCard(
            title: context.t('data_export'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  context.t('data_export_note'),
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  onPressed: () async {
                    final repos = context.repos;
                    final messenger = ScaffoldMessenger.of(context);
                    final requested = context.t('export_requested');
                    final failed = context.t('export_failed');
                    try {
                      final result = await repos.account.requestDataExport();
                      messenger.showSnackBar(
                        SnackBar(
                          content: Text(
                              '$requested ${result['status'] ?? ''}'.trim()),
                        ),
                      );
                    } on ApiException catch (error) {
                      messenger.showSnackBar(
                        SnackBar(content: Text('$failed ${error.userMessage}')),
                      );
                    }
                  },
                  icon: const Icon(Icons.download_outlined, size: 18),
                  label: Text(context.t('data_export')),
                ),
                const SizedBox(height: 10),
                Text(
                  context.t('delete_account_note'),
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 6),
                OutlinedButton.icon(
                  onPressed: _confirmDelete,
                  icon: const Icon(Icons.delete_forever_outlined, size: 18),
                  label: Text(context.t('delete_account')),
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),
          SectionCard(
            title: context.t('developer_options'),
            subtitle: context.t('api_base_url_note'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                FormTextField(
                  label: context.t('api_base_url'),
                  controller: _baseUrl,
                  hint: 'http://192.168.1.5:8000',
                  keyboardType: TextInputType.url,
                  helper: 'Default: ${AppConfig.builtInBaseUrl}',
                ),
                Row(
                  children: [
                    Expanded(
                      child: BusyButton(
                        label: context.t('save'),
                        busy: _savingBaseUrl,
                        onPressed: _saveBaseUrl,
                      ),
                    ),
                    const SizedBox(width: 10),
                    OutlinedButton(
                      onPressed: () async {
                        _baseUrl.clear();
                        await context.session.setBaseUrl(null);
                        if (mounted) {
                          setState(() {
                            _baseUrl.text = context.session.api.baseUrl;
                            _baseUrlMessage = context.t('reset_default');
                          });
                        }
                      },
                      child: Text(context.t('reset_default')),
                    ),
                  ],
                ),
                if (_baseUrlMessage != null) ...[
                  const SizedBox(height: 8),
                  Notice(kind: NoticeKind.info, message: _baseUrlMessage!),
                ],
                const SizedBox(height: 8),
                TextButton.icon(
                  onPressed: () => showModalBottomSheet<void>(
                    context: context,
                    isScrollControlled: true,
                    showDragHandle: true,
                    builder: (_) =>
                        ServerSettingsSheet(session: context.session),
                  ),
                  icon: const Icon(Icons.network_check, size: 18),
                  label: Text(context.t('check_connection')),
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),
          Card(
            child: Column(
              children: [
                ListTile(
                  leading: const Icon(Icons.info_outline),
                  title: Text(context.t('about_app')),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => Navigator.of(context).pushNamed(Routes.about),
                ),
                ListTile(
                  leading: const Icon(Icons.memory_outlined),
                  title: Text(context.t('ai_models')),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => Navigator.of(context).pushNamed(Routes.aiHub),
                ),
                ListTile(
                  leading: const Icon(Icons.notifications_outlined),
                  title: Text(context.t('notification_preferences')),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () =>
                      Navigator.of(context).pushNamed(Routes.notifications),
                ),
                ListTile(
                  leading: const Icon(Icons.logout),
                  title: Text(context.t('sign_out')),
                  onTap: () async {
                    await session.signOut();
                    if (context.mounted) {
                      Navigator.of(context).pushNamedAndRemoveUntil(
                        Routes.auth,
                        (route) => false,
                      );
                    }
                  },
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  /// Deletes the account for real: `DELETE /users/me` with the literal `DELETE`
  /// confirmation the API requires, typed by the user in the dialog. The receipt
  /// the API returns (what was erased, what was retained) is shown before the
  /// app signs out, because "your data was deleted" is a claim that must be
  /// backed by what the server actually did.
  Future<void> _confirmDelete() async {
    final session = context.session;
    final repos = context.repos;
    final confirmation = TextEditingController();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(context.t('delete_account')),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(context.t('delete_account_note')),
            const SizedBox(height: 12),
            TextField(
              controller: confirmation,
              autocorrect: false,
              textCapitalization: TextCapitalization.characters,
              decoration:
                  const InputDecoration(labelText: 'Type DELETE to confirm'),
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
            child: Text(context.t('delete')),
          ),
        ],
      ),
    );
    final typed = confirmation.text.trim().toUpperCase();
    confirmation.dispose();
    if (confirmed != true) return;
    if (typed != 'DELETE') {
      if (mounted) {
        _snack('Type DELETE exactly to confirm. Nothing was deleted.');
      }
      return;
    }
    try {
      final receipt = await repos.account.deleteAccount();
      await session.signOut();
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: Text(context.t('delete_account')),
          content: SelectableText(
            '${receipt['status'] ?? 'deleted'}\n'
            '${_receiptLine(receipt)}',
          ),
          actions: [
            FilledButton(
              onPressed: () => Navigator.of(dialogContext).pop(),
              child: Text(context.t('ok')),
            ),
          ],
        ),
      );
      if (!mounted) return;
      Navigator.of(context)
          .pushNamedAndRemoveUntil(Routes.auth, (route) => false);
    } on ApiException catch (error) {
      if (mounted) _snack(error.userMessage);
    }
  }

  /// One readable line per retained item, so the receipt is not a raw map dump.
  static String _receiptLine(Map<String, dynamic> receipt) {
    final retained = receipt['retained'];
    if (retained is! Map) return '';
    return retained.entries
        .map((entry) => '• ${entry.key}: ${entry.value}')
        .join('\n');
  }
}

class _ProfileCard extends StatelessWidget {
  const _ProfileCard({required this.tick});

  final int tick;

  @override
  Widget build(BuildContext context) {
    return AsyncSection<FarmerProfile>(
      refreshTick: tick,
      load: () => context.repos.farmer.me(),
      builder: (context, profile, reload) => SectionCard(
        title: profile.displayName,
        subtitle: profile.placeLabel,
        trailing: Text(
          '${profile.profileCompleteness}%',
          style: Theme.of(context).textTheme.titleMedium,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            InfoRow(label: context.t('village'), value: profile.village ?? '—'),
            InfoRow(label: context.t('taluka'), value: profile.taluka ?? '—'),
            InfoRow(
                label: context.t('district'), value: profile.district ?? '—'),
            InfoRow(label: context.t('state'), value: profile.state ?? '—'),
            InfoRow(label: context.t('pincode'), value: profile.pincode ?? '—'),
            InfoRow(
              label: context.t('experience_years'),
              value: profile.farmingExperienceYears?.toString() ?? '—',
            ),
            InfoRow(
              label: context.t('primary_crops'),
              value: profile.primaryCrops.isEmpty
                  ? '—'
                  : profile.primaryCrops.join(', '),
            ),
            InfoRow(
              label: context.t('total_land'),
              value: profile.totalLandArea == null
                  ? '—'
                  : Fmt.area(profile.totalLandArea, profile.totalLandUnit),
            ),
            if (profile.hasCoordinates)
              InfoRow(
                label: context.t('coordinates'),
                value:
                    '${Fmt.coord(profile.latitude)}, ${Fmt.coord(profile.longitude)}',
              ),
            if (profile.organisation != null)
              InfoRow(
                  label: context.t('organisation'),
                  value: profile.organisation!),
            if (profile.bio != null)
              InfoRow(label: context.t('bio'), value: profile.bio!),
            InfoRow(
              label: context.t('public_profile'),
              value: profile.isPublic ? context.t('yes') : context.t('no'),
            ),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              onPressed: () async {
                final edited = await showModalBottomSheet<bool>(
                  context: context,
                  isScrollControlled: true,
                  builder: (sheetContext) =>
                      _EditProfileSheet(profile: profile),
                );
                if (edited == true) await reload();
              },
              icon: const Icon(Icons.edit_outlined, size: 18),
              label: Text(context.t('edit_profile')),
            ),
          ],
        ),
      ),
    );
  }
}

class _EditProfileSheet extends StatefulWidget {
  const _EditProfileSheet({required this.profile});

  final FarmerProfile profile;

  @override
  State<_EditProfileSheet> createState() => _EditProfileSheetState();
}

class _EditProfileSheetState extends State<_EditProfileSheet> {
  late final _displayName =
      TextEditingController(text: widget.profile.displayName);
  late final _village =
      TextEditingController(text: widget.profile.village ?? '');
  late final _taluka = TextEditingController(text: widget.profile.taluka ?? '');
  late final _district =
      TextEditingController(text: widget.profile.district ?? '');
  late final _state = TextEditingController(text: widget.profile.state ?? '');
  late final _pincode =
      TextEditingController(text: widget.profile.pincode ?? '');
  late final _experience = TextEditingController(
    text: widget.profile.farmingExperienceYears?.toString() ?? '',
  );
  late final _crops =
      TextEditingController(text: widget.profile.primaryCrops.join(', '));
  late final _bio = TextEditingController(text: widget.profile.bio ?? '');
  late final _organisation =
      TextEditingController(text: widget.profile.organisation ?? '');
  late final _latitude = TextEditingController(
    text: widget.profile.latitude?.toString() ?? '',
  );
  late final _longitude = TextEditingController(
    text: widget.profile.longitude?.toString() ?? '',
  );
  late bool _isPublic = widget.profile.isPublic;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    for (final controller in [
      _displayName,
      _village,
      _taluka,
      _district,
      _state,
      _pincode,
      _experience,
      _crops,
      _bio,
      _organisation,
      _latitude,
      _longitude,
    ]) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    final session = context.session;
    final repos = context.repos;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final crops = _crops.text
          .split(',')
          .map((value) => value.trim())
          .where((value) => value.isNotEmpty)
          .toList();
      await repos.farmer.update({
        'display_name': _displayName.text.trim(),
        'village': _village.text.trim().isEmpty ? null : _village.text.trim(),
        'taluka': _taluka.text.trim().isEmpty ? null : _taluka.text.trim(),
        'district':
            _district.text.trim().isEmpty ? null : _district.text.trim(),
        'state': _state.text.trim().isEmpty ? null : _state.text.trim(),
        'pincode': _pincode.text.trim().isEmpty ? null : _pincode.text.trim(),
        'farming_experience_years': int.tryParse(_experience.text.trim()),
        'primary_crops': crops,
        'bio': _bio.text.trim().isEmpty ? null : _bio.text.trim(),
        'organisation': _organisation.text.trim().isEmpty
            ? null
            : _organisation.text.trim(),
        'latitude': double.tryParse(_latitude.text.trim()),
        'longitude': double.tryParse(_longitude.text.trim()),
        'is_public': _isPublic,
      });
      await session.refreshProfile();
      if (!mounted) return;
      Navigator.of(context).pop(true);
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
            Text(context.t('edit_profile'),
                style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 16),
            if (_error != null) ...[
              Notice(kind: NoticeKind.danger, message: _error!),
              const SizedBox(height: 14),
            ],
            FormTextField(
              label: context.t('display_name'),
              controller: _displayName,
              required: true,
            ),
            Row(
              children: [
                Expanded(
                  child: FormTextField(
                      label: context.t('village'), controller: _village),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FormTextField(
                      label: context.t('taluka'), controller: _taluka),
                ),
              ],
            ),
            Row(
              children: [
                Expanded(
                  child: FormTextField(
                      label: context.t('district'), controller: _district),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FormTextField(
                      label: context.t('state'), controller: _state),
                ),
              ],
            ),
            Row(
              children: [
                Expanded(
                  child: FormTextField(
                    label: context.t('pincode'),
                    controller: _pincode,
                    keyboardType: TextInputType.number,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FormTextField(
                    label: context.t('experience_years'),
                    controller: _experience,
                    keyboardType: TextInputType.number,
                  ),
                ),
              ],
            ),
            FormTextField(
              label: context.t('primary_crops'),
              controller: _crops,
              helper: 'Comma separated crop codes, e.g. onion, tomato, soybean',
            ),
            Row(
              children: [
                Expanded(
                  child: FormTextField(
                    label: 'Latitude',
                    controller: _latitude,
                    keyboardType: const TextInputType.numberWithOptions(
                        decimal: true, signed: true),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FormTextField(
                    label: 'Longitude',
                    controller: _longitude,
                    keyboardType: const TextInputType.numberWithOptions(
                        decimal: true, signed: true),
                  ),
                ),
              ],
            ),
            FormTextField(
                label: context.t('organisation'), controller: _organisation),
            FormTextField(
                label: context.t('bio'), controller: _bio, maxLines: 3),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              value: _isPublic,
              onChanged: (value) => setState(() => _isPublic = value),
              title: Text(context.t('public_profile')),
            ),
            const SizedBox(height: 12),
            BusyButton(label: context.t('save'), busy: _busy, onPressed: _save),
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

class _ConsentsCard extends StatelessWidget {
  const _ConsentsCard({required this.tick});

  final int tick;

  @override
  Widget build(BuildContext context) {
    return AsyncSection<ConsentOverview>(
      refreshTick: tick,
      load: () => context.repos.account.consents(),
      builder: (context, overview, reload) => SectionCard(
        title: context.t('consents_title'),
        subtitle: '${context.t('policy_version')}: ${overview.policyVersion}',
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(overview.note, style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 10),
            ...overview.items.map(
              (item) => SwitchListTile(
                contentPadding: EdgeInsets.zero,
                value: item.granted,
                onChanged: item.required
                    ? null
                    : (value) async {
                        try {
                          await context.repos.account.updateConsents([
                            {'kind': item.kind, 'granted': value},
                          ]);
                          await reload();
                        } on ApiException catch (error) {
                          if (!context.mounted) return;
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(content: Text(error.userMessage)),
                          );
                        }
                      },
                title: Row(
                  children: [
                    Expanded(child: Text(item.title)),
                    if (item.required)
                      MetaPill(
                        text: context.t('consent_required'),
                        color: Theme.of(context).colorScheme.outline,
                      ),
                  ],
                ),
                subtitle: Text(
                  item.description,
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                isThreeLine: true,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
