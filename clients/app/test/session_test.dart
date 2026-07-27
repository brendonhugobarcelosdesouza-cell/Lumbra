import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_app/core/session.dart';

/// Armazenamento de token em memória — sem plugins nativos nos testes.
class FakeTokenStorage implements TokenStorage {
  FakeTokenStorage([this._session]);
  Session? _session;

  @override
  Future<Session?> read() async => _session;

  @override
  Future<void> save(Session session) async => _session = session;

  @override
  Future<void> clear() async => _session = null;
}

void main() {
  test('carrega a sessão do armazenamento no start', () async {
    final fake = FakeTokenStorage(
      const Session(accessToken: 'abc', refreshToken: 'ref'),
    );
    final container = ProviderContainer(
      overrides: [tokenStorageProvider.overrideWithValue(fake)],
    );
    addTearDown(container.dispose);

    final sessao = await container.read(sessionControllerProvider.future);
    expect(sessao, isNotNull);
    expect(sessao!.accessToken, 'abc');
  });

  test('sem token guardado, a sessão nasce nula (pede login)', () async {
    final container = ProviderContainer(
      overrides: [tokenStorageProvider.overrideWithValue(FakeTokenStorage())],
    );
    addTearDown(container.dispose);

    expect(await container.read(sessionControllerProvider.future), isNull);
  });

  test('logout limpa o armazenamento e zera a sessão', () async {
    final fake = FakeTokenStorage(
      const Session(accessToken: 'abc', refreshToken: 'ref'),
    );
    final container = ProviderContainer(
      overrides: [tokenStorageProvider.overrideWithValue(fake)],
    );
    addTearDown(container.dispose);

    await container.read(sessionControllerProvider.future); // garante o build
    await container.read(sessionControllerProvider.notifier).logout();

    expect(container.read(sessionControllerProvider).valueOrNull, isNull);
    expect(await fake.read(), isNull);
  });
}
