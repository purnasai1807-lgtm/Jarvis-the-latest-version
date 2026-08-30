import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'jarvis_api.dart';

/// Whether the phone is talking to the PC or running on its own.
enum ConnectionMode {
  online,      // PC reachable
  standalone,  // PC unreachable — fall back to lite brain
  unknown,     // not yet probed
}

class ConnectionState {
  const ConnectionState({
    required this.mode,
    required this.lastChange,
    this.lastError,
    this.manualOverride = false,
  });

  final ConnectionMode mode;
  final DateTime lastChange;
  final String? lastError;
  final bool manualOverride;

  bool get isOnline => mode == ConnectionMode.online;
  bool get isStandalone => mode == ConnectionMode.standalone;

  ConnectionState copyWith({
    ConnectionMode? mode,
    DateTime? lastChange,
    String? lastError,
    bool? manualOverride,
  }) {
    return ConnectionState(
      mode: mode ?? this.mode,
      lastChange: lastChange ?? this.lastChange,
      lastError: lastError,
      manualOverride: manualOverride ?? this.manualOverride,
    );
  }
}

/// Periodically probes /api/mobile/health and updates the connection state.
class ConnectionMonitor extends StateNotifier<ConnectionState> {
  ConnectionMonitor()
      : super(ConnectionState(
          mode: ConnectionMode.unknown,
          lastChange: DateTime.now(),
        ));

  Timer? _timer;
  JarvisApi? _api;

  /// Bind to a JarvisApi instance and start polling every [interval].
  void start(JarvisApi api, {Duration interval = const Duration(seconds: 20)}) {
    _api = api;
    _timer?.cancel();
    _timer = Timer.periodic(interval, (_) => probe());
    // Kick off an immediate probe so the UI doesn't sit on "unknown".
    Future.microtask(probe);
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
  }

  Future<void> probe() async {
    if (_api == null || state.manualOverride) return;
    try {
      final ok = await _api!.health();
      _setMode(ok ? ConnectionMode.online : ConnectionMode.standalone,
          error: ok ? null : 'Health check failed');
    } catch (e) {
      debugPrint('ConnectionMonitor: probe error — $e');
      _setMode(ConnectionMode.standalone, error: e.toString());
    }
  }

  void forceStandalone() {
    state = state.copyWith(
      mode: ConnectionMode.standalone,
      lastChange: DateTime.now(),
      manualOverride: true,
    );
  }

  void forceOnline() {
    state = state.copyWith(
      mode: ConnectionMode.online,
      lastChange: DateTime.now(),
      manualOverride: true,
    );
  }

  void clearOverride() {
    state = state.copyWith(manualOverride: false);
    Future.microtask(probe);
  }

  void _setMode(ConnectionMode m, {String? error}) {
    if (state.mode == m && state.lastError == error) return;
    state = ConnectionState(
      mode: m,
      lastChange: DateTime.now(),
      lastError: error,
      manualOverride: state.manualOverride,
    );
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}

final connectionMonitorProvider =
    StateNotifierProvider<ConnectionMonitor, ConnectionState>(
  (ref) => ConnectionMonitor(),
);
