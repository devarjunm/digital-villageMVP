import 'dart:io';

import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/config.dart';
import '../core/l10n.dart';
import '../core/session.dart';
import 'common.dart';

/// Bottom sheet for inspecting and changing the backend address.
///
/// Shown before sign-in (from the login screen) and from in-app settings, so a
/// user who cannot reach the backend is never stuck behind an authenticated
/// screen to fix it. Nothing here is decoration: "Save and test connection"
/// performs real requests to `/health` and `/ready` on the address as typed, and
/// reports what the server actually answered (status code, latency, service and
/// version, and on `/ready` the per-dependency checks).
///
/// `/health` and `/ready` live outside the versioned API prefix, which is why
/// [ApiClient.probe] exists alongside the typed CRUD methods.
class ServerSettingsSheet extends StatefulWidget {
  const ServerSettingsSheet({super.key, required this.session});

  final Session session;

  @override
  State<ServerSettingsSheet> createState() => _ServerSettingsSheetState();
}

class _ServerSettingsSheetState extends State<ServerSettingsSheet> {
  late final TextEditingController _url =
      TextEditingController(text: widget.session.api.baseUrl);
  ServerProbe? _health;
  ServerProbe? _ready;
  bool _busy = false;

  /// Set when the typed address could not be used; the panel then says so
  /// rather than saving an address that would fail silently.
  bool _invalid = false;

  /// The address as stored, shown when it differs from what was typed — typing
  /// `192.168.1.5:8000` really does become `http://192.168.1.5:8000`, and the
  /// user should see that rather than guess.
  String? _savedAs;

  /// Interface addresses of this phone, when the platform reports them. Used
  /// only to compare with what was typed: a *different* subnet is the most
  /// common reason a probe that works on the developer's machine answers
  /// nothing on the phone.
  List<String> _localIPv4 = const [];

  @override
  void dispose() {
    _url.dispose();
    super.dispose();
  }

  @override
  void initState() {
    super.initState();
    // Read the device's own addresses once, as the sheet opens. It is a local,
    // offline call, but it is *not* on the path of the button: probing must
    // start immediately, and if this read fails the advice simply cannot offer
    // the comparison.
    _loadDeviceNetworks();
  }

  Future<void> _loadDeviceNetworks() async {
    List<String> found;
    try {
      final interfaces = await NetworkInterface.list(
        type: InternetAddressType.IPv4,
        includeLinkLocal: false,
        includeLoopback: false,
      );
      found = [
        for (final interface in interfaces)
          for (final address in interface.addresses) address.address,
      ];
    } on Object {
      found = const [];
    }
    if (mounted) setState(() => _localIPv4 = found);
  }

  Future<void> _saveAndCheck() async {
    final accepted = await widget.session.setBaseUrl(_url.text);
    if (!mounted) return;
    if (!accepted) {
      setState(() => _invalid = true);
      return;
    }
    final typed = _url.text;
    setState(() {
      _invalid = false;
      _savedAs = widget.session.api.baseUrl == typed
          ? null
          : widget.session.api.baseUrl;
    });
    // The address as saved, not as typed: `192.168.1.5:8000` becomes
    // `http://192.168.1.5:8000`, and seeing that is how the user knows the
    // panel understood them.
    _url.text = widget.session.api.baseUrl;
    await _check();
  }

  Future<void> _check() async {
    setState(() {
      _busy = true;
      _health = null;
      _ready = null;
    });
    final health = await widget.session.api.probe('/health');
    if (!mounted) return;
    setState(() {
      _health = health;
      _busy = false;
    });
    if (!health.reachable) return;
    // Only worth asking whether it is *ready* if it answered at all.
    final ready = await widget.session.api.probe('/ready');
    if (mounted) setState(() => _ready = ready);
  }

  @override
  Widget build(BuildContext context) {
    final session = widget.session;
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
            Text(
              context.t('server_settings'),
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 4),
            Text(
              context.t('server_help'),
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 16),
            FormTextField(
              label: context.t('server_address'),
              controller: _url,
              hint: AppConfig.platformDefaultBaseUrl,
              keyboardType: TextInputType.url,
              helper: context.t('server_examples'),
            ),
            if (_invalid) ...[
              const SizedBox(height: 6),
              Notice(
                kind: NoticeKind.warning,
                message: context.t('server_invalid'),
              ),
            ] else if (_savedAs != null) ...[
              const SizedBox(height: 6),
              Notice(
                kind: NoticeKind.info,
                message: '${context.t('server_saved')} $_savedAs',
              ),
            ],
            const SizedBox(height: 8),
            Text(
              context.t('check_connection_saves'),
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: BusyButton(
                    label: context.t('check_connection'),
                    busy: _busy,
                    icon: Icons.network_check,
                    onPressed: _saveAndCheck,
                  ),
                ),
                const SizedBox(width: 10),
                OutlinedButton(
                  onPressed: _busy
                      ? null
                      : () async {
                          _url.text = AppConfig.platformDefaultBaseUrl;
                          await widget.session.setBaseUrl(null);
                          if (mounted) setState(() {});
                        },
                  child: Text(context.t('reset_default')),
                ),
              ],
            ),
            const SizedBox(height: 16),
            _ProbeLine(name: '/health', probe: _health, busy: _busy),
            if (_health != null && !_health!.reachable)
              _ProbeAdvice(
                detail: _health!.detail,
                baseUrl: session.api.baseUrl,
                localIPv4: _localIPv4,
              ),
            const SizedBox(height: 6),
            _ProbeLine(name: '/ready', probe: _ready, busy: _busy),
            const SizedBox(height: 14),
            Notice(
              kind: NoticeKind.info,
              title: context.t('after_connecting'),
              message: session.isSignedIn
                  ? 'Signed in as ${session.user?.fullName ?? ''}.'
                  : context.t('sign_in_hint'),
            ),
          ],
        ),
      ),
    );
  }
}

/// One probe result, phrased as what it means for the person holding the phone.
class _ProbeLine extends StatelessWidget {
  const _ProbeLine(
      {required this.name, required this.probe, required this.busy});

  /// Transport failures are reported as what happened, in the app's own
  /// language. An OS message that the app does not recognise is passed through
  /// unchanged rather than replaced by something vaguer.
  static String _reasonLabel(String detail, BuildContext context) =>
      switch (detail) {
        'timeout' => context.t('reason_timeout'),
        'no_url' => context.t('reason_no_url'),
        'no_answer' => context.t('reason_no_answer'),
        _ => detail,
      };

  final String name;
  final ServerProbe? probe;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    final result = probe;
    final scheme = Theme.of(context).colorScheme;
    if (busy && result == null) {
      return Row(
        children: [
          const SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(strokeWidth: 2)),
          const SizedBox(width: 10),
          Text('$name …', style: Theme.of(context).textTheme.bodySmall),
        ],
      );
    }
    if (result == null) {
      return Text(
        '$name —',
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: scheme.onSurfaceVariant,
            ),
      );
    }
    final (icon, color, label) = switch (result) {
      ServerProbe(reachable: false) => (
          Icons.cloud_off_outlined,
          scheme.error,
          context.t('connection_unreachable')
        ),
      ServerProbe(ok: true) => (
          Icons.check_circle_outline,
          const Color(0xFF1F6F3F),
          context.t('connection_reachable')
        ),
      _ => (
          Icons.warning_amber_outlined,
          const Color(0xFF9A5B00),
          context.t('connection_not_ready')
        ),
    };
    final detail = StringBuffer();
    if (result.statusCode != null) detail.write('HTTP ${result.statusCode}');
    if (result.latencyMs != null) {
      detail.write(detail.isEmpty ? '' : ' · ');
      detail.write('${result.latencyMs} ms');
    }
    final service = result.body?['service'];
    final version = result.body?['version'];
    if (service != null || version != null) {
      detail.write(detail.isEmpty ? '' : ' · ');
      detail.write([service, version].whereType<Object>().join(' '));
    }
    if (!result.reachable && result.detail != null) {
      detail.write(detail.isEmpty ? '' : ' · ');
      detail.write(_reasonLabel(result.detail!, context));
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, size: 16, color: color),
            const SizedBox(width: 8),
            Text(name, style: Theme.of(context).textTheme.bodyMedium),
            const SizedBox(width: 8),
            Flexible(
              child: Text(
                label,
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(color: color),
              ),
            ),
          ],
        ),
        if (detail.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(left: 24, top: 2),
            child: Text(
              detail.toString(),
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: scheme.onSurfaceVariant,
                  ),
            ),
          ),
        if (result.body?['checks'] is Map) ...[
          const SizedBox(height: 4),
          ...(result.body!['checks'] as Map<dynamic, dynamic>).entries.map(
                (entry) => Padding(
                  padding: const EdgeInsets.only(left: 24),
                  child: Text(
                    '• ${entry.key}: ${entry.value}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ),
              ),
        ],
      ],
    );
  }
}

/// What to do about a probe that got no answer.
///
/// "No answer" alone is not actionable, so this turns the transport-level reason
/// into the next step, and — the case behind most reports of "the APK cannot
/// reach the server" — tells a phone that is not even on the same network as the
/// address it was given to go and join it. It never claims the backend is broken.
class _ProbeAdvice extends StatelessWidget {
  const _ProbeAdvice({
    required this.detail,
    required this.baseUrl,
    required this.localIPv4,
  });

  final String? detail;
  final String baseUrl;
  final List<String> localIPv4;

  @override
  Widget build(BuildContext context) {
    final lines = <String>[];

    // The reason first: the user can act on "Connection refused" (nothing is
    // listening there) but not on a bare "No answer".
    if (detail == 'no_url') {
      lines.add(context.t('advice_invalid'));
    } else if (detail == 'timeout') {
      lines.add(context.t('advice_timeout'));
    } else if (detail == null || detail == 'no_answer') {
      lines.add(context.t('advice_unreachable'));
    } else {
      lines.add(context.t('advice_refused'));
    }

    if (localIPv4.isEmpty) {
      lines.add(context.t('advice_firewall'));
    } else if (AppConfig.isProbablyForeignSubnet(baseUrl, localIPv4)) {
      lines.add(context.tf('advice_network', {
        'local': localIPv4.join(', '),
        'target': _networkOf(Uri.tryParse(baseUrl)?.host ?? baseUrl),
      }));
    } else {
      lines.add(context.t('advice_same_network'));
    }
    lines.add(context.t('advice_help'));
    lines.add(context.tf('advice_check', {'path': '/health'}));

    return Padding(
      padding: const EdgeInsets.only(left: 24, top: 2),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final line in lines)
            Padding(
              padding: const EdgeInsets.only(bottom: 3),
              child: Text(
                '— $line',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
            ),
        ],
      ),
    );
  }

  /// The /24 of an IPv4 literal in [host]; the host itself for anything else
  /// (a DNS name, or an IPv6 address).
  static String _networkOf(String host) => AppConfig.ipv4Subnet(host) ?? host;
}
