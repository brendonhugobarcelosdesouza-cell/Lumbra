import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_api/api.dart';
import 'package:lumbra_app/core/api.dart';
import 'package:lumbra_app/core/node_status.dart';
import 'package:lumbra_app/core/session.dart';
import 'package:lumbra_app/features/agents/agents_providers.dart';
import 'package:lumbra_app/features/approvals/approvals_providers.dart';
import 'package:lumbra_app/features/chat/chat_providers.dart';
import 'package:lumbra_app/features/documents/documents_providers.dart';
import 'package:lumbra_app/features/memories/memories_providers.dart';
import 'package:lumbra_app/features/playbooks/playbooks_providers.dart';
import 'package:lumbra_app/features/shell/barra_lateral.dart';
import 'package:lumbra_app/features/shell/secao_atual.dart';
import 'package:lumbra_app/features/visao_geral/saude_providers.dart';
import 'package:lumbra_app/main.dart';

import 'node_status_test.dart';
import 'session_test.dart';

void main() {
  testWidgets('sem sessão, a raiz mostra a tela de login', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          // o Nó vem antes de tudo na raiz do app: sem sobrepor, o teste
          // acabaria na tela de "Nó fora do ar"
          nodeStateProvider.overrideWith(() => NoFixo(NodeState.noAr)),
          tokenStorageProvider.overrideWithValue(FakeTokenStorage()),
        ],
        child: const LumbraApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Entrar'), findsOneWidget);
    expect(find.text('Criar uma conta'), findsOneWidget);
  });

  testWidgets('com sessão, a raiz abre na Visão geral', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          nodeStateProvider.overrideWith(() => NoFixo(NodeState.noAr)),
          tokenStorageProvider.overrideWithValue(
            FakeTokenStorage(
              const Session(accessToken: 'abc', refreshToken: 'ref'),
            ),
          ),
          // sem rede: a home recebe uma lista vazia de conversas
          conversationsProvider.overrideWith(
            (ref) async => const <ConversationOut>[],
          ),
          // a casca monta as quatro seções de uma vez (IndexedStack), então
          // todas precisam de dado falso — nenhuma pode ir à rede no teste
          pendingApprovalsProvider.overrideWith(
            (ref) async => const <ApprovalOut>[],
          ),
          agentsProvider.overrideWith((ref) async => const <AgentOut>[]),
          playbooksProvider.overrideWith((ref) async => const <PlaybookOut>[]),
          memoriesProvider.overrideWith((ref) async => const <MemoryItemOut>[]),
          documentsProvider.overrideWith((ref) async => const <DocumentOut>[]),
          devicesListProvider.overrideWith((ref) async => const <DeviceResponse>[]),
          // a Visão geral é a primeira tela: sem diagnóstico falso ela iria
          // à rede no teste
          saudeProvider.overrideWith((ref) async => null),
        ],
        child: const LumbraApp(),
      ),
    );
    await tester.pumpAndSettle();

    // a Lumbra abre dizendo o que tem e como está, sem exigir uma escolha
    // antes: entrar direto numa conversa vazia era pedir que a pessoa
    // soubesse o que perguntar antes de saber o que existe ali
    expect(
      find.text('Isto é o que a Lumbra guarda e como ela está agora.'),
      findsOneWidget,
    );
    // as conversas continuam a um clique. Pela barra, e não pelo cartão:
    // "Conversas" é o nome dos dois, e o teste precisa dizer qual dos
    // caminhos está exercitando
    await tester.tap(
      find.descendant(
        of: find.byType(BarraLateral),
        matching: find.text('Conversas'),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Nenhuma conversa ainda.'), findsOneWidget);
    // botão redondo com "+", como na referência: o rótulo virou dica
    expect(find.byTooltip('Nova conversa'), findsOneWidget);
    // a janela do teste tem 800px: abaixo de Largura.media, so a lista
    // aparece. O painel do meio e coberto em conversas_layout_test.dart,
    // onde a largura e explicita.

    // `Secoes.ordem` e os filhos do IndexedStack são duas listas que
    // precisam concordar; quem acrescentar uma seção só de um lado passa a
    // abrir a tela errada, em silêncio
    final pilha = tester.widget<IndexedStack>(find.byType(IndexedStack));
    expect(pilha.children.length, Secoes.ordem.length);
  });
}
