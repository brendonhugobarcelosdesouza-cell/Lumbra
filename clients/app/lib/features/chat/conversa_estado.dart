import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../core/api.dart';
import '../../core/session.dart';
import 'chat_models.dart';
import 'chat_providers.dart';
import 'chat_stream.dart';

/// Tudo que uma conversa é, num objeto só.
///
/// Antes isto vivia em sete campos privados de `_ChatScreenState`, mexidos
/// por `setState` espalhado. Funcionava enquanto a conversa era a tela
/// inteira. Deixa de funcionar no instante em que um painel IRMÃO precisa
/// saber qual mensagem está em foco: estado preso dentro de um widget não é
/// legível por ninguém de fora dele.
class EstadoDaConversa {
  const EstadoDaConversa({
    this.bolhas = const [],
    this.parcial,
    this.citacoesParciais = const [],
    this.carregando = true,
    this.erroDeCarga,
    this.titulo,
    this.provedor,
    this.localApenas,
    this.ultimaResposta,
  });

  /// O que já está fixo no histórico.
  final List<ChatBubble> bolhas;

  /// Texto do assistente em construção. `null` quando não há stream.
  final String? parcial;
  final List<CitationOut> citacoesParciais;

  final bool carregando;
  final String? erroDeCarga;
  final String? titulo;

  /// Modelo escolhido para esta conversa (`null` = o padrão do Nó).
  final String? provedor;

  /// `true` em `local_only`, `false` em `allow_cloud`, `null` quando não
  /// sabemos. Os três casos são distintos de propósito: afirmar "Local" por
  /// falta de informação seria a pior mentira desta interface.
  final bool? localApenas;

  /// O que o Nó contou sobre a última resposta: modelo, provedor e custo.
  ///
  /// Vem do evento `done`, que **já carrega `usage`** — o cliente
  /// simplesmente descartava. Não é dado novo: é dado que atravessava o fio
  /// e morria no parser.
  final RespostaConcluida? ultimaResposta;

  /// Derivado, e não um campo: `_enviando` e `_parcial` viviam separados e
  /// eram sempre ligados/desligados juntos. Dois campos que precisam
  /// concordar são um campo e um bug esperando acontecer.
  bool get enviando => parcial != null;

  /// As bolhas com a resposta viva no fim — o que a tela realmente desenha.
  List<ChatBubble> get visiveis => [
    ...bolhas,
    if (parcial != null)
      ChatBubble(
        BubbleRole.assistant,
        parcial!.isEmpty ? '…' : parcial!,
        citations: citacoesParciais,
      ),
  ];

  EstadoDaConversa com({
    List<ChatBubble>? bolhas,
    String? parcial,
    bool limparParcial = false,
    List<CitationOut>? citacoesParciais,
    bool? carregando,
    String? erroDeCarga,
    String? titulo,
    String? provedor,
    bool? localApenas,
    RespostaConcluida? ultimaResposta,
  }) {
    return EstadoDaConversa(
      bolhas: bolhas ?? this.bolhas,
      // `null` em Dart não distingue "não mexa" de "apague", e apagar o
      // parcial é o fim de todo stream. Daí a bandeira explícita.
      parcial: limparParcial ? null : (parcial ?? this.parcial),
      citacoesParciais: citacoesParciais ?? this.citacoesParciais,
      carregando: carregando ?? this.carregando,
      erroDeCarga: erroDeCarga ?? this.erroDeCarga,
      titulo: titulo ?? this.titulo,
      provedor: provedor ?? this.provedor,
      localApenas: localApenas ?? this.localApenas,
      ultimaResposta: ultimaResposta ?? this.ultimaResposta,
    );
  }
}

/// O que o Nó informou ao concluir uma resposta.
class RespostaConcluida {
  const RespostaConcluida({
    required this.messageId,
    required this.provider,
    required this.model,
    this.tokensIn,
    this.tokensOut,
    this.duracao,
  });

  final String messageId;
  final String provider;
  final String model;
  final int? tokensIn;
  final int? tokensOut;

  /// Medida no cliente: o Nó não devolve latência. Só existe para a resposta
  /// que ACABOU de chegar — no histórico não há como saber, e inventar um
  /// número ali seria pior que não mostrar nada.
  final Duration? duracao;
}

/// A assinatura do leitor de stream, para poder ser trocada no teste.
///
/// Sem isto, testar a tela exigiria subir um servidor SSE de mentira. O
/// caminho do stream é o mais frágil do app — é onde mora a renovação de
/// token no meio da resposta — e era justamente o único sem cobertura no
/// nível da tela.
typedef LeitorDeStream =
    Stream<ChatStreamEvent> Function({
      required String baseUrl,
      required String? token,
      required String conversationId,
      required String content,
    });

final leitorDeStreamProvider = Provider<LeitorDeStream>((_) => streamChat);

final conversaProvider = NotifierProvider.autoDispose
    .family<ControladorDaConversa, EstadoDaConversa, String>(
      ControladorDaConversa.new,
    );

/// Conduz uma conversa: carrega o histórico, envia, recebe token a token,
/// renova a sessão quando o token vence no meio, e para quando pedirem.
class ControladorDaConversa
    extends AutoDisposeFamilyNotifier<EstadoDaConversa, String> {
  StreamSubscription<ChatStreamEvent>? _sub;
  String? _ultimoTexto;
  bool _tentouRenovar = false;
  KeepAliveLink? _preso;
  Stopwatch? _cronometro;

  String get _conversa => arg;

  @override
  EstadoDaConversa build(String arg) {
    ref.onDispose(() {
      _sub?.cancel();
      _sub = null;
    });
    unawaited(_carregarHistorico());
    return const EstadoDaConversa();
  }

  Future<void> _carregarHistorico() async {
    try {
      final api = ref.read(chatApiProvider);
      final hist = await api
          .historyApiV1ChatConversationsConversationIdMessagesGet(_conversa);
      state = state.com(
        bolhas: (hist?.messages ?? const []).map(ChatBubble.fromMessage).toList(),
        carregando: false,
      );
    } catch (e) {
      state = state.com(carregando: false, erroDeCarga: '$e');
    }
  }

  /// Adota o que a LISTA já sabia: título e política de modelo.
  ///
  /// Sem sobrescrever o que a conversa já descobriu por si — a lista é uma
  /// fonte mais velha que o histórico e que a escolha do usuário.
  void adotarDaLista({String? titulo, String? provedor, bool? localApenas}) {
    state = state.com(
      titulo: state.titulo ?? titulo,
      provedor: state.provedor ?? provedor,
      localApenas: state.localApenas ?? localApenas,
    );
  }

  void enviar(String bruto) {
    final texto = bruto.trim();
    if (texto.isEmpty || state.enviando) return;
    _ultimoTexto = texto;
    _tentouRenovar = false;
    state = state.com(
      bolhas: [...state.bolhas, ChatBubble.user(texto)],
      // conversa nova ganha título já na primeira pergunta, como o Nó faz no
      // servidor (_title_from) — o cabeçalho deixa de dizer "Conversa".
      titulo: state.titulo ?? _tituloDe(texto),
    );
    _abrirStream(texto);
  }

  void _abrirStream(String texto) {
    // enquanto gera, a conversa não pode ser coletada: trocar de seção no
    // meio de uma resposta jogaria fora o que já chegou, e o Nó seguiria
    // gerando para ninguém
    _preso ??= ref.keepAlive();
    _cronometro = Stopwatch()..start();
    final token = ref.read(sessionControllerProvider).valueOrNull?.accessToken;
    state = state.com(parcial: '', citacoesParciais: const []);
    _sub = ref
        .read(leitorDeStreamProvider)(
          baseUrl: noBaseUrl,
          token: token,
          conversationId: _conversa,
          content: texto,
        )
        .listen(
          _aoEvento,
          onError: (Object e) => state = _fechado(
            bolhas: [...state.bolhas, ChatBubble.error('Falha ao responder: $e')],
          ),
          onDone: () {
            if (state.parcial != null) state = _fixarParcial();
          },
        );
  }

  void _aoEvento(ChatStreamEvent ev) {
    // token venceu no meio da resposta: renova e re-tenta a última mensagem
    // UMA vez, sem incomodar quem está escrevendo
    if (ev is StreamErrorEvent &&
        ev.detail.contains('401') &&
        !_tentouRenovar &&
        _ultimoTexto != null) {
      _tentouRenovar = true;
      state = _fechado();
      unawaited(_renovarERetentar());
      return;
    }

    switch (ev) {
      case TokenEvent():
        state = state.com(parcial: (state.parcial ?? '') + ev.delta);
      case SourcesEvent():
        state = state.com(citacoesParciais: ev.citations);
      case DoneEvent():
        state = _fixarParcial(
          concluida: RespostaConcluida(
            messageId: ev.messageId,
            provider: ev.provider,
            model: ev.model,
            tokensIn: ev.tokensIn,
            tokensOut: ev.tokensOut,
            duracao: _cronometro?.elapsed,
          ),
        );
      case CancelledEvent():
        state = _fixarParcial();
      case StreamErrorEvent():
        state = _fechado(
          bolhas: [...state.bolhas, ChatBubble.error(ev.detail)],
        );
    }
  }

  Future<void> _renovarERetentar() async {
    await ref.read(sessionControllerProvider.notifier).renovarAgora();
    final texto = _ultimoTexto;
    if (texto != null) _abrirStream(texto);
  }

  /// Fixa o texto acumulado como bolha definitiva e encerra o stream.
  EstadoDaConversa _fixarParcial({RespostaConcluida? concluida}) {
    final texto = state.parcial;
    final bolhas = (texto != null && texto.isNotEmpty)
        ? [
            ...state.bolhas,
            ChatBubble(
              BubbleRole.assistant,
              texto,
              citations: state.citacoesParciais,
            ),
          ]
        : state.bolhas;
    return _fechado(bolhas: bolhas, concluida: concluida);
  }

  /// Encerra o stream e devolve o estado sem nada em voo.
  EstadoDaConversa _fechado({
    List<ChatBubble>? bolhas,
    RespostaConcluida? concluida,
  }) {
    _sub?.cancel();
    _sub = null;
    _cronometro?.stop();
    _preso?.close();
    _preso = null;
    return state.com(
      bolhas: bolhas,
      limparParcial: true,
      citacoesParciais: const [],
      ultimaResposta: concluida,
    );
  }

  /// Interrompe a geração guardando o que já chegou. Fechar a conexão faz o
  /// Nó perceber a desconexão e soltar a GPU.
  void parar() {
    if (!state.enviando) return;
    state = _fixarParcial();
  }

  /// Troca o modelo desta conversa. Local não sai da máquina; nuvem exige
  /// optar por `allow_cloud` — privacidade é escolha explícita (docs/24).
  Future<void> escolherProvedor(ProviderChoice escolha) async {
    await ref
        .read(chatApiProvider)
        .setPolicyApiV1ChatConversationsConversationIdPolicyPatch(
          _conversa,
          PolicyBody(
            privacy: escolha.isLocal ? 'local_only' : 'allow_cloud',
            provider: escolha.name,
          ),
        );
    state = state.com(provedor: escolha.name, localApenas: escolha.isLocal);
  }

  /// Espelha o `_title_from` do Nó: espaços colapsados, 60 caracteres.
  static String _tituloDe(String texto) {
    final limpo = texto.trim().replaceAll(RegExp(r'\s+'), ' ');
    return limpo.length > 60 ? '${limpo.substring(0, 60)}…' : limpo;
  }
}
