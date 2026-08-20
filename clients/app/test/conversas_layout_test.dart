import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_api/api.dart';
import 'package:lumbra_app/design/tokens.dart';
import 'package:lumbra_app/features/chat/chat_providers.dart';
import 'package:lumbra_app/features/chat/conversations_screen.dart';

/// A seção Conversas muda de forma com a largura, e essa é a regra que o R1
/// introduziu. Ela precisa de teste porque o sintoma de errá-la é sutil: no
/// estreito, mostrar as duas colunas não quebra nada — só espreme a conversa
/// a ponto de a leitura ficar ruim, e ninguém abre um chamado por isso.
///
/// Os testes fixam a largura explicitamente. A janela padrão do
/// `flutter_test` tem 800px, e depender dela seria testar um acidente.
///
/// A medida é o espaço DA SEÇÃO, não o da janela: a seção vive dentro da
/// moldura e recebe a janela menos a barra lateral. Comparar com a largura da
/// janela fazia uma tela de 1263px cair no desenho estreito — o app mostrava
/// uma coluna onde cabiam duas, e nenhum teste acusava porque o teste também
/// media a coisa errada.

/// Só o que a coluna precisa. O histórico devolve vazio porque abrir a
/// conversa é parte do teste de LAYOUT — se ele fosse à rede de verdade, o
/// teste passaria a medir a rede.
class _ChatApiComConversas extends ChatApi {
  @override
  Future<HistoryResponse?> historyApiV1ChatConversationsConversationIdMessagesGet(
    String conversationId, {
    int? limit,
  }) async => HistoryResponse(messages: []);

  @override
  Future<ConversationsOut?> listConversationsApiV1ChatConversationsGet({
    int? limit,
  }) async => ConversationsOut(
        conversations: [
          ConversationOut(
            id: 'c1',
            userId: 'u1',
            createdAt: DateTime.now().toIso8601String(),
            lastMessageAt: DateTime.now().toIso8601String(),
            title: 'Plano financeiro',
          ),
        ],
      );
}

class _ChatApiSemConversas extends ChatApi {
  @override
  Future<ConversationsOut?> listConversationsApiV1ChatConversationsGet({
    int? limit,
  }) async => ConversationsOut(conversations: []);
}

Future<void> _montar(
  WidgetTester tester, {
  required double largura,
  ChatApi? api,
}) async {
  tester.view.physicalSize = Size(largura, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);

  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        chatApiProvider.overrideWithValue(api ?? _ChatApiComConversas()),
      ],
      child: const MaterialApp(home: Scaffold(body: ConversationsScreen())),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('no largo, a lista e o painel convivem', (tester) async {
    await _montar(tester, largura: Coluna.cabeAColecao + 200);

    expect(find.text('Conversas'), findsOneWidget);
    expect(find.text('Plano financeiro'), findsOneWidget);
    // nada aberta ainda: o meio convida em vez de ficar em branco
    expect(find.text('Escolha uma conversa ou comece outra.'), findsOneWidget);
    // e não há botão de voltar: não há para onde voltar quando tudo está à
    // vista — botão que não faz sentido é pior que botão ausente
    expect(find.byTooltip('Voltar às conversas'), findsNothing);
  });

  testWidgets('no estreito, abrir a conversa substitui a lista', (tester) async {
    await _montar(tester, largura: Coluna.cabeAColecao - 200);

    expect(find.text('Plano financeiro'), findsOneWidget);
    expect(find.text('Escolha uma conversa ou comece outra.'), findsNothing);

    await tester.tap(find.text('Plano financeiro'));
    await tester.pumpAndSettle();

    // a lista cedeu o lugar, e existe o caminho de volta
    expect(find.text('Conversas'), findsNothing);
    expect(find.byTooltip('Voltar às conversas'), findsOneWidget);

    await tester.tap(find.byTooltip('Voltar às conversas'));
    await tester.pumpAndSettle();
    expect(find.text('Conversas'), findsOneWidget);
  });

  testWidgets('no largo, abrir a conversa NÃO esconde a lista', (tester) async {
    await _montar(tester, largura: Coluna.cabeAColecao + 200);

    await tester.tap(find.text('Plano financeiro'));
    await tester.pumpAndSettle();

    // a diferença que justifica o layout: trocar de conversa segue a um
    // clique de distância, sem desfazer nada antes
    expect(find.text('Conversas'), findsOneWidget);
    expect(find.byTooltip('Voltar às conversas'), findsNothing);
  });

  testWidgets('com espaço de sobra, o contexto entra como terceira coluna', (
    tester,
  ) async {
    // mesma classe de regra que eu já errei uma vez comparando a largura da
    // JANELA com o espaço da SEÇÃO. Aqui ela fica presa por teste.
    await _montar(tester, largura: Coluna.cabeOContexto + 100);
    await tester.tap(find.text('Plano financeiro'));
    await tester.pumpAndSettle();

    expect(find.text('Contexto'), findsOneWidget);
  });

  testWidgets('sem espaço, o contexto não espreme a conversa', (tester) async {
    // ele explica a resposta; não pode roubar a largura da resposta que
    // explica. Um pixel abaixo do limite ele fica de fora.
    await _montar(tester, largura: Coluna.cabeOContexto - 1);
    await tester.tap(find.text('Plano financeiro'));
    await tester.pumpAndSettle();

    expect(find.text('Contexto'), findsNothing);
    // e o botão que o chamaria continua na tela, para não sumir sem aviso
    expect(find.byTooltip('Ocultar o contexto'), findsOneWidget);
  });

  testWidgets('fechar o contexto devolve a largura à conversa', (tester) async {
    await _montar(tester, largura: Coluna.cabeOContexto + 100);
    await tester.tap(find.text('Plano financeiro'));
    await tester.pumpAndSettle();
    expect(find.text('Contexto'), findsOneWidget);

    await tester.tap(find.byTooltip('Fechar o contexto'));
    await tester.pumpAndSettle();
    expect(find.text('Contexto'), findsNothing);
    expect(find.byTooltip('Mostrar de onde veio a resposta'), findsOneWidget);
  });

  testWidgets('sem conversa nenhuma, diz isso e oferece começar', (
    tester,
  ) async {
    await _montar(
      tester,
      largura: Coluna.cabeAColecao + 200,
      api: _ChatApiSemConversas(),
    );

    expect(find.text('Nenhuma conversa ainda.'), findsOneWidget);
    expect(find.byTooltip('Nova conversa'), findsOneWidget);
  });
}
