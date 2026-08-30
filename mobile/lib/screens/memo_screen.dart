import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:record/record.dart';

import '../services/jarvis_api.dart';
import '../theme.dart';

/// Voice memo: tap to record → server transcribes + auto-categorises into
/// idea / todo / note / decision / reminder, with tags + summary, then
/// optionally saves to the long-term memory store.
class MemoScreen extends StatefulWidget {
  const MemoScreen({super.key, required this.api});
  final JarvisApi api;

  @override
  State<MemoScreen> createState() => _MemoScreenState();
}

enum _Phase { idle, recording, uploading, done }

class _MemoScreenState extends State<MemoScreen>
    with SingleTickerProviderStateMixin {
  final _recorder = AudioRecorder();
  late final AnimationController _pulse = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 900),
  )..repeat(reverse: true);

  _Phase _phase = _Phase.idle;
  String? _path;
  DateTime? _startedAt;
  Duration _elapsed = Duration.zero;
  Timer? _ticker;

  Map<String, dynamic>? _result;
  String? _error;

  @override
  void dispose() {
    _ticker?.cancel();
    _pulse.dispose();
    _recorder.dispose();
    super.dispose();
  }

  Future<void> _toggle() async {
    if (_phase == _Phase.recording) {
      await _stopAndUpload();
    } else if (_phase == _Phase.idle || _phase == _Phase.done) {
      await _startRecording();
    }
  }

  Future<void> _startRecording() async {
    if (!await _recorder.hasPermission()) {
      final ok = await Permission.microphone.request();
      if (!ok.isGranted) {
        setState(() => _error = 'Microphone permission denied.');
        return;
      }
    }
    setState(() {
      _result = null;
      _error = null;
      _elapsed = Duration.zero;
    });
    try {
      final dir = await getTemporaryDirectory();
      final path =
          '${dir.path}/memo_${DateTime.now().millisecondsSinceEpoch}.wav';
      await _recorder.start(
        const RecordConfig(
            encoder: AudioEncoder.wav, sampleRate: 16000, numChannels: 1),
        path: path,
      );
      _path = path;
      _startedAt = DateTime.now();
      _ticker = Timer.periodic(const Duration(milliseconds: 100), (_) {
        if (!mounted) return;
        setState(() => _elapsed += const Duration(milliseconds: 100));
      });
      setState(() => _phase = _Phase.recording);
    } catch (e) {
      setState(() => _error = 'Start failed: $e');
    }
  }

  Future<void> _stopAndUpload() async {
    _ticker?.cancel();
    setState(() => _phase = _Phase.uploading);

    String? finalPath;
    try {
      finalPath = await _recorder.stop();
    } catch (_) {}
    final path = finalPath ?? _path;
    final started = _startedAt;
    _startedAt = null;
    _path = null;
    if (path == null ||
        (started != null &&
            DateTime.now().difference(started) <
                const Duration(milliseconds: 400))) {
      setState(() {
        _phase = _Phase.idle;
        _error = 'Memo too short.';
      });
      return;
    }
    final wav = File(path);

    try {
      final res = await widget.api.uploadMemo(
        wavFile: wav,
        language: 'en',
        autoSave: true,
      );
      if (!mounted) return;
      setState(() {
        _result = res;
        _phase = _Phase.done;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = 'Upload failed: $e';
        _phase = _Phase.idle;
      });
    } finally {
      try {
        await wav.delete();
      } catch (_) {}
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('VOICE MEMO')),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 24),
              Center(child: _RecordButton(
                phase: _phase,
                pulse: _pulse,
                elapsed: _elapsed,
                onTap: _toggle,
              )),
              const SizedBox(height: 12),
              Center(
                child: Text(
                  _phaseText(),
                  style: const TextStyle(color: kAccent, letterSpacing: 2),
                ),
              ),
              const SizedBox(height: 24),
              if (_error != null)
                Card(
                  color: kDanger.withValues(alpha: 0.15),
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Text(_error!,
                        style: const TextStyle(color: kDanger)),
                  ),
                ),
              if (_result != null)
                Expanded(child: SingleChildScrollView(child: _ResultCard(_result!))),
            ],
          ),
        ),
      ),
    );
  }

  String _phaseText() {
    switch (_phase) {
      case _Phase.idle:
        return 'TAP TO RECORD';
      case _Phase.recording:
        return 'RECORDING — ${_elapsed.inSeconds}s';
      case _Phase.uploading:
        return 'TRANSCRIBING…';
      case _Phase.done:
        final saved = _result?['saved'] == true;
        return saved ? 'SAVED' : 'DONE';
    }
  }
}

class _RecordButton extends StatelessWidget {
  const _RecordButton({
    required this.phase,
    required this.pulse,
    required this.elapsed,
    required this.onTap,
  });
  final _Phase phase;
  final AnimationController pulse;
  final Duration elapsed;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final recording = phase == _Phase.recording;
    return GestureDetector(
      onTap: onTap,
      child: AnimatedBuilder(
        animation: pulse,
        builder: (context, _) {
          final scale = recording ? 1.0 + (pulse.value * 0.08) : 1.0;
          return Transform.scale(
            scale: scale,
            child: Container(
              width: 140,
              height: 140,
              decoration: BoxDecoration(
                color: recording ? kDanger.withValues(alpha: 0.2) : kBgPanel,
                shape: BoxShape.circle,
                border: Border.all(
                  color: recording ? kDanger : kAccent,
                  width: 3,
                ),
                boxShadow: recording
                    ? [
                        BoxShadow(
                          color: kDanger.withValues(alpha: 0.4),
                          blurRadius: 20,
                          spreadRadius: 4,
                        )
                      ]
                    : [],
              ),
              child: Icon(
                recording ? Icons.stop : Icons.mic,
                color: recording ? kDanger : kAccent,
                size: 60,
              ),
            ),
          );
        },
      ),
    );
  }
}

class _ResultCard extends StatelessWidget {
  const _ResultCard(this.r);
  final Map<String, dynamic> r;

  @override
  Widget build(BuildContext context) {
    final cat = (r['category'] as String?) ?? 'note';
    final key = (r['key'] as String?) ?? '';
    final value = (r['value'] as String?) ?? '';
    final tags = (r['tags'] as List?)?.cast<String>() ?? const [];
    final transcript = (r['transcript'] as String?) ?? '';
    final urgency = (r['urgency'] as String?) ?? 'normal';
    final saved = r['saved'] == true;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                _CategoryChip(category: cat),
                const SizedBox(width: 8),
                if (urgency != 'normal') _UrgencyChip(urgency: urgency),
                const Spacer(),
                if (saved)
                  const Row(
                    children: [
                      Icon(Icons.check_circle_outline,
                          color: kAccent, size: 14),
                      SizedBox(width: 4),
                      Text('SAVED',
                          style: TextStyle(
                              color: kAccent,
                              fontSize: 10,
                              letterSpacing: 1.5)),
                    ],
                  )
                else
                  const Text('NOT SAVED',
                      style: TextStyle(
                          color: Colors.white38,
                          fontSize: 10,
                          letterSpacing: 1.5)),
              ],
            ),
            const SizedBox(height: 12),
            if (key.isNotEmpty) ...[
              Text(key,
                  style: const TextStyle(
                      color: Colors.white,
                      fontSize: 16,
                      fontWeight: FontWeight.w600)),
              const SizedBox(height: 6),
            ],
            if (value.isNotEmpty)
              Text(value,
                  style: const TextStyle(
                      color: Colors.white70, height: 1.4)),
            if (tags.isNotEmpty) ...[
              const SizedBox(height: 12),
              Wrap(
                spacing: 6,
                runSpacing: 4,
                children: tags
                    .map((t) => Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 8, vertical: 2),
                          decoration: BoxDecoration(
                            color: kBgPanel,
                            borderRadius: BorderRadius.circular(4),
                            border: Border.all(
                                color: kAccentDim.withValues(alpha: 0.5)),
                          ),
                          child: Text(
                            '#$t',
                            style: const TextStyle(
                                color: Colors.white60, fontSize: 11),
                          ),
                        ))
                    .toList(),
              ),
            ],
            if (transcript.isNotEmpty) ...[
              const SizedBox(height: 16),
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: kBg,
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(
                      color: kAccentDim.withValues(alpha: 0.4)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('TRANSCRIPT',
                        style: TextStyle(
                            color: Colors.white38,
                            fontSize: 10,
                            letterSpacing: 1.5)),
                    const SizedBox(height: 4),
                    SelectableText(
                      transcript,
                      style: const TextStyle(
                          color: Colors.white60,
                          fontSize: 12,
                          height: 1.3),
                    ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _CategoryChip extends StatelessWidget {
  const _CategoryChip({required this.category});
  final String category;

  @override
  Widget build(BuildContext context) {
    final (icon, color) = _styleFor(category);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.18),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: color.withValues(alpha: 0.7)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: color, size: 12),
          const SizedBox(width: 4),
          Text(
            category.toUpperCase(),
            style: TextStyle(
              color: color,
              fontSize: 10,
              letterSpacing: 1.6,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }

  static (IconData, Color) _styleFor(String c) {
    switch (c) {
      case 'idea':
        return (Icons.lightbulb_outline, kAmber);
      case 'todo':
        return (Icons.check_box_outline_blank, kAccent);
      case 'reminder':
        return (Icons.alarm, Colors.purpleAccent);
      case 'decision':
        return (Icons.flag_outlined, Colors.lightGreenAccent);
      default:
        return (Icons.notes, Colors.white70);
    }
  }
}

class _UrgencyChip extends StatelessWidget {
  const _UrgencyChip({required this.urgency});
  final String urgency;

  @override
  Widget build(BuildContext context) {
    final color = urgency == 'high' ? kDanger : kAmber;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.18),
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: color.withValues(alpha: 0.6)),
      ),
      child: Text(
        urgency.toUpperCase(),
        style: TextStyle(
          color: color,
          fontSize: 9,
          letterSpacing: 1.4,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}
