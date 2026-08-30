import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/widgets.dart';
import 'package:geolocator/geolocator.dart';

import 'jarvis_api.dart';

/// Foreground geofence engine.
///
/// While the app is in foreground (or has wake permission), polls location
/// every ~30s, computes which named zones contain the user, and POSTs an
/// 'enter' or 'exit' event when membership changes. The PC's routine engine
/// fires whatever's wired to that geofence trigger.
///
/// True background geofences (zero foreground required, system-managed) need
/// a native plugin — that's a follow-up; this MVP works while the app is
/// alive and Android keeps it warm via the heartbeat foreground state.
class LocationService with WidgetsBindingObserver {
  LocationService._();
  static final LocationService instance = LocationService._();

  static const Duration _interval = Duration(seconds: 30);
  static const double _earthRadiusM = 6371000.0;

  JarvisApi? _api;
  Timer? _timer;
  bool _registered = false;
  bool _enabled = false;

  /// zone name → currently inside?
  final Map<String, bool> _membership = {};
  List<Map<String, dynamic>> _zones = const [];

  final ValueNotifier<Position?> lastFix = ValueNotifier<Position?>(null);

  Future<void> start(JarvisApi api) async {
    _api = api;
    if (api.isLiteOnly) return;

    if (!_registered) {
      WidgetsBinding.instance.addObserver(this);
      _registered = true;
    }

    final hasPermission = await _ensurePermission();
    if (!hasPermission) {
      debugPrint('LocationService: permission denied');
      return;
    }
    _enabled = true;
    await _refreshZones();
    _restartTimer();
  }

  void stop() {
    _enabled = false;
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
    if (!_enabled) return;
    if (state == AppLifecycleState.resumed) {
      _refreshZones();
      _restartTimer();
    } else if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached) {
      _timer?.cancel();
      _timer = null;
    }
  }

  Future<bool> _ensurePermission() async {
    if (!await Geolocator.isLocationServiceEnabled()) return false;
    var perm = await Geolocator.checkPermission();
    if (perm == LocationPermission.denied) {
      perm = await Geolocator.requestPermission();
    }
    return perm == LocationPermission.always ||
        perm == LocationPermission.whileInUse;
  }

  Future<void> _refreshZones() async {
    final api = _api;
    if (api == null) return;
    try {
      _zones = await api.listZones();
    } catch (_) {
      // keep last known set
    }
  }

  void _restartTimer() {
    _timer?.cancel();
    if (!_enabled) return;
    _tick();
    _timer = Timer.periodic(_interval, (_) => _tick());
  }

  Future<void> _tick() async {
    if (!_enabled || _api == null) return;
    Position pos;
    try {
      pos = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.medium,
          timeLimit: Duration(seconds: 12),
        ),
      );
    } catch (_) {
      return;
    }
    lastFix.value = pos;

    if (_zones.isEmpty) {
      // Re-fetch occasionally in case the user added a zone via the screen
      await _refreshZones();
      if (_zones.isEmpty) return;
    }

    for (final z in _zones) {
      final name = (z['name'] as String?) ?? '';
      if (name.isEmpty) continue;
      final lat = (z['latitude'] as num?)?.toDouble() ?? 0;
      final lon = (z['longitude'] as num?)?.toDouble() ?? 0;
      final radius = ((z['radius_m'] as num?) ?? 200).toDouble();

      final dist = _haversineMeters(pos.latitude, pos.longitude, lat, lon);
      final inside = dist <= radius;
      final wasInside = _membership[name] ?? false;
      _membership[name] = inside;

      if (inside != wasInside) {
        try {
          await _api!.reportGeofence(
            event: inside ? 'enter' : 'exit',
            zoneName: name,
            latitude: pos.latitude,
            longitude: pos.longitude,
          );
        } catch (e) {
          debugPrint('LocationService: report failed for $name — $e');
        }
      }
    }
  }

  static double _haversineMeters(
      double lat1, double lon1, double lat2, double lon2) {
    final rlat1 = lat1 * math.pi / 180;
    final rlat2 = lat2 * math.pi / 180;
    final dlat = (lat2 - lat1) * math.pi / 180;
    final dlon = (lon2 - lon1) * math.pi / 180;
    final a = math.pow(math.sin(dlat / 2), 2) +
        math.cos(rlat1) * math.cos(rlat2) *
            math.pow(math.sin(dlon / 2), 2);
    return 2 * _earthRadiusM * math.asin(math.sqrt(a));
  }
}
