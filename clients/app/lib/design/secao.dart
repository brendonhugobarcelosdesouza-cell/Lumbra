import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'tokens.dart';

/// A moldura de uma seção da Lumbra e os três estados que toda lista tem.
///
/// Sete telas — Memória, Documentos, Procedimentos, Aprovações, Dispositivos,
/// Conversas e o status de documento — escreveram cada uma o seu próprio
/// `CircularProgressIndicator` centralizado, o seu próprio texto de lista
/// vazia e o seu próprio jeito de mostrar um erro. Sete versões da mesma
/// coisa não são sete decisões: são uma decisão que ninguém tomou.
///
/// O custo disso não é estético. Quando a lista vazia de uma tela diz "Nada
/// guardado nesta camada" e a de outra fica em branco, a pessoa não aprende
/// a ler a interface — ela precisa reaprender em cada lugar.

/// O cabeçalho padrão de uma seção: título à esquerda, ações à direita.
///
/// Substitui o `Scaffold` + `AppBar` que cada tela trazia. As seções vivem
/// DENTRO da moldura do app (a barra lateral já diz onde se está), então um
/// Scaffold por tela empilha uma segunda barra de topo sobre a primeira —
/// exatamente o que o R1 desfez no chat.
class MolduraDeSecao extends StatelessWidget {
  const MolduraDeSecao({
    super.key,
    required this.titulo,
    required this.child,
    this.acoes = const [],
    this.abaixoDoTitulo,
  });

  final String titulo;
  final Widget child;
  final List<Widget> acoes;

  /// Filtros, abas, busca — o que pertence ao cabeçalho mas não é ação.
  final Widget? abaixoDoTitulo;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(
            Espaco.grande,
            Espaco.largo,
            Espaco.largo,
            Espaco.medio,
          ),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  titulo,
                  style: Theme.of(context).textTheme.titleLarge,
                ),
              ),
              ...acoes,
            ],
          ),
        ),
        if (abaixoDoTitulo != null) abaixoDoTitulo!,
        Divider(height: 1, color: cores.outlineVariant),
        Expanded(child: child),
      ],
    );
  }
}

/// Desenha uma lista assíncrona com os três estados sempre iguais.
///
/// Recebe `List<T>` e não `T` de propósito: as sete seções da Lumbra são
/// listas, e a lista VAZIA é um estado próprio — nem carregando, nem erro,
/// nem conteúdo. Tratá-la como "conteúdo de tamanho zero" é o que produz
/// telas em branco que não explicam nada.
class ListaAssincrona<T> extends StatelessWidget {
  const ListaAssincrona({
    super.key,
    required this.valor,
    required this.aoTerConteudo,
    required this.oQueSeria,
    required this.quandoVazio,
    this.iconeDoVazio = Icons.inbox_outlined,
    this.acaoDoVazio,
  });

  final AsyncValue<List<T>> valor;
  final Widget Function(List<T> itens) aoTerConteudo;

  /// O que a tela deveria mostrar, em minúsculas, para compor a frase de
  /// erro: "a memória", "os documentos". Assim a mensagem diz o que falhou
  /// em vez de um "erro ao carregar" que serve para tudo e não ajuda em nada.
  final String oQueSeria;

  final String quandoVazio;
  final IconData iconeDoVazio;

  /// O empurrão que tira a pessoa do estado vazio. Opcional: onde não há
  /// nada a oferecer, não se oferece um botão que não leva a lugar nenhum.
  final Widget? acaoDoVazio;

  @override
  Widget build(BuildContext context) {
    return valor.when(
      loading: () => const Carregando(),
      error: (erro, _) => Falhou(oQueSeria: oQueSeria, detalhe: '$erro'),
      data: (itens) => itens.isEmpty
          ? Vazio(
              texto: quandoVazio,
              icone: iconeDoVazio,
              acao: acaoDoVazio,
            )
          : aoTerConteudo(itens),
    );
  }
}

/// Esperando. Pequeno e discreto de propósito: um indicador enorme no meio
/// da tela transforma meio segundo de espera em susto.
class Carregando extends StatelessWidget {
  const Carregando({super.key});

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: SizedBox(
        width: 20,
        height: 20,
        child: CircularProgressIndicator(strokeWidth: 2),
      ),
    );
  }
}

/// Não há nada aqui — e por quê.
class Vazio extends StatelessWidget {
  const Vazio({super.key, required this.texto, required this.icone, this.acao});

  final String texto;
  final IconData icone;
  final Widget? acao;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(Espaco.enorme),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icone, size: 30, color: cores.onSurfaceVariant),
            const SizedBox(height: Espaco.largo),
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 360),
              child: Text(
                texto,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodyMedium,
              ),
            ),
            if (acao != null) ...[
              const SizedBox(height: Espaco.amplo),
              acao!,
            ],
          ],
        ),
      ),
    );
  }
}

/// Deu errado, e dizemos o quê.
///
/// A frase nomeia o que falhou ("Não foi possível carregar a memória") em vez
/// de um genérico. O detalhe técnico vem embaixo, menor: quem precisa dele
/// consegue lê-lo, e quem não precisa não é obrigado a encará-lo.
class Falhou extends StatelessWidget {
  const Falhou({
    super.key,
    required this.oQueSeria,
    required this.detalhe,
    this.aoTentarDeNovo,
  });

  final String oQueSeria;
  final String detalhe;
  final VoidCallback? aoTentarDeNovo;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(Espaco.enorme),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.error_outline, size: 26, color: cores.error),
              const SizedBox(height: Espaco.largo),
              Text(
                'Não foi possível carregar $oQueSeria.',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodyMedium,
              ),
              const SizedBox(height: Espaco.curto),
              SelectableText(
                detalhe,
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 11.5, color: cores.onSurfaceVariant),
              ),
              if (aoTentarDeNovo != null) ...[
                const SizedBox(height: Espaco.amplo),
                TextButton.icon(
                  onPressed: aoTentarDeNovo,
                  icon: const Icon(Icons.refresh, size: 16),
                  label: const Text('Tentar de novo'),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// O cartão em que a Lumbra guarda uma coisa: memória, documento,
/// procedimento, aparelho. Superfície um degrau acima do fundo, borda
/// discreta, raio de cartão — os mesmos do cartão de resposta do chat.
class CartaoDaLumbra extends StatelessWidget {
  const CartaoDaLumbra({super.key, required this.child, this.aoTocar});

  final Widget child;
  final VoidCallback? aoTocar;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: Espaco.medio),
      child: Material(
        color: cores.surfaceContainerLow,
        borderRadius: Raio.bordaCartao,
        child: InkWell(
          onTap: aoTocar,
          borderRadius: Raio.bordaCartao,
          child: Container(
            decoration: BoxDecoration(
              borderRadius: Raio.bordaCartao,
              border: Border.all(color: cores.outlineVariant),
            ),
            padding: const EdgeInsets.all(Espaco.largo),
            child: child,
          ),
        ),
      ),
    );
  }
}

/// A largura de leitura da seção. As listas da Lumbra são de texto — correr
/// de ponta a ponta numa tela larga cansa do mesmo jeito que na conversa.
class ColunaDeLeitura extends StatelessWidget {
  const ColunaDeLeitura({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: Coluna.leitura),
        child: child,
      ),
    );
  }
}
