import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import '../services/jarvis_api.dart';
import '../theme.dart';

/// Background tasks (research / monitoring). Shows status, lets the user
/// kick off a new task, drill into result + log, and cancel in-flight ones.
class TasksScreen extends StatefulWidget {
  const TasksScreen({super.key, required this.api});
  final JarvisApi api;

  @override
  State<TasksScreen> createState() => _TasksScreenState();
}

class _TasksScreenState extends State<TasksScreen> {
  static const _refreshInterval = Duration(seconds: 4);

  List<Map<String, dynamic>> _tasks = const [];
  bool _loading = true;
  String? _error;
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    _refresh();
    _poll = Timer.periodic(_refreshInterval, (_) {
      // Only poll while there's work in progress — avoids flicker on idle screens
      if (_tasks.any((t) => t['status'] == 'running' || t['status'] == 'pending')) {
        _refresh(silent: true);
      }
    });
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _refresh({bool silent = false}) async {
    try {
      final tasks = await widget.api.listTasks(limit: 30);
      if (!mounted) return;
      setState(() {
        _tasks = tasks;
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

  Future<void> _newTask() async {
    final controller = TextEditingController();
    final prompt = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('New research task'),
        content: TextField(
          controller: controller,
          autofocus: true,
          maxLines: 3,
          decoration: const InputDecoration(
            hintText: 'e.g. find the best 4K monitor under 2000 lei',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () =>
                Navigator.pop(ctx, controller.text.trim()),
            child: const Text('START'),
          ),
        ],
      ),
    );
    if (prompt == null || prompt.isEmpty) return;

    try {
      final id = await widget.api.startTask(prompt: prompt);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Task #$id started')),
      );
      await _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Start failed: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('TASKS'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _refresh),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: kAccent,
        foregroundColor: kBg,
        icon: const Icon(Icons.travel_explore),
        label: const Text('NEW RESEARCH'),
        onPressed: _newTask,
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: kAccent))
          : _error != null && _tasks.isEmpty
              ? _ErrorView(message: _error!, onRetry: _refresh)
              : _tasks.isEmpty
                  ? const _EmptyView()
                  : RefreshIndicator(
                      color: kAccent,
                      onRefresh: _refresh,
                      child: ListView.builder(
                        padding: const EdgeInsets.fromLTRB(12, 12, 12, 96),
                        itemCount: _tasks.length,
                        itemBuilder: (ctx, i) => _TaskCard(
                          task: _tasks[i],
                          api: widget.api,
                          onChanged: _refresh,
                        ),
                      ),
                    ),
    );
  }
}

class _TaskCard extends StatelessWidget {
  const _TaskCard({
    required this.task,
    required this.api,
    required this.onChanged,
  });
  final Map<String, dynamic> task;
  final JarvisApi api;
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context) {
    final id = task['id'] as int;
    final status = (task['status'] as String?) ?? '';
    final prompt = (task['prompt'] as String?) ?? '';
    final preview = (task['result_preview'] as String?) ?? '';
    final logLines = task['log_lines'] is int ? task['log_lines'] as int : 0;
    final updated = (task['updated_at'] as String?) ?? '';

    final (statusLabel, statusColor, statusIcon) = _styleForStatus(status);

    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => _TaskDetailScreen(api: api, taskId: id),
          ),
        ),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(statusIcon, color: statusColor, size: 16),
                  const SizedBox(width: 6),
                  Text(
                    statusLabel,
                    style: TextStyle(
                      color: statusColor,
                      letterSpacing: 1.6,
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(width: 8),
                  Text(
                    '#$id',
                    style: const TextStyle(color: Colors.white38, fontSize: 11),
                  ),
                  const Spacer(),
                  Text(
                    updated.length > 16 ? updated.substring(11, 16) : updated,
                    style: const TextStyle(color: Colors.white38, fontSize: 11),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Text(
                prompt,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(color: Colors.white, height: 1.3),
              ),
              if (preview.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(
                  preview,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: Colors.white60, fontSize: 12),
                ),
              ],
              const SizedBox(height: 6),
              Row(
                children: [
                  Icon(Icons.notes_outlined,
                      size: 12, color: Colors.white38),
                  const SizedBox(width: 4),
                  Text(
                    '$logLines log lines',
                    style: const TextStyle(color: Colors.white38, fontSize: 11),
                  ),
                  const Spacer(),
                  if (status == 'running' || status == 'pending')
                    TextButton(
                      onPressed: () async {
                        try {
                          await api.cancelTask(id);
                          onChanged();
                        } catch (_) {}
                      },
                      style: TextButton.styleFrom(
                        foregroundColor: kDanger,
                        padding: const EdgeInsets.symmetric(horizontal: 8),
                      ),
                      child: const Text('CANCEL'),
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  static (String, Color, IconData) _styleForStatus(String status) {
    switch (status) {
      case 'pending':
        return ('PENDING', Colors.white54, Icons.hourglass_empty);
      case 'running':
        return ('RUNNING', kAmber, Icons.autorenew);
      case 'done':
        return ('DONE', kAccent, Icons.check_circle_outline);
      case 'failed':
        return ('FAILED', kDanger, Icons.error_outline);
      case 'cancelled':
        return ('CANCELLED', Colors.white38, Icons.cancel_outlined);
      default:
        return (status.toUpperCase(), Colors.white54, Icons.circle_outlined);
    }
  }
}

class _TaskDetailScreen extends StatefulWidget {
  const _TaskDetailScreen({required this.api, required this.taskId});
  final JarvisApi api;
  final int taskId;

  @override
  State<_TaskDetailScreen> createState() => _TaskDetailScreenState();
}

class _TaskDetailScreenState extends State<_TaskDetailScreen>
    with SingleTickerProviderStateMixin {
  Map<String, dynamic>? _task;
  Timer? _poll;
  late final TabController _tabs;

  @override
  void initState() {
    super.initState();
    _tabs = TabController(length: 2, vsync: this);
    _refresh();
    _poll = Timer.periodic(const Duration(seconds: 3), (_) {
      final s = _task?['status'];
      if (s == 'running' || s == 'pending') _refresh();
    });
  }

  @override
  void dispose() {
    _poll?.cancel();
    _tabs.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    try {
      final t = await widget.api.getTask(widget.taskId);
      if (!mounted) return;
      setState(() => _task = t);
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final t = _task;
    return Scaffold(
      appBar: AppBar(
        title: Text(t == null ? 'TASK #${widget.taskId}' : 'TASK #${t['id']}'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _refresh),
        ],
        bottom: TabBar(
          controller: _tabs,
          indicatorColor: kAccent,
          labelColor: kAccent,
          unselectedLabelColor: Colors.white54,
          tabs: const [
            Tab(text: 'RESULT'),
            Tab(text: 'LOG'),
          ],
        ),
      ),
      body: t == null
          ? const Center(child: CircularProgressIndicator(color: kAccent))
          : Column(
              children: [
                Container(
                  width: double.infinity,
                  color: kBgPanel,
                  padding: const EdgeInsets.all(14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        t['prompt'] as String? ?? '',
                        style: const TextStyle(color: Colors.white),
                      ),
                      const SizedBox(height: 6),
                      Row(
                        children: [
                          _StatusBadge(status: t['status'] as String? ?? ''),
                          const SizedBox(width: 8),
                          Text(
                            'kind: ${t['kind']}',
                            style: const TextStyle(
                                color: Colors.white54, fontSize: 12),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
                Expanded(
                  child: TabBarView(
                    controller: _tabs,
                    children: [
                      _ResultTab(text: t['result'] as String? ?? ''),
                      _LogTab(text: t['log'] as String? ?? ''),
                    ],
                  ),
                ),
              ],
            ),
    );
  }
}

class _ResultTab extends StatelessWidget {
  const _ResultTab({required this.text});
  final String text;

  @override
  Widget build(BuildContext context) {
    if (text.trim().isEmpty) {
      return const Center(
        child: Text('No result yet.', style: TextStyle(color: Colors.white38)),
      );
    }
    return Markdown(
      data: text,
      padding: const EdgeInsets.all(16),
      selectable: true,
      styleSheet: MarkdownStyleSheet(
        p: const TextStyle(color: Colors.white, height: 1.4),
        h1: const TextStyle(color: kAccent, fontSize: 20),
        h2: const TextStyle(color: kAccent, fontSize: 18),
        h3: const TextStyle(color: kAccent, fontSize: 16),
        listBullet: const TextStyle(color: Colors.white),
        a: const TextStyle(color: kAmber),
        code: const TextStyle(color: kAmber, backgroundColor: kBgPanel),
        blockquote: const TextStyle(color: Colors.white70),
      ),
    );
  }
}

class _LogTab extends StatelessWidget {
  const _LogTab({required this.text});
  final String text;

  @override
  Widget build(BuildContext context) {
    if (text.trim().isEmpty) {
      return const Center(
        child: Text('No log entries.', style: TextStyle(color: Colors.white38)),
      );
    }
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: SelectableText(
        text,
        style: const TextStyle(
          color: Colors.white70,
          fontFamily: 'monospace',
          height: 1.35,
          fontSize: 12,
        ),
      ),
    );
  }
}

class _StatusBadge extends StatelessWidget {
  const _StatusBadge({required this.status});
  final String status;

  @override
  Widget build(BuildContext context) {
    final (label, color, _) = _TaskCard._styleForStatus(status);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: color.withValues(alpha: 0.7), width: 1),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontSize: 10,
          letterSpacing: 1.4,
          fontWeight: FontWeight.w600,
        ),
      ),
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
            Icon(Icons.travel_explore, color: kAccentDim, size: 64),
            SizedBox(height: 12),
            Text(
              'No tasks yet',
              style: TextStyle(color: kAccent, letterSpacing: 2),
            ),
            SizedBox(height: 8),
            Text(
              'Tap NEW RESEARCH to dispatch one,\n'
              'or say "find me…" to Jarvis on the PC.',
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
