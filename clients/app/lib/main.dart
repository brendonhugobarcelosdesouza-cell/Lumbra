import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/node_status.dart';
import 'core/session.dart';
import 'core/theme.dart';
import 'features/auth/login_screen.dart';
import 'features/shell/home_shell.dart';
import 'features/shell/node_offline_screen.dart';

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
      // claro e escuro de verdade, seguindo a preferência do sistema: quem
      // deixa o computador no escuro não quer uma janela branca na cara
      theme: LumbraTheme.claro,
      darkTheme: LumbraTheme.escuro,
      themeMode: ThemeMode.system,
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
    // o Nó vem ANTES da sessão: sem servidor não há login, e um erro de
    // credencial seria a explicação errada para "o servidor não está no ar"
    final no = ref.watch(nodeStateProvider);
    if (no == NodeState.foraDoAr) return const NodeOfflineScreen();

    final sessao = ref.watch(sessionControllerProvider);
    if (no == NodeState.verificando || (sessao.isLoading && !sessao.hasValue)) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    return sessao.valueOrNull != null ? const HomeShell() : const LoginScreen();
  }
}
