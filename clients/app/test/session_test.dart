import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_api/api.dart';
import 'package:lumbra_app/core/api.dart';
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

/// AuthApi que devolve um par novo sem tocar na rede.
class FakeAuthApi extends AuthApi {
  @override
  Future<TokenPair?> refreshApiV1AuthRefreshPost(
    RefreshRequest refreshRequest,
  ) async => TokenPair(
    accessToken: 'novo-access',
    refreshToken: 'novo-refresh',
    expiresIn: 900,
    tokenType: 'Bearer',
  );
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

  test('refresh troca o par de tokens e persiste', () async {
    final fake = FakeTokenStorage(
      const Session(accessToken: 'velho', refreshToken: 'ref'),
    );
    final container = ProviderContainer(
      overrides: [
        tokenStorageProvider.overrideWithValue(fake),
        authApiProvider.overrideWithValue(FakeAuthApi()),
      ],
    );
    addTearDown(container.dispose);

    await container.read(sessionControllerProvider.future); // build
    await container.read(sessionControllerProvider.notifier).refresh();

    expect(
      container.read(sessionControllerProvider).valueOrNull?.accessToken,
      'novo-access',
    );
    expect((await fake.read())?.accessToken, 'novo-access');
  });

  test('a renovação preserva quem está logado', () async {
    // a renovação não passa pelo formulário de entrada, então o e-mail não
    // vem da resposta: ele tem de ser carregado da sessão anterior. Sem isto
    // o rodapé da barra lateral esvaziava sozinho a cada dez minutos — sinal
    // de sessão perdida quando nada tinha se perdido.
    final fake = FakeTokenStorage(
      const Session(
        accessToken: 'velho',
        refreshToken: 'ref',
        email: 'brendon@exemplo.com',
      ),
    );
    final container = ProviderContainer(
      overrides: [
        tokenStorageProvider.overrideWithValue(fake),
        authApiProvider.overrideWithValue(FakeAuthApi()),
      ],
    );
    addTearDown(container.dispose);

    await container.read(sessionControllerProvider.future);
    await container.read(sessionControllerProvider.notifier).refresh();

    expect(
      container.read(sessionControllerProvider).valueOrNull?.email,
      'brendon@exemplo.com',
    );
    expect((await fake.read())?.email, 'brendon@exemplo.com');
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

  group('renovação depois de um 401 (ADR-068)', () {
    test('seis abas pedindo junto renovam UMA vez', () async {
      // é o cenário real de abrir o app com o token vencido: as seis telas
      // disparam juntas e levam 401 ao mesmo tempo. Sem trava, as cinco
      // renovações perdedoras usariam um refresh token já gasto e o usuário
      // seria deslogado por excesso de zelo.
      final auth = _AuthContando();
      final container = ProviderContainer(
        overrides: [
          tokenStorageProvider.overrideWithValue(
            FakeTokenStorage(const Session(accessToken: 'velho', refreshToken: 'ref')),
          ),
          authApiProvider.overrideWithValue(auth),
        ],
      );
      addTearDown(container.dispose);
      await container.read(sessionControllerProvider.future);

      final ctrl = container.read(sessionControllerProvider.notifier);
      final resultados = await Future.wait(List.generate(6, (_) => ctrl.renovarAgora()));

      expect(resultados, everyElement(isTrue));
      expect(auth.chamadas, 1);
    });

    test('refresh vencido desliga a sessão e diz que não adianta tentar', () async {
      final fake = FakeTokenStorage(
        const Session(accessToken: 'velho', refreshToken: 'tambem-vencido'),
      );
      final container = ProviderContainer(
        overrides: [
          tokenStorageProvider.overrideWithValue(fake),
          authApiProvider.overrideWithValue(_AuthQueRecusa()),
        ],
      );
      addTearDown(container.dispose);
      await container.read(sessionControllerProvider.future);

      final ok = await container.read(sessionControllerProvider.notifier).renovarAgora();

      expect(ok, isFalse);
      // deslogar é a resposta honesta: a tela de login explica o que houve,
      // enquanto "ApiException 401" em seis abas não explicava nada
      expect(container.read(sessionControllerProvider).valueOrNull, isNull);
      expect(await fake.read(), isNull);
    });

    test('sem refresh token guardado, nem tenta a rede', () async {
      final auth = _AuthContando();
      final container = ProviderContainer(
        overrides: [
          tokenStorageProvider.overrideWithValue(
            FakeTokenStorage(const Session(accessToken: 'velho', refreshToken: '')),
          ),
          authApiProvider.overrideWithValue(auth),
        ],
      );
      addTearDown(container.dispose);
      await container.read(sessionControllerProvider.future);

      expect(await container.read(sessionControllerProvider.notifier).renovarAgora(), isFalse);
      expect(auth.chamadas, 0);
    });
  });
}

/// Conta quantas renovações chegaram até a rede.
class _AuthContando extends AuthApi {
  var chamadas = 0;

  @override
  Future<TokenPair?> refreshApiV1AuthRefreshPost(RefreshRequest refreshRequest) async {
    chamadas++;
    // um respiro para que as chamadas concorrentes se sobreponham de verdade
    await Future<void>.delayed(const Duration(milliseconds: 10));
    return TokenPair(
      accessToken: 'novo-access',
      refreshToken: 'novo-refresh',
      expiresIn: 900,
      tokenType: 'Bearer',
    );
  }
}

/// O Nó recusa: o refresh token também venceu (14 dias).
class _AuthQueRecusa extends AuthApi {
  @override
  Future<TokenPair?> refreshApiV1AuthRefreshPost(RefreshRequest refreshRequest) async {
    throw ApiException(401, 'refresh token inválido ou expirado');
  }
}
