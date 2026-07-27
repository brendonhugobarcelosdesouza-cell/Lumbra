import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'features/system/connection_screen.dart';

void main() {
  // ProviderScope: a raiz do Riverpod (ADR-048). Todo estado do app vive
  // em providers, testáveis e sem singletons globais.
  runApp(const ProviderScope(child: LumbraApp()));
}

class LumbraApp extends StatelessWidget {
  const LumbraApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Lumbra',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorSchemeSeed: const Color(0xFF6750A4),
        useMaterial3: true,
      ),
      home: const ConnectionScreen(),
    );
  }
}
