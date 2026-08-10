import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_api/api.dart';
import 'package:lumbra_app/features/memories/memories_providers.dart';
import 'package:lumbra_app/features/memories/memories_screen.dart';

/// A tela existe por causa de um episódio real: a reflexão automática
/// guardou uma resposta ERRADA como fato, a memória passou a vencer o
/// documento na busca, e o chat repetiu o erro por dias. A correção foi
/// apagar o registro — por linha de comando, porque não havia onde clicar.

MemoryItemOut _memoria({
  String id = 'm1',
  String conteudo = 'Possui uma fatura do Itau de R\$ 6314,94',
  String camada = 'episodic',
  int usos = 0,
}) => MemoryItemOut(
  id: id,
  userId: 'u',
  kind: camada,
  content: conteudo,
  importance: 0.5,
  accessCount: usos,
  lastAccessedAt: '2026-08-01T10:00:00Z',
  createdAt: '2026-08-01T10:00:00Z',
);

Future<void> _montar(WidgetTester tester, List<MemoryItemOut> itens) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [memoriesProvider.overrideWith((ref) async => itens)],
      child: const MaterialApp(home: MemoriesScreen()),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('mostra o conteúdo do que a plataforma guardou', (tester) async {
    await _montar(tester, [_memoria()]);
    expect(
      find.text('Possui uma fatura do Itau de R\$ 6314,94'),
      findsOneWidget,
    );
  });

  testWidgets('as camadas aparecem em português, não no código', (tester) async {
    await _montar(tester, [_memoria(camada: 'semantic')]);
    // 'semantic' não diz nada a quem só quer saber o que a Lumbra sabe
    expect(find.textContaining('Fatos'), findsWidgets);
    expect(find.textContaining('semantic'), findsNothing);
  });

  testWidgets('memória nunca usada se identifica', (tester) async {
    // usos == 0 é o sinal mais forte de que aquilo não deveria estar ali
    await _montar(tester, [_memoria(usos: 0)]);
    expect(find.textContaining('nunca usada'), findsOneWidget);
  });

  testWidgets('memória usada mostra quantas vezes', (tester) async {
    await _montar(tester, [_memoria(usos: 7)]);
    expect(find.textContaining('usada 7x'), findsOneWidget);
  });

  testWidgets('esquecer está sempre a um toque', (tester) async {
    await _montar(tester, [_memoria()]);
    expect(find.widgetWithText(TextButton, 'Esquecer'), findsOneWidget);
  });

  testWidgets('sem memórias, a tela diz isso sem parecer erro', (tester) async {
    await _montar(tester, const []);
    expect(find.text('Nada guardado nesta camada.'), findsOneWidget);
  });

  testWidgets('o filtro oferece todas as camadas mais "Tudo"', (tester) async {
    await _montar(tester, [_memoria()]);
    for (final rotulo in camadas.values) {
      expect(find.widgetWithText(ChoiceChip, rotulo), findsOneWidget);
    }
  });
}
