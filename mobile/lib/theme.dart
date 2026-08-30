import 'package:flutter/material.dart';

const kBg = Color(0xFF050D1A);
const kBgPanel = Color(0xFF0A1628);
const kAccent = Color(0xFF00D9FF);
const kAccentDim = Color(0xFF0088B0);
const kAmber = Color(0xFFFFB800);
const kDanger = Color(0xFFFF4060);

ThemeData jarvisTheme() {
  final base = ThemeData.dark(useMaterial3: true);
  return base.copyWith(
    scaffoldBackgroundColor: kBg,
    colorScheme: base.colorScheme.copyWith(
      primary: kAccent,
      secondary: kAccentDim,
      surface: kBgPanel,
      error: kDanger,
    ),
    cardTheme: const CardThemeData(
      color: kBgPanel,
      elevation: 0,
      shape: RoundedRectangleBorder(
        side: BorderSide(color: kAccentDim, width: 1),
        borderRadius: BorderRadius.all(Radius.circular(12)),
      ),
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: kBg,
      foregroundColor: kAccent,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        color: kAccent,
        fontSize: 20,
        letterSpacing: 3,
        fontWeight: FontWeight.w600,
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: kBgPanel,
      border: OutlineInputBorder(
        borderSide: const BorderSide(color: kAccentDim),
        borderRadius: BorderRadius.circular(8),
      ),
      focusedBorder: OutlineInputBorder(
        borderSide: const BorderSide(color: kAccent, width: 2),
        borderRadius: BorderRadius.circular(8),
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: kAccent,
        foregroundColor: kBg,
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(8),
        ),
        textStyle: const TextStyle(
          fontWeight: FontWeight.w700,
          letterSpacing: 1.5,
        ),
      ),
    ),
  );
}
