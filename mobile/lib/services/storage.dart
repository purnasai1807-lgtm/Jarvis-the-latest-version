import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class JarvisCredentials {
  JarvisCredentials({required this.baseUrl, required this.apiKey});
  final String baseUrl;
  final String apiKey;
}

class CredentialStore {
  CredentialStore._();
  static final CredentialStore instance = CredentialStore._();

  static const _kBaseUrl = 'jarvis_base_url';
  static const _kApiKey = 'jarvis_api_key';
  static const _kLiteOpenAiKey = 'jarvis_lite_openai_key';

  final _storage = const FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
  );

  Future<JarvisCredentials?> read() async {
    final base = await _storage.read(key: _kBaseUrl);
    final key = await _storage.read(key: _kApiKey);
    if (base == null || key == null || base.isEmpty || key.isEmpty) {
      return null;
    }
    return JarvisCredentials(baseUrl: base, apiKey: key);
  }

  Future<void> save(JarvisCredentials creds) async {
    await _storage.write(key: _kBaseUrl, value: creds.baseUrl);
    await _storage.write(key: _kApiKey, value: creds.apiKey);
  }

  Future<void> clear() async {
    await _storage.delete(key: _kBaseUrl);
    await _storage.delete(key: _kApiKey);
  }

  /// OpenAI key used only when running in standalone (lite) mode —
  /// kept separate from the PC API key so we never leak one as the other.
  Future<String?> readLiteOpenAiKey() async {
    final v = await _storage.read(key: _kLiteOpenAiKey);
    return (v == null || v.isEmpty) ? null : v;
  }

  Future<void> saveLiteOpenAiKey(String key) async {
    await _storage.write(key: _kLiteOpenAiKey, value: key.trim());
  }

  Future<void> clearLiteOpenAiKey() async {
    await _storage.delete(key: _kLiteOpenAiKey);
  }
}
