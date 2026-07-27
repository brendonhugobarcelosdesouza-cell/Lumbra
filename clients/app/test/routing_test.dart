import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_api/api.dart';
import 'package:lumbra_app/core/api.dart';
import 'package:lumbra_app/core/session.dart';
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

  testWidgets('com sessão, a raiz mostra a Home (lista de dispositivos)', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          tokenStorageProvider.overrideWithValue(
            FakeTokenStorage(
              const Session(accessToken: 'abc', refreshToken: 'ref'),
            ),
          ),
          // sem rede: a Home recebe uma lista vazia de dispositivos
          devicesListProvider.overrideWith((ref) async => const <DeviceResponse>[]),
        ],
        child: const LumbraApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Nenhum dispositivo pareado ainda.'), findsOneWidget);
    expect(find.byIcon(Icons.logout), findsOneWidget);
  });
}
