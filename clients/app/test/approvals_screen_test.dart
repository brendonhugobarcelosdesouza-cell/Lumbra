import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_api/api.dart';
import 'package:lumbra_app/features/approvals/approvals_providers.dart';
import 'package:lumbra_app/features/approvals/approvals_screen.dart';

ApprovalOut _pedido() => ApprovalOut(
  id: '019f-abc',
  action: 'playbook.write',
  subject: 'user:1',
  riskLevel: 'medium',
  reason: 'procedimento aprendido de uma execução bem-sucedida',
  createdAt: '2026-08-01T00:00:00Z',
  payload: {
    'title': 'Reindexar após mudar a extração',
    'steps': ['Reiniciar o Nó', 'Rodar reindexar com force'],
  },
);

Future<void> _montar(WidgetTester tester, List<ApprovalOut> fila) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [pendingApprovalsProvider.overrideWith((ref) async => fila)],
      child: const MaterialApp(home: ApprovalsScreen()),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('fila vazia diz que não há nada a decidir', (tester) async {
    await _montar(tester, const []);
    expect(find.text('Nada aguardando sua decisão.'), findsOneWidget);
  });

  testWidgets('o pedido mostra o que será feito, não só o nome da ação', (
    tester,
  ) async {
    await _montar(tester, [_pedido()]);

    // o título vem do payload: o usuário decide vendo o conteúdo
    expect(find.text('Reindexar após mudar a extração'), findsOneWidget);
    // e os passos propostos, um a um
    expect(find.text('• Reiniciar o Nó'), findsOneWidget);
    expect(find.text('• Rodar reindexar com force'), findsOneWidget);
    // o risco fica visível, e a ação técnica também
    expect(find.text('medium'), findsOneWidget);
    expect(find.text('playbook.write'), findsOneWidget);
  });

  testWidgets('as duas decisões estão disponíveis', (tester) async {
    await _montar(tester, [_pedido()]);
    expect(find.widgetWithText(FilledButton, 'Aprovar'), findsOneWidget);
    expect(find.widgetWithText(TextButton, 'Descartar'), findsOneWidget);
  });

  testWidgets('pedido sem título cai no nome da ação', (tester) async {
    final semTitulo = ApprovalOut(
      id: 'x',
      action: 'memory.forget',
      subject: 'user:1',
      riskLevel: 'high',
      reason: '',
      createdAt: '2026-08-01T00:00:00Z',
      payload: const {},
    );
    await _montar(tester, [semTitulo]);
    // aparece duas vezes: como título e como ação técnica
    expect(find.text('memory.forget'), findsNWidgets(2));
  });
}
