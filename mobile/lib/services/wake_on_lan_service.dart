import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Wake-on-LAN — sends a UDP magic packet to the PC's MAC address so it
/// powers up from sleep / hibernate / soft-off. Pure dart:io, no plugins.
///
/// The PC's MAC + broadcast IP are discovered automatically the first time
/// /api/mobile/health succeeds and persisted in secure storage.
class WakeOnLanService {
  WakeOnLanService._();
  static final WakeOnLanService instance = WakeOnLanService._();

  static const _kMacKey = 'wol_mac';
  static const _kBroadcastKey = 'wol_broadcast';
  static const _storage = FlutterSecureStorage();

  /// Cache the MAC + broadcast IP returned by /api/mobile/health.
  Future<void> remember({required String mac, required String broadcast}) async {
    if (mac.isEmpty) return;
    await _storage.write(key: _kMacKey, value: mac);
    await _storage.write(key: _kBroadcastKey, value: broadcast);
  }

  Future<({String? mac, String broadcast})> stored() async {
    final mac = await _storage.read(key: _kMacKey);
    final bcast =
        await _storage.read(key: _kBroadcastKey) ?? '255.255.255.255';
    return (mac: mac, broadcast: bcast);
  }

  Future<bool> hasMac() async {
    final s = await stored();
    return (s.mac != null && s.mac!.isNotEmpty);
  }

  /// Send the magic packet. Returns true on success.
  /// Default port 9 is the standard WoL port (some BIOS expect 7 — we send to both).
  Future<bool> wake({String? macOverride, String? broadcastOverride}) async {
    final s = await stored();
    final mac = (macOverride ?? s.mac ?? '').trim();
    final broadcast =
        (broadcastOverride ?? s.broadcast).trim().isEmpty
            ? '255.255.255.255'
            : (broadcastOverride ?? s.broadcast).trim();

    if (mac.isEmpty) {
      debugPrint('WoL: no MAC stored.');
      return false;
    }

    final List<int> macBytes;
    try {
      macBytes = mac
          .split(RegExp(r'[:\-\s]'))
          .where((s) => s.isNotEmpty)
          .map((s) => int.parse(s, radix: 16))
          .toList();
    } catch (e) {
      debugPrint('WoL: malformed MAC $mac — $e');
      return false;
    }
    if (macBytes.length != 6) {
      debugPrint('WoL: MAC must have 6 octets, got ${macBytes.length}');
      return false;
    }

    // Build the magic packet: 6 × 0xFF + 16 × MAC
    final packet = Uint8List(6 + 16 * 6);
    for (int i = 0; i < 6; i++) {
      packet[i] = 0xFF;
    }
    for (int i = 0; i < 16; i++) {
      for (int j = 0; j < 6; j++) {
        packet[6 + i * 6 + j] = macBytes[j];
      }
    }

    try {
      final socket =
          await RawDatagramSocket.bind(InternetAddress.anyIPv4, 0);
      socket.broadcastEnabled = true;

      final dest = InternetAddress(broadcast);
      // Many BIOSes listen on port 9, some on 7 — fire both.
      socket.send(packet, dest, 9);
      socket.send(packet, dest, 7);
      // Also unicast a global broadcast in case the LAN-specific one is filtered
      if (broadcast != '255.255.255.255') {
        socket.send(packet, InternetAddress('255.255.255.255'), 9);
      }

      socket.close();
      debugPrint('WoL: magic packet sent to $mac via $broadcast');
      return true;
    } catch (e) {
      debugPrint('WoL: send failed — $e');
      return false;
    }
  }
}
