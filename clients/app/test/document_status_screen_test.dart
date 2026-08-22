import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_api/api.dart';
import 'package:lumbra_app/features/documents/document_status_screen.dart';
import 'package:lumbra_app/features/documents/documents_providers.dart';

/// A lista de documentos diz O QUE aconteceu; esta tela diz ONDE. É a
/// ferramenta de quando a Lumbra "não sabe" de algo que deveria saber —
/// sem ela, "por que não achou minha fatura?" vira adivinhação.

const _id = 'doc-1';

DocumentStatusOut _status({
  String estado = 'indexed',
  int versao = 1,
  List<TimelineEntryOut> etapas = const [],
  List<DocumentVersionOut> versoes = const [],
}) => DocumentStatusOut(
  state: estado,
  version: versao,
  timeline: etapas,
  versions: versoes,
);

TimelineEntryOut _etapa({
  String estagio = 'extract',
  bool ok = true,
  double ms = 120,
  String mensagem = '',
}) => TimelineEntryOut(
  stage: estagio,
  startedAt: '2026-08-01T10:00:00Z',
  durationMs: ms,
  success: ok,
  message: mensagem,
);

Future<void> _montar(WidgetTester tester, DocumentStatusOut? status) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        documentStatusProvider(_id).overrideWith((ref) async => status),
      ],
      child: const MaterialApp(
        home: DocumentStatusScreen(documentId: _id, titulo: 'Fatura Itaú'),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('resume o estado em português e a versão', (tester) async {
    await _montar(tester, _status(estado: 'indexed', versao: 2));
    expect(find.textContaining('pesquisável'), findsOneWidget);
    expect(find.textContaining('versão 2'), findsOneWidget);
  });

  testWidgets('mostra as etapas do pipeline com a duração', (tester) async {
    await _montar(
      tester,
      _status(etapas: [_etapa(estagio: 'extract', ms: 120), _etapa(estagio: 'chunk', ms: 2500)]),
    );
    expect(find.text('extract'), findsOneWidget);
    expect(find.text('chunk'), findsOneWidget);
    // milissegundo cru não diz nada a quem só quer saber se demorou
    expect(find.text('120 ms'), findsOneWidget);
    expect(find.text('2.5 s'), findsOneWidget);
  });

  testWidgets('a etapa que falhou se explica', (tester) async {
    await _montar(
      tester,
      _status(
        estado: 'failed',
        etapas: [_etapa(estagio: 'extract', ok: false, mensagem: 'PDF sem camada de texto')],
      ),
    );
    expect(find.text('PDF sem camada de texto'), findsOneWidget);
    expect(find.textContaining('falhou'), findsOneWidget);
  });

  testWidgets('etapa bem-sucedida em silêncio não ganha linha extra', (
    tester,
  ) async {
    await _montar(tester, _status(etapas: [_etapa(mensagem: '')]));
    expect(find.text('extract'), findsOneWidget);
    expect(find.text(''), findsNothing);
  });

  testWidgets('versão nunca indexada é dita, não omitida', (tester) async {
    // ausência de data de indexação é INFORMAÇÃO: aquela versão nunca
    // chegou a ficar pesquisável
    await _montar(
      tester,
      _status(
        versoes: [
          DocumentVersionOut(version: 2, reason: 'conteúdo mudou', createdAt: '2026-08-01'),
        ],
      ),
    );
    expect(find.textContaining('nunca indexada'), findsOneWidget);
  });

  testWidgets('sem informação, diz o que fazer a respeito', (tester) async {
    // "Sem informação sobre este documento." era um encolher de ombros:
    // verdadeiro e inútil. Quem chega aqui chegou perguntando por que a
    // Lumbra não acha um arquivo, e a resposta tem que ter uma saída.
    await _montar(tester, null);
    expect(find.textContaining('não tem registro'), findsOneWidget);
    expect(find.textContaining('Reindexar'), findsOneWidget);
  });
}
