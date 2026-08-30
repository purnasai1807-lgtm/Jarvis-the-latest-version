import 'dart:async';

import 'package:flutter/material.dart';

import '../services/jarvis_api.dart';
import '../theme.dart';
import 'ask_screen.dart';

/// Mirror of the cross-device conversation store. Same turns the user sees
/// on the PC's HUD/dashboard, regardless of where they were spoken/typed.
class ConversationScreen extends StatefulWidget {
  const ConversationScreen({super.key, required this.api});
  final JarvisApi api;

  @override
  State<ConversationScreen> createState() => _ConversationScreenState();
}

class _ConversationScreenState extends State<ConversationScreen> {
  static const _refreshInterval = Duration(seconds: 5);

  List<Map<String, dynamic>> _turns = const [];
  String? _error;
  bool _loading = true;
  Timer? _poll;
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _refresh();
    _poll = Timer.periodic(_refreshInterval, (_) => _refresh(silent: true));
  }

  @override
  void dispose() {
    _poll?.cancel();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _refresh({bool silent = false}) async {
    try {
      final turns = await widget.api.conversationRecent(limit: 60);
      if (!mounted) return;
      final shouldStick = _isAtBottom();
      setState(() {
        _turns = turns;
        _error = null;
        _loading = false;
      });
      if (shouldStick) _scrollToBottom();
    } catch (e) {
      if (!mounted) return;
      if (silent) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  bool _isAtBottom() {
    if (!_scroll.hasClients) return true;
    final pos = _scroll.position;
    return pos.maxScrollExtent - pos.pixels < 80;
  }

  void _scrollToBottom() {
    if (!_scroll.hasClients) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      _scroll.jumpTo(_scroll.position.maxScrollExtent);
    });
  }

  Future<void> _confirmClear() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Clear conversation?'),
        content: const Text(
          'This wipes the shared history on every Jarvis surface (PC voice, '
          'HUD, dashboard, this phone). The current session will lose memory.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            style: TextButton.styleFrom(foregroundColor: kDanger),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('CLEAR'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      final n = await widget.api.conversationClear();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Cleared $n turns')),
      );
      await _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Clear failed: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('CONVERSATION'),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: () => _refresh(),
          ),
          IconButton(
            tooltip: 'Clear all',
            icon: const Icon(Icons.delete_outline, color: kDanger),
            onPressed: _confirmClear,
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: kAccent,
        foregroundColor: kBg,
        icon: const Icon(Icons.chat_bubble_outline),
        label: const Text('CONTINUE'),
        onPressed: () => Navigator.of(context).push(
          MaterialPageRoute(builder: (_) => AskScreen(api: widget.api)),
        ),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: kAccent))
          : _error != null && _turns.isEmpty
              ? _ErrorState(message: _error!, onRetry: _refresh)
              : _turns.isEmpty
                  ? const _EmptyState()
                  : RefreshIndicator(
                      color: kAccent,
                      onRefresh: _refresh,
                      child: ListView.builder(
                        controller: _scroll,
                        padding: const EdgeInsets.fromLTRB(12, 12, 12, 96),
                        itemCount: _turns.length,
                        itemBuilder: (ctx, i) => _TurnBubble(turn: _turns[i]),
                      ),
                    ),
    );
  }
}

class _TurnBubble extends StatelessWidget {
  const _TurnBubble({required this.turn});
  final Map<String, dynamic> turn;

  @override
  Widget build(BuildContext context) {
    final role = (turn['role'] as String?) ?? 'user';
    final source = (turn['source'] as String?) ?? '';
    final content = (turn['content'] as String?) ?? '';
    final ts = _formatTs(turn['ts'] as String?);
    final isUser = role == 'user';

    final bubbleColor = isUser ? kAccentDim.withValues(alpha: 0.18) : kBgPanel;
    final align = isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start;
    final mainAlign =
        isUser ? MainAxisAlignment.end : MainAxisAlignment.start;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(
        crossAxisAlignment: align,
        children: [
          Row(
            mainAxisAlignment: mainAlign,
            children: [
              if (source.isNotEmpty) _SourceChip(source: source),
              const SizedBox(width: 6),
              Text(
                ts,
                style: const TextStyle(
                  color: Colors.white38,
                  fontSize: 11,
                  letterSpacing: 1.2,
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          ConstrainedBox(
            constraints: BoxConstraints(
              maxWidth: MediaQuery.of(context).size.width * 0.85,
            ),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                color: bubbleColor,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: isUser ? kAccent.withValues(alpha: 0.5) : kAccentDim,
                  width: 1,
                ),
              ),
              child: Text(
                content,
                style: const TextStyle(color: Colors.white, height: 1.35),
              ),
            ),
          ),
        ],
      ),
    );
  }

  static String _formatTs(String? iso) {
    if (iso == null || iso.isEmpty) return '';
    try {
      final dt = DateTime.parse(iso).toLocal();
      final now = DateTime.now();
      final sameDay = dt.year == now.year &&
          dt.month == now.month &&
          dt.day == now.day;
      final hh = dt.hour.toString().padLeft(2, '0');
      final mm = dt.minute.toString().padLeft(2, '0');
      if (sameDay) return '$hh:$mm';
      return '${dt.month}/${dt.day} $hh:$mm';
    } catch (_) {
      return '';
    }
  }
}

class _SourceChip extends StatelessWidget {
  const _SourceChip({required this.source});
  final String source;

  @override
  Widget build(BuildContext context) {
    final (label, icon, color) = _styleFor(source);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: color.withValues(alpha: 0.6), width: 1),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 10, color: color),
          const SizedBox(width: 4),
          Text(
            label,
            style: TextStyle(
              color: color,
              fontSize: 9,
              letterSpacing: 1.4,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }

  static (String, IconData, Color) _styleFor(String src) {
    switch (src) {
      case 'voice':
        return ('VOICE', Icons.mic, kAccent);
      case 'mobile':
        return ('PHONE', Icons.smartphone, kAmber);
      case 'dashboard':
        return ('WEB', Icons.web, Colors.lightGreenAccent);
      case 'scheduler':
        return ('AUTO', Icons.schedule, Colors.purpleAccent);
      case 'system':
        return ('SYS', Icons.bolt, Colors.white54);
      default:
        return (src.toUpperCase(), Icons.circle, Colors.white54);
    }
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Padding(
        padding: EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.chat_outlined, color: kAccentDim, size: 64),
            SizedBox(height: 12),
            Text(
              'No conversation yet',
              style: TextStyle(color: kAccent, letterSpacing: 2),
            ),
            SizedBox(height: 8),
            Text(
              'Talk to Jarvis on the PC or tap CONTINUE to start here.',
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.white60),
            ),
          ],
        ),
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message, required this.onRetry});
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
            Text(
              message,
              textAlign: TextAlign.center,
              style: const TextStyle(color: kDanger),
            ),
            const SizedBox(height: 16),
            ElevatedButton(onPressed: onRetry, child: const Text('RETRY')),
          ],
        ),
      ),
    );
  }
}
