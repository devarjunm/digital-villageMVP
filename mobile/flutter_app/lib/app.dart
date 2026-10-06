import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'core/l10n.dart';

// Re-exported so screens that import `app.dart` (for Routes / context extensions)
// also receive the `context.t('key')` localisation extension.
export 'core/l10n.dart';
import 'core/session.dart';
import 'core/theme.dart';
import 'repositories/repositories.dart';
import 'screens/about/about_screen.dart';
import 'screens/ai/ai_hub_screen.dart';
import 'screens/ai/assistant_screen.dart';
import 'screens/ai/crop_recommendation_screen.dart';
import 'screens/ai/disease_detection_screen.dart';
import 'screens/ai/yield_prediction_screen.dart';
import 'screens/auth/auth_screen.dart';
import 'screens/community/community_screen.dart';
import 'screens/community/create_post_screen.dart';
import 'screens/community/post_detail_screen.dart';
import 'screens/farm/farm_detail_screen.dart';
import 'screens/farm/farms_screen.dart';
import 'screens/home/home_shell.dart';
import 'screens/markets/markets_screen.dart';
import 'screens/notifications/notifications_screen.dart';
import 'screens/profile/profile_screen.dart';
import 'screens/schemes/schemes_screen.dart';
import 'screens/search/search_screen.dart';
import 'screens/splash_screen.dart';
import 'screens/weather/weather_screen.dart';

/// Makes the session and its repositories available to every screen.
///
/// An inherited widget (rather than a service locator or a global) so that a
/// widget test can inject a session with a stub HTTP client, and so that
/// `context.session` is type-checked at compile time.
class AppScope extends InheritedNotifier<Session> {
  const AppScope({super.key, required Session session, required super.child})
      : super(notifier: session);

  static Session of(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<AppScope>();
    assert(scope?.notifier != null, 'AppScope is missing above this widget');
    return scope!.notifier!;
  }

  static Repositories repositoriesOf(BuildContext context) =>
      of(context).repositories;
}

extension SessionContextX on BuildContext {
  Session get session => AppScope.of(this);
  Repositories get repos => AppScope.repositoriesOf(this);
}

/// Route names are collected here so deep links (from a notification's
/// `deep_link` field) can be resolved without string duplication.
class Routes {
  Routes._();

  static const splash = '/';
  static const auth = '/auth';
  static const home = '/home';
  static const farms = '/farms';
  static const aiHub = '/ai';
  static const assistant = '/ai/assistant';
  static const cropRecommendation = '/ai/crop-recommendation';
  static const diseaseDetection = '/ai/disease-detection';
  static const yieldPrediction = '/ai/yield-prediction';
  static const community = '/community';
  static const createPost = '/community/new';
  static const markets = '/markets';
  static const weather = '/weather';
  static const schemes = '/schemes';
  static const notifications = '/notifications';
  static const profile = '/profile';
  static const search = '/search';
  static const about = '/about';

  static Route<void> post(String postId) => MaterialPageRoute<void>(
        settings: const RouteSettings(name: '/community/post'),
        builder: (_) => PostDetailScreen(postId: postId),
      );

  static Route<void> farm(String farmId) => MaterialPageRoute<void>(
        settings: const RouteSettings(name: '/farms/detail'),
        builder: (_) => FarmDetailScreen(farmId: farmId),
      );
}

class DigitalVillageApp extends StatelessWidget {
  const DigitalVillageApp({super.key, required this.session});

  final Session session;

  @override
  Widget build(BuildContext context) {
    return AppScope(
      session: session,
      child: AnimatedBuilder(
        animation: session,
        builder: (context, _) {
          return MaterialApp(
            title: 'Digital Village',
            debugShowCheckedModeBanner: false,
            theme: AppTheme.light(),
            darkTheme: AppTheme.dark(),
            themeMode: ThemeMode.system,
            locale: Locale(session.languageCode),
            supportedLocales: AppLocalizations.supportedLocales,
            localizationsDelegates: const [
              AppLocalizations.delegate,
              // Material/Cupertino widgets need their own bundles for mr and hi:
              // without these, MaterialApp asserts on a non-English locale.
              GlobalMaterialLocalizations.delegate,
              GlobalWidgetsLocalizations.delegate,
              GlobalCupertinoLocalizations.delegate,
            ],
            initialRoute: Routes.splash,
            routes: {
              Routes.splash: (_) => const SplashScreen(),
              Routes.auth: (_) => const AuthScreen(),
              Routes.home: (_) => const HomeShell(),
              Routes.farms: (_) => const FarmsScreen(),
              Routes.aiHub: (_) => const AiHubScreen(),
              Routes.assistant: (_) => const AssistantScreen(),
              Routes.cropRecommendation: (_) =>
                  const CropRecommendationScreen(),
              Routes.diseaseDetection: (_) => const DiseaseDetectionScreen(),
              Routes.yieldPrediction: (_) => const YieldPredictionScreen(),
              Routes.community: (_) => const CommunityScreen(),
              Routes.createPost: (_) => const CreatePostScreen(),
              Routes.markets: (_) => const MarketsScreen(),
              Routes.weather: (_) => const WeatherScreen(),
              Routes.schemes: (_) => const SchemesScreen(),
              Routes.notifications: (_) => const NotificationsScreen(),
              Routes.profile: (_) => const ProfileScreen(),
              Routes.search: (_) => const SearchScreen(),
              Routes.about: (_) => const AboutScreen(),
            },
            onUnknownRoute: (settings) => MaterialPageRoute<void>(
              builder: (_) => Scaffold(
                appBar: AppBar(title: const Text('Digital Village')),
                body: Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const Icon(Icons.explore_off_outlined, size: 36),
                        const SizedBox(height: 12),
                        Text(
                          'This screen (${settings.name}) is not part of the app.',
                          textAlign: TextAlign.center,
                        ),
                        const SizedBox(height: 16),
                        FilledButton(
                          onPressed: () => Navigator.of(context)
                              .pushNamedAndRemoveUntil(
                                  Routes.home, (r) => false),
                          child: const Text('Go to home'),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}

/// Resolves a notification `deep_link` / subject pair to a route.
///
/// Kept in one place so that tapping a notification opens the same screen as
/// navigating to it manually. Unknown links return null and the caller stays
/// where it is rather than pushing a broken route.
class DeepLinks {
  DeepLinks._();

  static void open(BuildContext context,
      {String? link, String? subjectType, String? subjectId}) {
    final navigator = Navigator.of(context);
    final target = link ?? subjectType;
    switch (target) {
      case 'post':
      case 'community_post':
      case 'community':
        if (subjectId != null) {
          navigator.push(Routes.post(subjectId));
          return;
        }
        navigator.pushNamed(Routes.community);
        return;
      case 'farm':
        if (subjectId != null) {
          navigator.push(Routes.farm(subjectId));
          return;
        }
        navigator.pushNamed(Routes.farms);
        return;
      case 'scheme':
      case 'schemes':
        navigator.pushNamed(Routes.schemes);
        return;
      case 'market':
      case 'markets':
        navigator.pushNamed(Routes.markets);
        return;
      case 'weather':
        navigator.pushNamed(Routes.weather);
        return;
      case 'ai':
      case 'prediction':
        navigator.pushNamed(Routes.aiHub);
        return;
      default:
        if (link != null && link.startsWith('/')) {
          navigator.pushNamed(link);
        }
    }
  }
}
