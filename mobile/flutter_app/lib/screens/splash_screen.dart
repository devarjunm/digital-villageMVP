import 'package:flutter/material.dart';

import '../app.dart';
import '../core/config.dart';
import '../core/session.dart';

/// Waits for [Session.restore] and then routes to the shell or the login screen.
///
/// It also surfaces the configured backend address, because "the app cannot
/// reach the server" is the single most common problem when running the app
/// against a development backend, and the address is the first thing to check.
class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _route());
  }

  Future<void> _route() async {
    final session = context.session;
    // Give restore() a moment to finish; it may already have completed.
    for (var attempt = 0; attempt < 40; attempt++) {
      if (session.status != SessionStatus.checking) break;
      await Future<void>.delayed(const Duration(milliseconds: 100));
    }
    if (!mounted) return;
    final target = session.isSignedIn ? Routes.home : Routes.auth;
    Navigator.of(context).pushReplacementNamed(target);
  }

  @override
  Widget build(BuildContext context) {
    final session = context.session;
    return Scaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // The same mark as the launcher icon and the Android window
              // splash, so the app does not visibly change identity between the
              // launcher tap and the first screen (scripts/make_branding.py).
              Image.asset(
                'assets/branding/app_icon.png',
                width: 96,
                height: 96,
                filterQuality: FilterQuality.medium,
                semanticLabel: AppConfig.appName,
              ),
              const SizedBox(height: 16),
              Text(
                AppConfig.appName,
                style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
              ),
              const SizedBox(height: 6),
              Text(
                context.t('app_tagline'),
                style: Theme.of(context).textTheme.bodyMedium,
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 28),
              const SizedBox(
                width: 24,
                height: 24,
                child: CircularProgressIndicator(strokeWidth: 2.4),
              ),
              const SizedBox(height: 28),
              Text(
                session.api.baseUrl,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
