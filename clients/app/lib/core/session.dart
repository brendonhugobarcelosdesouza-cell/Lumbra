import 'dart:async';

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
  Timer? _renovacao;

  @override
  Future<Session?> build() async {
    ref.onDispose(() => _renovacao?.cancel());
    final sessao = await _storage.read();
    if (sessao != null) _agendarRenovacao();
    return sessao;
  }

  Future<void> login(String email, String password) async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() async {
      // /token é OAuth2 password grant: a assinatura gerada é (password,
      // username) — username é o e-mail.
      final pair = await _auth.tokenApiV1AuthTokenPost(password, email);
      return _guardar(pair);
    });
    if (state.valueOrNull != null) _agendarRenovacao();
  }

  Future<void> register(String email, String password) async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() async {
      await _auth.registerApiV1AuthRegisterPost(
        RegisterRequest(email: email, password: password),
      );
      final pair = await _auth.tokenApiV1AuthTokenPost(password, email);
      return _guardar(pair);
    });
    if (state.valueOrNull != null) _agendarRenovacao();
  }

  /// Renova o par de tokens com o refresh token. Chamado por timer (proativo,
  /// antes de expirar) e após um 401 (reativo). Se o refresh também expirou
  /// (14 dias), desloga.
  Future<void> refresh() => renovarAgora();

  /// Renova e diz se valeu: `true` quando existe um token novo para tentar de
  /// novo, `false` quando a sessão acabou de verdade (e já foi encerrada).
  ///
  /// Uma renovação por vez. Ao abrir o app com o token vencido, as seis abas
  /// disparam juntas e todas levam 401 ao mesmo tempo; sem esta trava seriam
  /// seis renovações simultâneas, e as cinco perdedoras usariam um refresh
  /// token que a primeira já rodou — o servidor recusaria e nós
  /// deslogaríamos o usuário por excesso de zelo.
  Future<bool> renovarAgora() {
    return _emCurso ??= _renovar().whenComplete(() => _emCurso = null);
  }

  Future<bool>? _emCurso;

  Future<bool> _renovar() async {
    final atual = state.valueOrNull;
    if (atual == null || atual.refreshToken.isEmpty) return false;
    try {
      final pair = await _auth.refreshApiV1AuthRefreshPost(
        RefreshRequest(refreshToken: atual.refreshToken),
      );
      final nova = await _guardar(pair);
      state = AsyncValue.data(nova);
      _agendarRenovacao();
      return true;
    } catch (_) {
      // O refresh também venceu: não há mais como provar quem é o usuário.
      // Deslogar é a resposta honesta — a tela de login diz o que aconteceu,
      // enquanto "ApiException 401" em seis abas não dizia nada.
      await logout();
      return false;
    }
  }

  Future<void> logout() async {
    _renovacao?.cancel();
    _renovacao = null;
    await _storage.clear();
    state = const AsyncValue.data(null);
  }

  Future<Session> _guardar(TokenPair? pair) async {
    if (pair == null) throw Exception('resposta vazia do Nó');
    final session = Session(
      accessToken: pair.accessToken,
      refreshToken: pair.refreshToken,
    );
    await _storage.save(session);
    return session;
  }

  void _agendarRenovacao() {
    // o access token vive ~15 min; renova a cada 10 para ter folga
    _renovacao?.cancel();
    _renovacao = Timer.periodic(const Duration(minutes: 10), (_) => refresh());
  }
}

final sessionControllerProvider =
    AsyncNotifierProvider<SessionController, Session?>(SessionController.new);
