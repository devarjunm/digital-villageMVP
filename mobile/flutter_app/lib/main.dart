import 'dart:async';

import 'package:flutter/material.dart';

import 'app.dart';
import 'core/session.dart';

/// Entry point.
///
/// The session is created before the first frame and restored during the splash
/// screen, so a signed-in user never sees a flash of the login form. Failures
/// while restoring are handled inside [Session.restore]: a network problem keeps
/// the cached identity, a rejected token returns to the login screen.
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final session = Session();
  unawaited(session.restore());
  runApp(DigitalVillageApp(session: session));
}
