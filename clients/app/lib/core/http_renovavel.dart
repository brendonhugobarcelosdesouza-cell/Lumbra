// O cliente gerado é uma biblioteca `part of`: dentro dela os tipos do http
// são visíveis, mas ela não os reexporta. Quem estende o ApiClient de fora
// precisa importá-los por conta própria.
import 'package:http/http.dart' show MultipartFile, MultipartRequest, Response;
import 'package:lumbra_api/api.dart';

/// Cliente HTTP que renova o token quando o Nó responde 401 (ADR-068).
///
/// Encontrado usando o app: depois de alguns dias fechado, a Lumbra abria
/// direto na tela principal e TODAS as abas mostravam
/// `ApiException 401: token inválido ou expirado`. Nenhuma parte do sistema
/// estava errada isoladamente — o token guardado existia, o Nó fazia certo
/// em recusá-lo, cada tela reportava fielmente o erro que recebeu. O que
/// faltava era alguém responsável por notar que "expirado" tem conserto.
///
/// O conserto mora AQUI, e não nas telas, por uma razão: token expirado não é
/// assunto de "conversas" nem de "documentos". Se cada tela tratasse o 401, o
/// mesmo remendo apareceria seis vezes e a sétima tela nasceria sem ele.
/// Como o cliente gerado é a única porta do app para o Core (docs/24, Regra
/// 1), a porta é o único lugar que vê todas as requisições.
///
/// O token é lido a cada chamada, e não fixado na construção: entre criar o
/// cliente e usá-lo pode ter havido uma renovação, e um cliente que carrega
/// uma cópia velha do token mandaria a credencial errada com toda a
/// convicção do mundo.
class ClienteRenovavel extends ApiClient {
  ClienteRenovavel({
    required super.basePath,
    required this.tokenAtual,
    required this.renovar,
  });

  /// O token de agora — chamado no momento do envio, nunca antes.
  final String? Function() tokenAtual;

  /// Tenta renovar a sessão. `true` se agora há um token novo para tentar.
  /// Devolver `false` significa "não há o que fazer": quem chamou deve
  /// entregar o 401 ao usuário, e a sessão já terá sido encerrada.
  final Future<bool> Function() renovar;

  @override
  Future<Response> invokeAPI(
    String path,
    String method,
    List<QueryParam> queryParams,
    Object? body,
    Map<String, String> headerParams,
    Map<String, String> formParams,
    String? contentType,
  ) async {
    Future<Response> enviar() {
      final token = tokenAtual();
      if (token != null) headerParams['Authorization'] = 'Bearer $token';
      return super.invokeAPI(
        path,
        method,
        queryParams,
        body,
        headerParams,
        formParams,
        contentType,
      );
    }

    final resposta = await enviar();
    if (resposta.statusCode != 401) return resposta;

    // Um corpo que já foi consumido não pode ser reenviado: um upload é um
    // fluxo de bytes lido uma vez só. Preferimos devolver o 401 honesto a
    // reenviar um arquivo vazio e gravar meio documento no acervo.
    if (body is MultipartFile || body is MultipartRequest) return resposta;

    if (!await renovar()) return resposta;
    return enviar();
  }
}
