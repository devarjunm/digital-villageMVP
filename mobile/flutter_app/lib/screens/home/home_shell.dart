import 'package:flutter/material.dart';

import '../../app.dart';
import '../../core/api_exception.dart';
import '../ai/ai_hub_screen.dart';
import '../community/community_screen.dart';
import '../farm/farms_screen.dart';
import 'dashboard_screen.dart';
import 'more_screen.dart';

/// Bottom-navigation shell. Five destinations, all of which are real screens
/// backed by endpoints — there is no placeholder tab.
class HomeShell extends StatefulWidget {
  const HomeShell({super.key, this.initialIndex = 0});

  final int initialIndex;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  late int _index = widget.initialIndex;
  int _unread = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadUnread());
  }

  Future<void> _loadUnread() async {
    if (!context.session.isSignedIn) return;
    try {
      final count = await context.repos.notifications.unreadCount();
      if (mounted) setState(() => _unread = count.unreadCount);
    } on ApiException {
      // The badge is decoration; a failure here must not disturb the home screen.
    }
  }

  void _go(int index) {
    setState(() => _index = index);
    if (index == 0) _loadUnread();
  }

  @override
  Widget build(BuildContext context) {
    final screens = [
      const DashboardScreen(),
      const FarmsScreen(embedded: true),
      const AiHubScreen(embedded: true),
      const CommunityScreen(embedded: true),
      MoreScreen(unreadCount: _unread, onUnreadChanged: _loadUnread),
    ];

    return Scaffold(
      body: IndexedStack(index: _index, children: screens),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: _go,
        destinations: [
          NavigationDestination(
            icon: const Icon(Icons.home_outlined),
            selectedIcon: const Icon(Icons.home),
            label: context.t('nav_home'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.grass_outlined),
            selectedIcon: const Icon(Icons.grass),
            label: context.t('nav_farm'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.auto_awesome_outlined),
            selectedIcon: const Icon(Icons.auto_awesome),
            label: context.t('nav_ai'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.forum_outlined),
            selectedIcon: const Icon(Icons.forum),
            label: context.t('nav_community'),
          ),
          NavigationDestination(
            icon: Badge(
              isLabelVisible: _unread > 0,
              label: Text('$_unread'),
              child: const Icon(Icons.menu_outlined),
            ),
            selectedIcon: const Icon(Icons.menu),
            label: context.t('nav_more'),
          ),
        ],
      ),
    );
  }
}

/// A screen shown inside the shell: it must not push its own app bar title twice
/// and it must show a sign-in prompt when the session is gone.
class EmbeddedScreenScaffold extends StatelessWidget {
  const EmbeddedScreenScaffold({
    super.key,
    required this.title,
    required this.child,
    this.actions,
    this.embedded = false,
    this.floatingActionButton,
    this.onRefresh,
  });

  final String title;
  final Widget child;
  final List<Widget>? actions;
  final bool embedded;
  final Widget? floatingActionButton;
  final Future<void> Function()? onRefresh;

  @override
  Widget build(BuildContext context) {
    final session = context.session;
    final body = session.isSignedIn
        ? (onRefresh == null
            ? child
            : RefreshIndicator(onRefresh: onRefresh!, child: child))
        : const _SignInPrompt();

    return Scaffold(
      appBar: AppBar(
        title: Text(title),
        automaticallyImplyLeading: !embedded,
        actions: actions,
      ),
      body: body,
      floatingActionButton: session.isSignedIn ? floatingActionButton : null,
    );
  }
}

class _SignInPrompt extends StatelessWidget {
  const _SignInPrompt();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.lock_outline, size: 40),
            const SizedBox(height: 14),
            Text(context.t('sign_in_required'),
                style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: () => Navigator.of(context).pushNamed(Routes.auth),
              child: Text(context.t('sign_in')),
            ),
          ],
        ),
      ),
    );
  }
}
