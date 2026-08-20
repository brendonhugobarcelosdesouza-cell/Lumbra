import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../design/tokens.dart';

/// Onde se fala com a Lumbra.
///
/// A caixa de texto padrão do Material serve para preencher um formulário:
/// borda fina, altura de uma linha, um botão ao lado. Aqui ela é a peça mais
/// usada da tela inteira e o lugar onde a pessoa PENSA — precisa de altura
/// para uma pergunta de cinco linhas caber sem virar uma fresta, e de peso
/// visual suficiente para o olho voltar a ela sozinho.
///
/// O campo continua habilitado enquanto a Lumbra responde. Bloqueá-lo, como
/// estava antes, obriga a esperar para começar a escrever a próxima pergunta
/// — e a resposta pode levar um minuto. O que muda durante a geração é o
/// botão: enviar vira parar.
class Composer extends StatefulWidget {
  const Composer({
    super.key,
    required this.controlador,
    required this.enviando,
    required this.aoEnviar,
    required this.aoParar,
  });

  final TextEditingController controlador;
  final bool enviando;
  final VoidCallback aoEnviar;
  final VoidCallback aoParar;

  @override
  State<Composer> createState() => _ComposerState();
}

class _ComposerState extends State<Composer> {
  final _foco = FocusNode();
  var _temTexto = false;

  @override
  void initState() {
    super.initState();
    widget.controlador.addListener(_conferirTexto);
    // sem isto a borda de foco nunca acenderia: `hasFocus` lido no build
    // não redesenha nada por si só
    _foco.addListener(_redesenhar);
  }

  @override
  void dispose() {
    widget.controlador.removeListener(_conferirTexto);
    _foco.removeListener(_redesenhar);
    _foco.dispose();
    super.dispose();
  }

  void _redesenhar() {
    if (mounted) setState(() {});
  }

  /// Só reconstrói quando o campo cruza a fronteira vazio/não-vazio.
  /// Reconstruir a cada tecla, para mudar a cor de um botão, é desperdício
  /// que aparece como travada em quem digita rápido.
  void _conferirTexto() {
    final tem = widget.controlador.text.trim().isNotEmpty;
    if (tem != _temTexto) setState(() => _temTexto = tem);
  }

  /// Enter envia; Shift+Enter quebra linha.
  ///
  /// A escolha vale a pena justificar: o contrário (Enter quebra linha,
  /// Ctrl+Enter envia) é mais seguro contra envio acidental, mas cobra um
  /// atalho a cada mensagem numa ferramenta de uso contínuo. Quem escreve
  /// texto longo aprende o Shift+Enter uma vez; quem escreve perguntas
  /// curtas — a maioria esmagadora — nunca precisa aprender nada.
  KeyEventResult _aoTeclar(FocusNode _, KeyEvent evento) {
    if (evento is! KeyDownEvent) return KeyEventResult.ignored;
    if (evento.logicalKey != LogicalKeyboardKey.enter &&
        evento.logicalKey != LogicalKeyboardKey.numpadEnter) {
      return KeyEventResult.ignored;
    }
    if (HardwareKeyboard.instance.isShiftPressed) return KeyEventResult.ignored;
    if (widget.enviando) return KeyEventResult.handled; // já está gerando
    // a mesma condição do botão: um Enter em campo só com espaços não pode
    // fazer o que o botão apagado ao lado se recusa a fazer
    if (!_temTexto) return KeyEventResult.handled;
    widget.aoEnviar();
    return KeyEventResult.handled;
  }

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;

    return Padding(
      padding: const EdgeInsets.fromLTRB(
        Espaco.grande,
        Espaco.curto,
        Espaco.grande,
        Espaco.medio,
      ),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: Coluna.leitura),
          child: Column(
            children: [
              Container(
                decoration: BoxDecoration(
                  color: cores.surfaceContainerLow,
                  borderRadius: Raio.bordaPainel,
                  border: Border.all(
                    color: _foco.hasFocus ? cores.primary : cores.outline,
                  ),
                ),
                padding: const EdgeInsets.fromLTRB(
                  Espaco.amplo,
                  Espaco.medio,
                  Espaco.curto,
                  Espaco.curto,
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Expanded(
                      child: Focus(
                        onKeyEvent: _aoTeclar,
                        child: TextField(
                          controller: widget.controlador,
                          focusNode: _foco,
                          minLines: 1,
                          maxLines: 8,
                          autofocus: true,
                          style: Theme.of(context).textTheme.bodyMedium
                              ?.copyWith(fontSize: 14, height: 1.5),
                          // decoração zerada: quem desenha a caixa é o
                          // Container acima. Duas bordas concêntricas é o
                          // erro clássico de compor campo com moldura.
                          decoration: InputDecoration(
                            isDense: true,
                            filled: false,
                            border: InputBorder.none,
                            enabledBorder: InputBorder.none,
                            focusedBorder: InputBorder.none,
                            contentPadding: const EdgeInsets.only(
                              bottom: Espaco.curto,
                            ),
                            hintText: 'Pergunte ou diga à Lumbra o que fazer…',
                            hintStyle: TextStyle(
                              fontSize: 14,
                              color: cores.onSurfaceVariant,
                            ),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(width: Espaco.curto),
                    _BotaoDeAcao(
                      enviando: widget.enviando,
                      ativo: _temTexto,
                      aoEnviar: widget.aoEnviar,
                      aoParar: widget.aoParar,
                    ),
                  ],
                ),
              ),
              const SizedBox(height: Espaco.curto),
              Text(
                // a mesma franqueza do prompt, na moldura: a Lumbra erra, e
                // dizer isso onde a pergunta é feita custa uma linha
                'A Lumbra pode errar. Confira o que for importante.',
                style: TextStyle(fontSize: 11, color: cores.onSurfaceVariant),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Enviar quando há o que enviar; parar quando está gerando.
///
/// Um botão só, no mesmo lugar, trocando de função. Dois botões lado a lado
/// — um sempre inerte — fariam a pessoa mirar antes de clicar.
class _BotaoDeAcao extends StatelessWidget {
  const _BotaoDeAcao({
    required this.enviando,
    required this.ativo,
    required this.aoEnviar,
    required this.aoParar,
  });

  final bool enviando;
  final bool ativo;
  final VoidCallback aoEnviar;
  final VoidCallback aoParar;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    final habilitado = enviando || ativo;

    return Tooltip(
      message: enviando ? 'Parar' : 'Enviar  ·  Enter',
      child: Material(
        color: habilitado ? cores.primary : cores.surfaceContainerHigh,
        shape: const CircleBorder(),
        child: InkWell(
          customBorder: const CircleBorder(),
          onTap: enviando ? aoParar : (ativo ? aoEnviar : null),
          child: SizedBox(
            width: 36,
            height: 36,
            child: Icon(
              enviando ? Icons.stop_rounded : Icons.arrow_upward_rounded,
              size: 19,
              color: habilitado
                  ? (Theme.of(context).brightness == Brightness.dark
                        ? const Color(0xFF241800)
                        : Colors.white)
                  : cores.onSurfaceVariant,
            ),
          ),
        ),
      ),
    );
  }
}
