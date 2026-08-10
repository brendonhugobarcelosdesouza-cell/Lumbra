import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_api/api.dart';
import 'package:lumbra_app/core/node_status.dart';
import 'package:lumbra_app/core/session.dart';
import 'package:lumbra_app/features/approvals/approvals_providers.dart';
import 'package:lumbra_app/features/chat/chat_providers.dart';
import 'package:lumbra_app/features/documents/documents_providers.dart';
import 'package:lumbra_app/features/memories/memories_providers.dart';
import 'package:lumbra_app/features/playbooks/playbooks_providers.dart';
import 'package:lumbra_app/main.dart';

import 'session_test.dart';

/// O Nó fora do ar aparecia como um erro DIFERENTE em cada tela — "não foi
/// possível carregar as conversas", "…os procedimentos", "…a memória" — e
/// nenhum deles dizia a verdade. Um problema, uma explicação.

/// Notifier de mentira: devolve o estado que o teste pedir, sem rede.
class NoFixo extends EstadoDoNo {
  NoFixo(this._estado);

  final NodeState _estado;
  var pedidosDeNovaTentativa = 0;

  @override
  NodeState build() => _estado;

  @override
  Future<void> verificarAgora() async => pedidosDeNovaTentativa++;
}

/// [assentar] existe por causa da tela de "verificando": ela mostra um
/// CircularProgressIndicator, que anima PARA SEMPRE — e `pumpAndSettle`
/// espera a árvore parar de animar, então estoura por timeout. Um quadro
/// basta para conferir o que está na tela.
Future<void> _montar(
  WidgetTester tester,
  NodeState estado, {
  NoFixo? no,
  bool assentar = true,
}) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        nodeStateProvider.overrideWith(() => no ?? NoFixo(estado)),
        tokenStorageProvider.overrideWithValue(FakeTokenStorage()),
        conversationsProvider.overrideWith((ref) async => const <ConversationOut>[]),
        pendingApprovalsProvider.overrideWith((ref) async => const <ApprovalOut>[]),
        playbooksProvider.overrideWith((ref) async => const <PlaybookOut>[]),
        memoriesProvider.overrideWith((ref) async => const <MemoryItemOut>[]),
        documentsProvider.overrideWith((ref) async => const <DocumentOut>[]),
      ],
      child: const LumbraApp(),
    ),
  );
  if (assentar) {
    await tester.pumpAndSettle();
  } else {
    await tester.pump();
  }
}

void main() {
  testWidgets('Nó fora do ar: uma explicação, não seis erros', (tester) async {
    await _montar(tester, NodeState.foraDoAr);

    expect(find.text('O Nó não está no ar'), findsOneWidget);
    // nem login nem conversas: sem servidor, nada disso faz sentido
    expect(find.text('Entrar'), findsNothing);
    expect(find.text('Nenhuma conversa ainda.'), findsNothing);
  });

  testWidgets('a tela ensina o comando e deixa copiar', (tester) async {
    await _montar(tester, NodeState.foraDoAr);
    // digitar caminho longo à mão é onde o erro acontece
    expect(find.textContaining('lumbra dev'), findsOneWidget);
    expect(find.byTooltip('Copiar'), findsOneWidget);
  });

  testWidgets('"Tentar de novo" pergunta ao Nó outra vez', (tester) async {
    final no = NoFixo(NodeState.foraDoAr);
    await _montar(tester, NodeState.foraDoAr, no: no);

    await tester.tap(find.widgetWithText(FilledButton, 'Tentar de novo'));
    await tester.pump();
    expect(no.pedidosDeNovaTentativa, 1);
  });

  testWidgets('enquanto verifica, não acusa nada', (tester) async {
    // o susto de "está fora do ar" não pode aparecer antes da resposta
    await _montar(tester, NodeState.verificando, assentar: false);
    expect(find.text('O Nó não está no ar'), findsNothing);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
  });

  testWidgets('com o Nó no ar e sem sessão, cai no login', (tester) async {
    await _montar(tester, NodeState.noAr);
    expect(find.text('Entrar'), findsOneWidget);
    expect(find.text('O Nó não está no ar'), findsNothing);
  });
}
