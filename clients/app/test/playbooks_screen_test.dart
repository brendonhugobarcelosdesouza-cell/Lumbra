import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_api/api.dart';
import 'package:lumbra_app/features/playbooks/playbooks_providers.dart';
import 'package:lumbra_app/features/playbooks/playbooks_screen.dart';

PlaybookOut _playbook({String origin = 'user', int uses = 0}) => PlaybookOut(
  id: 'pb-1',
  title: 'Reindexar após mudar a extração',
  whenToUse: 'quando o pipeline muda e os chunks ficam obsoletos',
  steps: ['Reiniciar o Nó', 'Rodar reindexar com force'],
  pitfalls: ['Reindexar sem reiniciar reprocessa com o código antigo'],
  verification: 'o valor certo aparece no topo',
  origin: origin,
  uses: uses,
  createdAt: '2026-08-01T00:00:00Z',
);

Future<void> _montar(WidgetTester tester, List<PlaybookOut> lista) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [playbooksProvider.overrideWith((ref) async => lista)],
      child: const MaterialApp(home: PlaybooksScreen()),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('sem procedimentos, explica de onde eles vêm', (tester) async {
    await _montar(tester, const []);
    expect(find.textContaining('Nenhum procedimento ainda.'), findsOneWidget);
  });

  testWidgets('lista mostra título e quando usar sem abrir', (tester) async {
    await _montar(tester, [_playbook()]);
    expect(find.text('Reindexar após mudar a extração'), findsOneWidget);
    expect(
      find.text('quando o pipeline muda e os chunks ficam obsoletos'),
      findsOneWidget,
    );
  });

  testWidgets('ao expandir, mostra passos, armadilha e verificação', (
    tester,
  ) async {
    await _montar(tester, [_playbook()]);
    await tester.tap(find.text('Reindexar após mudar a extração'));
    await tester.pumpAndSettle();

    expect(find.text('1. Reiniciar o Nó'), findsOneWidget);
    expect(find.text('2. Rodar reindexar com force'), findsOneWidget);
    // a armadilha é onde mora o valor: o erro que já custou caro
    expect(find.text('Atenção:'), findsOneWidget);
    expect(
      find.text('• Reindexar sem reiniciar reprocessa com o código antigo'),
      findsOneWidget,
    );
    expect(
      find.text('Como verificar: o valor certo aparece no topo'),
      findsOneWidget,
    );
  });

  testWidgets('a proveniência é dita em português, não no código', (
    tester,
  ) async {
    await _montar(tester, [_playbook(origin: 'agent', uses: 3)]);
    await tester.tap(find.text('Reindexar após mudar a extração'));
    await tester.pumpAndSettle();

    expect(find.text('aprendido pela Lumbra'), findsOneWidget);
    expect(find.text('usado 3x'), findsOneWidget);
    expect(find.text('agent'), findsNothing);
  });

  testWidgets('o usuário pode esquecer o que a plataforma aprendeu', (
    tester,
  ) async {
    await _montar(tester, [_playbook()]);
    await tester.tap(find.text('Reindexar após mudar a extração'));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(TextButton, 'Esquecer'), findsOneWidget);
  });
}
