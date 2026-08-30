import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'screens/dashboard_screen.dart';
import 'screens/setup_screen.dart';
import 'services/push_service.dart';
import 'services/storage.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // Initialize FCM + local notifications + timezone up front.
  // Safe no-op if Firebase isn't configured yet (lite-mode reminders still work).
  await PushService.instance.initialize();
  final creds = await CredentialStore.instance.read();
  runApp(
    ProviderScope(child: JarvisApp(hasCredentials: creds != null)),
  );
}

class JarvisApp extends StatelessWidget {
  const JarvisApp({super.key, required this.hasCredentials});
  final bool hasCredentials;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'J.A.R.V.I.S.',
      debugShowCheckedModeBanner: false,
      theme: jarvisTheme(),
      home: hasCredentials ? const DashboardScreen() : const SetupScreen(),
    );
  }
}
