import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_app/design/tokens.dart';

/// Tokens só valem enquanto forem uma ESCALA. No dia em que alguém acrescenta
/// um `13.0` no meio porque "ficou melhor assim", eles viram uma lista de
/// números com nomes bonitos — e voltamos ao problema que eles resolvem.
///
/// Estes testes são baratos e chatos de propósito. O que eles protegem não é
/// o pixel: é a propriedade de que existe UM lugar para mudar densidade.
void main() {
  test('a escala de espaço sobe sempre', () {
    const escala = [
      Espaco.nada,
      Espaco.micro,
      Espaco.minimo,
      Espaco.curto,
      Espaco.medio,
      Espaco.largo,
      Espaco.amplo,
      Espaco.grande,
      Espaco.enorme,
      Espaco.vasto,
    ];
    for (var i = 1; i < escala.length; i++) {
      expect(
        escala[i],
        greaterThan(escala[i - 1]),
        reason: 'a escala precisa ser monótona para "maior" querer dizer algo',
      );
    }
  });

  test('os espaços de layout são múltiplos de 4', () {
    // micro (2) fica de fora: ele existe para ajuste ótico dentro de um selo,
    // não para separar blocos. Se um dia virar espaçamento de layout, este
    // teste é o lugar de discutir isso.
    const deLayout = [
      Espaco.minimo,
      Espaco.curto,
      Espaco.medio,
      Espaco.largo,
      Espaco.amplo,
      Espaco.grande,
      Espaco.enorme,
      Espaco.vasto,
    ];
    for (final v in deLayout) {
      expect(v % 4, 0, reason: '$v quebra a grade de 4');
    }
  });

  test('cada raio const casa com a sua medida', () {
    // este é o que importa. As duas formas existem porque BorderRadius.circular
    // nao e const; se alguem mudar `cartao` de 12 para 14 e esquecer
    // `bordaCartao`, metade da interface muda e a outra metade nao — e o
    // sintoma seria "uns cartoes estao diferentes", que ninguem liga ao token.
    expect(Raio.bordaSelo, BorderRadius.circular(Raio.selo));
    expect(Raio.bordaItem, BorderRadius.circular(Raio.item));
    expect(Raio.bordaCartao, BorderRadius.circular(Raio.cartao));
    expect(Raio.bordaPainel, BorderRadius.circular(Raio.painel));
  });

  test('o raio cresce com o tamanho da superfície', () {
    expect(Raio.selo, lessThan(Raio.item));
    expect(Raio.item, lessThan(Raio.cartao));
    expect(Raio.cartao, lessThan(Raio.painel));
  });

  test('o painel de contexto só abre quando sobra leitura', () {
    // a conta que definiu o ponto de quebra, e o motivo de ele existir. Eu
    // mesmo errei isto na primeira versao: colocar as tres colunas mais o
    // painel em 1100 px deixa 300 para a conversa — o painel roubando
    // justamente aquilo que a tela existe para mostrar.
    const molduras = Coluna.lateral + Coluna.colecao + Coluna.contexto;
    expect(
      Largura.total - molduras,
      greaterThanOrEqualTo(Coluna.leitura),
      reason: 'o painel precisa esperar caber a largura de leitura inteira',
    );
  });

  test('as tres colunas cabem antes do painel de contexto', () {
    const semPainel = Coluna.lateral + Coluna.colecao;
    expect(Largura.larga - semPainel, greaterThan(600));
  });

  test('os pontos de quebra sobem', () {
    const quebras = [
      Largura.compacta,
      Largura.media,
      Largura.larga,
      Largura.total,
    ];
    for (var i = 1; i < quebras.length; i++) {
      expect(quebras[i], greaterThan(quebras[i - 1]));
    }
  });
}
