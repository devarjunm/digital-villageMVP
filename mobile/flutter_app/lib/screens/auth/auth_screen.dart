import 'package:flutter/material.dart';

import '../../app.dart';
import '../../core/api_exception.dart';
import '../../core/formatters.dart';
import '../../models/identity.dart';
import '../../widgets/common.dart';
import '../../widgets/server_settings.dart';

/// Sign-in and registration.
///
/// Three real paths are supported, all of them implemented by the backend:
/// password login, OTP login (with the development console provider), and
/// registration. Nothing here simulates an SMS or accepts a magic code.
class AuthScreen extends StatefulWidget {
  const AuthScreen({super.key});

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

enum _Mode { password, otp, register }

class _AuthScreenState extends State<AuthScreen> {
  _Mode _mode = _Mode.password;

  final _identifier = TextEditingController();
  final _password = TextEditingController();
  final _otp = TextEditingController();
  final _fullName = TextEditingController();
  final _registerPassword = TextEditingController();

  bool _busy = false;
  String? _error;
  bool _errorIsNetwork = false;
  OtpChallenge? _challenge;

  @override
  void dispose() {
    _identifier.dispose();
    _password.dispose();
    _otp.dispose();
    _fullName.dispose();
    _registerPassword.dispose();
    super.dispose();
  }

  Future<void> _run(Future<void> Function() action) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
      if (!mounted) return;
      if (context.session.isSignedIn) {
        Navigator.of(context).pushReplacementNamed(Routes.home);
      }
    } on ApiException catch (error) {
      setState(() {
        _error = error.userMessage;
        _errorIsNetwork = error.isNetworkError;
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _passwordLogin() => _run(
        () => context.session.signInWithPassword(
          identifier: _identifier.text.trim(),
          password: _password.text,
        ),
      );

  Future<void> _requestOtp() => _run(() async {
        final challenge = await context.session.requestOtp(
          identifier: _identifier.text.trim(),
        );
        setState(() => _challenge = challenge);
      });

  Future<void> _verifyOtp() => _run(
        () => context.session.signInWithOtp(
          identifier: _identifier.text.trim(),
          code: _otp.text.trim(),
        ),
      );

  Future<void> _register() => _run(() async {
        final identifier = _identifier.text.trim();
        final isEmail = identifier.contains('@');
        await context.session.register(
          fullName: _fullName.text.trim(),
          phone: isEmail ? null : identifier,
          email: isEmail ? identifier : null,
          password:
              _registerPassword.text.isEmpty ? null : _registerPassword.text,
        );
      });

  void _useDemoAccount(String phone) {
    setState(() {
      _mode = _Mode.password;
      _identifier.text = phone;
      _password.text = 'DemoPass!23';
      _error = null;
    });
  }

  Future<void> _openServerSettings() async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (_) => ServerSettingsSheet(session: context.session),
    );
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final session = context.session;
    return Scaffold(
      appBar: AppBar(
        title: Text(context.t('app_title')),
        actions: [
          IconButton(
            tooltip: context.t('server_settings'),
            icon: const Icon(Icons.dns_outlined),
            onPressed: _busy ? null : _openServerSettings,
          ),
        ],
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
          children: [
            Text(
              context.t('app_tagline'),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            // Shown, and changeable, *before* sign-in: a device that cannot
            // reach the developer's machine cannot sign in either, so if this
            // lived only in the profile screen the very first run would be
            // unrecoverable on a physical phone.
            InkWell(
              onTap: _busy ? null : _openServerSettings,
              borderRadius: BorderRadius.circular(10),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 2),
                child: Row(
                  children: [
                    Icon(
                      Icons.dns_outlined,
                      size: 16,
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        '${context.t('server_address')}: ${session.api.baseUrl}',
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color: Theme.of(context)
                                  .colorScheme
                                  .onSurfaceVariant,
                            ),
                      ),
                    ),
                    Text(
                      context.t('change'),
                      style: Theme.of(context).textTheme.labelSmall?.copyWith(
                            color: Theme.of(context).colorScheme.primary,
                          ),
                    ),
                    const SizedBox(width: 4),
                    Icon(
                      Icons.tune,
                      size: 16,
                      color: Theme.of(context).colorScheme.primary,
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 20),
            SegmentedButton<_Mode>(
              segments: [
                ButtonSegment(
                  value: _Mode.password,
                  label: Text(context.t('password')),
                  icon: const Icon(Icons.key_outlined, size: 16),
                ),
                ButtonSegment(
                  value: _Mode.otp,
                  label: const Text('OTP'),
                  icon: const Icon(Icons.sms_outlined, size: 16),
                ),
                ButtonSegment(
                  value: _Mode.register,
                  label: Text(context.t('create_account')),
                  icon: const Icon(Icons.person_add_alt, size: 16),
                ),
              ],
              selected: {_mode},
              onSelectionChanged: (selection) => setState(() {
                _mode = selection.first;
                _error = null;
              }),
            ),
            const SizedBox(height: 20),
            if (_error != null) ...[
              Notice(
                kind: NoticeKind.danger,
                title: context.t('error_title'),
                message: _error!,
                items: _errorIsNetwork
                    ? [context.t('network_error_hint')]
                    : const [],
              ),
              const SizedBox(height: 16),
            ],
            ..._buildModeFields(context),
            const SizedBox(height: 4),
            if (_busy)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: LoadingState(),
              )
            else
              ..._buildActions(context),
            const SizedBox(height: 28),
            _DemoAccountsCard(onPick: _useDemoAccount, enabled: !_busy),
          ],
        ),
      ),
    );
  }

  List<Widget> _buildModeFields(BuildContext context) {
    final apiField = FormTextField(
      label: _mode == _Mode.register
          ? context.t('phone')
          : context.t('phone_or_email'),
      controller: _identifier,
      hint: _mode == _Mode.register
          ? '+919000000001'
          : '+919000000001 / name@example.com',
      keyboardType: TextInputType.emailAddress,
      required: true,
      helper: _mode == _Mode.register ? context.t('phone_hint') : null,
    );

    switch (_mode) {
      case _Mode.password:
        return [
          apiField,
          FormTextField(
            label: context.t('password'),
            controller: _password,
            obscure: true,
            required: true,
            textInputAction: TextInputAction.done,
            onChanged: (_) {},
          ),
        ];
      case _Mode.otp:
        return [
          apiField,
          if (_challenge == null)
            const SizedBox.shrink()
          else ...[
            if (_challenge!.isDemoProvider)
              Notice(
                kind: NoticeKind.demo,
                title: context.t('dev_otp_notice'),
                message: context.t('dev_otp_explanation'),
              ),
            if (_challenge!.devOtp != null) ...[
              const SizedBox(height: 10),
              SectionCard(
                title: 'Development OTP',
                child: Row(
                  children: [
                    SelectableText(
                      _challenge!.devOtp!,
                      style:
                          Theme.of(context).textTheme.headlineSmall?.copyWith(
                        letterSpacing: 4,
                        fontFeatures: const [FontFeature.tabularFigures()],
                      ),
                    ),
                    const Spacer(),
                    Text(
                      _challenge!.provider ?? '',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
            ],
            if (_challenge!.expiresInSeconds != null) ...[
              const SizedBox(height: 12),
              Text(
                '${context.t('otp_requested')} ${_challenge!.expiresInSeconds} ${context.t('seconds')}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
            const SizedBox(height: 16),
            FormTextField(
              label: context.t('otp_code'),
              controller: _otp,
              keyboardType: TextInputType.number,
              required: true,
            ),
          ],
        ];
      case _Mode.register:
        return [
          FormTextField(
            label: context.t('full_name'),
            controller: _fullName,
            required: true,
          ),
          apiField,
          FormTextField(
            label: '${context.t('password')} (${context.t('optional')})',
            controller: _registerPassword,
            obscure: true,
            helper: '${context.t('phone_hint')} — ${context.t('optional')}',
          ),
        ];
    }
  }

  List<Widget> _buildActions(BuildContext context) {
    switch (_mode) {
      case _Mode.password:
        return [
          BusyButton(
            label: context.t('sign_in'),
            icon: Icons.login,
            onPressed: _passwordLogin,
          ),
        ];
      case _Mode.otp:
        return [
          if (_challenge == null)
            BusyButton(
              label: context.t('send_otp'),
              icon: Icons.sms_outlined,
              onPressed: _identifier.text.trim().isEmpty ? null : _requestOtp,
            )
          else ...[
            BusyButton(
              label: context.t('verify_and_sign_in'),
              icon: Icons.verified_outlined,
              onPressed: _verifyOtp,
            ),
            const SizedBox(height: 8),
            OutlinedButton(
              onPressed: _requestOtp,
              child: Text(context.t('resend_otp')),
            ),
          ],
        ];
      case _Mode.register:
        return [
          BusyButton(
            label: context.t('create_account'),
            icon: Icons.person_add_alt,
            onPressed: _register,
          ),
        ];
    }
  }
}

class _DemoAccountsCard extends StatelessWidget {
  const _DemoAccountsCard({required this.onPick, required this.enabled});

  final void Function(String phone) onPick;
  final bool enabled;

  static const _accounts = [
    ('+919000000001', 'farmer'),
    ('+919000000002', 'expert'),
    ('+919000000003', 'moderator'),
    ('+919000000004', 'admin'),
  ];

  @override
  Widget build(BuildContext context) {
    return SectionCard(
      title: context.t('demo_accounts'),
      subtitle: context.t('demo_accounts_note'),
      child: Column(
        children: _accounts
            .map(
              (account) => ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.person_outline, size: 18),
                title: Text(account.$1),
                subtitle: Text(Fmt.humanize(account.$2)),
                trailing: TextButton(
                  onPressed: enabled ? () => onPick(account.$1) : null,
                  child: Text(context.t('use_this_account')),
                ),
              ),
            )
            .toList(),
      ),
    );
  }
}

/// Backend address and reachability, reachable without an account.
///
/// The two probes are the backend's own observability endpoints: `/health`
/// (liveness, no dependencies) and `/ready` (database, cache, providers). They
/// live outside `/api/v1`, which is why [ApiClient.probe] exists. The result
/// distinguishes "no answer at all" from "answered, but not ready", because the
/// fix for the farmer is different in each case.
