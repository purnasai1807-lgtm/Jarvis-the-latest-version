import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

import '../services/jarvis_api.dart';
import 'lite_tools.dart';

/// Stripped-down brain that runs entirely on the phone via the OpenAI API
/// when the PC is unreachable. Tool surface is intentionally tiny:
///   - get_weather (Open-Meteo, no key)
///   - set_reminder (local notifications)
///   - calculate (in-app shunting yard)
class LiteBrain {
  LiteBrain({
    required String openaiKey,
    required FlutterLocalNotificationsPlugin notifications,
    String model = 'gpt-4o-mini',
  })  : _key = openaiKey,
        _model = model,
        _weather = LiteWeatherTool(),
        _reminder = LiteReminderTool(notifications),
        _calc = LiteCalcTool(),
        _dio = Dio(BaseOptions(
          baseUrl: 'https://api.openai.com',
          connectTimeout: const Duration(seconds: 10),
          receiveTimeout: const Duration(seconds: 30),
          headers: {
            'Authorization': 'Bearer $openaiKey',
            'Content-Type': 'application/json',
          },
        ));

  final String _key;
  final String _model;
  final Dio _dio;
  final LiteWeatherTool _weather;
  final LiteReminderTool _reminder;
  final LiteCalcTool _calc;
  final List<Map<String, dynamic>> _history = [];

  static const _maxToolHops = 4;

  bool get hasKey => _key.isNotEmpty;

  void resetHistory() => _history.clear();

  String _systemPrompt(String language) {
    final lang = language == 'ro' ? 'Romanian' : 'English';
    return '''
You are Jarvis, running in **lite mode** on the user's phone because the
home PC is offline. Be concise and acknowledge the limited mode if the
user asks something only the PC can do (lights, Spotify, screen, OS
control, email send, calendar create, etc.).

You DO have these tools: get_weather, set_reminder, calculate.
For anything else, answer from your own knowledge.

Reply in $lang. Keep replies under 3 sentences for simple queries.
''';
  }

  /// Stream a reply token-by-token. Mirrors JarvisApi.ask() so callers can
  /// swap brains transparently.
  Stream<AskEvent> ask({
    required String text,
    String language = 'en',
  }) async* {
    if (!hasKey) {
      yield AskEvent.error(
        'Lite mode needs an OpenAI API key — open Settings to add one.',
      );
      yield AskEvent.done();
      return;
    }

    _history.add({'role': 'user', 'content': text});

    try {
      for (var hop = 0; hop < _maxToolHops; hop++) {
        final result = await _callOpenAi(language);
        final toolCalls = result['tool_calls'] as List?;

        if (toolCalls != null && toolCalls.isNotEmpty) {
          // Append the assistant turn that requested tools, then run them.
          _history.add({
            'role': 'assistant',
            'content': result['content'] ?? '',
            'tool_calls': toolCalls,
          });
          for (final tc in toolCalls) {
            final name = tc['function']['name'] as String;
            final argsJson = tc['function']['arguments'] as String? ?? '{}';
            Map<String, dynamic> args = {};
            try {
              args = jsonDecode(argsJson) as Map<String, dynamic>;
            } catch (_) {}
            final out = await _runTool(name, args);
            _history.add({
              'role': 'tool',
              'tool_call_id': tc['id'],
              'name': name,
              'content': encodeToolResult(out),
            });
          }
          continue; // next hop will produce the final answer
        }

        // Final answer — stream it character-by-character so the UI feels
        // similar to the SSE flow.
        final reply = (result['content'] as String?)?.trim() ?? '';
        _history.add({'role': 'assistant', 'content': reply});
        for (final piece in _chunkForUi(reply)) {
          yield AskEvent.chunk(piece);
        }
        yield AskEvent.done();
        return;
      }
      yield AskEvent.error('Tool loop limit reached.');
      yield AskEvent.done();
    } catch (e) {
      yield AskEvent.error('Lite brain failed: $e');
      yield AskEvent.done();
    }
  }

  Future<Map<String, dynamic>> _callOpenAi(String language) async {
    final messages = <Map<String, dynamic>>[
      {'role': 'system', 'content': _systemPrompt(language)},
      ..._history,
    ];
    final resp = await _dio.post<Map<String, dynamic>>(
      '/v1/chat/completions',
      data: {
        'model': _model,
        'messages': messages,
        'tools': [
          LiteWeatherTool.schema,
          LiteReminderTool.schema,
          LiteCalcTool.schema,
        ],
        'tool_choice': 'auto',
        'max_tokens': 600,
      },
    );
    final data = resp.data ?? const <String, dynamic>{};
    final choices = (data['choices'] as List?) ?? const [];
    if (choices.isEmpty) {
      return {'content': '', 'tool_calls': null};
    }
    final msg = (choices.first as Map)['message'] as Map<String, dynamic>;
    return {
      'content': msg['content'] ?? '',
      'tool_calls': msg['tool_calls'],
    };
  }

  Future<String> _runTool(String name, Map<String, dynamic> args) async {
    switch (name) {
      case 'get_weather':
        return _weather.call(args);
      case 'set_reminder':
        return _reminder.call(args);
      case 'calculate':
        return _calc.call(args);
      default:
        return 'Unknown tool: $name';
    }
  }

  /// Split the final reply into modest chunks so the UI bubble fills in
  /// progressively rather than appearing all at once.
  Iterable<String> _chunkForUi(String text) sync* {
    const chunkLen = 24;
    for (var i = 0; i < text.length; i += chunkLen) {
      yield text.substring(i, (i + chunkLen).clamp(0, text.length));
    }
  }
}
