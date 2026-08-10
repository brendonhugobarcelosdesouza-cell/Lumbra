import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_api/api.dart';
import 'package:lumbra_app/features/documents/documents_providers.dart';
import 'package:lumbra_app/features/documents/documents_screen.dart';

/// O acervo é a coisa mais central da Lumbra e só era alcançável pelo
/// Developer Console. Aqui o que importa é que a tela diga o ESTADO: saber
/// que um arquivo foi visto mas ainda não indexado é a diferença entre "a
/// Lumbra não sabe disso" e "a Lumbra ainda não terminou de ler".

DocumentOut _documento({
  String id = 'd1',
  String uri = 'file:///C:/faturas/itau%20agosto.pdf',
  String? titulo = 'Fatura Itaú',
  String estado = 'indexed',
  int versao = 1,
}) => DocumentOut(
  id: id,
  uri: uri,
  title: titulo,
  source: 'filesystem',
  processingState: estado,
  version: versao,
);

Future<void> _montar(WidgetTester tester, List<DocumentOut> docs) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [documentsProvider.overrideWith((ref) async => docs)],
      child: const MaterialApp(home: DocumentsScreen()),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('lista o que a Lumbra leu', (tester) async {
    await _montar(tester, [_documento()]);
    expect(find.text('Fatura Itaú'), findsOneWidget);
  });

  testWidgets('sem título, mostra o nome do arquivo — não a URI inteira', (
    tester,
  ) async {
    await _montar(tester, [_documento(titulo: null)]);
    expect(find.text('itau agosto.pdf'), findsOneWidget);
    expect(find.textContaining('file:///'), findsNothing);
  });

  testWidgets('os estados do pipeline são ditos em português', (tester) async {
    await _montar(tester, [
      _documento(id: 'a', estado: 'pending', titulo: 'Na fila'),
      _documento(id: 'b', estado: 'indexed', titulo: 'Pronto'),
      _documento(id: 'c', estado: 'failed', titulo: 'Quebrado'),
    ]);
    expect(find.text('na fila'), findsOneWidget);
    expect(find.text('pesquisável'), findsOneWidget);
    expect(find.text('falhou'), findsOneWidget);
    // o vocabulário do pipeline não vaza para a tela
    expect(find.text('indexed'), findsNothing);
  });

  testWidgets('versão só aparece quando há mais de uma', (tester) async {
    await _montar(tester, [_documento(versao: 3)]);
    expect(find.textContaining('versão 3'), findsOneWidget);

    await _montar(tester, [_documento(versao: 1)]);
    expect(find.textContaining('versão'), findsNothing);
  });

  testWidgets('acervo vazio convida a indexar', (tester) async {
    await _montar(tester, const []);
    expect(find.textContaining('Nenhum documento ainda.'), findsOneWidget);
    expect(find.widgetWithText(FloatingActionButton, 'Indexar pasta'), findsWidgets);
  });

  testWidgets('o diálogo de indexar promete privacidade e pede o caminho', (
    tester,
  ) async {
    await _montar(tester, const []);
    await tester.tap(find.text('Indexar pasta'));
    await tester.pumpAndSettle();

    expect(find.text('Indexar pasta'), findsWidgets);
    expect(find.textContaining('Nada sai do seu computador.'), findsOneWidget);
    expect(find.widgetWithText(TextField, ''), findsOneWidget);
  });
}
