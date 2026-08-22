import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_app/design/tokens.dart';
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
    Map<String, int> selos = const {},
    bool recolhida = false,
  }) {
    return MaterialApp(
      home: Scaffold(
        body: BarraLateral(
          grupos: grupos,
          fixos: fixos,
          selos: selos,
          recolhida: recolhida,
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

  group('recolhida', () {
    // 220px de barra numa janela de 500 deixam 280 para o trabalho. O que
    // a versão recolhida promete é que nada SOME — só o texto sai.

    testWidgets('ocupa 60px e some com os rótulos', (tester) async {
      await tester.pumpWidget(
        montar(
          grupos: {'Meu sistema': [disponivel, futura]},
          aoSelecionar: (_) {},
          recolhida: true,
        ),
      );

      expect(
        tester.getSize(find.byType(BarraLateral)).width,
        Coluna.lateralRecolhida,
      );
      expect(find.text('Conversas'), findsNothing);
      // nem o título do grupo: em 60px ele viraria três letras cortadas
      expect(find.text('MEU SISTEMA'), findsNothing);
    });

    testWidgets('todo destino continua alcançável e nomeado', (tester) async {
      final visitadas = <String>[];
      await tester.pumpWidget(
        montar(
          grupos: {'Meu sistema': [disponivel]},
          aoSelecionar: visitadas.add,
          recolhida: true,
        ),
      );

      // o tooltip É o rótulo quando não há rótulo: sem ele a barra vira
      // oito ícones que só se aprende clicando
      expect(find.byTooltip('Conversas'), findsOneWidget);
      // pelo tooltip e não pelo ícone: 'Conversas' é a seção ATIVA aqui, e
      // ativa ela desenha `iconeAtivo`. Procurar o ícone apagado passaria a
      // testar qual dos dois está na tela, não se o destino abre.
      await tester.tap(find.byTooltip('Conversas'));
      expect(visitadas, ['Conversas']);
    });

    testWidgets('seção futura diz que é futura no tooltip', (tester) async {
      // 'Agenda' e 'Agenda (P5)' são promessas diferentes, e recolhida o
      // selo não tem onde aparecer
      await tester.pumpWidget(
        montar(
          grupos: {'Meu sistema': [futura]},
          aoSelecionar: (_) {},
          recolhida: true,
        ),
      );
      expect(find.byTooltip('Agenda (P5)'), findsOneWidget);
    });

    testWidgets('pedido pendente continua visível', (tester) async {
      // o contador não cabe ao lado do ícone, mas sumir seria pior: pedido
      // que ninguém vê equivale a pedido negado
      const aprovacoes = Secao(
        nome: 'Aprovações',
        icone: Icons.verified_user_outlined,
        iconeAtivo: Icons.verified_user,
      );
      await tester.pumpWidget(
        montar(
          grupos: {'Controle': [aprovacoes]},
          aoSelecionar: (_) {},
          selos: {'Aprovações': 3},
          recolhida: true,
        ),
      );

      // não é o número (não cabe), é o ponto — a forma que já significa
      // "tem coisa aqui" em qualquer barra de tarefas
      expect(find.text('3'), findsNothing);
      final pontos = tester.widgetList<Container>(
        find.descendant(
          of: find.byType(BarraLateral),
          matching: find.byType(Container),
        ),
      ).where((c) {
        final d = c.decoration;
        return d is BoxDecoration && d.shape == BoxShape.circle;
      });
      expect(pontos, isNotEmpty);
    });
  });
}
