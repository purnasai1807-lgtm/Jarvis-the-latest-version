import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:timezone/timezone.dart' as tz;

/// Tool: current weather via Open-Meteo (no API key required).
class LiteWeatherTool {
  final Dio _dio = Dio(BaseOptions(
    connectTimeout: const Duration(seconds: 5),
    receiveTimeout: const Duration(seconds: 5),
  ));

  static Map<String, dynamic> get schema => {
        'type': 'function',
        'function': {
          'name': 'get_weather',
          'description': 'Current weather for a city. Uses Open-Meteo (free).',
          'parameters': {
            'type': 'object',
            'properties': {
              'city': {
                'type': 'string',
                'description': 'City name, e.g. "Bucharest"',
              },
            },
            'required': ['city'],
          },
        },
      };

  Future<String> call(Map<String, dynamic> args) async {
    final city = (args['city'] as String?)?.trim() ?? '';
    if (city.isEmpty) return 'No city given.';
    try {
      final geo = await _dio.get(
        'https://geocoding-api.open-meteo.com/v1/search',
        queryParameters: {'name': city, 'count': 1, 'language': 'en'},
      );
      final results = (geo.data?['results'] as List?) ?? const [];
      if (results.isEmpty) return 'Could not find $city.';
      final lat = results.first['latitude'];
      final lon = results.first['longitude'];
      final name = results.first['name'];
      final country = results.first['country'] ?? '';

      final wx = await _dio.get(
        'https://api.open-meteo.com/v1/forecast',
        queryParameters: {
          'latitude': lat,
          'longitude': lon,
          'current':
              'temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m',
        },
      );
      final cur = wx.data?['current'] as Map?;
      if (cur == null) return 'Weather unavailable for $name.';
      final temp = cur['temperature_2m'];
      final feels = cur['apparent_temperature'];
      final hum = cur['relative_humidity_2m'];
      final wind = cur['wind_speed_10m'];
      final code = cur['weather_code'];
      return '$name${country.isNotEmpty ? ", $country" : ""}: '
          '${_describe(code)}, $temp°C (feels $feels°C), '
          'humidity $hum%, wind $wind km/h.';
    } catch (e) {
      return 'Weather lookup failed: $e';
    }
  }

  String _describe(dynamic code) {
    if (code is! int) return 'unknown conditions';
    // WMO weather codes — abbreviated.
    if (code == 0) return 'clear';
    if (code <= 3) return 'partly cloudy';
    if (code <= 48) return 'foggy';
    if (code <= 57) return 'drizzle';
    if (code <= 67) return 'rain';
    if (code <= 77) return 'snow';
    if (code <= 82) return 'rain showers';
    if (code <= 86) return 'snow showers';
    if (code <= 99) return 'thunderstorms';
    return 'unknown';
  }
}

/// Tool: schedule a local reminder notification on the phone.
class LiteReminderTool {
  LiteReminderTool(this._notifications);
  final FlutterLocalNotificationsPlugin _notifications;
  static int _idCounter = 1000;

  static Map<String, dynamic> get schema => {
        'type': 'function',
        'function': {
          'name': 'set_reminder',
          'description':
              'Schedule a local notification on this phone. Use when the user '
                  'asks to be reminded about something.',
          'parameters': {
            'type': 'object',
            'properties': {
              'message': {'type': 'string', 'description': 'What to remind about.'},
              'minutes_from_now': {
                'type': 'integer',
                'description': 'Delay in minutes from now (1 to 1440).',
              },
            },
            'required': ['message', 'minutes_from_now'],
          },
        },
      };

  Future<String> call(Map<String, dynamic> args) async {
    final message = (args['message'] as String?)?.trim() ?? '';
    final minutes = (args['minutes_from_now'] as num?)?.toInt() ?? 0;
    if (message.isEmpty) return 'Reminder message is empty.';
    if (minutes < 1 || minutes > 1440) {
      return 'minutes_from_now must be between 1 and 1440.';
    }
    final id = _idCounter++;
    final when = tz.TZDateTime.now(tz.local).add(Duration(minutes: minutes));
    try {
      await _notifications.zonedSchedule(
        id,
        'Jarvis reminder',
        message,
        when,
        const NotificationDetails(
          android: AndroidNotificationDetails(
            'jarvis_reminders',
            'Reminders',
            channelDescription: 'Local reminders set in lite mode',
            importance: Importance.high,
            priority: Priority.high,
          ),
          iOS: DarwinNotificationDetails(),
        ),
        androidScheduleMode: AndroidScheduleMode.exactAllowWhileIdle,
        uiLocalNotificationDateInterpretation:
            UILocalNotificationDateInterpretation.absoluteTime,
      );
      return 'Reminder set for $minutes min from now: "$message".';
    } catch (e) {
      return 'Failed to schedule reminder: $e';
    }
  }
}

/// Tool: simple math / unit conversion via the model itself — no implementation
/// needed beyond the schema; the LLM does the arithmetic and returns it as the
/// reply directly.
class LiteCalcTool {
  static Map<String, dynamic> get schema => {
        'type': 'function',
        'function': {
          'name': 'calculate',
          'description':
              'Evaluate a math expression. Supports +, -, *, /, %, parentheses.',
          'parameters': {
            'type': 'object',
            'properties': {
              'expression': {'type': 'string'},
            },
            'required': ['expression'],
          },
        },
      };

  String call(Map<String, dynamic> args) {
    final expr = (args['expression'] as String?)?.trim() ?? '';
    if (expr.isEmpty) return 'Empty expression.';
    try {
      final value = _eval(expr);
      return '$expr = $value';
    } catch (e) {
      return 'Could not evaluate "$expr": $e';
    }
  }

  /// Tiny shunting-yard evaluator for + - * / % and parentheses.
  num _eval(String expr) {
    final tokens = _tokenize(expr);
    final output = <Object>[];
    final ops = <String>[];
    const prec = {'+': 1, '-': 1, '*': 2, '/': 2, '%': 2};
    for (final t in tokens) {
      final asNum = num.tryParse(t);
      if (asNum != null) {
        output.add(asNum);
      } else if (t == '(') {
        ops.add(t);
      } else if (t == ')') {
        while (ops.isNotEmpty && ops.last != '(') {
          output.add(ops.removeLast());
        }
        if (ops.isNotEmpty) ops.removeLast();
      } else if (prec.containsKey(t)) {
        while (ops.isNotEmpty &&
            ops.last != '(' &&
            (prec[ops.last] ?? 0) >= prec[t]!) {
          output.add(ops.removeLast());
        }
        ops.add(t);
      } else {
        throw FormatException('unexpected token: $t');
      }
    }
    while (ops.isNotEmpty) {
      output.add(ops.removeLast());
    }
    final stack = <num>[];
    for (final tok in output) {
      if (tok is num) {
        stack.add(tok);
      } else {
        final b = stack.removeLast();
        final a = stack.removeLast();
        switch (tok as String) {
          case '+':
            stack.add(a + b);
            break;
          case '-':
            stack.add(a - b);
            break;
          case '*':
            stack.add(a * b);
            break;
          case '/':
            stack.add(a / b);
            break;
          case '%':
            stack.add(a % b);
            break;
        }
      }
    }
    return stack.single;
  }

  List<String> _tokenize(String s) {
    final out = <String>[];
    final buf = StringBuffer();
    for (var i = 0; i < s.length; i++) {
      final c = s[i];
      if (c == ' ') continue;
      if ('()+-*/%'.contains(c)) {
        if (buf.isNotEmpty) {
          out.add(buf.toString());
          buf.clear();
        }
        out.add(c);
      } else {
        buf.write(c);
      }
    }
    if (buf.isNotEmpty) out.add(buf.toString());
    return out;
  }
}

/// Encode a tool result as the OpenAI `tool` message JSON content.
String encodeToolResult(String text) => jsonEncode({'result': text});
