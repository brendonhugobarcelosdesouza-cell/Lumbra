import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_app/features/chat/composer.dart';

/// O campo de escrita é a peça mais usada da tela, e as regras dele são de
/// teclado — a classe de comportamento que some numa refatoração sem que
/// ninguém perceba, porque a tela continua desenhando igual.
void main() {
  late TextEditingController campo;
  late List<String> enviados;
  late int paradas;

  setUp(() {
    campo = TextEditingController();
    enviados = [];
    paradas = 0;
  });

  tearDown(() => campo.dispose());

  Future<void> montar(WidgetTester tester, {bool enviando = false}) {
    return tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Composer(
            controlador: campo,
            enviando: enviando,
            aoEnviar: () => enviados.add(campo.text),
            aoParar: () => paradas++,
          ),
        ),
      ),
    );
  }

  testWidgets('Enter envia', (tester) async {
    await montar(tester);
    await tester.enterText(find.byType(TextField), 'quanto gastei?');
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pump();

    expect(enviados, ['quanto gastei?']);
  });

  testWidgets('Shift+Enter NÃO envia — quebra linha', (tester) async {
    await montar(tester);
    await tester.enterText(find.byType(TextField), 'primeira linha');

    await tester.sendKeyDownEvent(LogicalKeyboardKey.shiftLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.shiftLeft);
    await tester.pump();

    expect(enviados, isEmpty);
  });

  testWidgets('Enter durante a geração não dispara outro envio', (
    tester,
  ) async {
    // sem isto, apertar Enter sem querer enquanto a resposta chega enfileira
    // uma segunda pergunta que ninguém pediu
    await montar(tester, enviando: true);
    await tester.enterText(find.byType(TextField), 'outra pergunta');
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pump();

    expect(enviados, isEmpty);
  });

  testWidgets('o campo continua editável enquanto a Lumbra responde', (
    tester,
  ) async {
    // bloquear o campo obrigava a esperar a resposta inteira para começar a
    // escrever a próxima pergunta — e a resposta pode levar um minuto
    await montar(tester, enviando: true);
    final campoWidget = tester.widget<TextField>(find.byType(TextField));
    expect(campoWidget.enabled, isNot(false));

    await tester.enterText(find.byType(TextField), 'rascunho');
    expect(campo.text, 'rascunho');
  });

  testWidgets('o botão vira parar durante a geração', (tester) async {
    await montar(tester, enviando: true);
    expect(find.byTooltip('Parar'), findsOneWidget);

    await tester.tap(find.byTooltip('Parar'));
    await tester.pump();
    expect(paradas, 1);
    expect(enviados, isEmpty);
  });

  testWidgets('sem texto, o botão de enviar não faz nada', (tester) async {
    await montar(tester);
    await tester.tap(find.byTooltip('Enviar  ·  Enter'));
    await tester.pump();
    expect(enviados, isEmpty);

    // e com texto, faz
    await tester.enterText(find.byType(TextField), 'agora sim');
    await tester.pump();
    await tester.tap(find.byTooltip('Enviar  ·  Enter'));
    await tester.pump();
    expect(enviados, ['agora sim']);
  });

  testWidgets('só espaço em branco não conta como texto', (tester) async {
    await montar(tester);
    await tester.enterText(find.byType(TextField), '   \n  ');
    await tester.pump();
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pump();

    // o Composer chama `aoEnviar`; quem recusa o vazio é a tela — mas o
    // BOTÃO precisa estar apagado, senão ele promete uma ação que não vem
    await tester.tap(find.byTooltip('Enviar  ·  Enter'));
    await tester.pump();
    expect(enviados, isEmpty);
  });
}
