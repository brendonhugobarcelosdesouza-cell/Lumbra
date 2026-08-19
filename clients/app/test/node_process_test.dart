import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_api/api.dart';
import 'package:lumbra_app/core/api.dart';
import 'package:lumbra_app/core/node_process.dart';
// o comando é um CONTRATO entre o app e a CLI: se um lado mudar sozinho, o
// sintoma aparece só na máquina do usuário
import 'package:lumbra_app/core/node_process_io.dart';
// direto do stub: em `node_process.dart` a importação é CONDICIONAL, então no
// desktop (onde os testes rodam) quem entra é a implementação de processo real
import 'package:lumbra_app/core/node_process_stub.dart';
import 'package:lumbra_app/core/node_status.dart';
import 'package:lumbra_app/core/session.dart';
import 'package:lumbra_app/features/approvals/approvals_providers.dart';
import 'package:lumbra_app/features/chat/chat_providers.dart';
import 'package:lumbra_app/features/documents/documents_providers.dart';
import 'package:lumbra_app/features/memories/memories_providers.dart';
import 'package:lumbra_app/features/playbooks/playbooks_providers.dart';
import 'package:lumbra_app/main.dart';

import 'node_status_test.dart';
import 'session_test.dart';

/// O sidecar (ADR-046). A regra que mais importa aqui não é "sobe o Nó" —
/// é **só derrubamos o que nós subimos**. Matar o servidor de alguém que
/// estava depurando seria uma traição difícil de diagnosticar: o sintoma é
/// "o Nó morre sozinho".

class _GerenteFalso implements GerenteDoNo {
  var iniciadas = 0;
  var paradas = 0;

  @override
  Future<PartidaDoNo> iniciar() async {
    iniciadas++;
    return PartidaDoNo.iniciado;
  }

  @override
  Future<void> parar() async => paradas++;

  @override
  bool get somosDonos => iniciadas > paradas;

  @override
  final ValueNotifier<String> ultimoErro = ValueNotifier('');
}

/// Um Nó que não responde — o estado em que ele fica enquanto recupera.
class _OpsQueNaoResponde extends OpsApi {
  @override
  Future<Map<String, String>?> healthHealthGet() async {
    throw ApiException(503, 'ainda subindo');
  }
}

Future<void> _montar(WidgetTester tester, _GerenteFalso gerente, NodeState estado) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        gerenteDoNoProvider.overrideWithValue(gerente),
        nodeStateProvider.overrideWith(() => NoFixo(estado)),
        tokenStorageProvider.overrideWithValue(FakeTokenStorage()),
        conversationsProvider.overrideWith((ref) async => const <ConversationOut>[]),
        pendingApprovalsProvider.overrideWith((ref) async => const <ApprovalOut>[]),
        playbooksProvider.overrideWith((ref) async => const <PlaybookOut>[]),
        memoriesProvider.overrideWith((ref) async => const <MemoryItemOut>[]),
        documentsProvider.overrideWith((ref) async => const <DocumentOut>[]),
      ],
      child: const LumbraApp(),
    ),
  );
  await tester.pump();
}

void main() {
  testWidgets('enquanto o Nó sobe, a tela explica em vez de girar em silêncio', (
    tester,
  ) async {
    await _montar(tester, _GerenteFalso(), NodeState.subindo);
    expect(find.text('Iniciando o Nó…'), findsOneWidget);
    // a primeira partida carrega o modelo de embeddings: avisar evita a
    // sensação de travado
    expect(find.textContaining('primeira vez demora'), findsOneWidget);
    // e NÃO acusa o Nó de ausente
    expect(find.text('O Nó não está no ar'), findsNothing);
  });

  testWidgets('com o Nó no ar, nada de sidecar na frente do usuário', (tester) async {
    await _montar(tester, _GerenteFalso(), NodeState.noAr);
    await tester.pumpAndSettle();
    expect(find.text('Iniciando o Nó…'), findsNothing);
  });

  test('Nó nosso ainda vivo é "subindo", nunca "fora do ar"', () async {
    // O app declarava o Nó morto TRÊS SEGUNDOS depois de o ter iniciado,
    // porque o vigia só tentava subir uma vez e, na verificação seguinte,
    // caía direto em "fora do ar". Só que recuperar um banco interrompido
    // leva mais de meio minuto: o app desistia de algo que estava dando
    // certo — e oferecia, ao lado, um comando que subiria um SEGUNDO Nó na
    // mesma porta.
    final gerente = _GerenteFalso();
    final container = ProviderContainer(
      overrides: [
        gerenteDoNoProvider.overrideWithValue(gerente),
        // sem rede no teste: o Nó "nunca responde", que é justamente o
        // estado em que ele está enquanto recupera o banco
        opsApiProvider.overrideWithValue(_OpsQueNaoResponde()),
      ],
    );
    addTearDown(container.dispose);

    final vigia = container.read(nodeStateProvider.notifier);
    await vigia.verificarAgora(); // não há Nó: sobe um
    expect(gerente.iniciadas, 1);
    expect(container.read(nodeStateProvider), NodeState.subindo);

    await vigia.verificarAgora(); // ainda não responde, mas o processo vive
    expect(container.read(nodeStateProvider), NodeState.subindo);
    expect(gerente.iniciadas, 1, reason: 'não pode tentar subir um segundo Nó');
  });

  test('esperar não é para sempre: passa a avisar que demorou', () async {
    // A primeira correção do bug acima não tinha teto, e trocou um problema
    // por outro: o app girava indefinidamente por um Nó que podia estar
    // travado. Prometer que algo está acontecendo sem ter como saber se
    // ainda está é tão desonesto quanto desistir cedo demais.
    final gerente = _GerenteFalso();
    final container = ProviderContainer(
      overrides: [
        gerenteDoNoProvider.overrideWithValue(gerente),
        opsApiProvider.overrideWithValue(_OpsQueNaoResponde()),
      ],
    );
    addTearDown(container.dispose);

    final vigia = container.read(nodeStateProvider.notifier);
    await vigia.verificarAgora();
    expect(container.read(nodeStateProvider), NodeState.subindo);

    vigia.debugNasceuEm(DateTime.now().subtract(const Duration(minutes: 5)));
    await vigia.debugVerificarSemZerar();
    expect(container.read(nodeStateProvider), NodeState.demorandoDemais);
    // e continua sendo NOSSO processo: não vira "fora do ar" nem oferece
    // um comando que subiria um segundo Nó
    expect(gerente.iniciadas, 1);
  });

  group('o comando que o app dá ao Nó', () {
    test('é `up`, o Nó como produto — não `dev`', () {
      // Enquanto isto dizia `dev`, o caminho que o usuário percorre ignorava
      // o Postgres embutido e a chave própria: o app exigia Docker sem
      // avisar, enquanto o `lumbra up` no terminal funcionava sem ele.
      expect(argumentosDoNo.first, 'up');
    });

    test('pede para o Nó seguir a entrada padrão', () {
      // é o que permite desligar sem matar: fechamos o stdin dele e ele
      // encerra sozinho. Sem isto, no Windows só resta TerminateProcess —
      // que já pegou o Postgres embutido no meio de um COMMIT.
      expect(argumentosDoNo, contains('--seguir-a-entrada'));
    });
  });

  group('gerente indisponível (Web e Android)', () {
    test('não finge que subiu', () async {
      final gerente = GerenteIndisponivel();
      expect(await gerente.iniciar(), PartidaDoNo.indisponivel);
    });

    test('nunca se diz dono de processo nenhum', () {
      // é o que impede a interface de oferecer "reiniciar o Nó" onde isso
      // não existe
      expect(GerenteIndisponivel().somosDonos, isFalse);
    });

    test('parar é inofensivo e idempotente', () async {
      final gerente = GerenteIndisponivel();
      await gerente.parar();
      await gerente.parar();
      expect(gerente.ultimoErro.value, isEmpty);
    });
  });
}
