import 'dart:async';

import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';

import '../services/jarvis_api.dart';
import '../services/location_service.dart';
import '../theme.dart';

/// Manage named geofence zones (Home, Work, Gym, …). Each zone has a
/// centre lat/lng and a radius. Routines on the PC can trigger on
/// `geofence.enter:<name>` or `geofence.exit:<name>` events.
class LocationsScreen extends StatefulWidget {
  const LocationsScreen({super.key, required this.api});
  final JarvisApi api;

  @override
  State<LocationsScreen> createState() => _LocationsScreenState();
}

class _LocationsScreenState extends State<LocationsScreen> {
  List<Map<String, dynamic>> _zones = const [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    try {
      final list = await widget.api.listZones();
      if (!mounted) return;
      setState(() {
        _zones = list;
        _loading = false;
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _addCurrent() async {
    final name = await showDialog<String>(
      context: context,
      builder: (_) => const _NameZoneDialog(),
    );
    if (name == null || name.trim().isEmpty) return;

    try {
      // Make sure permission first
      var perm = await Geolocator.checkPermission();
      if (perm == LocationPermission.denied) {
        perm = await Geolocator.requestPermission();
      }
      if (perm != LocationPermission.always &&
          perm != LocationPermission.whileInUse) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Location permission required.')),
        );
        return;
      }

      final pos = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          timeLimit: Duration(seconds: 15),
        ),
      );

      final id = await widget.api.createZone(
        name: name.trim(),
        latitude: pos.latitude,
        longitude: pos.longitude,
        radiusM: 200,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Zone "$name" saved (#$id)')),
      );
      await _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed: $e')),
      );
    }
  }

  Future<void> _delete(int id, String name) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Delete "$name"?'),
        content: const Text(
            'Routines wired to this zone will stop firing until you re-create it.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            style: TextButton.styleFrom(foregroundColor: kDanger),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('DELETE'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await widget.api.deleteZone(id);
      await _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Delete failed: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('LOCATIONS'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _refresh),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: kAccent,
        foregroundColor: kBg,
        icon: const Icon(Icons.my_location),
        label: const Text('SAVE HERE'),
        onPressed: _addCurrent,
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: kAccent))
          : _error != null && _zones.isEmpty
              ? _Error(message: _error!, onRetry: _refresh)
              : Column(
                  children: [
                    const _LiveFixBanner(),
                    Expanded(
                      child: _zones.isEmpty
                          ? const _Empty()
                          : RefreshIndicator(
                              color: kAccent,
                              onRefresh: _refresh,
                              child: ListView.builder(
                                padding: const EdgeInsets.fromLTRB(12, 12, 12, 96),
                                itemCount: _zones.length,
                                itemBuilder: (ctx, i) => _ZoneCard(
                                  zone: _zones[i],
                                  onDelete: _delete,
                                ),
                              ),
                            ),
                    ),
                  ],
                ),
    );
  }
}

class _LiveFixBanner extends StatelessWidget {
  const _LiveFixBanner();

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<Position?>(
      valueListenable: LocationService.instance.lastFix,
      builder: (context, fix, _) {
        if (fix == null) {
          return Container(
            width: double.infinity,
            color: kBgPanel,
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
            child: const Text(
              'Waiting for first GPS fix…',
              style: TextStyle(color: Colors.white54, fontSize: 12),
            ),
          );
        }
        return Container(
          width: double.infinity,
          color: kBgPanel,
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
          child: Row(
            children: [
              const Icon(Icons.gps_fixed, size: 14, color: kAccent),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  '${fix.latitude.toStringAsFixed(5)}, '
                  '${fix.longitude.toStringAsFixed(5)} '
                  '(±${fix.accuracy.toStringAsFixed(0)}m)',
                  style: const TextStyle(color: kAccent, fontSize: 12),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _ZoneCard extends StatelessWidget {
  const _ZoneCard({required this.zone, required this.onDelete});
  final Map<String, dynamic> zone;
  final void Function(int id, String name) onDelete;

  @override
  Widget build(BuildContext context) {
    final id = zone['id'] as int;
    final name = (zone['name'] as String?) ?? '';
    final lat = (zone['latitude'] as num?)?.toDouble() ?? 0;
    final lon = (zone['longitude'] as num?)?.toDouble() ?? 0;
    final radius = ((zone['radius_m'] as num?) ?? 0).toInt();

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.place_outlined, color: kAccent),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    name,
                    style: const TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w600,
                        fontSize: 16),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '${lat.toStringAsFixed(5)}, ${lon.toStringAsFixed(5)}',
                    style: const TextStyle(color: kAmber, fontSize: 12),
                  ),
                  Text(
                    'radius ${radius}m · trigger: '
                    'geofence.enter:${name.toLowerCase()}',
                    style:
                        const TextStyle(color: Colors.white54, fontSize: 11),
                  ),
                ],
              ),
            ),
            IconButton(
              icon: const Icon(Icons.delete_outline, color: kDanger),
              onPressed: () => onDelete(id, name),
            ),
          ],
        ),
      ),
    );
  }
}

class _NameZoneDialog extends StatefulWidget {
  const _NameZoneDialog();

  @override
  State<_NameZoneDialog> createState() => _NameZoneDialogState();
}

class _NameZoneDialogState extends State<_NameZoneDialog> {
  final _ctrl = TextEditingController();

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Save current location'),
      content: TextField(
        controller: _ctrl,
        autofocus: true,
        decoration: const InputDecoration(
          labelText: 'Name',
          hintText: 'e.g. home, work, gym',
          helperText: 'Used as the trigger key in routines.yaml',
          helperMaxLines: 2,
        ),
        textCapitalization: TextCapitalization.words,
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        ElevatedButton(
          onPressed: () => Navigator.pop(context, _ctrl.text.trim()),
          child: const Text('SAVE'),
        ),
      ],
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Padding(
        padding: EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.place_outlined, size: 64, color: kAccentDim),
            SizedBox(height: 12),
            Text('No zones yet',
                style: TextStyle(color: kAccent, letterSpacing: 2)),
            SizedBox(height: 8),
            Text(
              'Stand at a meaningful spot and tap SAVE HERE.\n'
              'Then add a routine in data/routines.yaml:\n\n'
              'triggers:\n  - type: event\n    event: "geofence.enter:home"',
              textAlign: TextAlign.center,
              style: TextStyle(
                  color: Colors.white60, height: 1.4, fontSize: 12),
            ),
          ],
        ),
      ),
    );
  }
}

class _Error extends StatelessWidget {
  const _Error({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off, color: kDanger, size: 56),
            const SizedBox(height: 12),
            Text(message,
                textAlign: TextAlign.center,
                style: const TextStyle(color: kDanger)),
            const SizedBox(height: 16),
            ElevatedButton(onPressed: onRetry, child: const Text('RETRY')),
          ],
        ),
      ),
    );
  }
}
