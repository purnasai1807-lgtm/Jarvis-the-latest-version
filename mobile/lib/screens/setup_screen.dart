import 'package:flutter/material.dart';

import '../services/jarvis_api.dart';
import '../services/storage.dart';
import '../theme.dart';
import 'dashboard_screen.dart';

class SetupScreen extends StatefulWidget {
  const SetupScreen({super.key});

  @override
  State<SetupScreen> createState() => _SetupScreenState();
}

class _SetupScreenState extends State<SetupScreen> {
  final _formKey = GlobalKey<FormState>();
  final _urlCtl = TextEditingController(text: 'http://100.x.x.x:9000');
  final _keyCtl = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _urlCtl.dispose();
    _keyCtl.dispose();
    super.dispose();
  }

  Future<void> _connect() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final creds = JarvisCredentials(
      baseUrl: _urlCtl.text.trim().replaceAll(RegExp(r'/$'), ''),
      apiKey: _keyCtl.text.trim(),
    );
    final api = JarvisApi(creds);
    final ok = await api.health();
    if (!ok) {
      setState(() {
        _busy = false;
        _error = 'Cannot reach PC. Check URL, Tailscale, and that Jarvis is running.';
      });
      return;
    }
    try {
      await api.dashboard();
    } catch (e) {
      setState(() {
        _busy = false;
        _error = 'Auth failed (${e.toString()}). Check API key.';
      });
      return;
    }
    await CredentialStore.instance.save(creds);
    if (!mounted) return;
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => const DashboardScreen()),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('J.A.R.V.I.S. — SETUP')),
      body: Padding(
        padding: const EdgeInsets.all(20),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'Connect to your PC',
                style: TextStyle(color: kAccent, fontSize: 18, letterSpacing: 2),
              ),
              const SizedBox(height: 8),
              const Text(
                'Install Tailscale on PC + phone, join the same tailnet, then '
                'paste the PC Tailscale IP below.',
                style: TextStyle(color: Colors.white70),
              ),
              const SizedBox(height: 24),
              TextFormField(
                controller: _urlCtl,
                decoration: const InputDecoration(
                  labelText: 'PC base URL',
                  hintText: 'http://100.x.x.x:9000',
                ),
                validator: (v) =>
                    (v == null || !v.startsWith('http')) ? 'Must start with http' : null,
              ),
              const SizedBox(height: 16),
              TextFormField(
                controller: _keyCtl,
                obscureText: true,
                decoration: const InputDecoration(
                  labelText: 'API key',
                  hintText: 'apis.mobile.api_key from config.yaml',
                ),
                validator: (v) =>
                    (v == null || v.length < 16) ? 'Key looks too short' : null,
              ),
              const SizedBox(height: 24),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Text(_error!, style: const TextStyle(color: kDanger)),
                ),
              ElevatedButton(
                onPressed: _busy ? null : _connect,
                child: _busy
                    ? const SizedBox(
                        height: 18, width: 18,
                        child: CircularProgressIndicator(
                          strokeWidth: 2, color: kBg,
                        ),
                      )
                    : const Text('CONNECT'),
              ),
              const SizedBox(height: 24),
              const Divider(color: kAccentDim),
              const SizedBox(height: 12),
              const Text(
                'No PC nearby?',
                style: TextStyle(color: Colors.white70),
              ),
              const SizedBox(height: 4),
              const Text(
                'Skip and use lite mode only — answers questions, weather, '
                'and reminders directly from your phone via OpenAI. You can '
                'connect to your PC later from Settings.',
                style: TextStyle(color: Colors.white54, fontSize: 12),
              ),
              const SizedBox(height: 12),
              OutlinedButton(
                onPressed: _busy ? null : _skipToLite,
                style: OutlinedButton.styleFrom(
                  foregroundColor: kAmber,
                  side: const BorderSide(color: kAmber),
                  padding:
                      const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
                ),
                child: const Text('SKIP — EXPLORE IN LITE MODE'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _skipToLite() async {
    // Save sentinel credentials so the dashboard bootstraps in standalone mode
    // and the user can flip to "real" PC setup later from Settings.
    await CredentialStore.instance.save(JarvisCredentials(
      baseUrl: 'http://lite-mode.local',
      apiKey: 'lite-mode-placeholder-key',
    ));
    if (!mounted) return;
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => const DashboardScreen()),
    );
  }
}
