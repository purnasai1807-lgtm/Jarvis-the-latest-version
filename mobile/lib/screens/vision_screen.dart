import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../services/jarvis_api.dart';
import '../theme.dart';

/// Camera tool: snap a photo (or pick from gallery), add an optional prompt,
/// send to GPT-4 Vision via /api/mobile/vision. The Q&A is mirrored to the
/// shared conversation store so it shows up on PC too.
class VisionScreen extends StatefulWidget {
  const VisionScreen({super.key, required this.api});
  final JarvisApi api;

  @override
  State<VisionScreen> createState() => _VisionScreenState();
}

class _VisionScreenState extends State<VisionScreen> {
  final _picker = ImagePicker();
  final _promptController = TextEditingController();

  File? _picked;
  String? _answer;
  String? _error;
  bool _busy = false;

  static const _suggestions = [
    "What's in this image?",
    'Translate the text in this photo',
    'Summarize this menu and recommend something',
    'Extract amounts/dates from this receipt',
    'What ingredients can I cook with these?',
    'Read this whiteboard',
  ];

  @override
  void dispose() {
    _promptController.dispose();
    super.dispose();
  }

  Future<void> _pick(ImageSource source) async {
    try {
      final x = await _picker.pickImage(
        source: source,
        maxWidth: 1920,
        imageQuality: 85,
      );
      if (x == null) return;
      setState(() {
        _picked = File(x.path);
        _answer = null;
        _error = null;
      });
    } catch (e) {
      setState(() => _error = 'Pick failed: $e');
    }
  }

  Future<void> _analyze() async {
    if (_picked == null) return;
    final prompt = _promptController.text.trim().isEmpty
        ? "Describe what's in this image."
        : _promptController.text.trim();

    setState(() {
      _busy = true;
      _answer = null;
      _error = null;
    });
    try {
      final answer = await widget.api.visionAnalyze(
        imageFile: _picked!,
        prompt: prompt,
      );
      if (!mounted) return;
      setState(() => _answer = answer.isEmpty ? '(no answer)' : answer);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('VISION')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (_picked == null) _PickerEmptyCard() else _PreviewCard(file: _picked!),
              const SizedBox(height: 16),
              Row(
                children: [
                  Expanded(
                    child: ElevatedButton.icon(
                      onPressed: _busy ? null : () => _pick(ImageSource.camera),
                      icon: const Icon(Icons.photo_camera),
                      label: const Text('CAMERA'),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: ElevatedButton.icon(
                      style: ElevatedButton.styleFrom(
                        backgroundColor: kBgPanel,
                        foregroundColor: kAccent,
                        side: const BorderSide(color: kAccent, width: 1),
                      ),
                      onPressed: _busy ? null : () => _pick(ImageSource.gallery),
                      icon: const Icon(Icons.photo_library_outlined),
                      label: const Text('GALLERY'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 20),
              Text(
                'PROMPT',
                style: TextStyle(
                  color: kAccent.withValues(alpha: 0.8),
                  letterSpacing: 2,
                ),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: _promptController,
                maxLines: 3,
                minLines: 2,
                decoration: const InputDecoration(
                  hintText: "What do you want to know about the image?",
                ),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: _suggestions
                    .map(
                      (s) => ActionChip(
                        backgroundColor: kBgPanel,
                        side: BorderSide(
                          color: kAccentDim.withValues(alpha: 0.6),
                        ),
                        labelStyle: const TextStyle(
                          color: Colors.white70,
                          fontSize: 12,
                        ),
                        label: Text(s),
                        onPressed: _busy
                            ? null
                            : () => setState(() {
                                  _promptController.text = s;
                                }),
                      ),
                    )
                    .toList(),
              ),
              const SizedBox(height: 16),
              ElevatedButton.icon(
                onPressed: _busy || _picked == null ? null : _analyze,
                icon: _busy
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: kBg,
                        ),
                      )
                    : const Icon(Icons.auto_awesome),
                label: Text(_busy ? 'ANALYZING...' : 'ANALYZE'),
              ),
              const SizedBox(height: 20),
              if (_error != null)
                Card(
                  color: kDanger.withValues(alpha: 0.15),
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Text(
                      _error!,
                      style: const TextStyle(color: kDanger),
                    ),
                  ),
                ),
              if (_answer != null)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'ANSWER',
                          style: TextStyle(color: kAccent, letterSpacing: 2),
                        ),
                        const SizedBox(height: 8),
                        SelectableText(
                          _answer!,
                          style: const TextStyle(
                            color: Colors.white,
                            height: 1.4,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              const SizedBox(height: 60),
            ],
          ),
        ),
      ),
    );
  }
}

class _PickerEmptyCard extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Container(
      height: 220,
      decoration: BoxDecoration(
        color: kBgPanel,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: kAccentDim, width: 1),
      ),
      child: const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.image_outlined, size: 56, color: kAccentDim),
            SizedBox(height: 8),
            Text(
              'No image yet',
              style: TextStyle(color: Colors.white54, letterSpacing: 1.4),
            ),
            SizedBox(height: 4),
            Text(
              'Tap CAMERA or GALLERY below',
              style: TextStyle(color: Colors.white38, fontSize: 12),
            ),
          ],
        ),
      ),
    );
  }
}

class _PreviewCard extends StatelessWidget {
  const _PreviewCard({required this.file});
  final File file;

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(12),
      child: Image.file(
        file,
        fit: BoxFit.cover,
        height: 260,
        width: double.infinity,
      ),
    );
  }
}
