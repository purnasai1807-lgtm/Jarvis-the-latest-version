# J.A.R.V.I.S. Mobile (Phase 1 — Flutter)

Companion app: dashboard + remote text control over Tailscale.

## First-time setup

1. **Install Flutter** on your dev machine: <https://docs.flutter.dev/get-started/install>
2. **Generate platform folders** (this directory ships only Dart sources + `pubspec.yaml`):

   ```bash
   cd mobile
   flutter create . --project-name jarvis_mobile --platforms=android,ios
   flutter pub get
   ```

3. **Install Tailscale** on your PC (`https://tailscale.com/download/windows`) and on your phone (Play Store / App Store). Join the same tailnet. Note the PC's Tailscale IP (e.g. `100.x.x.x`).

4. **Generate a mobile API key** on the PC:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   Paste it into `config.yaml`:

   ```yaml
   apis:
     mobile:
       api_key: "PASTE_HERE"
   ```

   Restart Jarvis (`python main.py`).

5. **Smoke test from a terminal** before launching the app:

   ```bash
   curl http://100.x.x.x:9000/api/mobile/health
   curl -H "Authorization: Bearer YOUR_KEY" \
        http://100.x.x.x:9000/api/mobile/dashboard
   ```

6. **Run the app** on a connected phone:

   ```bash
   flutter run
   ```

   On first launch enter `http://100.x.x.x:9000` and the API key. Credentials are stored in the device keychain.

## What works

**Phase 1 — text remote**
- Live dashboard cards (system, weather, calendar, emails, Spotify, lights), 30s refresh + pull-to-refresh
- "Ask" screen — text in → SSE-streamed brain reply, optional `Speak on PC` toggle
- EN ↔ RO language switch
- Tailscale-only connectivity (no port forwarding required)

**Phase 2 — voice on phone**
- Hold-to-talk mic FAB on the dashboard → `Voice` screen
- Records 16 kHz mono WAV on the phone
- Pipeline: `/api/mobile/transcribe` → `/api/mobile/ask` (SSE) → `/api/mobile/synthesize` → playback on phone speaker
- Optional `Also speak on PC` toggle

### Required permissions

After running `flutter create .`, add these once:

**Android** — `android/app/src/main/AndroidManifest.xml`:

```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.RECORD_AUDIO" />
```

If your PC server uses plain HTTP (Tailscale magic IP, no TLS), also add to the `<application>` tag:

```xml
android:usesCleartextTraffic="true"
```

**iOS** — `ios/Runner/Info.plist`:

```xml
<key>NSMicrophoneUsageDescription</key>
<string>Jarvis needs the microphone to capture voice commands.</string>
<key>NSAppTransportSecurity</key>
<dict>
  <key>NSAllowsArbitraryLoads</key>
  <true/>
</dict>
```

**Phase 3 — push notifications (FCM)**
- New unread emails (60s poll)
- Upcoming calendar events (10 min lead)
- Claude Code task finished
- Foreground display via `flutter_local_notifications`; background uses the system tray.

### Firebase setup (one-time)

1. Create a project: <https://console.firebase.google.com> → "Add project".
2. **Android app** — package name `com.myjarvis.jarvis_mobile` (or whatever the `--org` flag in `flutter create` set). Download `google-services.json` and place it at `mobile/android/app/google-services.json`.
3. **iOS app** — bundle ID matching your Xcode project. Download `GoogleService-Info.plist` and drag it into `Runner` in Xcode (target Runner, copy if needed). Set up an APNs auth key in `Project settings → Cloud Messaging → Apple app configuration`.
4. **Backend service account** — `Project settings → Service accounts → Generate new private key`. Save the JSON to the PC at `data/fcm-service-account.json`.
5. In `config.yaml` on the PC, fill:

   ```yaml
   apis:
     fcm:
       service_account_path: "data/fcm-service-account.json"
       project_id: "your-firebase-project-id"
   ```

   (project_id is at the top of the Firebase console General tab.)

6. **Android Gradle wiring** — after `flutter create .`, add to `android/build.gradle`:

   ```gradle
   buildscript {
     dependencies {
       classpath 'com.google.gms:google-services:4.4.2'
     }
   }
   ```

   And to `android/app/build.gradle` at the bottom:

   ```gradle
   apply plugin: 'com.google.gms.google-services'
   ```

7. Restart `python main.py` (logs should say "Proactive pollers started"), then launch the app. After login the device auto-registers.

### Test push

```bash
curl -X POST -H "Authorization: Bearer YOUR_KEY" \
     -H "Content-Type: application/json" \
     -d '{"title":"Jarvis","body":"hello sir"}' \
     http://100.x.x.x:9000/api/mobile/push/test
```

**Phase 4 — standalone (lite) mode**
- Auto-detects when the PC is unreachable (probes `/api/mobile/health` every 20s).
- Amber `PC offline — running in lite mode` banner appears on the dashboard.
- Tap **ASK** in lite mode and the phone calls the OpenAI API **directly** with a stripped-down brain. Replies are prefixed `[lite mode]`.
- Lite tools shipped:
  - `get_weather` (Open-Meteo, no API key)
  - `set_reminder` (local notification scheduled via `flutter_local_notifications`)
  - `calculate` (in-app shunting-yard evaluator)
- Voice screen disabled in lite mode (STT/TTS still need the PC) — use ASK instead.
- Add an OpenAI key in **Settings → LITE MODE** before going offline. Stored in the device keychain, kept separate from the PC API key.
- Override toggle in Settings → `FORCE LITE` for testing, then `AUTO DETECT` to resume probing.

## Coming next

- Replay queue (lite-mode commands offered to PC when it comes back online)
- Optional on-device LLM (Gemma 2B int4 via `flutter_gemma`) — adds ~1.4 GB so opt-in only
