import 'package:flutter/material.dart';

import '../../design/tokens.dart';

/// Uma seção da Lumbra na barra lateral.
class Secao {
  const Secao({
    required this.nome,
    required this.icone,
    required this.iconeAtivo,
    this.selo,
  });

  final String nome;
  final IconData icone;
  final IconData iconeAtivo;

  /// Quando presente, a seção AINDA NÃO EXISTE e o selo diz em que etapa
  /// ela chega. Ela aparece apagada e não abre nada.
  ///
  /// Mostrar o que não existe é uma escolha discutível, e por isso vale
  /// justificar: o menu vira um mapa do que a Lumbra será, e a promessa fica
  /// datada em vez de vaga. O que NÃO se pode fazer é o meio-termo — listar
  /// "Agenda" como se funcionasse e abrir uma tela vazia. Seria a versão em
  /// interface do assistente inventando capacidades, que acabamos de
  /// consertar no prompt.
  final String? selo;

  bool get disponivel => selo == null;
}

/// Barra lateral com seções agrupadas por INTENÇÃO.
///
/// Substituiu o `NavigationRail`, que empilhava dez destinos numa lista
/// chapada. Dez itens sem hierarquia é uma lista que se lê inteira toda vez;
/// dois grupos de cinco é uma que se navega pelo grupo certo.
///
/// A separação não é decorativa: **"Meu sistema"** é o que a Lumbra guarda de
/// você — conversas, memória, documentos, procedimentos. **"Controle"** é
/// como você manda nela — o que autoriza, quais aparelhos entram, quais
/// agentes existem. Um é conteúdo, o outro é poder sobre o conteúdo.
class BarraLateral extends StatelessWidget {
  const BarraLateral({
    super.key,
    required this.grupos,
    required this.selecionada,
    required this.aoSelecionar,
    required this.rodape,
    this.selos = const {},
    this.fixos = const [],
  });

  /// Grupos na ordem de exibição. Chave vazia = sem título (topo).
  final Map<String, List<Secao>> grupos;
  final String selecionada;
  final ValueChanged<String> aoSelecionar;

  /// Contadores por seção (ex.: aprovações pendentes).
  final Map<String, int> selos;

  /// Seções ancoradas ao pé da lista, fora da rolagem: Configurações e Ajuda.
  ///
  /// Elas não pertencem a "Meu sistema" nem a "Controle" — não são um lugar
  /// onde se trabalha, são onde se recorre quando algo está errado. Ficarem
  /// sempre no mesmo pixel importa mais para elas do que para as outras.
  final List<Secao> fixos;
  final Widget rodape;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Container(
      width: Coluna.lateral,
      color: cores.surfaceContainer,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const _Marca(),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.only(bottom: Espaco.curto),
              children: [
                for (final grupo in grupos.entries) ...[
                  if (grupo.key.isNotEmpty) _TituloDoGrupo(grupo.key),
                  for (final secao in grupo.value)
                    _Item(
                      secao: secao,
                      ativa: secao.nome == selecionada,
                      pendentes: selos[secao.nome] ?? 0,
                      aoTocar: secao.disponivel ? () => aoSelecionar(secao.nome) : null,
                    ),
                ],
              ],
            ),
          ),
          if (fixos.isNotEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: Espaco.curto),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (final secao in fixos)
                    _Item(
                      secao: secao,
                      ativa: secao.nome == selecionada,
                      pendentes: 0,
                      aoTocar: secao.disponivel
                          ? () => aoSelecionar(secao.nome)
                          : null,
                    ),
                ],
              ),
            ),
          Divider(height: 1, color: cores.outlineVariant),
          rodape,
        ],
      ),
    );
  }
}

class _Marca extends StatelessWidget {
  const _Marca();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(Espaco.largo, Espaco.amplo, Espaco.largo, Espaco.medio),
      child: Text(
        'LUMBRA',
        style: Theme.of(context).textTheme.labelLarge?.copyWith(
          fontWeight: FontWeight.w800,
          // espaçamento largo: a marca é assinatura, não rótulo de botão
          letterSpacing: 2.4,
          fontSize: 12.5,
        ),
      ),
    );
  }
}

class _TituloDoGrupo extends StatelessWidget {
  const _TituloDoGrupo(this.texto);

  final String texto;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(Espaco.largo, Espaco.largo, Espaco.largo, Espaco.curto),
      child: Text(
        texto.toUpperCase(),
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
          fontWeight: FontWeight.w700,
          letterSpacing: 1.1,
          fontSize: 10,
        ),
      ),
    );
  }
}

class _Item extends StatelessWidget {
  const _Item({
    required this.secao,
    required this.ativa,
    required this.pendentes,
    required this.aoTocar,
  });

  final Secao secao;
  final bool ativa;
  final int pendentes;
  final VoidCallback? aoTocar;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    final textos = Theme.of(context).textTheme;
    // seção futura fica visível e claramente inerte: a diferença tem que ser
    // óbvia SEM depender de tentar clicar
    final futura = !secao.disponivel;
    final cor = futura
        ? cores.onSurfaceVariant
        : (ativa ? cores.onSurface : cores.onSurfaceVariant);

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: Espaco.curto, vertical: 1),
      child: Material(
        color: ativa ? cores.surfaceContainerHigh : Colors.transparent,
        borderRadius: Raio.bordaItem,
        child: InkWell(
          onTap: aoTocar,
          borderRadius: Raio.bordaItem,
          child: Opacity(
            opacity: futura ? Opacidade.futuro : 1,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: Espaco.medio, vertical: Espaco.curto),
              child: Row(
                children: [
                  Icon(ativa ? secao.iconeAtivo : secao.icone, size: 17, color: cor),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      secao.nome,
                      style: textos.bodyMedium?.copyWith(
                        color: cor,
                        fontSize: 13,
                        fontWeight: ativa ? FontWeight.w600 : FontWeight.w400,
                        fontStyle: futura ? FontStyle.italic : FontStyle.normal,
                      ),
                    ),
                  ),
                  if (secao.selo != null) _Selo(secao.selo!),
                  // o contador vive na barra e não dentro da tela: pedido que
                  // ninguém vê equivale a pedido negado
                  if (pendentes > 0) _Contador(pendentes),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Selo extends StatelessWidget {
  const _Selo(this.texto);

  final String texto;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
      decoration: BoxDecoration(
        color: cores.surfaceContainerHigh,
        borderRadius: Raio.bordaSelo,
      ),
      child: Text(
        texto,
        style: TextStyle(
          fontSize: 9,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.4,
          fontStyle: FontStyle.normal,
          color: cores.onSurfaceVariant,
        ),
      ),
    );
  }
}

class _Contador extends StatelessWidget {
  const _Contador(this.quantos);

  final int quantos;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      decoration: BoxDecoration(
        color: cores.primary,
        borderRadius: Raio.pilula,
      ),
      child: Text(
        '$quantos',
        style: TextStyle(
          fontSize: 10,
          fontWeight: FontWeight.w700,
          color: cores.surface,
        ),
      ),
    );
  }
}
