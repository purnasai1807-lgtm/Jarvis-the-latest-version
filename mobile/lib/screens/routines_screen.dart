import 'package:flutter/material.dart';

import '../services/jarvis_api.dart';
import '../theme.dart';

/// Read-only viewer for the routines defined in data/routines.yaml,
/// with one-tap manual trigger + reload-from-disk. Editing happens in
/// the YAML file itself (kept simple — UI is for visibility & quick run).
class RoutinesScreen extends StatefulWidget {
  const RoutinesScreen({super.key, required this.api});
  final JarvisApi api;

  @override
  State<RoutinesScreen> createState() => _RoutinesScreenState();
}

class _RoutinesScreenState extends State<RoutinesScreen> {
  List<Map<String, dynamic>> _routines = const [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    try {
      final list = await widget.api.listRoutines();
      if (!mounted) return;
      setState(() {
        _routines = list;
        _error = null;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _reload() async {
    try {
      final n = await widget.api.reloadRoutines();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Reloaded $n routines from YAML')),
      );
      await _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Reload failed: $e')),
      );
    }
  }

  Future<void> _run(String name) async {
    try {
      await widget.api.runRoutine(name);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Running "$name"…')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Run failed: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('ROUTINES'),
        actions: [
          IconButton(
            tooltip: 'Reload from YAML',
            icon: const Icon(Icons.sync),
            onPressed: _reload,
          ),
          IconButton(icon: const Icon(Icons.refresh), onPressed: _refresh),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: kAccent))
          : _error != null && _routines.isEmpty
              ? _Error(message: _error!, onRetry: _refresh)
              : _routines.isEmpty
                  ? const _Empty()
                  : RefreshIndicator(
                      color: kAccent,
                      onRefresh: _refresh,
                      child: ListView.builder(
                        padding: const EdgeInsets.fromLTRB(12, 12, 12, 16),
                        itemCount: _routines.length,
                        itemBuilder: (ctx, i) =>
                            _RoutineCard(routine: _routines[i], onRun: _run),
                      ),
                    ),
    );
  }
}

class _RoutineCard extends StatelessWidget {
  const _RoutineCard({required this.routine, required this.onRun});
  final Map<String, dynamic> routine;
  final void Function(String name) onRun;

  @override
  Widget build(BuildContext context) {
    final name = (routine['name'] as String?) ?? '';
    final description = (routine['description'] as String?) ?? '';
    final phrases = (routine['voice_phrases'] as List?)?.cast<String>() ?? const [];
    final schedule = (routine['schedule'] as List?)?.cast<dynamic>() ?? const [];
    final stepCount = (routine['step_count'] as int?) ?? 0;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.auto_awesome_motion, color: kAccent, size: 18),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    name,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      letterSpacing: 1.2,
                    ),
                  ),
                ),
                ElevatedButton.icon(
                  onPressed: () => onRun(name),
                  icon: const Icon(Icons.play_arrow, size: 16),
                  label: const Text('RUN'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: kAccent,
                    foregroundColor: kBg,
                    padding:
                        const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                    minimumSize: Size.zero,
                    visualDensity: VisualDensity.compact,
                  ),
                ),
              ],
            ),
            if (description.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(
                description,
                style: const TextStyle(color: Colors.white60, fontSize: 12),
              ),
            ],
            const SizedBox(height: 10),
            if (phrases.isNotEmpty)
              Wrap(
                spacing: 6,
                runSpacing: 4,
                children: phrases
                    .map(
                      (p) => Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(
                          color: kAccentDim.withValues(alpha: 0.18),
                          borderRadius: BorderRadius.circular(4),
                          border: Border.all(
                              color: kAccentDim.withValues(alpha: 0.6)),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Icon(Icons.mic, size: 10, color: kAccent),
                            const SizedBox(width: 4),
                            Text(
                              '"$p"',
                              style: const TextStyle(
                                  color: kAccent, fontSize: 11),
                            ),
                          ],
                        ),
                      ),
                    )
                    .toList(),
              ),
            if (schedule.isNotEmpty) ...[
              const SizedBox(height: 6),
              Wrap(
                spacing: 6,
                children: schedule.map((s) {
                  final m = s as Map?;
                  final t = (m?['time'] as String?) ?? '';
                  final d = (m?['days'] as String?) ?? '';
                  return Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 8, vertical: 2),
                    decoration: BoxDecoration(
                      color: kAmber.withValues(alpha: 0.18),
                      borderRadius: BorderRadius.circular(4),
                      border: Border.all(color: kAmber.withValues(alpha: 0.6)),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.schedule, size: 10, color: kAmber),
                        const SizedBox(width: 4),
                        Text(
                          '$t $d',
                          style: const TextStyle(color: kAmber, fontSize: 11),
                        ),
                      ],
                    ),
                  );
                }).toList(),
              ),
            ],
            const SizedBox(height: 6),
            Text(
              '$stepCount step${stepCount == 1 ? '' : 's'}',
              style: const TextStyle(color: Colors.white38, fontSize: 11),
            ),
          ],
        ),
      ),
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
            Icon(Icons.auto_awesome_motion, size: 64, color: kAccentDim),
            SizedBox(height: 12),
            Text('No routines yet',
                style: TextStyle(color: kAccent, letterSpacing: 2)),
            SizedBox(height: 8),
            Text(
              'Edit data/routines.yaml on the PC,\n'
              'then tap the sync button to reload.',
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.white60, height: 1.4),
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
