import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../services/connection_mode.dart';
import '../services/heartbeat_service.dart';
import '../services/jarvis_api.dart';
import '../services/location_service.dart';
import '../services/push_service.dart';
import '../services/status_service.dart';
import '../services/storage.dart';
import '../services/wake_on_lan_service.dart';
import '../theme.dart';
import 'ask_screen.dart';
import 'conversation_screen.dart';
import 'locations_screen.dart';
import 'memo_screen.dart';
import 'routines_screen.dart';
import 'settings_screen.dart';
import 'setup_screen.dart';
import 'tasks_screen.dart';
import 'vision_screen.dart';
import 'voice_screen.dart';
import 'watches_screen.dart';

class DashboardScreen extends ConsumerStatefulWidget {
  const DashboardScreen({super.key});

  @override
  ConsumerState<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends ConsumerState<DashboardScreen> {
  JarvisApi? _api;
  Map<String, dynamic>? _data;
  String? _error;
  bool _loading = true;
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    _bootstrap();
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _bootstrap() async {
    final creds = await CredentialStore.instance.read();
    if (creds == null) {
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => const SetupScreen()),
      );
      return;
    }
    _api = JarvisApi(creds);
    // Register this phone for push notifications (no-op if Firebase missing).
    unawaited(PushService.instance.registerWith(_api!));
    // Start probing PC reachability for lite-mode auto-detection.
    ref.read(connectionMonitorProvider.notifier).start(_api!);
    // Start the presence heartbeat so the PC knows the phone is here.
    HeartbeatService.instance.start(_api!);
    // Start foreground geofence engine (no-op if no zones / permission denied).
    unawaited(LocationService.instance.start(_api!));
    // Persistent live-status notification (Android foreground service).
    unawaited(StatusService.instance.start());
    if (_api!.isLiteOnly) {
      // No PC paired — skip dashboard refresh, just settle UI.
      setState(() => _loading = false);
      return;
    }
    await _refresh();
    _poll = Timer.periodic(const Duration(seconds: 30), (_) => _refresh());
  }

  Future<void> _refresh() async {
    if (_api == null) return;
    try {
      final data = await _api!.dashboard();
      if (!mounted) return;
      setState(() {
        _data = data;
        _error = null;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = 'PC unreachable: ${e.toString().substring(0, e.toString().length.clamp(0, 80))}';
        _loading = false;
      });
    }
  }

  void _openTasks() {
    if (_api == null) return;
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => TasksScreen(api: _api!)),
    );
  }

  void _openWatches() {
    if (_api == null) return;
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => WatchesScreen(api: _api!)),
    );
  }

  Future<void> _runRoutine(String name) async {
    if (_api == null) return;
    try {
      await _api!.runRoutine(name);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Running "$name"…')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Run failed: $e')),
      );
    }
  }

  Future<void> _confirmPlan() async {
    if (_api == null) return;
    try {
      // Send a literal "confirm" message through the brain — it'll match
      // the pending plan and call confirm_last_plan.
      await for (final _ in _api!.ask(text: 'confirm', language: 'en')) {}
      await _refresh();
    } catch (_) {}
  }

  Future<void> _cancelPlan() async {
    if (_api == null) return;
    try {
      await for (final _ in _api!.ask(text: 'cancel', language: 'en')) {}
      await _refresh();
    } catch (_) {}
  }

  Future<void> _logout() async {
    HeartbeatService.instance.stop();
    LocationService.instance.stop();
    await StatusService.instance.stop();
    await CredentialStore.instance.clear();
    if (!mounted) return;
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => const SetupScreen()),
    );
  }

  @override
  Widget build(BuildContext context) {
    final mode = ref.watch(connectionMonitorProvider);
    return Scaffold(
      appBar: AppBar(
        title: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('J.A.R.V.I.S.'),
            const SizedBox(width: 10),
            const _PresenceChip(),
          ],
        ),
        actions: [
          IconButton(
            tooltip: 'Tasks',
            icon: const Icon(Icons.travel_explore),
            onPressed: _api == null
                ? null
                : () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => TasksScreen(api: _api!),
                      ),
                    ),
          ),
          IconButton(
            tooltip: 'Vision',
            icon: const Icon(Icons.camera_alt_outlined),
            onPressed: _api == null
                ? null
                : () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => VisionScreen(api: _api!),
                      ),
                    ),
          ),
          IconButton(
            tooltip: 'Conversation',
            icon: const Icon(Icons.forum_outlined),
            onPressed: _api == null
                ? null
                : () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => ConversationScreen(api: _api!),
                      ),
                    ),
          ),
          PopupMenuButton<String>(
            tooltip: 'More',
            icon: const Icon(Icons.more_vert),
            onSelected: (value) {
              if (_api == null) return;
              switch (value) {
                case 'memo':
                  Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => MemoScreen(api: _api!),
                  ));
                  break;
                case 'watches':
                  Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => WatchesScreen(api: _api!),
                  ));
                  break;
                case 'locations':
                  Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => LocationsScreen(api: _api!),
                  ));
                  break;
                case 'routines':
                  Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => RoutinesScreen(api: _api!),
                  ));
                  break;
                case 'settings':
                  Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => const SettingsScreen(),
                  ));
                  break;
                case 'logout':
                  _logout();
                  break;
              }
            },
            itemBuilder: (_) => const [
              PopupMenuItem(
                value: 'memo',
                child: Row(children: [
                  Icon(Icons.fiber_manual_record, color: kAmber, size: 18),
                  SizedBox(width: 10),
                  Text('Voice memo'),
                ]),
              ),
              PopupMenuItem(
                value: 'watches',
                child: Row(children: [
                  Icon(Icons.add_alert_outlined, color: kAccent, size: 18),
                  SizedBox(width: 10),
                  Text('Watches'),
                ]),
              ),
              PopupMenuItem(
                value: 'locations',
                child: Row(children: [
                  Icon(Icons.place_outlined, color: kAccent, size: 18),
                  SizedBox(width: 10),
                  Text('Locations'),
                ]),
              ),
              PopupMenuItem(
                value: 'routines',
                child: Row(children: [
                  Icon(Icons.auto_awesome_motion, color: kAccent, size: 18),
                  SizedBox(width: 10),
                  Text('Routines'),
                ]),
              ),
              PopupMenuDivider(),
              PopupMenuItem(
                value: 'settings',
                child: Row(children: [
                  Icon(Icons.settings, size: 18),
                  SizedBox(width: 10),
                  Text('Settings'),
                ]),
              ),
              PopupMenuItem(
                value: 'logout',
                child: Row(children: [
                  Icon(Icons.logout, size: 18),
                  SizedBox(width: 10),
                  Text('Sign out'),
                ]),
              ),
            ],
          ),
          IconButton(icon: const Icon(Icons.refresh), onPressed: _refresh),
        ],
      ),
      floatingActionButton: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          FloatingActionButton(
            heroTag: 'voice',
            backgroundColor: kBgPanel,
            foregroundColor: kAccent,
            shape: const CircleBorder(side: BorderSide(color: kAccent, width: 2)),
            onPressed: _api == null
                ? null
                : () => Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => VoiceScreen(api: _api!)),
                    ),
            child: const Icon(Icons.mic),
          ),
          const SizedBox(height: 12),
          FloatingActionButton.extended(
            heroTag: 'ask',
            backgroundColor: kAccent,
            foregroundColor: kBg,
            icon: const Icon(Icons.chat_bubble_outline),
            label: const Text('ASK'),
            onPressed: _api == null
                ? null
                : () => Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => AskScreen(api: _api!)),
                    ),
          ),
        ],
      ),
      body: Column(
        children: [
          if (mode.isStandalone) const _LiteBanner(),
          Expanded(
            child: RefreshIndicator(
              color: kAccent,
              onRefresh: _refresh,
              child: _loading
                  ? const Center(child: CircularProgressIndicator(color: kAccent))
                  : (_api?.isLiteOnly == true)
                      ? const _LiteOnlyOnboarding()
                      : ListView(
                          padding: const EdgeInsets.all(16),
                          children: [
                            if (_error != null)
                              Card(
                                color: kDanger.withValues(alpha: 0.15),
                                child: Padding(
                                  padding: const EdgeInsets.all(14),
                                  child: Text(_error!,
                                      style: const TextStyle(color: kDanger)),
                                ),
                              ),
                            // Top priority: pending plan banner (if any)
                            _PendingPlanCard(
                              plan: _data?['pending_plan'],
                              onConfirm: _confirmPlan,
                              onCancel: _cancelPlan,
                            ),
                            _ActiveBriefCard(brief: _data?['active_brief']),
                            _QuickRoutinesRow(
                              routines: _data?['quick_routines'],
                              onRun: _runRoutine,
                            ),
                            // Live agentic state
                            _TasksMiniCard(
                              tasks: _data?['tasks'],
                              onTap: _openTasks,
                            ),
                            _WatchesMiniCard(
                              watches: _data?['watches'],
                              onTap: _openWatches,
                            ),
                            // Existing PC state cards
                            _SystemCard(_data?['system']),
                            _SimpleCard(
                                'WEATHER', _formatWeather(_data?['weather'])),
                            _SimpleCard(
                                'CALENDAR', _data?['calendar']?.toString()),
                            _SimpleCard(
                                'EMAILS', _data?['emails']?.toString()),
                            _SimpleCard(
                                'SPOTIFY', _data?['spotify']?.toString()),
                            _SimpleCard(
                                'LIGHTS', _data?['lights']?.toString()),
                            const SizedBox(height: 80),
                          ],
                        ),
            ),
          ),
        ],
      ),
    );
  }

  String? _formatWeather(dynamic w) {
    if (w is! Map) return null;
    return '${w['temp_c']}°C — ${w['description']}\n'
        'Feels ${w['feels_like']}°C · humidity ${w['humidity']}%';
  }
}

class _LiteOnlyOnboarding extends StatelessWidget {
  const _LiteOnlyOnboarding();

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        const SizedBox(height: 12),
        const Icon(Icons.smart_toy_outlined, size: 96, color: kAccent),
        const SizedBox(height: 16),
        const Text(
          'JARVIS LITE',
          textAlign: TextAlign.center,
          style: TextStyle(
              color: kAccent, letterSpacing: 4, fontSize: 22, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 24),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _step(1, 'Add an OpenAI API key',
                    'Open Settings → LITE MODE → paste a key (sk-…). '
                    'Stored only on this phone, never sent to the PC.'),
                _divider(),
                _step(2, 'Tap ASK',
                    'Type any question. Lite Jarvis answers directly via OpenAI.'),
                _divider(),
                _step(3, 'Try the lite tools',
                    '• "What\'s the weather in Bucharest?"\n'
                    '• "Set a reminder to drink water in 15 minutes."\n'
                    '• "Calculate 2389 * 14 / 5."'),
                _divider(),
                _step(4, 'When you\'re home',
                    'Settings → PC CONNECTION → SET UP PC NOW to pair with '
                    'the desktop and unlock voice + 47 tools.'),
              ],
            ),
          ),
        ),
        const SizedBox(height: 24),
        const Text(
          'Tap ASK in the bottom-right to start.',
          textAlign: TextAlign.center,
          style: TextStyle(color: Colors.white54),
        ),
        const SizedBox(height: 80),
      ],
    );
  }

  Widget _step(int n, String title, String body) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 28, height: 28,
              alignment: Alignment.center,
              decoration: const BoxDecoration(
                color: kAccent, shape: BoxShape.circle,
              ),
              child: Text(
                '$n',
                style: const TextStyle(
                    color: kBg, fontWeight: FontWeight.w700),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title,
                      style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.w600,
                          letterSpacing: 1.2)),
                  const SizedBox(height: 4),
                  Text(body,
                      style: const TextStyle(
                          color: Colors.white70, height: 1.4)),
                ],
              ),
            ),
          ],
        ),
      );

  Widget _divider() =>
      Divider(color: kAccentDim.withValues(alpha: 0.4), height: 12);
}

class _LiteBanner extends StatefulWidget {
  const _LiteBanner();

  @override
  State<_LiteBanner> createState() => _LiteBannerState();
}

class _LiteBannerState extends State<_LiteBanner> {
  bool _waking = false;
  bool _hasMac = false;

  @override
  void initState() {
    super.initState();
    _checkMac();
  }

  Future<void> _checkMac() async {
    final has = await WakeOnLanService.instance.hasMac();
    if (!mounted) return;
    setState(() => _hasMac = has);
  }

  Future<void> _wake() async {
    setState(() => _waking = true);
    final ok = await WakeOnLanService.instance.wake();
    if (!mounted) return;
    setState(() => _waking = false);
    final msg = ok
        ? 'Magic packet sent — give the PC ~30s.'
        : 'WoL failed (no MAC on file or send error).';
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      color: kAmber.withValues(alpha: 0.15),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      child: Row(
        children: [
          const Icon(Icons.cloud_off, color: kAmber, size: 18),
          const SizedBox(width: 8),
          const Expanded(
            child: Text(
              'PC offline — running in lite mode',
              style: TextStyle(color: kAmber, letterSpacing: 1.2),
            ),
          ),
          if (_hasMac)
            TextButton.icon(
              onPressed: _waking ? null : _wake,
              icon: _waking
                  ? const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: kAmber),
                    )
                  : const Icon(Icons.power_settings_new, size: 16),
              label: const Text('WAKE PC'),
              style: TextButton.styleFrom(foregroundColor: kAmber),
            ),
          TextButton(
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const SettingsScreen()),
            ),
            style: TextButton.styleFrom(foregroundColor: kAmber),
            child: const Text('SETTINGS'),
          ),
        ],
      ),
    );
  }
}

class _SystemCard extends StatelessWidget {
  const _SystemCard(this.sys);
  final dynamic sys;

  @override
  Widget build(BuildContext context) {
    if (sys is! Map) return const SizedBox.shrink();
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('SYSTEM', style: TextStyle(color: kAccent, letterSpacing: 2)),
            const SizedBox(height: 8),
            Text(
              'CPU ${sys['cpu_percent']}%   ·   '
              'RAM ${sys['ram_used_gb']} / ${sys['ram_total_gb']} GB '
              '(${sys['ram_percent']}%)',
              style: const TextStyle(color: Colors.white),
            ),
            Text(
              'Uptime ${sys['uptime_hours']}h',
              style: const TextStyle(color: Colors.white70),
            ),
          ],
        ),
      ),
    );
  }
}

class _SimpleCard extends StatelessWidget {
  const _SimpleCard(this.title, this.body);
  final String title;
  final String? body;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: const TextStyle(color: kAccent, letterSpacing: 2)),
            const SizedBox(height: 8),
            Text(
              body == null || body!.isEmpty ? '—' : body!,
              style: const TextStyle(color: Colors.white),
            ),
          ],
        ),
      ),
    );
  }
}

/// Live PC presence chip — driven by HeartbeatService.latest.
/// States: AT PC (cyan) · QUIET (purple) · PHONE-ONLY (amber) · AWAY (grey).
class _PresenceChip extends StatelessWidget {
  const _PresenceChip();

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<Map<String, dynamic>>(
      valueListenable: HeartbeatService.instance.latest,
      builder: (context, snap, _) {
        final state = (snap['presence'] as String?) ?? '';
        final quiet = snap['quiet_hours'] == true;
        final (label, color) = _styleFor(state, quiet);

        return Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.15),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: color.withValues(alpha: 0.7), width: 1),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 6,
                height: 6,
                decoration: BoxDecoration(
                  color: color,
                  shape: BoxShape.circle,
                ),
              ),
              const SizedBox(width: 6),
              Text(
                label,
                style: TextStyle(
                  color: color,
                  fontSize: 10,
                  letterSpacing: 1.6,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  static (String, Color) _styleFor(String state, bool quiet) {
    if (quiet) return ('QUIET', Colors.purpleAccent);
    switch (state) {
      case 'at_pc':
        return ('AT PC', kAccent);
      case 'phone_only':
        return ('ON PHONE', kAmber);
      case 'away':
        return ('AWAY', Colors.white38);
      default:
        return ('—', Colors.white24);
    }
  }
}

// ─────────────────────────────────────────────────────────────────
// New cards introduced when the backend grew (tasks, watches, plans,
// quick routines, active context). Each is null-safe — if the
// dashboard payload doesn't contain its slot, the widget renders a
// SizedBox.shrink() and disappears.
// ─────────────────────────────────────────────────────────────────

class _PendingPlanCard extends StatelessWidget {
  const _PendingPlanCard({
    required this.plan,
    required this.onConfirm,
    required this.onCancel,
  });
  final dynamic plan;
  final Future<void> Function() onConfirm;
  final Future<void> Function() onCancel;

  @override
  Widget build(BuildContext context) {
    if (plan is! Map) return const SizedBox.shrink();
    final id = plan['id'] as int?;
    final summary = (plan['summary'] as String?) ?? '';
    final stepCount = (plan['step_count'] as int?) ?? 0;
    final steps = (plan['step_summaries'] as List?)?.cast<String>() ?? const [];

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: kAmber.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: kAmber, width: 1.5),
        boxShadow: [
          BoxShadow(
            color: kAmber.withValues(alpha: 0.18),
            blurRadius: 14,
            spreadRadius: 1,
          ),
        ],
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.pending_actions, color: kAmber, size: 18),
                const SizedBox(width: 8),
                const Text(
                  'PENDING PLAN',
                  style: TextStyle(
                    color: kAmber,
                    letterSpacing: 2,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const Spacer(),
                if (id != null)
                  Text(
                    '#$id',
                    style: const TextStyle(color: Colors.white38, fontSize: 11),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              summary,
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w600,
                fontSize: 14,
              ),
            ),
            if (steps.isNotEmpty) ...[
              const SizedBox(height: 8),
              for (var i = 0; i < steps.length; i++)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 1.5),
                  child: Text(
                    '${i + 1}. ${steps[i]}',
                    style: const TextStyle(color: Colors.white70, fontSize: 12),
                  ),
                ),
            ],
            const SizedBox(height: 6),
            Text(
              '$stepCount step${stepCount == 1 ? '' : 's'}',
              style: const TextStyle(color: Colors.white38, fontSize: 11),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: onConfirm,
                    icon: const Icon(Icons.check, size: 18),
                    label: const Text('CONFIRM'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: kAccent,
                      foregroundColor: kBg,
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: onCancel,
                    icon: const Icon(Icons.close, size: 18),
                    label: const Text('CANCEL'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: kBgPanel,
                      foregroundColor: kDanger,
                      side: const BorderSide(color: kDanger, width: 1),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _ActiveBriefCard extends StatelessWidget {
  const _ActiveBriefCard({required this.brief});
  final dynamic brief;

  @override
  Widget build(BuildContext context) {
    if (brief is! String || (brief as String).isEmpty) {
      return const SizedBox.shrink();
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: kBgPanel,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: kAccentDim.withValues(alpha: 0.4)),
        ),
        child: Row(
          children: [
            const Icon(Icons.center_focus_weak, size: 14, color: kAccent),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                brief as String,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(color: Colors.white70, fontSize: 12),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _QuickRoutinesRow extends StatelessWidget {
  const _QuickRoutinesRow({required this.routines, required this.onRun});
  final dynamic routines;
  final Future<void> Function(String name) onRun;

  @override
  Widget build(BuildContext context) {
    if (routines is! List || (routines as List).isEmpty) {
      return const SizedBox.shrink();
    }
    final list = (routines as List).whereType<Map>().toList();
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Padding(
            padding: EdgeInsets.only(left: 4, bottom: 6),
            child: Text(
              'QUICK ROUTINES',
              style: TextStyle(
                color: kAccent,
                letterSpacing: 2,
                fontSize: 11,
              ),
            ),
          ),
          SizedBox(
            height: 36,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              itemCount: list.length,
              separatorBuilder: (_, __) => const SizedBox(width: 6),
              itemBuilder: (ctx, i) {
                final r = list[i];
                final name = (r['name'] as String?) ?? '';
                return ActionChip(
                  backgroundColor: kBgPanel,
                  side: const BorderSide(color: kAccent, width: 1),
                  avatar: const Icon(Icons.play_arrow, size: 14, color: kAccent),
                  label: Text(
                    name,
                    style: const TextStyle(color: kAccent, fontSize: 12),
                  ),
                  onPressed: () => onRun(name),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _TasksMiniCard extends StatelessWidget {
  const _TasksMiniCard({required this.tasks, required this.onTap});
  final dynamic tasks;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    if (tasks is! Map) return const SizedBox.shrink();
    final running = (tasks['running_count'] as int?) ?? 0;
    final recent = (tasks['recent'] as List?)?.cast<dynamic>() ?? const [];
    if (running == 0 && recent.isEmpty) return const SizedBox.shrink();

    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.travel_explore, color: kAccent, size: 18),
                  const SizedBox(width: 8),
                  const Text(
                    'TASKS',
                    style: TextStyle(color: kAccent, letterSpacing: 2),
                  ),
                  const Spacer(),
                  if (running > 0)
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(
                        color: kAmber.withValues(alpha: 0.18),
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: kAmber),
                      ),
                      child: Text(
                        '$running running',
                        style: const TextStyle(
                          color: kAmber,
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                          letterSpacing: 1,
                        ),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 8),
              for (final t in recent.take(3))
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: _TaskMiniRow(t: t),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _TaskMiniRow extends StatelessWidget {
  const _TaskMiniRow({required this.t});
  final dynamic t;

  @override
  Widget build(BuildContext context) {
    if (t is! Map) return const SizedBox.shrink();
    final status = (t['status'] as String?) ?? '';
    final prompt = (t['prompt'] as String?) ?? '';
    final id = t['id'];
    final color = switch (status) {
      'running' => kAmber,
      'pending' => Colors.white54,
      'done' => kAccent,
      'failed' => kDanger,
      'cancelled' => Colors.white38,
      _ => Colors.white54,
    };
    return Row(
      children: [
        Container(
          width: 6,
          height: 6,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 8),
        Text(
          '#$id',
          style: const TextStyle(color: Colors.white38, fontSize: 11),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            prompt,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(color: Colors.white, fontSize: 12),
          ),
        ),
      ],
    );
  }
}

class _WatchesMiniCard extends StatelessWidget {
  const _WatchesMiniCard({required this.watches, required this.onTap});
  final dynamic watches;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    if (watches is! Map) return const SizedBox.shrink();
    final active = (watches['active_count'] as int?) ?? 0;
    final fired = (watches['fired_count'] as int?) ?? 0;
    final last = watches['last_fired'];
    if (active == 0 && fired == 0) return const SizedBox.shrink();

    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.add_alert_outlined,
                      color: kAccent, size: 18),
                  const SizedBox(width: 8),
                  const Text(
                    'WATCHES',
                    style: TextStyle(color: kAccent, letterSpacing: 2),
                  ),
                  const Spacer(),
                  if (active > 0)
                    Text(
                      '$active active',
                      style:
                          const TextStyle(color: kAccent, fontSize: 11),
                    ),
                  if (active > 0 && fired > 0)
                    const Text(' · ',
                        style: TextStyle(color: Colors.white24)),
                  if (fired > 0)
                    Text(
                      '$fired fired',
                      style: const TextStyle(color: kAmber, fontSize: 11),
                    ),
                ],
              ),
              if (last is Map) ...[
                const SizedBox(height: 8),
                Container(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 10, vertical: 6),
                  decoration: BoxDecoration(
                    color: kAmber.withValues(alpha: 0.10),
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(
                        color: kAmber.withValues(alpha: 0.4)),
                  ),
                  child: Row(
                    children: [
                      const Icon(Icons.notifications_active,
                          color: kAmber, size: 14),
                      const SizedBox(width: 6),
                      Expanded(
                        child: Text(
                          (last['last_message'] as String?) ?? '',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              color: kAmber, fontSize: 12),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

