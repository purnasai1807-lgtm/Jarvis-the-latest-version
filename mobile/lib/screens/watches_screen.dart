import 'dart:async';

import 'package:flutter/material.dart';

import '../services/jarvis_api.dart';
import '../theme.dart';

/// URL watches — periodic page checks that fire a notification when a
/// condition becomes true. Backed by /api/mobile/watches.
class WatchesScreen extends StatefulWidget {
  const WatchesScreen({super.key, required this.api});
  final JarvisApi api;

  @override
  State<WatchesScreen> createState() => _WatchesScreenState();
}

class _WatchesScreenState extends State<WatchesScreen> {
  List<Map<String, dynamic>> _watches = const [];
  bool _showArchived = false;
  bool _loading = true;
  String? _error;
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    _refresh();
    _poll = Timer.periodic(const Duration(seconds: 15), (_) => _refresh(silent: true));
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _refresh({bool silent = false}) async {
    try {
      final list = await widget.api.listWatches(includeArchived: _showArchived);
      if (!mounted) return;
      setState(() {
        _watches = list;
        _error = null;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      if (silent) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _newWatch() async {
    final result = await showDialog<_WatchDraft>(
      context: context,
      builder: (_) => const _NewWatchDialog(),
    );
    if (result == null) return;
    try {
      final id = await widget.api.createWatch(
        url: result.url,
        condition: result.condition,
        intervalMinutes: result.intervalMinutes,
        label: result.label,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Watch #$id created')),
      );
      await _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Create failed: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('WATCHES'),
        actions: [
          IconButton(
            tooltip: _showArchived ? 'Hide archived' : 'Show archived',
            icon: Icon(_showArchived ? Icons.visibility : Icons.visibility_off),
            onPressed: () {
              setState(() => _showArchived = !_showArchived);
              _refresh();
            },
          ),
          IconButton(icon: const Icon(Icons.refresh), onPressed: _refresh),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: kAccent,
        foregroundColor: kBg,
        icon: const Icon(Icons.add_alert_outlined),
        label: const Text('NEW WATCH'),
        onPressed: _newWatch,
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: kAccent))
          : _error != null && _watches.isEmpty
              ? _ErrorView(message: _error!, onRetry: _refresh)
              : _watches.isEmpty
                  ? const _EmptyView()
                  : RefreshIndicator(
                      color: kAccent,
                      onRefresh: _refresh,
                      child: ListView.builder(
                        padding: const EdgeInsets.fromLTRB(12, 12, 12, 96),
                        itemCount: _watches.length,
                        itemBuilder: (ctx, i) => _WatchCard(
                          watch: _watches[i],
                          api: widget.api,
                          onChanged: _refresh,
                        ),
                      ),
                    ),
    );
  }
}

class _WatchCard extends StatelessWidget {
  const _WatchCard({
    required this.watch,
    required this.api,
    required this.onChanged,
  });
  final Map<String, dynamic> watch;
  final JarvisApi api;
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context) {
    final id = watch['id'] as int;
    final url = (watch['url'] as String?) ?? '';
    final cond = (watch['condition'] as String?) ?? 'changed';
    final status = (watch['status'] as String?) ?? '';
    final label = (watch['label'] as String?) ?? '';
    final intervalMin = ((watch['interval_seconds'] ?? 0) as int) ~/ 60;
    final hits = (watch['hits'] ?? 0) as int;
    final last = (watch['last_check_at'] as String?) ?? '';
    final lastMsg = (watch['last_message'] as String?) ?? '';

    final (statusLabel, statusColor) = _styleForStatus(status);
    final isActive = status == 'active';
    final isFired = status == 'fired';

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 8,
                  height: 8,
                  decoration: BoxDecoration(
                    color: statusColor,
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: 8),
                Text(
                  statusLabel,
                  style: TextStyle(
                    color: statusColor,
                    fontSize: 11,
                    letterSpacing: 1.6,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(width: 8),
                Text(
                  '#$id · every ${intervalMin}m · ${hits}x fired',
                  style: const TextStyle(color: Colors.white38, fontSize: 11),
                ),
              ],
            ),
            const SizedBox(height: 8),
            if (label.isNotEmpty) ...[
              Text(
                label,
                style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w600,
                    fontSize: 14),
              ),
              const SizedBox(height: 4),
            ],
            Text(
              url,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: kAmber, fontSize: 12),
            ),
            const SizedBox(height: 6),
            Row(
              children: [
                const Icon(Icons.help_outline, size: 12, color: Colors.white54),
                const SizedBox(width: 4),
                Expanded(
                  child: Text(
                    cond,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: Colors.white70, fontSize: 12),
                  ),
                ),
              ],
            ),
            if (lastMsg.isNotEmpty) ...[
              const SizedBox(height: 6),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: kBgPanel,
                  borderRadius: BorderRadius.circular(4),
                  border: Border.all(color: kAccentDim.withValues(alpha: 0.4)),
                ),
                child: Text(
                  lastMsg,
                  style: const TextStyle(color: Colors.white60, fontSize: 11),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
            const SizedBox(height: 4),
            Row(
              children: [
                Text(
                  last.isNotEmpty
                      ? 'last: ${last.length > 16 ? last.substring(11, 16) : last}'
                      : 'never checked',
                  style: const TextStyle(color: Colors.white38, fontSize: 11),
                ),
                const Spacer(),
                if (isFired)
                  TextButton(
                    onPressed: () async {
                      await api.reactivateWatch(id);
                      onChanged();
                    },
                    style: TextButton.styleFrom(
                      foregroundColor: kAccent,
                      padding: const EdgeInsets.symmetric(horizontal: 8),
                    ),
                    child: const Text('RE-ARM'),
                  ),
                if (isActive || isFired)
                  TextButton(
                    onPressed: () async {
                      await api.stopWatch(id);
                      onChanged();
                    },
                    style: TextButton.styleFrom(
                      foregroundColor: kDanger,
                      padding: const EdgeInsets.symmetric(horizontal: 8),
                    ),
                    child: const Text('STOP'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  static (String, Color) _styleForStatus(String status) {
    switch (status) {
      case 'active':
        return ('ACTIVE', kAccent);
      case 'fired':
        return ('FIRED', kAmber);
      case 'archived':
        return ('STOPPED', Colors.white38);
      default:
        return (status.toUpperCase(), Colors.white54);
    }
  }
}

class _NewWatchDialog extends StatefulWidget {
  const _NewWatchDialog();

  @override
  State<_NewWatchDialog> createState() => _NewWatchDialogState();
}

class _WatchDraft {
  _WatchDraft({
    required this.url,
    required this.condition,
    required this.intervalMinutes,
    required this.label,
  });
  final String url;
  final String condition;
  final int intervalMinutes;
  final String label;
}

class _NewWatchDialogState extends State<_NewWatchDialog> {
  final _url = TextEditingController();
  final _cond = TextEditingController(text: 'changed');
  final _label = TextEditingController();
  int _interval = 30;

  @override
  void dispose() {
    _url.dispose();
    _cond.dispose();
    _label.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('New watch'),
      content: SizedBox(
        width: 420,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              TextField(
                controller: _url,
                autofocus: true,
                decoration: const InputDecoration(
                  labelText: 'URL',
                  hintText: 'https://...',
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _label,
                decoration: const InputDecoration(
                  labelText: 'Label (optional)',
                  hintText: 'e.g. AMD CPU on PCGarage',
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _cond,
                maxLines: 2,
                decoration: const InputDecoration(
                  labelText: 'Condition',
                  hintText: '"changed" or a yes/no question',
                  helperText:
                      'e.g. "is the price under 1500 lei?" · "is the PR approved?"',
                  helperMaxLines: 2,
                ),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  const Text('Every', style: TextStyle(color: Colors.white70)),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Slider(
                      value: _interval.toDouble(),
                      min: 5,
                      max: 240,
                      divisions: 47,
                      label: '$_interval min',
                      onChanged: (v) =>
                          setState(() => _interval = v.round()),
                    ),
                  ),
                  Text('${_interval}m',
                      style: const TextStyle(color: kAccent)),
                ],
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        ElevatedButton(
          onPressed: () {
            final url = _url.text.trim();
            if (url.isEmpty) return;
            Navigator.pop(
              context,
              _WatchDraft(
                url: url,
                condition: _cond.text.trim().isEmpty
                    ? 'changed'
                    : _cond.text.trim(),
                intervalMinutes: _interval,
                label: _label.text.trim(),
              ),
            );
          },
          child: const Text('CREATE'),
        ),
      ],
    );
  }
}

class _EmptyView extends StatelessWidget {
  const _EmptyView();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Padding(
        padding: EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.add_alert_outlined, color: kAccentDim, size: 64),
            SizedBox(height: 12),
            Text('No watches', style: TextStyle(color: kAccent, letterSpacing: 2)),
            SizedBox(height: 8),
            Text(
              'Tap NEW WATCH or say:\n'
              '"Hey Jarvis, watch this PR for review"',
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.white60, height: 1.4),
            ),
          ],
        ),
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message, required this.onRetry});
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
