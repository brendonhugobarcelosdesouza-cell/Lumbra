import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../design/tokens.dart';
import 'chat_models.dart';
import 'conversa_estado.dart';
import 'mensagens.dart';

/// Se o painel de contexto está aberto.
///
/// Aberto por padrão: numa plataforma cujo argumento é que se pode CONFERIR
/// de onde veio cada afirmação, esconder a proveniência atrás de um clique
/// transforma auditoria em curiosidade.
final painelDeContextoProvider = StateProvider<bool>((_) => true);

/// A coluna da direita: de onde veio a última resposta e o que ela custou.
///
/// Tudo aqui já atravessava o fio e vivia no Developer Console — visível para
/// quem construiu, invisível para quem usa. `CitationOut` traz tipo, título,
/// trecho e SCORE; `ChatMessageOut` traz modelo, provedor e tokens, inclusive
/// no histórico. Este painel não inventa nada: ele muda de lugar uma
/// informação que já existia.
///
/// Descreve a ÚLTIMA resposta da conversa. Descrever uma mensagem escolhida
/// seria melhor e exige um mecanismo de seleção que ainda não existe — está
/// anotado, e enquanto não existir o painel diz claramente de qual resposta
/// está falando (pelo horário).
class PainelDeContexto extends StatelessWidget {
  const PainelDeContexto({super.key, required this.estado, this.aoFechar});

  final EstadoDaConversa estado;
  final VoidCallback? aoFechar;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    final resposta = _ultimaResposta(estado);

    return Container(
      color: cores.surfaceContainerLow,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _Titulo(aoFechar: aoFechar),
          Divider(height: 1, color: cores.outlineVariant),
          Expanded(
            child: resposta == null
                ? const _SemResposta()
                : ListView(
                    padding: const EdgeInsets.fromLTRB(
                      Espaco.largo,
                      Espaco.largo,
                      Espaco.largo,
                      Espaco.enorme,
                    ),
                    children: [
                      _OQueUsou(resposta.usedCitations),
                      const SizedBox(height: Espaco.amplo),
                      _FontesConsultadas(resposta.usedCitations),
                      const SizedBox(height: Espaco.amplo),
                      _Execucao(bolha: resposta, ultima: estado.ultimaResposta),
                    ],
                  ),
          ),
        ],
      ),
    );
  }

  /// A última fala da Lumbra que virou mensagem de verdade.
  ///
  /// Ignora a bolha viva do stream de propósito: enquanto o texto ainda
  /// chega, o custo e o modelo ainda não vieram, e o painel mostraria campos
  /// vazios piscando.
  static ChatBubble? _ultimaResposta(EstadoDaConversa estado) {
    for (final bolha in estado.bolhas.reversed) {
      if (bolha.role == BubbleRole.assistant) return bolha;
    }
    return null;
  }
}

class _Titulo extends StatelessWidget {
  const _Titulo({this.aoFechar});

  final VoidCallback? aoFechar;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(
        Espaco.largo,
        Espaco.medio,
        Espaco.curto,
        Espaco.medio,
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              'Contexto',
              style: Theme.of(context).textTheme.titleMedium,
            ),
          ),
          if (aoFechar != null)
            IconButton(
              tooltip: 'Fechar o contexto',
              iconSize: 18,
              onPressed: aoFechar,
              icon: Icon(Icons.close, color: cores.onSurfaceVariant),
            ),
        ],
      ),
    );
  }
}

class _SemResposta extends StatelessWidget {
  const _SemResposta();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(Espaco.grande),
        child: Text(
          'Quando a Lumbra responder, aqui aparece de onde ela tirou a resposta.',
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.bodySmall,
        ),
      ),
    );
  }
}

/// Quantas fontes de cada tipo entraram na resposta.
///
/// Agrupado por tipo, e não uma contagem só, porque "3 fontes" não distingue
/// a Lumbra ter lido três documentos seus de ter usado três lembranças —
/// que são coisas muito diferentes de conferir.
class _OQueUsou extends StatelessWidget {
  const _OQueUsou(this.fontes);

  final List<CitationOut> fontes;

  @override
  Widget build(BuildContext context) {
    if (fontes.isEmpty) {
      return _Secao(
        titulo: 'O que a Lumbra usou',
        child: Text(
          'Nada dos seus dados. Esta resposta veio do conhecimento geral do '
          'modelo.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
      );
    }

    final porTipo = <String, int>{};
    for (final f in fontes) {
      porTipo[f.kind] = (porTipo[f.kind] ?? 0) + 1;
    }

    return _Secao(
      titulo: 'O que a Lumbra usou',
      child: Column(
        children: [
          for (final tipo in porTipo.entries)
            _Linha(
              icone: iconeDoTipo(tipo.key),
              rotulo: nomeDoTipo(tipo.key),
              valor: tipo.value == 1 ? '1 item' : '${tipo.value} itens',
            ),
        ],
      ),
    );
  }
}

class _FontesConsultadas extends StatelessWidget {
  const _FontesConsultadas(this.fontes);

  final List<CitationOut> fontes;

  @override
  Widget build(BuildContext context) {
    if (fontes.isEmpty) return const SizedBox.shrink();
    return _Secao(
      titulo: 'Fontes consultadas',
      child: Column(
        children: [
          for (final f in fontes) _CartaoDeFonte(f),
        ],
      ),
    );
  }
}

class _CartaoDeFonte extends StatelessWidget {
  const _CartaoDeFonte(this.fonte);

  final CitationOut fonte;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: Espaco.curto),
      child: Material(
        color: cores.surfaceContainerHigh,
        borderRadius: Raio.bordaItem,
        child: InkWell(
          borderRadius: Raio.bordaItem,
          onTap: () => mostrarFonte(context, fonte),
          child: Padding(
            padding: const EdgeInsets.all(Espaco.medio),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  iconeDoTipo(fonte.kind),
                  size: 15,
                  color: cores.onSurfaceVariant,
                ),
                const SizedBox(width: Espaco.curto),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        fonte.title?.trim().isNotEmpty ?? false
                            ? fonte.title!
                            : 'Fonte [${fonte.ordinal}]',
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontSize: 12.5,
                          color: cores.onSurface,
                        ),
                      ),
                      const SizedBox(height: 1),
                      Text(
                        nomeDoTipo(fonte.kind),
                        style: TextStyle(
                          fontSize: 11,
                          color: cores.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                ),
                if (fonte.score != null) ...[
                  const SizedBox(width: Espaco.curto),
                  _Score(fonte.score!),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// O quanto a fonte se parecia com a pergunta, na escala do RAG.
///
/// Mostrar o número é o que separa "a Lumbra disse" de "a Lumbra disse, e dá
/// para conferir por quê aquela fonte e não outra".
class _Score extends StatelessWidget {
  const _Score(this.valor);

  final num valor;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: Espaco.curto,
        vertical: 1,
      ),
      decoration: BoxDecoration(
        color: cores.surfaceContainer,
        borderRadius: Raio.bordaSelo,
      ),
      child: Text(
        valor.toStringAsFixed(2).replaceFirst('.', ','),
        style: TextStyle(
          fontSize: 11,
          fontFeatures: const [FontFeature.tabularFigures()],
          color: cores.onSurfaceVariant,
        ),
      ),
    );
  }
}

/// Modelo, procedência e custo.
///
/// O tempo só aparece na resposta que acabou de chegar, porque ele é medido
/// no cliente: o Nó não devolve latência, e o histórico não tem como saber.
/// Inventar um número ali seria pior que a ausência dele.
class _Execucao extends StatelessWidget {
  const _Execucao({required this.bolha, required this.ultima});

  final ChatBubble bolha;
  final RespostaConcluida? ultima;

  @override
  Widget build(BuildContext context) {
    final desta = ultima != null && ultima!.model == bolha.modelo;
    final tokens = (bolha.tokensIn ?? 0) + (bolha.tokensOut ?? 0);

    return _Secao(
      titulo: 'Como foi respondida',
      child: Column(
        children: [
          if (bolha.modelo != null)
            _Linha(
              icone: Icons.memory,
              rotulo: 'Modelo',
              valor: bolha.modelo!,
            ),
          if (bolha.quando != null)
            _Linha(
              icone: Icons.schedule,
              rotulo: 'Respondida às',
              valor: horaDe(bolha.quando!),
            ),
          if (desta && ultima!.duracao != null)
            _Linha(
              icone: Icons.timer_outlined,
              rotulo: 'Levou',
              valor: _segundos(ultima!.duracao!),
            ),
          if (tokens > 0)
            _Linha(
              icone: Icons.toll_outlined,
              rotulo: 'Tokens',
              valor:
                  '${bolha.tokensIn ?? 0} entrada · ${bolha.tokensOut ?? 0} saída',
            ),
        ],
      ),
    );
  }

  static String _segundos(Duration d) {
    final s = d.inMilliseconds / 1000;
    return '${s.toStringAsFixed(1).replaceFirst('.', ',')} s';
  }
}

class _Secao extends StatelessWidget {
  const _Secao({required this.titulo, required this.child});

  final String titulo;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(bottom: Espaco.curto),
          child: Text(
            titulo.toUpperCase(),
            style: TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.8,
              color: cores.onSurfaceVariant,
            ),
          ),
        ),
        child,
      ],
    );
  }
}

class _Linha extends StatelessWidget {
  const _Linha({
    required this.icone,
    required this.rotulo,
    required this.valor,
  });

  final IconData icone;
  final String rotulo;
  final String valor;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: Espaco.minimo + 1),
      child: Row(
        children: [
          Icon(icone, size: 14, color: cores.onSurfaceVariant),
          const SizedBox(width: Espaco.curto),
          Expanded(
            child: Text(
              rotulo,
              style: TextStyle(fontSize: 12, color: cores.onSurfaceVariant),
            ),
          ),
          const SizedBox(width: Espaco.curto),
          Flexible(
            child: Text(
              valor,
              textAlign: TextAlign.right,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 12, color: cores.onSurface),
            ),
          ),
        ],
      ),
    );
  }
}
