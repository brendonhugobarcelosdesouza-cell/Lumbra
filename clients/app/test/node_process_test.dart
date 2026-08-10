import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_api/api.dart';
import 'package:lumbra_app/core/node_process.dart';
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
  _GerenteFalso({this.resultado = PartidaDoNo.iniciado, this.donos = true});

  final PartidaDoNo resultado;
  final bool donos;
  var iniciadas = 0;
  var paradas = 0;

  @override
  Future<PartidaDoNo> iniciar() async {
    iniciadas++;
    return resultado;
  }

  @override
  Future<void> parar() async => paradas++;

  @override
  bool get somosDonos => donos;

  @override
  String get ultimoErro => '';
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
      expect(gerente.ultimoErro, isEmpty);
    });
  });
}
