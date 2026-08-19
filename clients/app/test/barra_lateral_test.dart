import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_app/features/shell/barra_lateral.dart';

/// A barra lateral mostra seções que AINDA NÃO EXISTEM (Agenda, Tarefas,
/// Configurações). Isso é deliberado — o menu vira um mapa do que a Lumbra
/// será —, mas depende de uma propriedade que precisa ser garantida por
/// teste, não por atenção: **o que está marcado como futuro não abre nada**.
///
/// Se um dia alguém apagar o selo sem construir a tela, o clique passaria a
/// navegar para uma seção vazia. Seria a versão em interface do assistente
/// inventando capacidades, que já custou uma rodada inteira para consertar.
void main() {
  Widget montar({
    required Map<String, List<Secao>> grupos,
    required void Function(String) aoSelecionar,
    List<Secao> fixos = const [],
  }) {
    return MaterialApp(
      home: Scaffold(
        body: BarraLateral(
          grupos: grupos,
          fixos: fixos,
          selecionada: 'Conversas',
          aoSelecionar: aoSelecionar,
          rodape: const SizedBox.shrink(),
        ),
      ),
    );
  }

  const disponivel = Secao(
    nome: 'Conversas',
    icone: Icons.forum_outlined,
    iconeAtivo: Icons.forum,
  );
  const futura = Secao(
    nome: 'Agenda',
    icone: Icons.event_outlined,
    iconeAtivo: Icons.event,
    selo: 'P5',
  );

  testWidgets('seção com selo não navega', (tester) async {
    final visitadas = <String>[];
    await tester.pumpWidget(
      montar(
        grupos: {
          'Meu sistema': [disponivel, futura],
        },
        aoSelecionar: visitadas.add,
      ),
    );

    await tester.tap(find.text('Agenda'));
    await tester.pump();
    expect(visitadas, isEmpty, reason: 'Agenda ainda não existe (P5)');

    await tester.tap(find.text('Conversas'));
    await tester.pump();
    expect(visitadas, ['Conversas']);
  });

  testWidgets('o selo aparece ao lado do nome', (tester) async {
    await tester.pumpWidget(
      montar(
        grupos: {
          'Meu sistema': [futura],
        },
        aoSelecionar: (_) {},
      ),
    );

    // a diferença tem que ser visível SEM tentar clicar
    expect(find.text('P5'), findsOneWidget);
  });

  testWidgets('as seções fixas do pé seguem a mesma regra', (tester) async {
    final visitadas = <String>[];
    await tester.pumpWidget(
      montar(
        grupos: {
          'Meu sistema': [disponivel],
        },
        fixos: const [
          Secao(
            nome: 'Configurações',
            icone: Icons.settings_outlined,
            iconeAtivo: Icons.settings,
            selo: 'em breve',
          ),
        ],
        aoSelecionar: visitadas.add,
      ),
    );

    await tester.tap(find.text('Configurações'));
    await tester.pump();
    expect(visitadas, isEmpty);
  });

  testWidgets('grupo sem título não desenha cabeçalho', (tester) async {
    await tester.pumpWidget(
      montar(
        grupos: {
          '': [disponivel],
          'Controle': [
            const Secao(
              nome: 'Aprovações',
              icone: Icons.verified_user_outlined,
              iconeAtivo: Icons.verified_user,
            ),
          ],
        },
        aoSelecionar: (_) {},
      ),
    );

    expect(find.text('CONTROLE'), findsOneWidget);
    expect(find.text('Conversas'), findsOneWidget);
  });
}
