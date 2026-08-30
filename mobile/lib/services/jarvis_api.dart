import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';

import 'storage.dart';
import 'wake_on_lan_service.dart';

/// Streamed event from /api/mobile/ask SSE endpoint.
class AskEvent {
  AskEvent.chunk(this.text)
      : type = AskEventType.chunk,
        message = null;
  AskEvent.done()
      : type = AskEventType.done,
        text = null,
        message = null;
  AskEvent.error(this.message)
      : type = AskEventType.error,
        text = null;

  final AskEventType type;
  final String? text;
  final String? message;
}

enum AskEventType { chunk, done, error }

class JarvisApi {
  JarvisApi(this._creds)
      : _dio = Dio(BaseOptions(
          baseUrl: _creds.baseUrl,
          connectTimeout: const Duration(seconds: 5),
          receiveTimeout: const Duration(seconds: 30),
          headers: {
            'Authorization': 'Bearer ${_creds.apiKey}',
            'Accept': 'application/json',
          },
        ));

  final JarvisCredentials _creds;
  final Dio _dio;

  /// True when these credentials are the "skip setup" placeholder, meaning
  /// the user explicitly opted into lite-only mode. Skip every PC call.
  bool get isLiteOnly =>
      _creds.baseUrl == 'http://lite-mode.local' ||
      _creds.apiKey == 'lite-mode-placeholder-key';

  /// Pings /api/mobile/health. Returns true on 200.
  Future<bool> health() async {
    if (isLiteOnly) return false;
    try {
      final resp = await _dio.get(
        '/api/mobile/health',
        options: Options(
          headers: {'Authorization': null},
          validateStatus: (s) => s != null && s < 500,
        ),
      );
      final ok = resp.statusCode == 200 &&
          resp.data is Map &&
          resp.data['ok'] == true;
      // Cache the PC's MAC + broadcast for Wake-on-LAN. Best-effort.
      if (ok) {
        final mac = (resp.data['mac'] as String?) ?? '';
        final bcast =
            (resp.data['broadcast'] as String?) ?? '255.255.255.255';
        if (mac.isNotEmpty) {
          unawaited(WakeOnLanService.instance
              .remember(mac: mac, broadcast: bcast));
        }
      }
      return ok;
    } catch (_) {
      return false;
    }
  }

  Future<Map<String, dynamic>> dashboard() async {
    final resp = await _dio.get<Map<String, dynamic>>('/api/mobile/dashboard');
    return resp.data ?? {};
  }

  /// Register an FCM token so the PC can push notifications to this device.
  Future<void> registerDevice({
    required String token,
    String platform = '',
    String label = '',
  }) async {
    await _dio.post(
      '/api/mobile/devices/register',
      data: {'token': token, 'platform': platform, 'label': label},
    );
  }

  Future<void> unregisterDevice(String token) async {
    await _dio.delete('/api/mobile/devices/$token');
  }

  /// Tells the PC "the phone is here" so the router can pick the right channel.
  /// Returns the latest presence snapshot (state, quiet_hours, idle).
  Future<Map<String, dynamic>> heartbeat() async {
    if (isLiteOnly) return {};
    final resp = await _dio.post<Map<String, dynamic>>(
      '/api/mobile/heartbeat',
      options: Options(
        sendTimeout: const Duration(seconds: 4),
        receiveTimeout: const Duration(seconds: 4),
      ),
    );
    return resp.data ?? {};
  }

  /// Fetches the current PC presence snapshot without bumping the heartbeat.
  Future<Map<String, dynamic>> presence() async {
    final resp = await _dio.get<Map<String, dynamic>>('/api/mobile/presence');
    return resp.data ?? {};
  }

  /// Read recent turns from the cross-device conversation store.
  /// Each turn: {ts, role, content, source, lang}.
  Future<List<Map<String, dynamic>>> conversationRecent({int limit = 40}) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/api/mobile/conversation/recent',
      queryParameters: {'limit': limit},
    );
    final raw = (resp.data ?? const {})['turns'];
    if (raw is List) {
      return raw.whereType<Map<String, dynamic>>().toList();
    }
    return const [];
  }

  Future<int> conversationClear() async {
    final resp = await _dio.delete<Map<String, dynamic>>('/api/mobile/conversation');
    final n = (resp.data ?? const {})['cleared'];
    return n is int ? n : 0;
  }

  /// Upload a WAV file and return Whisper transcript.
  Future<({String text, String language})> transcribe({
    required File wavFile,
    String language = 'en',
  }) async {
    final form = FormData.fromMap({
      'audio': await MultipartFile.fromFile(
        wavFile.path,
        filename: 'speech.wav',
        contentType: DioMediaType('audio', 'wav'),
      ),
      'language': language,
    });
    final resp = await _dio.post<Map<String, dynamic>>(
      '/api/mobile/transcribe',
      data: form,
      options: Options(
        sendTimeout: const Duration(seconds: 30),
        receiveTimeout: const Duration(seconds: 30),
      ),
    );
    final data = resp.data ?? {};
    return (
      text: (data['text'] as String? ?? '').trim(),
      language: data['language'] as String? ?? language,
    );
  }

  // ── Routines ───────────────────────────────────────────────────

  Future<List<Map<String, dynamic>>> listRoutines() async {
    final resp =
        await _dio.get<Map<String, dynamic>>('/api/mobile/routines');
    final raw = (resp.data ?? const {})['routines'];
    return raw is List
        ? raw.whereType<Map<String, dynamic>>().toList()
        : const [];
  }

  Future<void> runRoutine(String name) async {
    await _dio.post('/api/mobile/routines/run', data: {'name': name});
  }

  /// Reload routines.yaml from disk on the PC. Returns the count loaded.
  Future<int> reloadRoutines() async {
    final resp = await _dio
        .post<Map<String, dynamic>>('/api/mobile/routines/reload');
    final n = resp.data?['loaded'];
    return n is int ? n : 0;
  }

  // ── Geofence zones ─────────────────────────────────────────────

  Future<List<Map<String, dynamic>>> listZones() async {
    final resp = await _dio.get<Map<String, dynamic>>('/api/mobile/zones');
    final raw = (resp.data ?? const {})['zones'];
    return raw is List
        ? raw.whereType<Map<String, dynamic>>().toList()
        : const [];
  }

  Future<int> createZone({
    required String name,
    required double latitude,
    required double longitude,
    int radiusM = 200,
  }) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/api/mobile/zones',
      data: {
        'name': name,
        'latitude': latitude,
        'longitude': longitude,
        'radius_m': radiusM,
      },
    );
    final id = resp.data?['zone_id'];
    return id is int ? id : 0;
  }

  Future<void> deleteZone(int id) async {
    await _dio.delete('/api/mobile/zones/$id');
  }

  /// Report a geofence transition (enter / exit / dwell) for a named zone.
  Future<List<String>> reportGeofence({
    required String event,
    required String zoneName,
    double? latitude,
    double? longitude,
  }) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/api/mobile/geofence-event',
      data: {
        'event': event,
        'zone_name': zoneName,
        if (latitude != null) 'latitude': latitude,
        if (longitude != null) 'longitude': longitude,
      },
    );
    final fired = resp.data?['fired'];
    return fired is List ? fired.cast<String>() : const [];
  }

  // ── URL watches ────────────────────────────────────────────────

  Future<List<Map<String, dynamic>>> listWatches({bool includeArchived = false}) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/api/mobile/watches',
      queryParameters: {'include_archived': includeArchived},
    );
    final raw = (resp.data ?? const {})['watches'];
    return raw is List
        ? raw.whereType<Map<String, dynamic>>().toList()
        : const [];
  }

  Future<int> createWatch({
    required String url,
    String condition = 'changed',
    int intervalMinutes = 30,
    String label = '',
  }) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/api/mobile/watches',
      data: {
        'url': url,
        'condition': condition,
        'interval_minutes': intervalMinutes,
        'label': label,
      },
    );
    final id = resp.data?['watch_id'];
    return id is int ? id : 0;
  }

  Future<void> stopWatch(int id) async {
    await _dio.post('/api/mobile/watches/$id/stop');
  }

  Future<void> reactivateWatch(int id) async {
    await _dio.post('/api/mobile/watches/$id/reactivate');
  }

  /// List recent background tasks (lightweight — for the tasks list view).
  Future<List<Map<String, dynamic>>> listTasks({int limit = 30}) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/api/mobile/tasks',
      queryParameters: {'limit': limit},
    );
    final raw = (resp.data ?? const {})['tasks'];
    return raw is List
        ? raw.whereType<Map<String, dynamic>>().toList()
        : const [];
  }

  /// Fetch the full record for one task (result text + log included).
  Future<Map<String, dynamic>> getTask(int id) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/api/mobile/tasks/$id',
    );
    return resp.data ?? {};
  }

  /// Spawn a new background task (defaults to research).
  Future<int> startTask({required String prompt, String kind = 'research'}) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/api/mobile/tasks',
      data: {'prompt': prompt, 'kind': kind},
    );
    final id = resp.data?['task_id'];
    return id is int ? id : 0;
  }

  /// Request cancellation of an in-flight task. Best-effort (worker must check).
  Future<void> cancelTask(int id) async {
    await _dio.post('/api/mobile/tasks/$id/cancel');
  }

  /// Tell the PC the user tapped an action button on a push notification.
  Future<Map<String, dynamic>> notificationAction({
    required String actionId,
    String kind = '',
    Map<String, String> data = const {},
  }) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/api/mobile/notification-action',
      data: {'action_id': actionId, 'kind': kind, 'data': data},
    );
    return resp.data ?? {};
  }

  /// Record on the phone, send WAV to /api/mobile/memo. Server transcribes,
  /// auto-categorises, optionally saves to the long-term memory store.
  /// Returns the structured result.
  Future<Map<String, dynamic>> uploadMemo({
    required File wavFile,
    String language = 'en',
    bool autoSave = true,
  }) async {
    final form = FormData.fromMap({
      'audio': await MultipartFile.fromFile(
        wavFile.path,
        filename: 'memo.wav',
        contentType: DioMediaType('audio', 'wav'),
      ),
      'language': language,
      'auto_save': autoSave ? 'true' : 'false',
    });
    final resp = await _dio.post<Map<String, dynamic>>(
      '/api/mobile/memo',
      data: form,
      options: Options(
        sendTimeout: const Duration(seconds: 30),
        receiveTimeout: const Duration(seconds: 60),
      ),
    );
    return resp.data ?? {};
  }

  /// Send an image + prompt to /api/mobile/vision. Returns the answer text.
  Future<String> visionAnalyze({
    required File imageFile,
    required String prompt,
    String language = 'en',
  }) async {
    final form = FormData.fromMap({
      'image': await MultipartFile.fromFile(
        imageFile.path,
        filename: 'photo.jpg',
        contentType: DioMediaType('image', 'jpeg'),
      ),
      'prompt': prompt,
      'language': language,
    });
    final resp = await _dio.post<Map<String, dynamic>>(
      '/api/mobile/vision',
      data: form,
      options: Options(
        sendTimeout: const Duration(seconds: 30),
        receiveTimeout: const Duration(seconds: 60),
      ),
    );
    return (resp.data?['answer'] as String? ?? '').trim();
  }

  /// Render text via PC TTS, return WAV bytes ready for playback.
  Future<Uint8List> synthesize({
    required String text,
    String language = 'en',
  }) async {
    final resp = await _dio.post<List<int>>(
      '/api/mobile/synthesize',
      data: {'text': text, 'language': language},
      options: Options(
        responseType: ResponseType.bytes,
        receiveTimeout: const Duration(seconds: 30),
      ),
    );
    return Uint8List.fromList(resp.data ?? const []);
  }

  /// Stream brain reply token-by-token via SSE.
  Stream<AskEvent> ask({
    required String text,
    String language = 'en',
    bool playOnPc = false,
  }) async* {
    final controller = StreamController<AskEvent>();
    final cancelToken = CancelToken();

    unawaited(() async {
      try {
        final response = await _dio.post<ResponseBody>(
          '/api/mobile/ask',
          data: {'text': text, 'language': language, 'play_on_pc': playOnPc},
          options: Options(
            responseType: ResponseType.stream,
            headers: {'Accept': 'text/event-stream'},
          ),
          cancelToken: cancelToken,
        );

        final body = response.data;
        if (body == null) {
          controller.add(AskEvent.error('Empty response'));
          await controller.close();
          return;
        }

        final buffer = StringBuffer();
        await for (final chunk in body.stream) {
          buffer.write(utf8.decode(chunk, allowMalformed: true));
          while (true) {
            final raw = buffer.toString();
            final idx = raw.indexOf('\n\n');
            if (idx < 0) break;
            final event = raw.substring(0, idx).trim();
            buffer
              ..clear()
              ..write(raw.substring(idx + 2));
            if (!event.startsWith('data:')) continue;
            final payload = event.substring(5).trim();
            try {
              final json = jsonDecode(payload) as Map<String, dynamic>;
              switch (json['type']) {
                case 'chunk':
                  controller.add(AskEvent.chunk(json['text'] as String? ?? ''));
                  break;
                case 'done':
                  controller.add(AskEvent.done());
                  break;
                case 'error':
                  controller.add(
                    AskEvent.error(json['message'] as String? ?? 'unknown'),
                  );
                  break;
              }
            } catch (_) {
              // skip malformed event
            }
          }
        }
      } catch (e) {
        controller.add(AskEvent.error(e.toString()));
      } finally {
        await controller.close();
      }
    }());

    yield* controller.stream;
  }
}
