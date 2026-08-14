"""Encerrar o Nó sem machucar o banco (P2-f.3, correção ao ADR-069).

O app desktop não tem como mandar um sinal para o Nó no Windows: o
``Process.kill`` do Dart vira ``TerminateProcess``. O preço apareceu no
primeiro uso real — o Postgres embutido levou um tiro no meio de um
``COMMIT`` e o cluster ficou precisando de recuperação.

O canal que existe nos dois sistemas é a entrada padrão. Fechá-la é um
pedido; matar é uma ordem. Estes testes travam o pedido.
"""

import io
import threading

from lumbra.cli import main as cli


class _ServidorFalso:
    should_exit = False


class TestSeguirAEntrada:
    def test_fim_da_entrada_pede_parada_limpa(self, monkeypatch):
        servidor = _ServidorFalso()
        monkeypatch.setattr(cli.sys, "stdin", io.StringIO(""))  # já no fim
        cli._vigiar_a_entrada(servidor)
        assert servidor.should_exit is True

    def test_o_que_chega_pela_entrada_e_ignorado(self, monkeypatch):
        """Só o FIM interessa. A entrada não é um canal de comandos — se um
        dia for, que seja uma decisão, e não um acidente de implementação."""
        servidor = _ServidorFalso()
        monkeypatch.setattr(cli.sys, "stdin", io.StringIO("oi\nmais uma linha\n"))
        cli._vigiar_a_entrada(servidor)
        assert servidor.should_exit is True

    def test_entrada_que_explode_tambem_e_fim(self, monkeypatch):
        """O caso que mais importa: quem nos iniciou morreu de repente.

        O cano quebra em vez de fechar. Se tratássemos isso como erro e
        seguíssemos vivos, o Nó viraria o órfão que este código existe para
        impedir — segurando a porta e o banco.
        """

        class _EntradaQuebrada:
            def __iter__(self):
                return self

            def __next__(self):
                raise OSError("cano quebrado")

        servidor = _ServidorFalso()
        monkeypatch.setattr(cli.sys, "stdin", _EntradaQuebrada())
        cli._vigiar_a_entrada(servidor)
        assert servidor.should_exit is True

    def test_enquanto_a_entrada_vive_o_no_vive(self, monkeypatch):
        """Sem isto o Nó encerraria sozinho assim que subisse."""
        servidor = _ServidorFalso()
        segura = threading.Event()

        class _EntradaAberta:
            def __iter__(self):
                return self

            def __next__(self):
                segura.wait(2.0)
                raise StopIteration

        monkeypatch.setattr(cli.sys, "stdin", _EntradaAberta())
        thread = threading.Thread(target=cli._vigiar_a_entrada, args=(servidor,), daemon=True)
        thread.start()
        thread.join(0.3)
        assert servidor.should_exit is False, "pediu parada com a entrada ainda aberta"
        segura.set()
        thread.join(2.0)
        assert servidor.should_exit is True


class TestOQueImpedeSubir:
    """`lumbra up` é o caminho do PRODUTO: barrar demais é não abrir."""

    def test_falta_de_ollama_nao_impede_a_lumbra_de_abrir(self):
        """Sem modelo de conversa não há chat — mas documentos, memória e
        busca continuam inteiros. Antes, qualquer falha barrava o `up`, o que
        significava: sem Ollama instalado, a Lumbra não abriria de jeito
        nenhum."""
        assert "ollama" not in cli.IMPEDEM_SUBIR
        assert "redis" not in cli.IMPEDEM_SUBIR
        assert "ia_nuvem" not in cli.IMPEDEM_SUBIR
        assert "docker" not in cli.IMPEDEM_SUBIR

    def test_o_que_compromete_os_dados_continua_barrando(self):
        """Falhar cedo vale para o que corrompe ou expõe: banco ausente,
        esquema desatualizado, segredo de desenvolvimento em produção."""
        for critico in ("postgres", "migracoes", "configuracao", "permissoes"):
            assert critico in cli.IMPEDEM_SUBIR


# canário anti-truncamento
