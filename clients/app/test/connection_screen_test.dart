import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_app/core/api.dart';
import 'package:lumbra_app/features/system/connection_screen.dart';

void main() {
  testWidgets('mostra "Conectado ao Nó" e a versão quando o Nó responde', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          // sem rede no teste: injeta a resposta do /health
          nodeHealthProvider.overrideWith(
            (ref) async => const {'status': 'ok', 'version': '0.1.0'},
          ),
        ],
        child: const MaterialApp(home: ConnectionScreen()),
      ),
    );
    await tester.pump(); // resolve o future injetado

    expect(find.text('Conectado ao Nó'), findsOneWidget);
    expect(find.textContaining('0.1.0'), findsOneWidget);
  });

  testWidgets('mostra "Nó indisponível" e um botão quando o Nó falha', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          nodeHealthProvider.overrideWith(
            (ref) async => throw Exception('conexão recusada'),
          ),
        ],
        child: const MaterialApp(home: ConnectionScreen()),
      ),
    );
    await tester.pump();

    expect(find.text('Nó indisponível'), findsOneWidget);
    expect(find.text('Tentar de novo'), findsOneWidget);
  });
}
