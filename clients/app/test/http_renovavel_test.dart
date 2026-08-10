import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:lumbra_app/core/http_renovavel.dart';

/// Token expirado tem conserto (ADR-068).
///
/// Encontrado usando o app: depois de dias fechado, a Lumbra abria na tela
/// principal e as seis abas mostravam `ApiException 401`. O teste que faltava
/// não era de tela — era deste degrau, que ninguém tinha.

/// Um Nó de mentira que recusa qualquer token fora da lista de válidos.
class _NoFalso {
  _NoFalso({required this.aceita});

  /// Tokens que este Nó considera bons. Trocar a lista simula uma renovação
  /// do lado do servidor.
  Set<String> aceita;
  final recebidos = <String?>[];

  http.Client get cliente => MockClient((req) async {
    final auth = req.headers['Authorization'];
    recebidos.add(auth);
    final token = auth?.replaceFirst('Bearer ', '');
    if (token == null || !aceita.contains(token)) {
      return http.Response('{"detail":"token inválido ou expirado"}', 401);
    }
    return http.Response('{"ok":true}', 200);
  });
}

ClienteRenovavel _montar(
  _NoFalso no, {
  required String? Function() token,
  required Future<bool> Function() renovar,
}) {
  return ClienteRenovavel(
    basePath: 'http://nó.falso',
    tokenAtual: token,
    renovar: renovar,
  )..client = no.cliente;
}

Future<http.Response> _chamar(ClienteRenovavel c, {Object? corpo}) {
  return c.invokeAPI('/api/v1/x', 'GET', [], corpo, <String, String>{}, {}, null);
}

void main() {
  test('401 vira renovação e a chamada é refeita com o token novo', () async {
    final no = _NoFalso(aceita: {'novo'});
    var token = 'velho';
    var renovacoes = 0;

    final cliente = _montar(
      no,
      token: () => token,
      renovar: () async {
        renovacoes++;
        token = 'novo';
        return true;
      },
    );

    final r = await _chamar(cliente);

    expect(r.statusCode, 200, reason: 'a segunda tentativa devia passar');
    expect(renovacoes, 1);
    // o essencial: a repetição levou o token NOVO. Um cliente que fixasse a
    // credencial na construção mandaria "velho" de novo, com toda a convicção
    expect(no.recebidos, ['Bearer velho', 'Bearer novo']);
  });

  test('renovação que falha devolve o 401 — sem insistir', () async {
    final no = _NoFalso(aceita: {'jamais'});
    final cliente = _montar(no, token: () => 'velho', renovar: () async => false);

    final r = await _chamar(cliente);

    expect(r.statusCode, 401);
    // uma tentativa só: insistir com a mesma credencial recusada é o começo
    // de um laço infinito contra o Nó
    expect(no.recebidos, hasLength(1));
  });

  test('resposta boa não chama renovação nenhuma', () async {
    final no = _NoFalso(aceita: {'bom'});
    var renovacoes = 0;
    final cliente = _montar(
      no,
      token: () => 'bom',
      renovar: () async {
        renovacoes++;
        return true;
      },
    );

    expect((await _chamar(cliente)).statusCode, 200);
    expect(renovacoes, 0);
  });

  test('sem sessão, o 401 passa direto (é a resposta certa)', () async {
    final no = _NoFalso(aceita: {'bom'});
    final cliente = _montar(no, token: () => null, renovar: () async => false);

    expect((await _chamar(cliente)).statusCode, 401);
    expect(no.recebidos, [null]);
  });

  test('upload não é repetido: o corpo já foi lido uma vez', () async {
    final no = _NoFalso(aceita: {'novo'});
    var renovacoes = 0;
    final cliente = _montar(
      no,
      token: () => 'velho',
      renovar: () async {
        renovacoes++;
        return true;
      },
    );

    final arquivo = http.MultipartFile.fromString('file', 'conteúdo');
    final r = await _chamar(cliente, corpo: arquivo);

    expect(r.statusCode, 401);
    // reenviar um fluxo já consumido gravaria meio documento no acervo:
    // preferimos o 401 honesto
    expect(renovacoes, 0);
  });
}
