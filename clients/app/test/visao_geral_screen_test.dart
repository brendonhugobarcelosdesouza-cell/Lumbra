import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_api/api.dart';
import 'package:lumbra_app/features/agents/agents_providers.dart';
import 'package:lumbra_app/features/approvals/approvals_providers.dart';
import 'package:lumbra_app/features/chat/chat_providers.dart';
import 'package:lumbra_app/features/documents/documents_providers.dart';
import 'package:lumbra_app/features/memories/memories_providers.dart';
import 'package:lumbra_app/features/playbooks/playbooks_providers.dart';
import 'package:lumbra_app/features/shell/secao_atual.dart';
import 'package:lumbra_app/features/visao_geral/saude_providers.dart';
import 'package:lumbra_app/features/visao_geral/visao_geral_screen.dart';

/// A Visão geral existe para responder duas perguntas sem que se precise
/// escolher nada antes: "o que tem aqui dentro?" e "está tudo bem?".
///
/// O que os testes guardam é justamente o que uma tela de painel tende a
/// perder com o tempo: não inventar número quando o dado ainda não chegou,
/// não afogar a única falha numa lista de dez "OK", e sempre dizer o que
/// fazer quando algo está errado.

CheckOut _check({
  String nome = 'banco',
  String status = 'ok',
  String resumo = 'Postgres respondendo.',
  String? conserto,
}) => CheckOut(name: nome, status: status, summary: resumo, fix: conserto);

HealthOut _saude({bool pronta = true, List<CheckOut>? checks}) => HealthOut(
  version: '0.9.0',
  environment: 'development',
  ready: pronta,
  summary: ResumoOut(ok: 4),
  modules: const ['chat', 'documents', 'memory'],
  skills: 7,
  checks: checks ?? [_check()],
);

Future<ProviderContainer> _montar(
  WidgetTester tester, {
  HealthOut? saude,
  Object? erroNaSaude,
  int conversas = 3,
  int aprovacoes = 0,
  bool contagensCarregando = false,
  Size janela = const Size(1000, 1400),
}) async {
  // uma resposta que nunca chega — é assim que a tela fica no primeiro
  // instante, e é o instante em que ela pode inventar um número
  Future<List<T>> pendente<T>() => Completer<List<T>>().future;
  Future<List<T>> pronta<T>(List<T> itens) =>
      contagensCarregando ? pendente<T>() : Future.value(itens);

  final container = ProviderContainer(
    overrides: [
      if (erroNaSaude != null)
        saudeProvider.overrideWith((ref) async => throw erroNaSaude)
      else
        saudeProvider.overrideWith((ref) async => saude),
      conversationsProvider.overrideWith(
        (ref) => pronta(
          List.generate(
            conversas,
            (i) => ConversationOut(
              id: '$i',
              userId: 'u1',
              title: 'c$i',
              createdAt: '2026-08-21T10:00:00Z',
            ),
          ),
        ),
      ),
      memoriesProvider.overrideWith((ref) => pronta(const <MemoryItemOut>[])),
      documentsProvider.overrideWith((ref) => pronta(const <DocumentOut>[])),
      playbooksProvider.overrideWith((ref) => pronta(const <PlaybookOut>[])),
      agentsProvider.overrideWith((ref) => pronta(const <AgentOut>[])),
      pendingApprovalsProvider.overrideWith(
        (ref) => pronta(
          List.generate(
            aprovacoes,
            (i) => ApprovalOut(
              id: '$i',
              action: 'documents.index',
              subject: 'documents',
              riskLevel: 'medium',
              createdAt: '2026-08-21T10:00:00Z',
            ),
          ),
        ),
      ),
    ],
  );
  addTearDown(container.dispose);

  // a tela é uma coluna longa; na janela padrão de 600px de altura o
  // diagnóstico ficaria fora da árvore e os testes passariam a medir o
  // tamanho da janela em vez do conteúdo
  tester.view.physicalSize = janela;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);

  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: Scaffold(body: VisaoGeralScreen())),
    ),
  );
  if (contagensCarregando) {
    await tester.pump();
  } else {
    await tester.pumpAndSettle();
  }
  return container;
}

void main() {
  testWidgets('conta o que está guardado e leva até lá', (tester) async {
    final container = await _montar(tester, saude: _saude());

    expect(find.text('3'), findsOneWidget);
    expect(find.text('Conversas'), findsOneWidget);

    // o cartão é um caminho, não um enfeite: clicar troca de seção
    await tester.tap(find.text('Conversas'));
    await tester.pump();
    expect(container.read(secaoAtualProvider), Secoes.conversas);
  });

  testWidgets('não chuta zero enquanto o número não chegou', (tester) async {
    // zero é uma afirmação forte — "você não tem nenhuma conversa" — e dizê-la
    // antes de saber é o jeito mais discreto de um painel mentir
    await _montar(tester, saude: _saude(), contagensCarregando: true);
    expect(find.text('0'), findsNothing);
    expect(find.text('—'), findsWidgets);
  });

  testWidgets('tudo em ordem cabe em um cartão só', (tester) async {
    await _montar(
      tester,
      saude: _saude(
        checks: [
          _check(nome: 'banco'),
          _check(nome: 'migrações'),
          _check(nome: 'modelo local'),
        ],
      ),
    );

    expect(find.text('Tudo pronto para usar.'), findsOneWidget);
    // as três não viram três cartões: uma lista de "OK" é ruído
    expect(find.text('banco'), findsNothing);
    expect(find.textContaining('3 verificações em ordem'), findsOneWidget);
  });

  testWidgets('a verificação que falhou aparece inteira, com o conserto', (
    tester,
  ) async {
    await _montar(
      tester,
      saude: _saude(
        pronta: false,
        checks: [
          _check(nome: 'banco'),
          _check(
            nome: 'modelo local',
            status: 'fail',
            resumo: 'Ollama não respondeu.',
            conserto: 'ollama serve',
          ),
        ],
      ),
    );

    expect(find.text('Há problemas impedindo o funcionamento.'), findsOneWidget);
    expect(find.text('modelo local'), findsOneWidget);
    expect(find.text('Ollama não respondeu.'), findsOneWidget);
    // um diagnóstico sem o que fazer a respeito é só uma reclamação
    expect(find.text('ollama serve'), findsOneWidget);
  });

  testWidgets('cabe numa coluna estreita', (tester) async {
    // a primeira versão desta tela estourava a partir de ~530px de largura,
    // e este arquivo não viu porque abria a janela em 1000. Um teste que
    // escolhe a largura onde tudo cabe não está testando o layout.
    await _montar(tester, saude: _saude(), janela: const Size(520, 1400));

    expect(tester.takeException(), isNull);
    expect(
      find.text('Isto é o que a Lumbra guarda e como ela está agora.'),
      findsOneWidget,
    );
  });

  testWidgets('sem diagnóstico, diz que não sabe em vez de dizer que está bem', (
    tester,
  ) async {
    await _montar(tester, erroNaSaude: Exception('sem rede'));

    expect(find.text('Tudo pronto para usar.'), findsNothing);
    expect(find.textContaining('diagnóstico'), findsWidgets);
  });
}
