import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:just_audio/just_audio.dart';
import 'package:path_provider/path_provider.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:record/record.dart';

import 'jarvis_api.dart';

/// Push-to-talk voice loop on the phone:
///   record WAV  →  POST /api/mobile/transcribe  →  POST /api/mobile/ask (SSE)
///                  → POST /api/mobile/synthesize → just_audio playback.
class VoicePipeline {
  VoicePipeline(this._api);

  final JarvisApi _api;
  final AudioRecorder _recorder = AudioRecorder();
  final AudioPlayer _player = AudioPlayer();

  String? _currentPath;
  DateTime? _recordStartedAt;
  bool _cancelled = false;

  Future<bool> ensurePermission() async {
    if (await _recorder.hasPermission()) return true;
    final status = await Permission.microphone.request();
    return status.isGranted;
  }

  Future<void> startRecording() async {
    if (!await ensurePermission()) {
      throw Exception('Microphone permission denied.');
    }

    final dir = await getTemporaryDirectory();
    final path =
        '${dir.path}/jarvis_${DateTime.now().millisecondsSinceEpoch}.wav';

    await _recorder.start(
      const RecordConfig(
        encoder: AudioEncoder.wav,
        sampleRate: 16000,
        numChannels: 1,
      ),
      path: path,
    );

    _currentPath = path;
    _recordStartedAt = DateTime.now();
    _cancelled = false;
  }

  /// Stop recording. Returns the WAV file, or null if the clip was shorter
  /// than ~300ms (probably an accidental tap).
  Future<File?> stopRecording() async {
    final path = await _recorder.stop();
    final startedAt = _recordStartedAt;
    _recordStartedAt = null;

    if (_cancelled || path == null) {
      _cleanupFile(path ?? _currentPath);
      _currentPath = null;
      return null;
    }

    if (startedAt != null &&
        DateTime.now().difference(startedAt) <
            const Duration(milliseconds: 300)) {
      _cleanupFile(path);
      _currentPath = null;
      return null;
    }

    _currentPath = null;
    return File(path);
  }

  Future<void> cancel() async {
    _cancelled = true;
    try {
      await _recorder.cancel();
    } catch (_) {
      try {
        await _recorder.stop();
      } catch (_) {}
    }
    _cleanupFile(_currentPath);
    _currentPath = null;
    _recordStartedAt = null;
  }

  /// Full turn: transcribe → ask (stream) → synthesize → play.
  ///
  /// Callbacks fire on the calling isolate. Audio playback (when the user did
  /// NOT pick "speak on PC") completes before this future resolves.
  Future<void> runTurn({
    required File wavFile,
    required String language,
    required bool playOnPc,
    required void Function(String transcript) onTranscript,
    required void Function(String chunk) onReplyChunk,
    required void Function() onReplyDone,
    required void Function(Uint8List wav) onAudioReady,
  }) async {
    try {
      final t = await _api.transcribe(wavFile: wavFile, language: language);
      onTranscript(t.text);

      final reply = StringBuffer();
      await for (final ev in _api.ask(
        text: t.text,
        language: t.language,
        playOnPc: playOnPc,
      )) {
        switch (ev.type) {
          case AskEventType.chunk:
            final c = ev.text ?? '';
            reply.write(c);
            onReplyChunk(c);
            break;
          case AskEventType.done:
            break;
          case AskEventType.error:
            throw Exception(ev.message ?? 'ask error');
        }
      }
      onReplyDone();

      if (!playOnPc && reply.isNotEmpty) {
        final wav = await _api.synthesize(
          text: reply.toString(),
          language: t.language,
        );
        onAudioReady(wav);
        await _playWav(wav);
      }
    } finally {
      _cleanupFile(wavFile.path);
    }
  }

  Future<void> _playWav(Uint8List bytes) async {
    final dir = await getTemporaryDirectory();
    final path =
        '${dir.path}/jarvis_reply_${DateTime.now().millisecondsSinceEpoch}.wav';
    final f = File(path);
    await f.writeAsBytes(bytes, flush: true);

    final done = Completer<void>();
    final sub = _player.playerStateStream.listen((s) {
      if (s.processingState == ProcessingState.completed && !done.isCompleted) {
        done.complete();
      }
    });

    try {
      await _player.setFilePath(path);
      await _player.play();
      await done.future
          .timeout(const Duration(minutes: 2), onTimeout: () {});
    } finally {
      await sub.cancel();
      try {
        await _player.stop();
      } catch (_) {}
      _cleanupFile(path);
    }
  }

  void _cleanupFile(String? path) {
    if (path == null) return;
    try {
      final f = File(path);
      if (f.existsSync()) f.deleteSync();
    } catch (_) {}
  }

  Future<void> dispose() async {
    try {
      await _recorder.dispose();
    } catch (_) {}
    try {
      await _player.dispose();
    } catch (_) {}
  }
}
