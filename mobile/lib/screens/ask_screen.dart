import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../services/connection_mode.dart';
import '../services/jarvis_api.dart';
import '../services/push_service.dart';
import '../services/storage.dart';
import '../standalone/lite_brain.dart';
import '../theme.dart';

class AskScreen extends ConsumerStatefulWidget {
  const AskScreen({super.key, required this.api});
  final JarvisApi api;

  @override
  ConsumerState<AskScreen> createState() => _AskScreenState();
}

class _AskScreenState extends ConsumerState<AskScreen> {
  LiteBrain? _liteBrain;
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final List<_Turn> _turns = [];
  bool _streaming = false;
  bool _playOnPc = true;
  String _language = 'en';

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<LiteBrain?> _ensureLiteBrain() async {
    if (_liteBrain != null) return _liteBrain;
    final key = await CredentialStore.instance.readLiteOpenAiKey();
    if (key == null || key.isEmpty) return null;
    _liteBrain = LiteBrain(
      openaiKey: key,
      notifications: PushService.instance.notifications,
    );
    return _liteBrain;
  }

  void _send() async {
    final text = _input.text.trim();
    if (text.isEmpty || _streaming) return;
    _input.clear();
    final user = _Turn.user(text);
    final reply = _Turn.assistant();
    setState(() {
      _turns..add(user)..add(reply);
      _streaming = true;
    });

    final mode = ref.read(connectionMonitorProvider);
    final Stream<AskEvent> stream;
    if (mode.isStandalone) {
      final brain = await _ensureLiteBrain();
      if (brain == null) {
        setState(() {
          reply.text +=
              'Lite mode needs an OpenAI key. Open Settings to add one.';
          _streaming = false;
        });
        return;
      }
      reply.text = '[lite mode] ';
      stream = brain.ask(text: text, language: _language);
    } else {
      stream = widget.api.ask(
        text: text, language: _language, playOnPc: _playOnPc,
      );
    }

    stream.listen(
      (event) {
        switch (event.type) {
          case AskEventType.chunk:
            setState(() => reply.text += event.text ?? '');
            _scrollToBottom();
            break;
          case AskEventType.done:
            setState(() => _streaming = false);
            break;
          case AskEventType.error:
            setState(() {
              reply.text += '\n\n[error: ${event.message}]';
              _streaming = false;
            });
            break;
        }
      },
      onError: (e) {
        setState(() {
          reply.text += '\n\n[stream error: $e]';
          _streaming = false;
        });
      },
      onDone: () {
        if (_streaming) setState(() => _streaming = false);
      },
    );
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(
          _scroll.position.maxScrollExtent,
          duration: const Duration(milliseconds: 150),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('ASK JARVIS'),
        actions: [
          PopupMenuButton<String>(
            initialValue: _language,
            onSelected: (v) => setState(() => _language = v),
            icon: Text(
              _language.toUpperCase(),
              style: const TextStyle(color: kAccent, letterSpacing: 2),
            ),
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'en', child: Text('English')),
              PopupMenuItem(value: 'ro', child: Text('Română')),
            ],
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: ListView.builder(
              controller: _scroll,
              padding: const EdgeInsets.all(12),
              itemCount: _turns.length,
              itemBuilder: (_, i) => _TurnBubble(_turns[i]),
            ),
          ),
          SwitchListTile(
            value: _playOnPc,
            onChanged: (v) => setState(() => _playOnPc = v),
            title: const Text('Speak on PC', style: TextStyle(color: Colors.white)),
            activeColor: kAccent,
            dense: true,
          ),
          Container(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 16),
            color: kBgPanel,
            child: SafeArea(
              top: false,
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _input,
                      textInputAction: TextInputAction.send,
                      onSubmitted: (_) => _send(),
                      decoration: const InputDecoration(
                        hintText: 'Type a command…',
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton(
                    icon: Icon(_streaming ? Icons.hourglass_empty : Icons.send),
                    color: kAccent,
                    onPressed: _streaming ? null : _send,
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Turn {
  _Turn.user(this.text) : isUser = true;
  _Turn.assistant()
      : text = '',
        isUser = false;
  String text;
  final bool isUser;
}

class _TurnBubble extends StatelessWidget {
  const _TurnBubble(this.turn);
  final _Turn turn;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: turn.isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        constraints: const BoxConstraints(maxWidth: 320),
        decoration: BoxDecoration(
          color: turn.isUser ? kAccentDim.withValues(alpha: 0.3) : kBgPanel,
          border: Border.all(color: turn.isUser ? kAccent : kAccentDim),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Text(
          turn.text.isEmpty ? '…' : turn.text,
          style: const TextStyle(color: Colors.white, height: 1.4),
        ),
      ),
    );
  }
}
