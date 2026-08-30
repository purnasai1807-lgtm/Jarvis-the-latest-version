import 'dart:convert';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_timezone/flutter_timezone.dart';
import 'package:timezone/data/latest_all.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

import 'jarvis_api.dart';
import 'storage.dart';

/// Background isolate handler — must be top-level. Fires when a data/
/// notification message arrives while the app is killed/backgrounded.
@pragma('vm:entry-point')
Future<void> _onBackgroundMessage(RemoteMessage message) async {
  // We don't do work here — the system tray handles display when the FCM
  // payload includes a `notification` block. This stub just keeps the
  // isolate alive so Flutter doesn't drop the message.
}

/// Top-level handler for action-button taps that arrive while the app is
/// in the background. Must be top-level (entry point for the isolate).
@pragma('vm:entry-point')
void _backgroundActionTap(NotificationResponse response) {
  // Forward to the singleton's dispatcher; if the app isn't running, this
  // wakes it up and the call is replayed on launch via getNotificationAppLaunchDetails.
  PushService.instance._handleActionTap(response);
}

class PushService {
  PushService._();
  static final PushService instance = PushService._();

  final FlutterLocalNotificationsPlugin _local =
      FlutterLocalNotificationsPlugin();
  bool _initialized = false;
  bool _firebaseReady = false;

  /// Exposed so lite-mode reminders can schedule via this same plug-in.
  FlutterLocalNotificationsPlugin get notifications => _local;

  Future<void> initialize() async {
    if (_initialized) return;

    try {
      tzdata.initializeTimeZones();
      final tzName = await FlutterTimezone.getLocalTimezone();
      tz.setLocalLocation(tz.getLocation(tzName));
    } catch (e) {
      debugPrint('PushService: timezone init failed — $e');
    }

    const androidInit = AndroidInitializationSettings('@mipmap/ic_launcher');
    const iosInit = DarwinInitializationSettings();
    await _local.initialize(
      const InitializationSettings(android: androidInit, iOS: iosInit),
      onDidReceiveNotificationResponse: _handleActionTap,
      onDidReceiveBackgroundNotificationResponse: _backgroundActionTap,
    );

    const channel = AndroidNotificationChannel(
      'jarvis_reminders',
      'Reminders',
      description: 'Reminders + push from the PC',
      importance: Importance.high,
    );
    await _local
        .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(channel);

    try {
      await Firebase.initializeApp();
      _firebaseReady = true;
      FirebaseMessaging.onBackgroundMessage(_onBackgroundMessage);

      // Foreground messages — surface via local notification with action
      // buttons parsed from the FCM data payload.
      FirebaseMessaging.onMessage.listen(_showFromFcm);
    } catch (e) {
      debugPrint('PushService: Firebase init skipped — $e');
      _firebaseReady = false;
    }

    _initialized = true;
  }

  /// Render a foreground FCM message as a local notification, including
  /// any action buttons declared in its data payload.
  void _showFromFcm(RemoteMessage msg) {
    final n = msg.notification;
    if (n == null) return;

    final data = msg.data;
    final actions = _decodeActions(data['actions']);
    final kind = (data['kind'] ?? '') as String;

    // Build a payload string we'll receive back when the user taps an action
    // — bundles the action context (kind + data) plus the title/body so the
    // server can re-fire snoozed alerts verbatim.
    final tapPayload = jsonEncode({
      'kind': kind,
      'data': {
        ...data,
        '__title': n.title ?? '',
        '__body': n.body ?? '',
      },
    });

    _local.show(
      n.hashCode,
      n.title ?? 'Jarvis',
      n.body ?? '',
      NotificationDetails(
        android: AndroidNotificationDetails(
          'jarvis_reminders',
          'Reminders',
          importance: Importance.high,
          priority: Priority.high,
          actions: actions
              .map((a) => AndroidNotificationAction(a.id, a.label,
                  showsUserInterface: false, cancelNotification: true))
              .toList(),
        ),
        iOS: const DarwinNotificationDetails(),
      ),
      payload: tapPayload,
    );
  }

  /// Dispatch a tap or action-button press back to the PC.
  Future<void> _handleActionTap(NotificationResponse response) async {
    final actionId = response.actionId;
    if (actionId == null || actionId.isEmpty) {
      // Body tap (no specific action) — open the app and we're done.
      return;
    }
    Map<String, dynamic> ctx = {};
    final raw = response.payload;
    if (raw != null && raw.isNotEmpty) {
      try {
        ctx = jsonDecode(raw) as Map<String, dynamic>;
      } catch (_) {
        ctx = {};
      }
    }
    final kind = (ctx['kind'] as String?) ?? '';
    final data = (ctx['data'] as Map?)?.cast<String, dynamic>() ?? {};
    final stringData = data.map((k, v) => MapEntry(k, v.toString()));

    try {
      final creds = await CredentialStore.instance.read();
      if (creds == null) return;
      final api = JarvisApi(creds);
      if (api.isLiteOnly) return;
      await api.notificationAction(
        actionId: actionId,
        kind: kind,
        data: stringData,
      );
    } catch (e) {
      debugPrint('PushService: action $actionId dispatch failed — $e');
    }
  }

  /// Decode the FCM data['actions'] JSON string into typed pairs.
  List<({String id, String label})> _decodeActions(dynamic raw) {
    if (raw is! String || raw.isEmpty) return const [];
    try {
      final list = jsonDecode(raw);
      if (list is! List) return const [];
      return list
          .whereType<Map>()
          .map((m) => (
                id: (m['id'] ?? '').toString(),
                label: (m['label'] ?? '').toString(),
              ))
          .where((a) => a.id.isNotEmpty && a.label.isNotEmpty)
          .toList();
    } catch (_) {
      return const [];
    }
  }

  /// Request notification permission and register the FCM token with the PC.
  Future<void> registerWith(JarvisApi api) async {
    if (!_firebaseReady) return;
    if (api.isLiteOnly) return;

    try {
      final fm = FirebaseMessaging.instance;
      await fm.requestPermission(alert: true, badge: true, sound: true);

      final token = await fm.getToken();
      if (token == null || token.isEmpty) {
        debugPrint('PushService: no FCM token yet');
        return;
      }
      await api.registerDevice(
        token: token,
        platform: defaultTargetPlatform.name,
      );

      // Re-register on rotation so the PC always has a live token.
      fm.onTokenRefresh.listen((newToken) async {
        try {
          await api.registerDevice(
            token: newToken,
            platform: defaultTargetPlatform.name,
          );
        } catch (e) {
          debugPrint('PushService: token refresh register failed — $e');
        }
      });
    } catch (e) {
      debugPrint('PushService: registerWith failed — $e');
    }
  }

  Future<void> unregister(JarvisApi api) async {
    if (!_firebaseReady) return;
    try {
      final token = await FirebaseMessaging.instance.getToken();
      if (token != null) await api.unregisterDevice(token);
    } catch (e) {
      debugPrint('PushService: unregister failed — $e');
    }
  }
}
