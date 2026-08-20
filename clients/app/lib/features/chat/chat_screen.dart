import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../design/tokens.dart';
import 'chat_providers.dart';
import 'composer.dart';
import 'conversa_estado.dart';
import 'mensagens.dart';
import 'painel_de_contexto.dart';

/// A conversa: histórico + envio com streaming (P2-c.2). A resposta aparece
/// token a token; as fontes chegam antes do texto e viram chips clicáveis.
///
/// A tela não conduz mais a conversa — quem conduz é o
/// [ControladorDaConversa]. Aqui só se desenha o que ele diz e se avisa o que
/// o usuário fez. A troca não foi estética: enquanto o estado morava neste
/// widget, nenhum painel irmão conseguia saber qual mensagem estava em foco,
/// e o painel de contexto da referência depende exatamente disso.
class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({
    super.key,
    required this.conversationId,
    this.aberta,
    this.aoVoltar,
  });

  final String conversationId;

  /// O que a lista já sabia sobre esta conversa: título e política de modelo.
  /// Chega antes do histórico e evita o cabeçalho piscar de "Conversa" para o
  /// título de verdade.
  final ConversaAberta? aberta;

  /// Só existe na largura estreita, onde a lista de conversas cede o lugar
  /// para a conversa. No desktop as duas convivem e voltar não quer dizer
  /// nada — daí ser opcional em vez de um botão sempre presente e às vezes
  /// inútil.
  final VoidCallback? aoVoltar;

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final _campo = TextEditingController();
  final _scroll = ScrollController();

  ControladorDaConversa get _controlador =>
      ref.read(conversaProvider(widget.conversationId).notifier);

  @override
  void initState() {
    super.initState();
    // fora do build: mexer em provider durante a construção do widget é o
    // caminho conhecido para reconstruções em cascata
    final aberta = widget.aberta;
    WidgetsBinding.instance.addPostFrameCallback(
      (_) => _controlador.adotarDaLista(
        titulo: aberta?.titulo,
        provedor: aberta?.provedor,
        localApenas: aberta?.localApenas,
      ),
    );
  }

  @override
  void dispose() {
    _campo.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _enviar() {
    final texto = _campo.text;
    if (texto.trim().isEmpty) return;
    _campo.clear();
    _controlador.enviar(texto);
  }

  void _rolarAoFim() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.jumpTo(_scroll.position.maxScrollExtent);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final conversa = conversaProvider(widget.conversationId);
    // `listen` e não uma chamada solta no build: rolar ao fim é reação a
    // CHEGAR conteúdo novo, não a redesenhar. Chamado no build, um simples
    // redimensionar a janela arrancaria o usuário de volta para baixo no meio
    // de uma leitura.
    ref.listen(conversa, (_, __) => _rolarAoFim());
    final estado = ref.watch(conversa);

    // sem Scaffold: a conversa deixou de ser uma TELA e virou o painel do
    // meio da moldura. Um Scaffold aqui traria uma segunda barra de topo por
    // cima da barra lateral, que e exatamente o empilhamento que o R1 veio
    // desfazer.
    return Column(
      children: [
        _Cabecalho(
          estado: estado,
          aoVoltar: widget.aoVoltar,
          aoTrocarModelo: _escolherProvedor,
          contextoAberto: ref.watch(painelDeContextoProvider),
          aoAlternarContexto: () {
            final aberto = ref.read(painelDeContextoProvider.notifier);
            aberto.state = !aberto.state;
          },
        ),
        Divider(height: 1, color: Theme.of(context).colorScheme.outlineVariant),
        Expanded(child: _corpo(estado)),
        Composer(
          controlador: _campo,
          enviando: estado.enviando,
          aoEnviar: _enviar,
          aoParar: _controlador.parar,
        ),
      ],
    );
  }

  Widget _corpo(EstadoDaConversa estado) {
    if (estado.carregando) {
      return const Center(child: CircularProgressIndicator());
    }
    if (estado.erroDeCarga != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(Espaco.grande),
          child: Text(
            'Não foi possível carregar a conversa.\n${estado.erroDeCarga}',
          ),
        ),
      );
    }
    final vivas = estado.visiveis;
    if (vivas.isEmpty) {
      return const Center(child: Text('Faça a primeira pergunta.'));
    }
    return ListView.builder(
      controller: _scroll,
      padding: const EdgeInsets.fromLTRB(
        Espaco.grande,
        Espaco.curto,
        Espaco.grande,
        Espaco.grande,
      ),
      itemCount: vivas.length,
      itemBuilder: (_, i) => MensagemDaConversa(vivas[i]),
    );
  }

  Future<void> _escolherProvedor() async {
    List<ProviderChoice> escolhas;
    try {
      escolhas = await ref.read(providersProvider.future);
    } catch (e) {
      _avisar('Não foi possível listar modelos: $e');
      return;
    }
    if (!mounted) return;
    final escolhido = await showDialog<ProviderChoice>(
      context: context,
      builder: (_) => SimpleDialog(
        title: const Text('Escolher modelo'),
        children: [
          for (final p in escolhas)
            SimpleDialogOption(
              onPressed: () => Navigator.pop(context, p),
              child: ListTile(
                contentPadding: EdgeInsets.zero,
                leading: Icon(p.isLocal ? Icons.computer : Icons.cloud),
                title: Text(p.name),
                subtitle: Text(
                  '${p.model} · ${p.isLocal ? "local, sem custo" : "nuvem"}',
                ),
              ),
            ),
        ],
      ),
    );
    if (escolhido == null) return;
    try {
      await _controlador.escolherProvedor(escolhido);
      _avisar(
        'Modelo: ${escolhido.name} (${escolhido.isLocal ? "local" : "nuvem"})',
      );
    } catch (e) {
      _avisar('Falha ao trocar de modelo: $e');
    }
  }

  void _avisar(String recado) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(recado)));
  }
}

/// O topo da conversa: onde se está e com que modelo se está falando.
///
/// O seletor de modelo diz o NOME e a PROCEDÊNCIA juntos. Numa plataforma
/// cujo argumento é que os dados não saem do computador, saber se a pergunta
/// vai para a máquina ou para a nuvem não é detalhe técnico — é a informação
/// que decide o que se pode perguntar.
///
/// Quando não sabemos, não dizemos. O selo tem três estados e não dois:
/// Local, Nuvem, e ausente. Mostrar "Local" por falta de informação seria a
/// mentira mais cara que esta tela poderia contar.
class _Cabecalho extends StatelessWidget {
  const _Cabecalho({
    required this.estado,
    required this.aoVoltar,
    required this.aoTrocarModelo,
    required this.contextoAberto,
    required this.aoAlternarContexto,
  });

  final EstadoDaConversa estado;
  final VoidCallback? aoVoltar;
  final VoidCallback aoTrocarModelo;
  final bool contextoAberto;
  final VoidCallback aoAlternarContexto;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(
        Espaco.curto,
        Espaco.medio,
        Espaco.largo,
        Espaco.medio,
      ),
      child: Row(
        children: [
          if (aoVoltar != null)
            IconButton(
              tooltip: 'Voltar às conversas',
              onPressed: aoVoltar,
              icon: const Icon(Icons.arrow_back, size: 20),
            )
          else
            const SizedBox(width: Espaco.medio),
          Expanded(
            child: Text(
              estado.titulo ?? 'Conversa',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.titleMedium,
            ),
          ),
          const SizedBox(width: Espaco.medio),
          if (estado.localApenas != null) _Procedencia(estado.localApenas!),
          const SizedBox(width: Espaco.curto),
          IconButton(
            tooltip: contextoAberto
                ? 'Ocultar o contexto'
                : 'Mostrar de onde veio a resposta',
            iconSize: 18,
            onPressed: aoAlternarContexto,
            icon: Icon(
              contextoAberto
                  ? Icons.view_sidebar
                  : Icons.view_sidebar_outlined,
              color: contextoAberto ? cores.primary : cores.onSurfaceVariant,
            ),
          ),
          Material(
            color: cores.surfaceContainer,
            borderRadius: Raio.bordaItem,
            child: InkWell(
              onTap: aoTrocarModelo,
              borderRadius: Raio.bordaItem,
              child: Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: Espaco.medio,
                  vertical: Espaco.curto,
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      estado.provedor ?? 'Modelo',
                      style: TextStyle(fontSize: 12.5, color: cores.onSurface),
                    ),
                    const SizedBox(width: Espaco.curto),
                    Icon(
                      Icons.expand_more,
                      size: 15,
                      color: cores.onSurfaceVariant,
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// De onde a resposta vem. Verde para local, âmbar para nuvem.
class _Procedencia extends StatelessWidget {
  const _Procedencia(this.local);

  final bool local;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    final cor = local ? const Color(0xFF4CAF7D) : cores.primary;
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: Espaco.curto + 2,
        vertical: Espaco.minimo + 1,
      ),
      decoration: BoxDecoration(
        color: cores.surfaceContainer,
        borderRadius: Raio.pilula,
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 6,
            height: 6,
            decoration: BoxDecoration(color: cor, shape: BoxShape.circle),
          ),
          const SizedBox(width: Espaco.curto),
          Text(
            local ? 'Local' : 'Nuvem',
            style: TextStyle(fontSize: 11.5, color: cores.onSurface),
          ),
        ],
      ),
    );
  }
}
