import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:lumbra_api/api.dart';

import 'api.dart';

/// Sessão autenticada: os tokens que provam a identidade do usuário ao Nó.
/// O `refreshToken` é guardado para renovação futura (o access expira em
/// minutos); a renovação automática entra num incremento posterior.
class Session {
  const Session({required this.accessToken, required this.refreshToken});

  final String accessToken;
  final String refreshToken;
}

/// Onde o token descansa. Abstração para (a) usar os cofres do SO em
/// produção e (b) injetar um fake nos testes, sem tocar em plugins nativos.
abstract class TokenStorage {
  Future<Session?> read();
  Future<void> save(Session session);
  Future<void> clear();
}

/// Guarda no cofre seguro do SO (flutter_secure_storage): Keychain no macOS/
/// iOS, Credential Manager no Windows, libsecret no Linux. Nunca em disco
/// plano.
class SecureTokenStorage implements TokenStorage {
  SecureTokenStorage([FlutterSecureStorage? storage])
    : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;
  static const _kAccess = 'lumbra.access_token';
  static const _kRefresh = 'lumbra.refresh_token';

  @override
  Future<Session?> read() async {
    final access = await _storage.read(key: _kAccess);
    if (access == null) return null;
    final refresh = await _storage.read(key: _kRefresh) ?? '';
    return Session(accessToken: access, refreshToken: refresh);
  }

  @override
  Future<void> save(Session session) async {
    await _storage.write(key: _kAccess, value: session.accessToken);
    await _storage.write(key: _kRefresh, value: session.refreshToken);
  }

  @override
  Future<void> clear() async {
    await _storage.delete(key: _kAccess);
    await _storage.delete(key: _kRefresh);
  }
}

final tokenStorageProvider = Provider<TokenStorage>(
  (ref) => SecureTokenStorage(),
);

/// Controla a sessão: carrega o token guardado no start, entra, registra e
/// sai. O estado (`AsyncValue<Session?>`) é a fonte única do "estou logado?"
/// — a raiz do app decide entre login e tela principal a partir dele.
class SessionController extends AsyncNotifier<Session?> {
  TokenStorage get _storage => ref.read(tokenStorageProvider);
  AuthApi get _auth => ref.read(authApiProvider);

  @override
  Future<Session?> build() => _storage.read();

  Future<void> login(String email, String password) async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() async {
      // /token é OAuth2 password grant: a assinatura gerada é (password,
      // username) — username é o e-mail.
      final pair = await _auth.tokenApiV1AuthTokenPost(password, email);
      if (pair == null) throw Exception('resposta vazia do Nó');
      final session = Session(
        accessToken: pair.accessToken,
        refreshToken: pair.refreshToken,
      );
      await _storage.save(session);
      return session;
    });
  }

  Future<void> register(String email, String password) async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() async {
      await _auth.registerApiV1AuthRegisterPost(
        RegisterRequest(email: email, password: password),
      );
      final pair = await _auth.tokenApiV1AuthTokenPost(password, email);
      if (pair == null) throw Exception('resposta vazia do Nó');
      final session = Session(
        accessToken: pair.accessToken,
        refreshToken: pair.refreshToken,
      );
      await _storage.save(session);
      return session;
    });
  }

  Future<void> logout() async {
    await _storage.clear();
    state = const AsyncValue.data(null);
  }
}

final sessionControllerProvider =
    AsyncNotifierProvider<SessionController, Session?>(SessionController.new);
