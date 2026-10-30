"""
HED 11.2 — app Android (Kivy).
Telas: lista de candidatos · edição · relatório · registrar posição · registro (PR/CC/AC/RP).
Dados salvos em JSON no armazenamento do app.
"""
import json
import os

from kivy.app import App
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import ScreenManager, Screen, NoTransition
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

from hed_core import (Candidato, ESTRATEGICOS, DIRETOS, ROTULOS, MI_CP, MI_PP, VERSAO,
                      RESULTADOS, analisar, relatorio, novo_registro, analise_registro)

Window.clearcolor = (0.11, 0.12, 0.14, 1)
ALTURA = dp(48)
AZUL, VERDE, CINZA, VERMELHO = (0.25, 0.45, 0.75, 1), (0.2, 0.6, 0.35, 1), (0.35, 0.35, 0.35, 1), (0.6, 0.2, 0.2, 1)
RES_TXT = {v: k for k, v in RESULTADOS.items()}
CICLO = ["—", "1", "½", "0"]


def seguro(txt: str) -> str:
    for a, b in (("→", "->"), ("×", "x"), ("⚠", "!"), ("–", "-"), ("Δ", "d")):
        txt = txt.replace(a, b)
    return txt


def num(txt, padrao=None):
    try:
        return float(str(txt).replace(",", "."))
    except ValueError:
        return padrao


def botao(texto, acao, cor=AZUL):
    b = Button(text=texto, size_hint_y=None, height=ALTURA, background_normal="", background_color=cor)
    b.bind(on_release=lambda *_: acao())
    return b


def rotulo(texto, **kw):
    lb = Label(text=texto, size_hint_y=None, height=ALTURA, halign="left", valign="middle", **kw)
    lb.bind(size=lambda w, s: setattr(w, "text_size", s))
    return lb


def rolavel(conteudo):
    conteudo.size_hint_y = None
    conteudo.bind(minimum_height=conteudo.setter("height"))
    sv = ScrollView()
    sv.add_widget(conteudo)
    return sv


def titulo(txt):
    return Label(text=f"[b]{txt}[/b]", markup=True, font_size="20sp", size_hint_y=None, height=dp(44))


def campo(texto="", filtro=None):
    return TextInput(text=texto, multiline=False, input_filter=filtro, size_hint_y=None, height=ALTURA)


# ---------------------------------------------------------------- Lista
class TelaLista(Screen):
    def on_enter(self, *_):
        self.montar()

    def montar(self):
        app = App.get_running_app()
        self.clear_widgets()
        raiz = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        raiz.add_widget(titulo(f"HED {VERSAO}"))

        mi = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(6))
        mi.add_widget(rotulo("MI peões"))
        self.mi_cp = TextInput(text=str(app.mi_cp), multiline=False, input_filter="float")
        mi.add_widget(self.mi_cp)
        mi.add_widget(rotulo("MI pp"))
        self.mi_pp = TextInput(text=str(app.mi_pp), multiline=False, input_filter="float")
        mi.add_widget(self.mi_pp)
        raiz.add_widget(mi)

        lista = GridLayout(cols=1, spacing=dp(6))
        if not app.cands:
            lista.add_widget(rotulo("Nenhum candidato. Toque em + Candidato."))
        for i, c in enumerate(app.cands):
            linha = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(6))
            wdl = f"  E {c.escore:.0f}%" if c.escore is not None else ""
            marca = "" if c.filtro_ok else "  [filtro X]"
            b = Button(text=f"{c.lance}   perda {c.delta:.2f}{wdl}   ATP {c.atp:.2f}{marca}",
                       background_normal="", background_color=(0.2, 0.22, 0.26, 1))
            b.bind(on_release=lambda _b, i=i: app.editar(i))
            linha.add_widget(b)
            x = Button(text="X", size_hint_x=None, width=ALTURA, background_normal="",
                       background_color=VERMELHO)
            x.bind(on_release=lambda _b, i=i: self.remover(i))
            linha.add_widget(x)
            lista.add_widget(linha)
        raiz.add_widget(rolavel(lista))

        a1 = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(8))
        a1.add_widget(botao("+ Candidato", lambda: app.editar(None)))
        a1.add_widget(botao("Analisar", self.analisar, VERDE))
        raiz.add_widget(a1)
        a2 = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(8))
        a2.add_widget(botao("Registro", lambda: app.ir("registro"), (0.45, 0.35, 0.6, 1)))
        a2.add_widget(botao("Nova posição", self.limpar, CINZA))
        raiz.add_widget(a2)
        self.add_widget(raiz)

    def remover(self, i):
        app = App.get_running_app()
        app.cands.pop(i)
        app.salvar()
        self.montar()

    def limpar(self):
        app = App.get_running_app()
        app.cands.clear()
        app.salvar()
        self.montar()

    def analisar(self):
        app = App.get_running_app()
        app.mi_cp = num(self.mi_cp.text, MI_CP)
        app.mi_pp = num(self.mi_pp.text, MI_PP)
        app.salvar()
        app.mostrar_relatorio()


# ---------------------------------------------------------------- Edição
class TelaEdicao(Screen):
    def carregar(self, c: Candidato):
        self.clear_widgets()
        self.sliders = {}
        corpo = GridLayout(cols=1, spacing=dp(4), padding=dp(10))

        corpo.add_widget(rotulo("Lance (ex.: e5, Rd1):"))
        self.lance = campo(c.lance)
        corpo.add_widget(self.lance)
        corpo.add_widget(rotulo("Perda vs melhor lance do motor (peões):"))
        self.delta = campo(str(c.delta), "float")
        corpo.add_widget(self.delta)

        lf = BoxLayout(size_hint_y=None, height=ALTURA)
        self.filtro = CheckBox(active=c.filtro_ok, size_hint_x=None, width=ALTURA)
        lf.add_widget(self.filtro)
        lf.add_widget(rotulo("Passou no filtro obrigatório"))
        corpo.add_widget(lf)

        corpo.add_widget(rotulo("WDL (%): W / D / L — se todos tiverem, usa pontuação esperada"))
        lw = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(6))
        self.wdl = []
        for v in (c.w, c.d, c.l):
            t = TextInput(text="" if v is None else str(v), multiline=False, input_filter="float")
            self.wdl.append(t)
            lw.add_widget(t)
        corpo.add_widget(lw)

        corpo.add_widget(Label(text="[b]Núcleo estratégico[/b]", markup=True, size_hint_y=None, height=dp(36)))
        for k in ESTRATEGICOS:
            self._slider(corpo, k, getattr(c, k))
        corpo.add_widget(Label(text="[b]Notas diretas[/b]", markup=True, size_hint_y=None, height=dp(36)))
        for k in DIRETOS:
            self._slider(corpo, k, getattr(c, k))

        self.resumo = Label(size_hint_y=None, height=dp(56), markup=True)
        corpo.add_widget(self.resumo)
        self.atualizar()

        raiz = BoxLayout(orientation="vertical")
        raiz.add_widget(rolavel(corpo))
        acoes = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(8), padding=(dp(10), 0))
        acoes.add_widget(botao("Cancelar", lambda: App.get_running_app().ir("lista"), CINZA))
        acoes.add_widget(botao("Salvar", self.salvar, VERDE))
        raiz.add_widget(acoes)
        self.add_widget(raiz)

    def _slider(self, pai, chave, valor):
        linha = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(6))
        lb = Label(text=f"{ROTULOS[chave]}: {valor:.1f}", size_hint_x=0.45, halign="left", valign="middle")
        lb.bind(size=lambda w, s: setattr(w, "text_size", s))
        s = Slider(min=0, max=10, step=0.5, value=valor, size_hint_x=0.55)

        def mudou(_s, v, lb=lb, k=chave):
            lb.text = f"{ROTULOS[k]}: {v:.1f}"
            self.atualizar()
        s.bind(value=mudou)
        linha.add_widget(lb)
        linha.add_widget(s)
        pai.add_widget(linha)
        self.sliders[chave] = s

    def _candidato(self):
        notas = {k: round(s.value, 1) for k, s in self.sliders.items()}
        w, d, l = (num(t.text) for t in self.wdl)
        return Candidato(lance=self.lance.text.strip() or "?", delta=abs(num(self.delta.text, 0.0)),
                         filtro_ok=self.filtro.active, w=w, d=d, l=l, **notas)

    def atualizar(self):
        if not hasattr(self, "resumo"):
            return
        c = self._candidato()
        self.resumo.text = (f"FO {c.fo:.2f}  ·  Robustez {c.robustez:.2f}  (calculados)\n"
                            f"[b]ATP {c.atp:.2f}[/b]")

    def salvar(self):
        app = App.get_running_app()
        c = self._candidato()
        if app.indice is None:
            app.cands.append(c)
        else:
            app.cands[app.indice] = c
        app.salvar()
        app.ir("lista")


# ---------------------------------------------------------------- Texto (relatório e análises)
class TelaTexto(Screen):
    def mostrar(self, texto, botoes):
        self.clear_widgets()
        raiz = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        lb = Label(text=seguro(texto), size_hint_y=None, halign="left", valign="top",
                   font_name="RobotoMono-Regular", font_size="13sp")
        lb.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
                texture_size=lambda w, s: setattr(w, "height", s[1]))
        sv = ScrollView()
        sv.add_widget(lb)
        raiz.add_widget(sv)
        linha = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(8))
        for txt, acao, cor in botoes:
            linha.add_widget(botao(txt, acao, cor))
        raiz.add_widget(linha)
        self.add_widget(raiz)


# ---------------------------------------------------------------- Registrar posição
class TelaRegistrar(Screen):
    def carregar(self):
        app = App.get_running_app()
        r = app.ultimo
        self.clear_widgets()
        corpo = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        corpo.add_widget(titulo("Registrar posição"))
        corpo.add_widget(rotulo(f"Escolha HED: {r['escolha']}   ·   Motor: {r['saidas']['Melhor objetivo']}"))
        corpo.add_widget(rotulo("Tipo de estrutura (ex.: IQP, Carlsbad, Siciliana):"))
        self.estrutura = campo(app.ultima_estrutura)
        corpo.add_widget(self.estrutura)
        corpo.add_widget(rotulo("Lance que você jogou:"))
        lances = [c.lance for c in app.cands if c.filtro_ok] or [r["escolha"]]
        self.jogado = Spinner(text=r["escolha"], values=lances, size_hint_y=None, height=ALTURA)
        corpo.add_widget(self.jogado)
        corpo.add_widget(rotulo("Resultado da partida (pode preencher depois):"))
        self.resultado = Spinner(text="—", values=CICLO, size_hint_y=None, height=ALTURA)
        corpo.add_widget(self.resultado)
        corpo.add_widget(Label())
        acoes = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(8))
        acoes.add_widget(botao("Cancelar", app.mostrar_relatorio, CINZA))
        acoes.add_widget(botao("Registrar", self.registrar, VERDE))
        corpo.add_widget(acoes)
        self.add_widget(corpo)

    def registrar(self):
        app = App.get_running_app()
        app.ultima_estrutura = self.estrutura.text.strip()
        app.registro.append(novo_registro(app.ultimo, self.estrutura.text, self.jogado.text,
                                          RESULTADOS[self.resultado.text]))
        app.salvar()
        app.ir("registro")


# ---------------------------------------------------------------- Registro
class TelaRegistro(Screen):
    def on_enter(self, *_):
        self.montar()

    def montar(self):
        app = App.get_running_app()
        self.clear_widgets()
        raiz = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        raiz.add_widget(titulo(f"Registro ({len(app.registro)})"))
        raiz.add_widget(rotulo("Toque numa linha para mudar o resultado (— / 1 / ½ / 0)",
                               font_size="12sp"))
        lista = GridLayout(cols=1, spacing=dp(6))
        if not app.registro:
            lista.add_widget(rotulo("Vazio. Analise uma posição e toque em Registrar."))
        for i, r in reversed(list(enumerate(app.registro))):
            linha = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(6))
            ok = "=" if r["jogado"] == r["hed"] else "/="
            res = RES_TXT.get(r.get("resultado"), "—")
            b = Button(text=f"{r['data'][5:]} {r['estrutura']} | HED {r['hed']} {ok} {r['jogado']} | {res}",
                       background_normal="", background_color=(0.2, 0.22, 0.26, 1), font_size="13sp")
            b.bind(on_release=lambda _b, i=i: self.ciclar(i))
            linha.add_widget(b)
            x = Button(text="X", size_hint_x=None, width=ALTURA, background_normal="",
                       background_color=VERMELHO)
            x.bind(on_release=lambda _b, i=i: self.remover(i))
            linha.add_widget(x)
            lista.add_widget(linha)
        raiz.add_widget(rolavel(lista))
        acoes = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(8))
        acoes.add_widget(botao("Voltar", lambda: app.ir("lista"), CINZA))
        acoes.add_widget(botao("PR/CC/AC/RP", app.mostrar_analise, VERDE))
        raiz.add_widget(acoes)
        self.add_widget(raiz)

    def ciclar(self, i):
        app = App.get_running_app()
        atual = RES_TXT.get(app.registro[i].get("resultado"), "—")
        app.registro[i]["resultado"] = RESULTADOS[CICLO[(CICLO.index(atual) + 1) % len(CICLO)]]
        app.salvar()
        self.montar()

    def remover(self, i):
        app = App.get_running_app()
        app.registro.pop(i)
        app.salvar()
        self.montar()


# ---------------------------------------------------------------- App
class HEDApp(App):
    title = f"HED {VERSAO}"

    def build(self):
        self.arquivo = os.path.join(self.user_data_dir, "hed_dados.json")
        self.cands, self.registro = [], []
        self.mi_cp, self.mi_pp, self.indice = MI_CP, MI_PP, None
        self.ultimo, self.ultima_estrutura = None, ""
        self.carregar()
        self.sm = ScreenManager(transition=NoTransition())
        for nome, cls in (("lista", TelaLista), ("edicao", TelaEdicao), ("texto", TelaTexto),
                          ("registrar", TelaRegistrar), ("registro", TelaRegistro)):
            self.sm.add_widget(cls(name=nome))
        self.sm.current = "lista"
        return self.sm

    # ---- persistência
    def carregar(self):
        try:
            with open(self.arquivo, encoding="utf-8") as f:
                dados = json.load(f)
            self.mi_cp = dados.get("mi_cp", MI_CP)
            self.mi_pp = dados.get("mi_pp", MI_PP)
            self.cands = [Candidato.de_dict(d) for d in dados.get("cands", [])]
            self.registro = dados.get("registro", [])
            self.ultima_estrutura = dados.get("ultima_estrutura", "")
        except (OSError, ValueError, TypeError):
            pass

    def salvar(self):
        try:
            with open(self.arquivo, "w", encoding="utf-8") as f:
                json.dump({"mi_cp": self.mi_cp, "mi_pp": self.mi_pp,
                           "cands": [c.para_dict() for c in self.cands],
                           "registro": self.registro, "ultima_estrutura": self.ultima_estrutura},
                          f, ensure_ascii=False)
        except OSError:
            pass

    # ---- navegação
    def ir(self, nome):
        self.sm.current = nome

    def editar(self, indice):
        self.indice = indice
        c = Candidato("") if indice is None else self.cands[indice]
        self.sm.get_screen("edicao").carregar(c)
        self.ir("edicao")

    def mostrar_relatorio(self):
        r = analisar(self.cands, self.mi_cp, self.mi_pp)
        self.ultimo = r if "escolha" in r else None
        botoes = [("Voltar", lambda: self.ir("lista"), CINZA)]
        if self.ultimo:
            botoes.append(("Registrar", self.abrir_registrar, VERDE))
        self.sm.get_screen("texto").mostrar(relatorio(self.cands, self.mi_cp, self.mi_pp), botoes)
        self.ir("texto")

    def abrir_registrar(self):
        self.sm.get_screen("registrar").carregar()
        self.ir("registrar")

    def mostrar_analise(self):
        self.sm.get_screen("texto").mostrar(analise_registro(self.registro),
                                            [("Voltar", lambda: self.ir("registro"), CINZA)])
        self.ir("texto")

    def on_pause(self):
        self.salvar()
        return True


if __name__ == "__main__":
    HEDApp().run()
