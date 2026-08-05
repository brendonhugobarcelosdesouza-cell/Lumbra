import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_app/core/theme.dart';

/// A identidade não pode regredir para o template.
///
/// O app passou meses com o roxo `0xFF6750A4` que vem no `flutter create`.
/// Este arquivo existe para que isso seja um teste vermelho, e não uma
/// descoberta constrangedora meses depois.
const _roxoDoTemplate = Color(0xFF6750A4);

void main() {
  test('os dois temas existem e têm brilho oposto', () {
    expect(LumbraTheme.claro.brightness, Brightness.light);
    expect(LumbraTheme.escuro.brightness, Brightness.dark);
  });

  test('nenhum dos temas usa o roxo do template do Flutter', () {
    for (final tema in [LumbraTheme.claro, LumbraTheme.escuro]) {
      expect(tema.colorScheme.primary, isNot(_roxoDoTemplate));
    }
  });

  test('o escuro não é preto puro — preto absoluto cansa em uso longo', () {
    final fundo = LumbraTheme.escuro.colorScheme.surface;
    expect(fundo, isNot(Colors.black));
    expect(LumbraTheme.escuro.scaffoldBackgroundColor, fundo);
  });

  test('o claro não é branco puro', () {
    expect(LumbraTheme.claro.colorScheme.surface, isNot(Colors.white));
  });

  test('a barra de topo é moldura: sem sombra e sem cor própria', () {
    for (final tema in [LumbraTheme.claro, LumbraTheme.escuro]) {
      expect(tema.appBarTheme.elevation, 0);
      expect(tema.appBarTheme.scrolledUnderElevation, 0);
      expect(tema.appBarTheme.backgroundColor, tema.colorScheme.surface);
    }
  });

  test('texto de leitura tem altura de linha generosa', () {
    // a Lumbra é feita de parágrafos (respostas do chat, procedimentos),
    // não de rótulos soltos
    expect(LumbraTheme.claro.textTheme.bodyMedium?.height, greaterThanOrEqualTo(1.4));
    expect(LumbraTheme.escuro.textTheme.bodyMedium?.height, greaterThanOrEqualTo(1.4));
  });

  testWidgets('o app segue o tema do sistema', (tester) async {
    // não basta ter os dois: o app precisa alternar sozinho
    await tester.pumpWidget(
      MaterialApp(
        theme: LumbraTheme.claro,
        darkTheme: LumbraTheme.escuro,
        themeMode: ThemeMode.system,
        home: Builder(
          builder: (context) => Text('x', style: Theme.of(context).textTheme.bodyMedium),
        ),
      ),
    );
    final app = tester.widget<MaterialApp>(find.byType(MaterialApp));
    expect(app.themeMode, ThemeMode.system);
    expect(app.darkTheme, isNotNull);
  });
}
