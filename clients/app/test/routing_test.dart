import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_api/api.dart';
import 'package:lumbra_app/core/session.dart';
import 'package:lumbra_app/features/chat/chat_providers.dart';
import 'package:lumbra_app/main.dart';

import 'session_test.dart';

void main() {
  testWidgets('sem sessão, a raiz mostra a tela de login', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
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
          tokenStorageProvider.overrideWithValue(
            FakeTokenStorage(
              const Session(accessToken: 'abc', refreshToken: 'ref'),
            ),
          ),
          // sem rede: a home recebe uma lista vazia de conversas
          conversationsProvider.overrideWith(
            (ref) async => const <ConversationOut>[],
          ),
        ],
        child: const LumbraApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Nenhuma conversa ainda.'), findsOneWidget);
    expect(find.text('Nova conversa'), findsOneWidget);
  });
}
