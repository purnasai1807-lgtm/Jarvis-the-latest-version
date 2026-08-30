import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../services/connection_mode.dart';
import '../services/storage.dart';
import '../theme.dart';
import 'setup_screen.dart';

class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  final _keyCtl = TextEditingController();
  bool _loading = true;
  bool _hasKey = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _keyCtl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final existing = await CredentialStore.instance.readLiteOpenAiKey();
    setState(() {
      _hasKey = existing != null;
      _loading = false;
    });
  }

  Future<void> _save() async {
    final value = _keyCtl.text.trim();
    if (value.isEmpty) return;
    await CredentialStore.instance.saveLiteOpenAiKey(value);
    _keyCtl.clear();
    if (!mounted) return;
    setState(() => _hasKey = true);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Lite mode key saved.'),
        backgroundColor: kAccentDim,
      ),
    );
  }

  Future<void> _clear() async {
    await CredentialStore.instance.clearLiteOpenAiKey();
    if (!mounted) return;
    setState(() => _hasKey = false);
  }

  @override
  Widget build(BuildContext context) {
    final mode = ref.watch(connectionMonitorProvider);
    final monitor = ref.read(connectionMonitorProvider.notifier);

    return Scaffold(
      appBar: AppBar(title: const Text('SETTINGS')),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: kAccent))
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                const Text(
                  'CONNECTION MODE',
                  style: TextStyle(color: kAccent, letterSpacing: 2),
                ),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          mode.isOnline
                              ? 'PC reachable — using full Jarvis.'
                              : mode.isStandalone
                                  ? 'PC unreachable — lite mode active.'
                                  : 'Probing PC…',
                          style: TextStyle(
                            color: mode.isOnline ? kAccent : kAmber,
                          ),
                        ),
                        if (mode.lastError != null) ...[
                          const SizedBox(height: 6),
                          Text(
                            mode.lastError!,
                            style: const TextStyle(
                                color: Colors.white54, fontSize: 12),
                          ),
                        ],
                        const SizedBox(height: 12),
                        Wrap(
                          spacing: 8,
                          children: [
                            OutlinedButton(
                              onPressed: monitor.probe,
                              child: const Text('PROBE NOW'),
                            ),
                            OutlinedButton(
                              onPressed: mode.manualOverride
                                  ? monitor.clearOverride
                                  : monitor.forceStandalone,
                              child: Text(mode.manualOverride
                                  ? 'AUTO DETECT'
                                  : 'FORCE LITE'),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                const Text(
                  'PC CONNECTION',
                  style: TextStyle(color: kAccent, letterSpacing: 2),
                ),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Connect to your PC for the full experience: '
                          'real dashboard cards, voice in/out via the desktop '
                          'mic and speakers, and 47 tools.',
                          style: TextStyle(color: Colors.white70, height: 1.4),
                        ),
                        const SizedBox(height: 12),
                        OutlinedButton(
                          onPressed: () async {
                            await CredentialStore.instance.clear();
                            if (!context.mounted) return;
                            Navigator.of(context).pushAndRemoveUntil(
                              MaterialPageRoute(
                                  builder: (_) => const SetupScreen()),
                              (_) => false,
                            );
                          },
                          child: const Text('SET UP PC NOW'),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                const Text(
                  'LITE MODE',
                  style: TextStyle(color: kAccent, letterSpacing: 2),
                ),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'When the PC is offline, Jarvis answers from the '
                          'phone using OpenAI directly. Provide a separate API '
                          'key — kept only in this device\'s keychain.',
                          style: TextStyle(color: Colors.white70, height: 1.4),
                        ),
                        const SizedBox(height: 12),
                        Row(
                          children: [
                            Icon(
                              _hasKey ? Icons.check_circle : Icons.warning,
                              color: _hasKey ? kAccent : kAmber,
                              size: 18,
                            ),
                            const SizedBox(width: 6),
                            Text(
                              _hasKey
                                  ? 'OpenAI key saved'
                                  : 'No OpenAI key — lite mode disabled',
                              style: const TextStyle(color: Colors.white),
                            ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: _keyCtl,
                          obscureText: true,
                          decoration: const InputDecoration(
                            labelText: 'OpenAI API key (sk-…)',
                          ),
                        ),
                        const SizedBox(height: 12),
                        Row(
                          children: [
                            ElevatedButton(
                              onPressed: _save,
                              child: const Text('SAVE'),
                            ),
                            const SizedBox(width: 8),
                            if (_hasKey)
                              OutlinedButton(
                                onPressed: _clear,
                                child: const Text('REMOVE'),
                              ),
                          ],
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
