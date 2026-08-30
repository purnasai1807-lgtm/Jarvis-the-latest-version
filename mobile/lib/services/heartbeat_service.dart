import 'dart:async';

import 'package:flutter/widgets.dart';

import 'jarvis_api.dart';

/// Periodic heartbeat to /api/mobile/heartbeat so the PC knows the phone
/// is reachable. The PC router uses this to decide whether to push to the
/// phone or speak through PC speakers.
///
/// Foreground-only: pauses on AppLifecycleState.paused, resumes on resumed.
class HeartbeatService with WidgetsBindingObserver {
  HeartbeatService._();
  static final HeartbeatService instance = HeartbeatService._();

  static const Duration _interval = Duration(seconds: 30);

  JarvisApi? _api;
  Timer? _timer;
  bool _registered = false;

  /// Latest presence snapshot returned by the PC, or empty if never reached.
  final ValueNotifier<Map<String, dynamic>> latest =
      ValueNotifier<Map<String, dynamic>>(const {});

  void start(JarvisApi api) {
    _api = api;
    if (api.isLiteOnly) return;
    if (!_registered) {
      WidgetsBinding.instance.addObserver(this);
      _registered = true;
    }
    _restart();
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
  }

  void dispose() {
    stop();
    if (_registered) {
      WidgetsBinding.instance.removeObserver(this);
      _registered = false;
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (_api == null || _api!.isLiteOnly) return;
    if (state == AppLifecycleState.resumed) {
      _restart();
    } else if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached) {
      stop();
    }
  }

  void _restart() {
    _timer?.cancel();
    // Fire one immediately so presence is fresh after the app comes forward.
    _tick();
    _timer = Timer.periodic(_interval, (_) => _tick());
  }

  Future<void> _tick() async {
    final api = _api;
    if (api == null || api.isLiteOnly) return;
    try {
      final snap = await api.heartbeat();
      latest.value = snap;
    } catch (_) {
      // Silent — connection_monitor will handle the user-facing offline banner.
    }
  }
}
