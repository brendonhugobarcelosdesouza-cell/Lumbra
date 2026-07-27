import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/session.dart';
import 'features/auth/login_screen.dart';
import 'features/chat/conversations_screen.dart';

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
      home: const _Raiz(),
    );
  }
}

/// Decide a tela pela sessão: splash só na carga inicial do token; depois,
/// Home se autenticado, Login caso contrário (inclusive se a leitura do
/// token falhar).
class _Raiz extends ConsumerWidget {
  const _Raiz();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sessao = ref.watch(sessionControllerProvider);
    if (sessao.isLoading && !sessao.hasValue) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    return sessao.valueOrNull != null
        ? const ConversationsScreen()
        : const LoginScreen();
  }
}
