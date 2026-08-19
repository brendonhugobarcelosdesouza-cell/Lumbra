// AppExitResponse é do dart:ui — não de material nem de services. O
// AppLifecycleListener vem de widgets (via material), mas o enum que ele
// devolve mora uma camada abaixo.
import 'dart:ui' show AppExitResponse;

import 'package:flutter/material.dart';
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
    // Demorando demais NÃO vira tela de erro: o Nó está vivo e pode terminar
    // a qualquer momento. Mudamos só o que dizemos — de "aguarde" para
    // "isto passou do normal, e aqui está onde olhar".
    if (no == NodeState.demorandoDemais) return const _Subindo(demorado: true);

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
  const _Subindo({this.demorado = false});

  /// Passou do tempo que uma partida deveria levar. O Nó ainda está vivo —
  /// então continuamos esperando —, mas paramos de fingir que é normal.
  final bool demorado;

  @override
  Widget build(BuildContext context) {
    final textos = Theme.of(context).textTheme;
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const CircularProgressIndicator(),
                const SizedBox(height: 20),
                Text(
                  demorado ? 'O Nó está demorando mais que o normal' : 'Iniciando o Nó…',
                  textAlign: TextAlign.center,
                  style: textos.titleMedium,
                ),
                const SizedBox(height: 6),
                Text(
                  demorado
                      ? 'Ele continua rodando, e o app entra sozinho se ele '
                            'terminar. Se preferir não esperar, feche a janela '
                            'e veja o registro:'
                      : 'A primeira vez demora um pouco mais. Se a Lumbra foi '
                            'fechada de repente, o banco também precisa se recuperar.',
                  textAlign: TextAlign.center,
                  style: textos.bodySmall,
                ),
                if (demorado && caminhoDoLogDoNo != null) ...[
                  const SizedBox(height: 10),
                  SelectableText(
                    caminhoDoLogDoNo!,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontFamily: 'monospace', fontSize: 11.5),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
