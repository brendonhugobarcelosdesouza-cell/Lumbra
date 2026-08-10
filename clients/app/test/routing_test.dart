import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_api/api.dart';
import 'package:lumbra_app/core/api.dart';
import 'package:lumbra_app/core/session.dart';
import 'package:lumbra_app/features/approvals/approvals_providers.dart';
import 'package:lumbra_app/features/chat/chat_providers.dart';
import 'package:lumbra_app/features/memories/memories_providers.dart';
import 'package:lumbra_app/features/playbooks/playbooks_providers.dart';
import 'package:lumbra_app/main.dart';

import 'node_status_test.dart';
import 'session_test.dart';

void main() {
  testWidgets('sem sessão, a raiz mostra a tela de login', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          // o Nó vem antes de tudo na raiz do app: sem sobrepor, o teste
          // acabaria na tela de "Nó fora do ar"
          nodeStateProvider.overrideWith(() => NoFixo(NodeState.noAr)),
          tokenStorageProvider.overrideWithValue(FakeTokenStorage()),
        ],
        child: const LumbraApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Entrar'), findsOneWidget);
    expect(find.text('Criar uma conta'), findsOneWidget);
  });

  testWidgets('com sessão, a raiz mostra as conversas', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          nodeStateProvider.overrideWith(() => NoFixo(NodeState.noAr)),
          tokenStorageProvider.overrideWithValue(
            FakeTokenStorage(
              const Session(accessToken: 'abc', refreshToken: 'ref'),
            ),
          ),
          // sem rede: a home recebe uma lista vazia de conversas
          conversationsProvider.overrideWith(
            (ref) async => const <ConversationOut>[],
          ),
          // a casca monta as quatro seções de uma vez (IndexedStack), então
          // todas precisam de dado falso — nenhuma pode ir à rede no teste
          pendingApprovalsProvider.overrideWith(
            (ref) async => const <ApprovalOut>[],
          ),
          playbooksProvider.overrideWith((ref) async => const <PlaybookOut>[]),
          memoriesProvider.overrideWith((ref) async => const <MemoryItemOut>[]),
          devicesListProvider.overrideWith((ref) async => const <DeviceResponse>[]),
        ],
        child: const LumbraApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Nenhuma conversa ainda.'), findsOneWidget);
    expect(find.text('Nova conversa'), findsOneWidget);
  });
}
