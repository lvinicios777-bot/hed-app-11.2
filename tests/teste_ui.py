"""Exercita as telas do app HED sem interação humana (roda sob xvfb)."""
import os
import sys

OUT = sys.argv[2]
sys.path.insert(0, sys.argv[1])
os.environ["KIVY_NO_ARGS"] = "1"
from kivy.config import Config
Config.set("graphics", "width", "412")
Config.set("graphics", "height", "860")

from kivy.clock import Clock
from kivy.core.window import Window
import main as M
from hed_core import Candidato

passos, erros = [], []


def passo(f):
    passos.append(f)
    return f


def foto(nome):
    Window.screenshot(name=os.path.join(OUT, nome + ".png"))


def tocar(sl):
    from kivy.tests.common import UnitTestTouch
    toque = UnitTestTouch(*sl.to_window(*sl.center))
    toque.touch_down()
    toque.touch_up()


def rodar(app):
    app.cands, app.registro = [], []

    @passo
    def p1():
        app.ir("lista")
        app.sm.get_screen("lista").montar()

    @passo
    def p2():
        # candidato importado (com aval_cp e sugestões) e um manual sem notas
        from hed_core import aplicar_sugestoes
        app.cands = [aplicar_sugestoes(Candidato("e6", 0.0, aval_cp=30)),
                     aplicar_sugestoes(Candidato("e5", 0.01, aval_cp=29)),
                     aplicar_sugestoes(Candidato("Ng4", 0.04, aval_cp=26))]
        app.sm.get_screen("lista").montar()

    @passo
    def p3():
        foto("1_lista_sem_notas")
        app.mostrar_detalhes()

    @passo
    def p4():
        foto("2_relatorio_bloqueado")
        assert app.ultimo is None, "relatório não deveria permitir registrar sem notas"
        app.editar(0)

    @passo
    def p5():
        t = app.sm.get_screen("edicao")
        assert t.resumo.text.startswith("[color"), t.resumo.text
        foto("3_edicao_vazia")
        valores = {"forcamento": 4, "urgencia": 6, "valor_opcao": 7, "informacao": 7, "reversibilidade": 3,
                   "eficiencia": 6, "atividade": 5, "estrutura": 8, "fc": 8, "assimetria": 5}
        for k, v in valores.items():
            if v != 5:
                t.sliders[k].value = v
        from kivy.uix.scrollview import ScrollView
        sv = [w for w in t.walk() if isinstance(w, ScrollView)][0]
        sv.scroll_to(t.sliders["atividade"], animate=False)

    @passo
    def p5a():
        t = app.sm.get_screen("edicao")
        tocar(t.sliders["atividade"])
        from kivy.uix.scrollview import ScrollView
        sv = [w for w in t.walk() if isinstance(w, ScrollView)][0]
        sv.scroll_to(t.sliders["assimetria"], animate=False)

    @passo
    def p5b():
        t = app.sm.get_screen("edicao")
        tocar(t.sliders["assimetria"])
        foto("4_edicao_preenchida")
        assert "ATP" in t.resumo.text, t.resumo.text
        t.salvar()
        c = app.cands[0]
        assert c.aval_cp == 30 and c.completo, c

    @passo
    def p6():
        # completa os outros dois direto no modelo
        for i, extra in ((1, dict(forcamento=6, atividade=7, assimetria=8, fc=6)),
                         (2, dict(forcamento=9, urgencia=8, atividade=8, fc=5, estrutura=4))):
            c = app.cands[i]
            for k in M.ESTRATEGICOS + M.DIRETOS:
                if getattr(c, k) is None:
                    setattr(c, k, 5.0)
            for k, v in extra.items():
                setattr(c, k, v)
        app.sm.get_screen("lista").montar()

    @passo
    def p7():
        foto("5_lista_completa")
        app.mostrar_detalhes()

    @passo
    def p8():
        foto("6_relatorio")
        assert app.ultimo and app.ultimo["escolha"], app.ultimo
        app.abrir_registrar()

    @passo
    def p9():
        app.sm.get_screen("registrar").registrar()

    @passo
    def p10():
        assert len(app.registro) == 1 and app.registro[0]["versao"] == "11.1.2"
        foto("7_registro")
        app.mostrar_analise()

    @passo
    def p11():
        app.ir("tf")

    @passo
    def p12():
        t = app.sm.get_screen("tf")
        for k, v in (("tranq", "2.0"), ("fim", "4.0"), ("falha", "-2.0"), ("p", "80")):
            t.campos[k].text = v
        t.calcular()
        assert "72%" in t.saida.text and "vale a pena" in t.saida.text, t.saida.text

    @passo
    def p13():
        foto("8_tf")
        app.salvar()
        app.carregar()
        assert app.tf.get("p") == "80" and app.cands[0].aval_cp == 30

    def proximo(dt, i=[0]):
        if i[0] >= len(passos):
            print("UI OK:", len(passos), "passos")
            app.stop()
            return
        try:
            passos[i[0]]()
        except Exception as e:
            import traceback
            traceback.print_exc()
            erros.append(e)
            app.stop()
            return
        i[0] += 1
        Clock.schedule_once(proximo, 0.4)

    Clock.schedule_once(proximo, 0.8)


class Teste(M.HEDApp):
    def on_start(self):
        rodar(self)


Teste().run()
sys.exit(1 if erros else 0)
