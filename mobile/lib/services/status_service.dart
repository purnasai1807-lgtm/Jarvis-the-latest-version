import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';

import 'heartbeat_service.dart';

/// Persistent "Live Activity" notification — a sticky entry in the notification
/// drawer that shows Jarvis's current presence + connection state, even when
/// the user is using other apps.
///
/// Implemented as an Android foreground service via `flutter_foreground_task`.
/// The service handler runs in its own isolate and just keeps the notification
/// alive; the main isolate pushes updated text whenever HeartbeatService or the
/// connection mode emits.
@pragma('vm:entry-point')
void jarvisStatusCallback() {
  FlutterForegroundTask.setTaskHandler(_StatusTaskHandler());
}

class _StatusTaskHandler extends TaskHandler {
  @override
  Future<void> onStart(DateTime timestamp, TaskStarter starter) async {
    // No-op — the main isolate updates the notification via updateService().
  }

  @override
  void onRepeatEvent(DateTime timestamp) {
    // Heartbeat tick — service stays alive, no per-tick work needed.
  }

  @override
  Future<void> onDestroy(DateTime timestamp) async {}

  @override
  void onReceiveData(Object data) {
    if (data is Map && data['type'] == 'update') {
      FlutterForegroundTask.updateService(
        notificationTitle: (data['title'] as String?) ?? 'Jarvis',
        notificationText: (data['body'] as String?) ?? '',
      );
    }
  }
}

class StatusService {
  StatusService._();
  static final StatusService instance = StatusService._();

  bool _running = false;
  void Function()? _heartbeatListener;

  /// Initialise channel + options. Safe to call repeatedly.
  Future<void> _ensureInit() async {
    FlutterForegroundTask.init(
      androidNotificationOptions: AndroidNotificationOptions(
        channelId: 'jarvis_status',
        channelName: 'Jarvis live status',
        channelDescription: 'Always-visible Jarvis presence and connection state',
        channelImportance: NotificationChannelImportance.LOW,
        priority: NotificationPriority.LOW,
        onlyAlertOnce: true,
      ),
      iosNotificationOptions: const IOSNotificationOptions(
        showNotification: true,
        playSound: false,
      ),
      foregroundTaskOptions: ForegroundTaskOptions(
        eventAction: ForegroundTaskEventAction.repeat(60000),
        autoRunOnBoot: false,
        allowWakeLock: false,
        allowWifiLock: false,
      ),
    );
  }

  Future<bool> _ensurePermissions() async {
    if (defaultTargetPlatform != TargetPlatform.android) return true;
    if (!await FlutterForegroundTask.isIgnoringBatteryOptimizations) {
      // Best-effort prompt — user can deny and it'll still kinda work.
      await FlutterForegroundTask.requestIgnoreBatteryOptimization();
    }
    final canPost = await FlutterForegroundTask.checkNotificationPermission();
    if (canPost != NotificationPermission.granted) {
      await FlutterForegroundTask.requestNotificationPermission();
    }
    return true;
  }

  Future<void> start() async {
    if (_running) return;
    if (defaultTargetPlatform != TargetPlatform.android &&
        defaultTargetPlatform != TargetPlatform.iOS) {
      return;
    }
    try {
      await _ensureInit();
      await _ensurePermissions();
      final initialBody = _composeBody();
      final result = await FlutterForegroundTask.startService(
        notificationTitle: 'Jarvis',
        notificationText: initialBody,
        callback: jarvisStatusCallback,
      );
      _running = result is ServiceRequestSuccess ||
          await FlutterForegroundTask.isRunningService;
      if (_running) {
        _wireListeners();
      }
    } on PlatformException catch (e) {
      debugPrint('StatusService start failed: $e');
    } catch (e) {
      debugPrint('StatusService start error: $e');
    }
  }

  Future<void> stop() async {
    _unwireListeners();
    if (!_running) return;
    try {
      await FlutterForegroundTask.stopService();
    } catch (_) {}
    _running = false;
  }

  void _wireListeners() {
    // HeartbeatService.latest is a ValueNotifier — listen with a closure
    // we can detach later.
    _heartbeatListener = _push;
    HeartbeatService.instance.latest.addListener(_heartbeatListener!);
    _push();
  }

  void _unwireListeners() {
    if (_heartbeatListener != null) {
      HeartbeatService.instance.latest.removeListener(_heartbeatListener!);
      _heartbeatListener = null;
    }
  }

  /// Update the persistent notification with the latest known state.
  void _push() {
    final body = _composeBody();
    FlutterForegroundTask.updateService(
      notificationTitle: 'Jarvis',
      notificationText: body,
    );
    // Mirror via sendDataToTask for consistency if the handler isolate cares.
    FlutterForegroundTask.sendDataToTask({
      'type': 'update',
      'title': 'Jarvis',
      'body': body,
    });
  }

  String _composeBody() {
    final snap = HeartbeatService.instance.latest.value;
    final state = (snap['presence'] as String?) ?? 'unknown';
    final quiet = snap['quiet_hours'] == true;
    final stateLabel = switch (state) {
      'at_pc' => 'AT PC',
      'phone_only' => 'ON PHONE',
      'away' => 'AWAY',
      _ => '—',
    };
    final pieces = <String>[stateLabel];
    if (quiet) pieces.add('quiet hours');
    return pieces.join(' · ');
  }
}
