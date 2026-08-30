import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../services/connection_mode.dart';
import '../services/jarvis_api.dart';
import '../services/voice_pipeline.dart';
import '../theme.dart';

class VoiceScreen extends ConsumerStatefulWidget {
  const VoiceScreen({super.key, required this.api});
  final JarvisApi api;

  @override
  ConsumerState<VoiceScreen> createState() => _VoiceScreenState();
}

enum _Phase { idle, recording, transcribing, thinking, speaking }

class _VoiceScreenState extends ConsumerState<VoiceScreen>
    with SingleTickerProviderStateMixin {
  late final VoicePipeline _pipeline = VoicePipeline(widget.api);
  late final AnimationController _pulse = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 900),
  )..repeat(reverse: true);

  _Phase _phase = _Phase.idle;
  String _transcript = '';
  String _reply = '';
  String _language = 'en';
  bool _playOnPc = false;
  Duration _elapsed = Duration.zero;
  Timer? _timer;

  @override
  void dispose() {
    _timer?.cancel();
    _pulse.dispose();
    _pipeline.dispose();
    super.dispose();
  }

  void _setPhase(_Phase p) {
    if (!mounted) return;
    setState(() => _phase = p);
  }

  Future<void> _onTapDown(_) async {
    if (_phase != _Phase.idle) return;
    if (ref.read(connectionMonitorProvider).isStandalone) {
      _showError('Voice needs the PC for STT/TTS — use ASK in lite mode.');
      return;
    }
    setState(() {
      _transcript = '';
      _reply = '';
      _elapsed = Duration.zero;
    });
    try {
      await _pipeline.startRecording();
      _setPhase(_Phase.recording);
      _timer = Timer.periodic(const Duration(milliseconds: 100), (_) {
        setState(() => _elapsed += const Duration(milliseconds: 100));
      });
    } catch (e) {
      _showError(e.toString());
    }
  }

  Future<void> _onTapUp(_) async {
    if (_phase != _Phase.recording) return;
    _timer?.cancel();
    _setPhase(_Phase.transcribing);
    try {
      final wav = await _pipeline.stopRecording();
      if (wav == null) {
        _setPhase(_Phase.idle);
        _showError('Clip too short.');
        return;
      }
      await _pipeline.runTurn(
        wavFile: wav,
        language: _language,
        playOnPc: _playOnPc,
        onTranscript: (t) {
          setState(() => _transcript = t);
          _setPhase(_Phase.thinking);
        },
        onReplyChunk: (c) {
          setState(() => _reply += c);
        },
        onReplyDone: () => _setPhase(_Phase.speaking),
        onAudioReady: (_) {},
      );
    } catch (e) {
      _showError(e.toString());
    } finally {
      _setPhase(_Phase.idle);
    }
  }

  Future<void> _onTapCancel() async {
    _timer?.cancel();
    if (_phase == _Phase.recording) {
      await _pipeline.cancel();
      _setPhase(_Phase.idle);
    }
  }

  void _showError(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(msg, style: const TextStyle(color: Colors.white)),
        backgroundColor: kDanger,
      ),
    );
  }

  Color _phaseColor() {
    switch (_phase) {
      case _Phase.idle:
        return kAccentDim;
      case _Phase.recording:
        return kAccent;
      case _Phase.transcribing:
      case _Phase.thinking:
        return kAmber;
      case _Phase.speaking:
        return kAccent;
    }
  }

  String _phaseLabel() {
    switch (_phase) {
      case _Phase.idle:
        return 'HOLD TO TALK';
      case _Phase.recording:
        return 'LISTENING…  ${_elapsed.inMilliseconds ~/ 100 / 10}s';
      case _Phase.transcribing:
        return 'TRANSCRIBING…';
      case _Phase.thinking:
        return 'THINKING…';
      case _Phase.speaking:
        return 'SPEAKING…';
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('VOICE'),
        actions: [
          PopupMenuButton<String>(
            initialValue: _language,
            onSelected: (v) => setState(() => _language = v),
            icon: Text(_language.toUpperCase(),
                style: const TextStyle(color: kAccent, letterSpacing: 2)),
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
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (_transcript.isNotEmpty)
                    _TranscriptBubble('YOU', _transcript, kAccentDim),
                  if (_reply.isNotEmpty)
                    _TranscriptBubble('JARVIS', _reply, kAccent),
                  const SizedBox(height: 80),
                ],
              ),
            ),
          ),
          SwitchListTile(
            value: _playOnPc,
            onChanged: (v) => setState(() => _playOnPc = v),
            title: const Text('Also speak on PC',
                style: TextStyle(color: Colors.white)),
            activeColor: kAccent,
            dense: true,
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(0, 0, 0, 32),
            child: GestureDetector(
              onTapDown: _onTapDown,
              onTapUp: _onTapUp,
              onTapCancel: _onTapCancel,
              child: AnimatedBuilder(
                animation: _pulse,
                builder: (_, __) {
                  final scale =
                      _phase == _Phase.recording ? 1.0 + _pulse.value * 0.15 : 1.0;
                  return Transform.scale(
                    scale: scale,
                    child: Container(
                      width: 160,
                      height: 160,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: _phaseColor().withValues(alpha: 0.15),
                        border: Border.all(color: _phaseColor(), width: 3),
                        boxShadow: [
                          BoxShadow(
                            color: _phaseColor().withValues(alpha: 0.4),
                            blurRadius: 30,
                            spreadRadius: 4,
                          ),
                        ],
                      ),
                      child: Icon(
                        _phase == _Phase.recording
                            ? Icons.mic
                            : Icons.mic_none,
                        size: 64,
                        color: _phaseColor(),
                      ),
                    ),
                  );
                },
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.only(bottom: 24),
            child: Text(
              _phaseLabel(),
              style: TextStyle(
                color: _phaseColor(),
                letterSpacing: 3,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _TranscriptBubble extends StatelessWidget {
  const _TranscriptBubble(this.label, this.body, this.accent);
  final String label;
  final String body;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: 6),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: kBgPanel,
        border: Border.all(color: accent),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label,
              style: TextStyle(color: accent, letterSpacing: 2, fontSize: 12)),
          const SizedBox(height: 4),
          Text(body,
              style: const TextStyle(color: Colors.white, height: 1.4)),
        ],
      ),
    );
  }
}
