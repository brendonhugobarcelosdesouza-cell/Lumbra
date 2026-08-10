import 'package:flutter/material.dart';
// AppExitResponse mora em services, não em material
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/node_process.dart';
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

class LumbraApp extends ConsumerStatefulWidget {
  const LumbraApp({super.key});

  @override
  ConsumerState<LumbraApp> createState() => _LumbraAppState();
}

class _LumbraAppState extends ConsumerState<LumbraApp> {
  AppLifecycleListener? _ciclo;

  @override
  void initState() {
    super.initState();
    // Fechar a janela derruba o Nó que NÓS subimos (ADR-046). Sem isto, cada
    // abertura do app deixaria para trás um servidor segurando a porta — e o
    // sintoma seria a próxima execução "funcionando" contra um Nó velho, com
    // código antigo. O gerente ignora o pedido quando o Nó é de outra pessoa.
    _ciclo = AppLifecycleListener(
      onExitRequested: () async {
        await ref.read(gerenteDoNoProvider).parar();
        return AppExitResponse.exit;
      },
    );
  }

  @override
  void dispose() {
    _ciclo?.dispose();
    super.dispose();
  }

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
    // 'subindo' é espera, não erro: mostramos o que está acontecendo em vez
    // de acusar o Nó de ausente enquanto ele nasce
    if (no == NodeState.subindo) return const _Subindo();

    final sessao = ref.watch(sessionControllerProvider);
    if (no == NodeState.verificando || (sessao.isLoading && !sessao.hasValue)) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    return sessao.valueOrNull != null ? const HomeShell() : const LoginScreen();
  }
}

/// A espera enquanto o Nó nasce.
///
/// Diz o que está acontecendo em vez de girar em silêncio: a primeira partida
/// carrega o modelo de embeddings e pode levar alguns segundos, e um app que
/// só mostra um círculo nesse tempo parece travado.
class _Subindo extends StatelessWidget {
  const _Subindo();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const CircularProgressIndicator(),
            const SizedBox(height: 20),
            Text('Iniciando o Nó…', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 6),
            Text(
              'A primeira vez demora um pouco mais.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}
