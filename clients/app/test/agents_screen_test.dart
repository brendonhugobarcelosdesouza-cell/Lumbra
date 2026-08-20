import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_api/api.dart';
import 'package:lumbra_app/features/agents/agents_providers.dart';
import 'package:lumbra_app/features/agents/agents_screen.dart';

/// Os agentes existiam desde a fase A e eram invisíveis: quando você pergunta
/// sobre um documento, é o `documents-agent` que responde, e nada na tela
/// dizia isso. Uma plataforma que delega precisa mostrar PARA QUEM delega.
///
/// A tela não cria nem configura agente — e os testes guardam essa fronteira
/// junto com o conteúdo, porque "criar agente" é o tipo de botão que aparece
/// sozinho numa tela que já parece um painel de administração.

AgentOut _agente({
  String nome = 'documents-agent',
  String risco = 'low',
  bool ligado = true,
  List<String> capabilities = const ['documents.search', 'documents.read'],
}) => AgentOut(
  id: 'a1',
  name: nome,
  version: '1.0.0',
  riskLevel: risco,
  enabled: ligado,
  description: 'Procura nos documentos indexados e cita a origem.',
  capabilities: capabilities,
);

Future<void> _montar(WidgetTester tester, List<AgentOut> lista) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [agentsProvider.overrideWith((ref) async => lista)],
      child: const MaterialApp(home: Scaffold(body: AgentsScreen())),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('mostra quem existe, o que sabe fazer e o risco', (tester) async {
    await _montar(tester, [_agente()]);

    expect(find.text('documents-agent'), findsOneWidget);
    expect(find.textContaining('Procura nos documentos'), findsOneWidget);
    // as capabilities são o limite do que a Lumbra pode delegar a ele
    expect(find.text('documents.search'), findsOneWidget);
    expect(find.text('documents.read'), findsOneWidget);
    expect(find.text('risco baixo'), findsOneWidget);
  });

  testWidgets('o risco é dito em português, como na fila de aprovações', (
    tester,
  ) async {
    // mesmo vocabulário nas duas telas: risco alto aqui e risco alto lá são
    // a mesma coisa, e dois desenhos para o mesmo conceito fariam a pessoa
    // aprender duas vezes
    await _montar(tester, [_agente(risco: 'high')]);
    expect(find.text('risco alto'), findsOneWidget);
    expect(find.text('high'), findsNothing);
  });

  testWidgets('agente desligado se identifica', (tester) async {
    // um agente desligado continua na lista; sem o selo ele pareceria ativo,
    // que é o oposto do que a tela existe para dizer
    await _montar(tester, [_agente(ligado: false)]);
    expect(find.text('desligado'), findsOneWidget);
  });

  testWidgets('sem agentes, explica o que eles são', (tester) async {
    await _montar(tester, const []);
    expect(find.textContaining('Nenhum agente registrado'), findsOneWidget);
    expect(find.textContaining('tarefas especializadas'), findsOneWidget);
  });

  testWidgets('a tela NÃO oferece criar agente', (tester) async {
    // criar agente é outro projeto. Um botão aqui prometeria uma capacidade
    // que não existe — o mesmo pecado que o prompt já custou consertar.
    await _montar(tester, [_agente()]);
    expect(find.textContaining('Criar'), findsNothing);
    expect(find.textContaining('Novo agente'), findsNothing);
  });
}
