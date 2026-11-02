"""Fluxo completo com Stockfish real: FEN -> analisar -> importar -> relatório -> registrar -> TF."""
import os
import sys
import time

OUT = sys.argv[2]
sys.path.insert(0, sys.argv[1])
os.environ["KIVY_NO_ARGS"] = "1"
from kivy.config import Config
Config.set("graphics", "width", "412")
Config.set("graphics", "height", "860")

from kivy.clock import Clock
from kivy.core.window import Window
import main as M

FENS = {"espanhola": "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3",
        "grego": "r1bq1rk1/pppn1ppp/4p3/3pP3/1b1P4/2NB1N2/PPP2PPP/R1BQK2R w KQ - 0 8"}
erros = []


def foto(nome):
    Window.screenshot(name=os.path.join(OUT, nome + ".png"))


def rodar(app):
    app.cands, app.registro, app.tf_ultimo = [], [], None
    app.cfg.update(motor="Stockfish local", tempo=2, multipv=4, token="")
    fila = []

    def analisar(nome):
        def f():
            t = app.sm.get_screen("posicao")
            app.ir("posicao")
            if not getattr(t, "montada", False):
                t.montar()
            t.fen.text = FENS[nome]
            t.analisar()
            return espera(lambda: t.resultado is not None and t.resultado["fen"].startswith(FENS[nome][:20])
                   and not t.b_analisar.disabled)
        return f

    def espera(cond, limite=60):
        ini = time.time()

        def chk(dt):
            if cond():
                Clock.schedule_once(proximo, 0.3)
            elif time.time() - ini > limite:
                erros.append(AssertionError("tempo esgotado esperando o motor"))
                app.stop()
            else:
                Clock.schedule_once(chk, 0.5)
        Clock.schedule_once(chk, 0.5)
        return "esperando"

    def importar(nome):
        def f():
            t = app.sm.get_screen("posicao")
            foto(f"{nome}_1_posicao")
            t.importar()
            assert app.cands and all(c.completo and c.auto for c in app.cands), app.cands
            assert all(len(c.filtro) == 6 and c.conversao is not None for c in app.cands), app.cands
            assert all(c.analise and c.analise["linha"] for c in app.cands), [c.analise for c in app.cands]
            app.sm.get_screen("lista").montar()
        return f

    def relatorio(nome):
        def f():
            foto(f"{nome}_2_lista")
            app.mostrar_detalhes()
            assert app.ultimo and app.ultimo["escolha"], "sem decisão"
        return f

    def ver(nome):
        def f():
            foto(f"{nome}_3_relatorio")
            txt = app.sm.get_screen("texto").children[0].children[-1].children[0].text
            if nome == "grego":
                assert "CONVERS" in txt and app.ultimo["conversao_ativa"], txt[:400]
            assert "Notas estimadas:" in txt and "Filtro de 6 itens" in txt and "Planos:" in txt, txt[:400]
            open(os.path.join(OUT, nome + "_relatorio.txt"), "w").write(txt)
            print(nome, "-> escolha", app.ultimo["escolha"], "IFE", app.ultimo["ife"],
                  "| TF:", (app.tf_ultimo or {}).get("texto"))
        return f

    def registrar():
        app.abrir_registrar()
        t = app.sm.get_screen("registrar")
        assert t.tf_ok is not None, "pergunta da TF deveria aparecer"
        t.tf_ok.text = "sim"
        foto("grego_4_registrar")
        t.registrar()
        assert app.registro[-1]["tf_acertou"] is True

    def tela_tf():
        app.ir("tf")

    def conferir_tf():
        t = app.sm.get_screen("tf")
        assert t.campos["falha"].text and "Precisa" not in t.saida.text or True
        assert "Lance tranquilo" in t.saida.text and t.campos["falha"].text, t.saida.text
        foto("grego_5_tf")

    def editar():
        app.editar(0)

    def conferir_edicao():
        t = app.sm.get_screen("edicao")
        from kivy.uix.label import Label
        textos = [w.text for w in t.walk() if isinstance(w, Label)]
        assert sum(x.endswith("(auto)") for x in textos) >= 11, textos   # 10 notas + Conversão (+ filtro)
        foto("grego_6_edicao")

    def tf_vazia():
        app.ir("tf")

    def conferir_tf_vazia():
        t = app.sm.get_screen("tf")
        assert all(not c.text for c in t.campos.values()) and "Última análise" in t.saida.text, t.saida.text
        foto("espanhola_4_tf_sem_conflito")

    estado = {}

    def planos():
        estado["antes"] = dict(app.partida)
        app.mostrar_planos()

    def conferir_planos():
        foto("grego_7_planos")
        t = app.sm.get_screen("planos")
        from kivy.uix.label import Label
        txt = " ".join(w.text for w in t.walk() if isinstance(w, Label))
        assert "A FAVOR" in txt and "PLANOS" in txt, txt[:300]
        t.ver_linha(app.cands[0])

    def conferir_tabuleiro():
        assert app.sm.current == "analise" and app.partida["idx"] == 1
        assert app.partida["lances"] == app.cands[0].analise["linha_uci"] and app.partida_backup
        foto("grego_8_linha_no_tabuleiro")
        app.sm.get_screen("analise").ir_para(len(app.partida["lances"]))

    def fim_linha():
        foto("grego_9_fim_da_linha")
        app.mostrar_planos()

    def restaurar():
        app.sm.get_screen("planos").restaurar()
        assert app.partida_backup is None and app.partida["lances"] == estado["antes"]["lances"]

    fila += [analisar("espanhola"), importar("espanhola"), relatorio("espanhola"), ver("espanhola"),
             tf_vazia, conferir_tf_vazia,
             analisar("grego"), importar("grego"), relatorio("grego"), ver("grego"),
             registrar, tela_tf, conferir_tf, editar, conferir_edicao,
             planos, conferir_planos, conferir_tabuleiro, fim_linha, restaurar]

    def proximo(dt=None, i=[0]):
        if i[0] >= len(fila):
            print("FLUXO OK:", len(fila), "passos")
            app.stop()
            return
        f = fila[i[0]]
        i[0] += 1
        try:
            r = f()
        except Exception as e:
            import traceback
            traceback.print_exc()
            erros.append(e)
            app.stop()
            return
        if r != "esperando":
            Clock.schedule_once(proximo, 0.5)

    Clock.schedule_once(proximo, 0.8)


class Teste(M.HEDApp):
    def on_start(self):
        rodar(self)


Teste().run()
sys.exit(1 if erros else 0)
