"""
HED 11.1.2 — app Android (Kivy).
Telas: lista de candidatos · edição · relatório · registrar posição · registro (PR/CC/AC/RP)
       · posição (FEN → Stockfish + Lichess) · TF × Conversão · configurações.
Dados salvos em JSON no armazenamento do app.
"""
import json
import os
import threading
from dataclasses import replace

from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
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

from hed_core import (Candidato, ESTRATEGICOS, DIRETOS, ROTULOS, MI_PP, VERSAO, FILTRO_ITENS, FILTRO_ROTULOS,
                      RESULTADOS, analisar, relatorio, relatorio_tf, novo_registro, analise_registro)
import hed_fontes as F
import hed_auto as A
from hed_tabuleiro import TelaAnalise

FEN_INICIAL = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

Window.clearcolor = (0.11, 0.12, 0.14, 1)
ALTURA = dp(48)
AZUL, VERDE, CINZA, VERMELHO = (0.25, 0.45, 0.75, 1), (0.2, 0.6, 0.35, 1), (0.35, 0.35, 0.35, 1), (0.6, 0.2, 0.2, 1)
RES_TXT = {v: k for k, v in RESULTADOS.items()}
CICLO = ["—", "1", "½", "0"]


def seguro(txt: str) -> str:
    for a, b in (("→", "->"), ("×", "x"), ("⚠", "!"), ("–", "-"), ("Δ", "d"),
                 ("λ", "lambda"), ("τ", "tau"), ("≥", ">="), ("≤", "<=")):
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


def plural_notas(n):
    return "falta 1 nota" if n == 1 else f"faltam {n} notas"


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
        mi.add_widget(rotulo("Aval. melhor", font_size="13sp"))
        self.aval = TextInput(text="" if app.aval_melhor is None else str(app.aval_melhor),
                              hint_text="ex.: 0.30", multiline=False)
        mi.add_widget(self.aval)
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
            marca = ("" if c.filtro_ok else "  [filtro X]") + ("  auto" if c.auto else "")
            atp = f"ATP {c.atp:.2f}" if c.atp is not None else plural_notas(len(c.faltando()))
            b = Button(text=f"{c.lance}   perda {c.delta:.2f}{wdl}   {atp}{marca}",
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
        a2.add_widget(botao("Tabuleiro / análise", lambda: app.ir("analise"), (0.7, 0.45, 0.15, 1)))
        a2.add_widget(botao("Registro", lambda: app.ir("registro"), (0.45, 0.35, 0.6, 1)))
        raiz.add_widget(a2)
        a3 = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(8))
        a3.add_widget(botao("Configurações", lambda: app.ir("config"), CINZA))
        a3.add_widget(botao("Limpar candidatos", self.limpar, CINZA))
        raiz.add_widget(a3)
        raiz.add_widget(botao("TF × Conversão (limiar p*)", lambda: app.ir("tf"), (0.55, 0.3, 0.3, 1)))
        self.add_widget(raiz)

    def remover(self, i):
        app = App.get_running_app()
        app.cands.pop(i)
        app.salvar()
        self.montar()

    def limpar(self):
        app = App.get_running_app()
        app.cands.clear()
        app.tf_ultimo = None
        app.salvar()
        self.montar()

    def analisar(self):
        app = App.get_running_app()
        app.aval_melhor = num(self.aval.text)
        app.mi_pp = num(self.mi_pp.text, MI_PP)
        app.salvar()
        app.mostrar_relatorio()


# ---------------------------------------------------------------- Edição
class TelaEdicao(Screen):
    def carregar(self, c: Candidato):
        self.clear_widgets()
        self.sliders = {}
        self.original = c
        self.definidos = {k for k in ESTRATEGICOS + DIRETOS + ["conversao"] if getattr(c, k) is not None}
        self.auto = set(c.auto)
        corpo = GridLayout(cols=1, spacing=dp(4), padding=dp(10))

        corpo.add_widget(rotulo("Lance (ex.: e5, Rd1):"))
        self.lance = campo(c.lance)
        corpo.add_widget(self.lance)
        if c.analise:
            from hed_plano import texto as texto_analise
            info = Label(text=seguro("[b]Continuação[/b]\n" + texto_analise(c.analise)), markup=True,
                         size_hint_y=None, halign="left", valign="top", font_size="13sp")
            info.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
                      texture_size=lambda w, t: setattr(w, "height", t[1] + dp(10)))
            corpo.add_widget(info)
        corpo.add_widget(rotulo("Perda vs melhor lance do motor (peões):"))
        self.delta = campo(str(c.delta), "float")
        corpo.add_widget(self.delta)

        self.filtro_auto = "filtro" in c.auto
        corpo.add_widget(Label(text="[b]Filtro obrigatório[/b]" + (" (auto)" if self.filtro_auto else ""),
                               markup=True, size_hint_y=None, height=dp(36)))
        self.filtros = {}
        for k in FILTRO_ITENS:
            lf = BoxLayout(size_hint_y=None, height=dp(40))
            cb = CheckBox(active=c.filtro.get(k, c.filtro_ok) if c.filtro else c.filtro_ok,
                          size_hint_x=None, width=dp(44))
            cb.bind(active=lambda *_: self._mexeu_filtro())
            self.filtros[k] = cb
            lf.add_widget(cb)
            lf.add_widget(rotulo(FILTRO_ROTULOS[k], font_size="14sp"))
            corpo.add_widget(lf)

        corpo.add_widget(rotulo("WDL (%): W / D / L — se todos tiverem, usa pontuação esperada"))
        lw = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(6))
        self.wdl = []
        for v in (c.w, c.d, c.l):
            t = TextInput(text="" if v is None else str(v), multiline=False, input_filter="float")
            self.wdl.append(t)
            lw.add_widget(t)
        corpo.add_widget(lw)

        dica = Label(text="— = nota não avaliada; (auto) = estimada pelo app. Toque ou arraste para dar ou confirmar a nota.",
                     font_size="12sp", size_hint_y=None, height=dp(30), halign="left", valign="middle")
        dica.bind(size=lambda w, s: setattr(w, "text_size", s))
        corpo.add_widget(dica)
        corpo.add_widget(Label(text="[b]Núcleo estratégico[/b]", markup=True, size_hint_y=None, height=dp(36)))
        for k in ESTRATEGICOS:
            self._slider(corpo, k, getattr(c, k))
        corpo.add_widget(Label(text="[b]Notas diretas[/b]", markup=True, size_hint_y=None, height=dp(36)))
        for k in DIRETOS:
            self._slider(corpo, k, getattr(c, k))
        corpo.add_widget(Label(text="[b]Eficiência de Conversão[/b] (só pesa em posição ganha)", markup=True,
                               size_hint_y=None, height=dp(36), font_size="14sp"))
        self._slider(corpo, "conversao", c.conversao)

        self.resumo = Label(size_hint_y=None, height=dp(56), markup=True, halign="center", valign="middle")
        self.resumo.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
                         texture_size=lambda w, t: setattr(w, "height", max(dp(56), t[1] + dp(8))))
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
        txt = f"{ROTULOS[chave]}: {valor:.1f}" if valor is not None else f"{ROTULOS[chave]}: —"
        if chave in self.auto:
            txt += " (auto)"
        lb = Label(text=txt, size_hint_x=0.45, halign="left", valign="middle")
        lb.bind(size=lambda w, s: setattr(w, "text_size", s))
        s = Slider(min=0, max=10, step=0.5, value=5.0 if valor is None else valor, size_hint_x=0.55)

        def mudou(_s, v, lb=lb, k=chave):
            self.definidos.add(k)
            self.auto.discard(k)              # ajustada por você: deixa de ser estimativa
            lb.text = f"{ROTULOS[k]}: {v:.1f}"
            self.atualizar()

        def tocou(sl, toque, lb=lb, k=chave):
            # um toque no controle também avalia (permite confirmar exatamente 5,0)
            if sl.collide_point(*toque.pos) and (k not in self.definidos or k in self.auto):
                mudou(sl, sl.value, lb, k)
        s.bind(on_touch_up=tocou)
        s.bind(value=mudou)
        linha.add_widget(lb)
        linha.add_widget(s)
        pai.add_widget(linha)
        self.sliders[chave] = s

    def _candidato(self):
        notas = {k: (round(s.value, 1) if k in self.definidos else None) for k, s in self.sliders.items()}
        w, d, l = (num(t.text) for t in self.wdl)
        delta = abs(num(self.delta.text, 0.0))
        o = self.original
        # perda editada à mão: a avaliação do motor deixa de valer para este lance
        aval = o.aval_cp if abs(delta - o.delta) < 1e-9 else None
        filtro = {k: cb.active for k, cb in self.filtros.items()}
        auto = [k for k in o.auto if k in self.auto or (k == "filtro" and self.filtro_auto)]
        return replace(o, lance=self.lance.text.strip() or "?", delta=delta, filtro=filtro,
                       filtro_ok=all(filtro.values()), w=w, d=d, l=l, aval_cp=aval, auto=auto, **notas)

    def _mexeu_filtro(self):
        self.filtro_auto = False

    def atualizar(self):
        if not hasattr(self, "resumo"):
            return
        c = self._candidato()
        if c.atp is None:
            falta = ", ".join(ROTULOS[k] for k in c.faltando())
            self.resumo.text = f"[color=ffcc66]{plural_notas(len(c.faltando())).capitalize()}:[/color] {falta}"
        else:
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
        self.tf_ok = None
        tf = app.tf_ultimo
        if tf and tf.get("situacao") == "conflito":
            corpo.add_widget(rotulo(f"Você achou a linha forçada ({tf['tf']}) sem o motor?", font_size="13sp"))
            self.tf_ok = Spinner(text="—", values=["—", "sim", "não"], size_hint_y=None, height=ALTURA)
            corpo.add_widget(self.tf_ok)
        corpo.add_widget(Label())
        acoes = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(8))
        acoes.add_widget(botao("Cancelar", app.mostrar_relatorio, CINZA))
        acoes.add_widget(botao("Registrar", self.registrar, VERDE))
        corpo.add_widget(acoes)
        self.add_widget(corpo)

    def registrar(self):
        app = App.get_running_app()
        app.ultima_estrutura = self.estrutura.text.strip()
        reg = novo_registro(app.ultimo, self.estrutura.text, self.jogado.text,
                            RESULTADOS[self.resultado.text])
        if app.fen:
            reg["fen"] = app.fen
        if self.tf_ok is not None and self.tf_ok.text != "—":
            reg["tf_acertou"] = self.tf_ok.text == "sim"
            reg["tf_lances"] = app.tf_ultimo.get("lances")
        app.registro.append(reg)
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


# ---------------------------------------------------------------- Posição (FEN → motor + banco)
class TelaPosicao(Screen):
    def on_enter(self, *_):
        if not getattr(self, "montada", False):
            self.montar()

    def montar(self):
        app = App.get_running_app()
        self.montada = True
        self.clear_widgets()
        self.marcas, self.resultado = {}, None
        raiz = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(6))
        raiz.add_widget(titulo("Posição"))
        raiz.add_widget(rotulo("Cole o FEN (no Lichess: menu > Compartilhar > FEN):", font_size="13sp"))
        self.fen = TextInput(text=app.fen or "", multiline=False, size_hint_y=None, height=ALTURA,
                             font_size="13sp")
        raiz.add_widget(self.fen)
        l1 = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(6))
        l1.add_widget(botao("Colar", self.colar, CINZA))
        l1.add_widget(botao("Inicial", lambda: setattr(self.fen, "text", FEN_INICIAL), CINZA))
        self.b_analisar = botao("Analisar", self.analisar, VERDE)
        l1.add_widget(self.b_analisar)
        raiz.add_widget(l1)

        self.status = Label(text="", markup=True, size_hint_y=None, halign="left", valign="top",
                            font_size="13sp")
        self.status.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
                         texture_size=lambda w, s: setattr(w, "height", s[1] + dp(6)))
        raiz.add_widget(self.status)

        self.lista = GridLayout(cols=1, spacing=dp(4))
        raiz.add_widget(rolavel(self.lista))

        l2 = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(6))
        l2.add_widget(botao("Voltar", lambda: app.ir("lista"), CINZA))
        self.b_importar = botao("Importar marcados", self.importar, AZUL)
        l2.add_widget(self.b_importar)
        raiz.add_widget(l2)
        self.add_widget(raiz)

    def colar(self):
        try:
            self.fen.text = " ".join((Clipboard.paste() or "").split())
        except Exception:
            pass

    def _status(self, txt):
        self.status.text = seguro(txt)

    def analisar(self):
        app = App.get_running_app()
        fen = " ".join(self.fen.text.split())
        try:
            F.validar_fen(fen)
        except F.FonteErro as e:
            self._status(f"[color=ff7777]{e}[/color]")
            return
        self.b_analisar.disabled = True
        self.lista.clear_widgets()
        self._status("Iniciando…")

        def progresso(s):
            Clock.schedule_once(lambda dt: self._status(s))

        def trabalho():
            try:
                motor = app.obter_motor() if app.cfg["motor"] == "Stockfish local" else None
                r = F.coletar(fen, app.cfg, motor, progresso, A.taxa_acerto_tf(app.registro))
                Clock.schedule_once(lambda dt: self.mostrar(r))
            except Exception as e:
                msg = str(e)
                Clock.schedule_once(lambda dt: self._erro(msg))

        threading.Thread(target=trabalho, daemon=True).start()

    def _erro(self, msg):
        self.b_analisar.disabled = False
        self._status(f"[color=ff7777]Erro: {msg}[/color]")

    def mostrar(self, r):
        app = App.get_running_app()
        self.b_analisar.disabled = False
        self.resultado = r
        app.fen = r["fen"]
        app.salvar()
        cab = [f"Joga: [b]{r['lado']}[/b]"]
        if r["abertura"]:
            cab.append(f"Abertura: {r['abertura']}")
        if r["fonte"]:
            cab.append(f"Motor: {r['fonte']} (prof. {r['prof']})")
        if r.get("total_masters") is not None:
            cab.append(f"Masters: {r['total_masters']} jogos | Lichess: {r.get('total_lichess', 0)} jogos")
        for a in r["avisos"]:
            cab.append(f"[color=ffcc66]! {a}[/color]")
        if r.get("tf"):
            cab.append(f"[color=99ccff]TF x Conversão: {r['tf']['texto']}[/color]")
        cab.append("[size=12sp]E = pontuação esperada | M/L = jogos e pontos nos bancos Masters/Lichess[/size]")
        self._status("\n".join(cab))

        self.lista.clear_widgets()
        self.marcas = {}
        ref = F.melhor_cp(r["opcoes"])
        for o in r["opcoes"]:
            linha = BoxLayout(size_hint_y=None, height=dp(58), spacing=dp(4))
            cb = CheckBox(size_hint_x=None, width=dp(40),
                          active=bool(o.multipv and o.multipv <= 3 and o.cp is not None),
                          disabled=o.cp is None)
            self.marcas[o.uci] = cb
            linha.add_widget(cb)
            txt = F.linha_texto(o, ref) + ("\n  " + " ".join(o.pv) if o.pv else "")
            lb = Label(text=seguro(txt), font_name="RobotoMono-Regular", font_size="12sp",
                       halign="left", valign="middle")
            lb.bind(size=lambda w, s: setattr(w, "text_size", s))
            linha.add_widget(lb)
            self.lista.add_widget(linha)

    def importar(self):
        app = App.get_running_app()
        if not self.resultado:
            self._status("Analise uma posição primeiro.")
            return
        ops = [o for o in self.resultado["opcoes"] if self.marcas.get(o.uci) and self.marcas[o.uci].active]
        if not ops:
            self._status("Marque pelo menos um lance avaliado.")
            return
        ref = F.melhor_cp(self.resultado["opcoes"])
        import chess
        board = chess.Board(self.resultado["fen"])
        app.cands = [F.para_candidato(o, ref, board) for o in ops]
        app.tf_ultimo = self.resultado.get("tf")
        app.salvar()
        app.ir("lista")


# ---------------------------------------------------------------- TF × Conversão
class TelaTF(Screen):
    """Regra de conflito da 11.1.2: a TF só vence o lance tranquilo se p > p*."""

    def on_enter(self, *_):
        if not getattr(self, "montada", False):
            self.montar()
            self.usar_ultima(silencioso=True)

    def montar(self):
        app = App.get_running_app()
        self.montada = True
        self.clear_widgets()
        corpo = GridLayout(cols=1, spacing=dp(4), padding=dp(10))
        corpo.add_widget(titulo("TF × Conversão"))
        ajuda = Label(text="Avaliações em peões, do ponto de vista de quem joga (ex.: 2.0, -1.5).",
                      font_size="12sp", size_hint_y=None, height=dp(30), halign="left", valign="middle")
        ajuda.bind(size=lambda w, s: setattr(w, "text_size", s))
        corpo.add_widget(ajuda)
        self.campos = {}
        for chave, txt, padrao in (("tranq", "Depois do lance tranquilo:", ""),
                                   ("fim", "Fim da TF, se o cálculo estiver certo:", ""),
                                   ("falha", "Se o cálculo estiver errado:", ""),
                                   ("p", "Sua confiança no cálculo (%):", "")):
            corpo.add_widget(rotulo(txt))
            t = campo(app.tf.get(chave, padrao))
            if chave == "p":
                t.hint_text = "opcional (com motor: 100)"
            self.campos[chave] = t
            corpo.add_widget(t)
        corpo.add_widget(botao("Usar a última análise do motor", self.usar_ultima, AZUL))
        self.saida = Label(text="", size_hint_y=None, halign="left", valign="top",
                           font_name="RobotoMono-Regular", font_size="13sp")
        self.saida.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
                        texture_size=lambda w, t: setattr(w, "height", t[1] + dp(8)))
        corpo.add_widget(self.saida)

        raiz = BoxLayout(orientation="vertical")
        raiz.add_widget(rolavel(corpo))
        acoes = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(8), padding=(dp(10), 0))
        acoes.add_widget(botao("Voltar", lambda: app.ir("lista"), CINZA))
        acoes.add_widget(botao("Calcular", self.calcular, VERDE))
        raiz.add_widget(acoes)
        self.add_widget(raiz)

    def on_pre_enter(self, *_):
        if getattr(self, "montada", False):
            self.usar_ultima(silencioso=True)

    def usar_ultima(self, silencioso=False):
        app = App.get_running_app()
        tf = app.tf_ultimo
        if not tf or tf.get("situacao") != "conflito" or tf.get("falha_cp") is None:
            if tf:
                # a última análise não tem TF a medir: nada de números de exemplo na tela
                for t in self.campos.values():
                    t.text = ""
                self.saida.text = seguro("Última análise: " + tf["texto"] +
                                         "\n\nPara um cálculo manual, preencha as avaliações e toque em Calcular.")
            elif not silencioso:
                self.saida.text = "Sem análise do motor com TF. Analise uma posição (Tabuleiro ou FEN)."
            return
        for k, v in (("tranq", tf["tranq_cp"]), ("fim", tf["fim_cp"]), ("falha", tf["falha_cp"])):
            self.campos[k].text = f"{v / 100:.2f}"
        self.campos["p"].text = f"{100 * tf['p']:.0f}"
        self.calcular()
        self.saida.text += seguro(f"\n\nTF {tf['tf']} × tranquilo {tf['tranquilo']}\n"
                                  f"Linha: {' '.join(tf.get('pv', []))}\nAcerto: {tf['fonte_p']}")

    def calcular(self):
        app = App.get_running_app()
        v = {k: num(t.text) for k, t in self.campos.items()}
        if None in (v["tranq"], v["fim"], v["falha"]):
            self.saida.text = "Preencha as três avaliações."
            return
        app.tf = {k: t.text for k, t in self.campos.items()}
        app.salvar()
        p = None if v["p"] is None else max(0.0, min(100.0, v["p"])) / 100
        self.saida.text = seguro(relatorio_tf(v["tranq"] * 100, v["fim"] * 100, v["falha"] * 100, p))


# ---------------------------------------------------------------- Configurações
class TelaConfig(Screen):
    def on_enter(self, *_):
        self.montar()

    def montar(self):
        app = App.get_running_app()
        c = app.cfg
        self.clear_widgets()
        corpo = GridLayout(cols=1, spacing=dp(4), padding=dp(10))
        corpo.add_widget(titulo("Configurações"))

        corpo.add_widget(rotulo("Token do Lichess (para o banco de partidas):"))
        self.token = campo(c["token"])
        self.token.password = True
        corpo.add_widget(self.token)
        ajuda = Label(text="Crie em lichess.org/account/oauth/token\nsem marcar nenhuma permissão. "
                           "Fica salvo só neste celular.",
                      font_size="12sp", size_hint_y=None, height=dp(40), halign="left", valign="middle")
        ajuda.bind(size=lambda w, s: setattr(w, "text_size", s))
        corpo.add_widget(ajuda)

        corpo.add_widget(rotulo("Motor:"))
        self.motor = Spinner(text=c["motor"], values=["Stockfish local", "Lichess nuvem"],
                             size_hint_y=None, height=ALTURA)
        corpo.add_widget(self.motor)

        self.sl = {}
        for chave, rot, mn, mx, passo in (("tempo", "Tempo por busca (s)", 1, 20, 1),
                                          ("multipv", "Linhas do motor (MultiPV)", 1, 8, 1),
                                          ("extras", "Lances do banco a avaliar", 0, 5, 1),
                                          ("prof_vivo", "Profundidade ao vivo (tabuleiro)", 14, 40, 1)):
            linha = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(6))
            lb = Label(text=f"{rot}: {c[chave]:.0f}", size_hint_x=0.55, halign="left", valign="middle")
            lb.bind(size=lambda w, s: setattr(w, "text_size", s))
            s = Slider(min=mn, max=mx, step=passo, value=float(c[chave]), size_hint_x=0.45)
            s.bind(value=lambda _s, v, lb=lb, rot=rot: setattr(lb, "text", f"{rot}: {v:.0f}"))
            linha.add_widget(lb)
            linha.add_widget(s)
            corpo.add_widget(linha)
            self.sl[chave] = s

        corpo.add_widget(rotulo("Banco Lichess — faixas de rating:"))
        self.ratings = campo(c["ratings"])
        corpo.add_widget(self.ratings)
        corpo.add_widget(rotulo("Banco Lichess — ritmos:"))
        self.speeds = campo(c["speeds"])
        corpo.add_widget(self.speeds)

        sf = F.caminho_stockfish()
        corpo.add_widget(rotulo(f"Stockfish no aparelho: {'encontrado' if sf else 'não encontrado'}",
                                font_size="12sp"))

        raiz = BoxLayout(orientation="vertical")
        raiz.add_widget(rolavel(corpo))
        acoes = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(8), padding=(dp(10), 0))
        acoes.add_widget(botao("Cancelar", lambda: app.ir("lista"), CINZA))
        acoes.add_widget(botao("Salvar", self.salvar, VERDE))
        raiz.add_widget(acoes)
        self.add_widget(raiz)

    def salvar(self):
        app = App.get_running_app()
        app.cfg.update(token=self.token.text.strip(), motor=self.motor.text,
                       ratings=self.ratings.text.strip() or F.CFG_PADRAO["ratings"],
                       speeds=self.speeds.text.strip() or F.CFG_PADRAO["speeds"],
                       **{k: int(s.value) for k, s in self.sl.items()})
        app.salvar()
        app.ir("lista")


# ---------------------------------------------------------------- App
class HEDApp(App):
    title = f"HED {VERSAO}"

    def build(self):
        self.arquivo = os.path.join(self.user_data_dir, "hed_dados.json")
        self.cands, self.registro = [], []
        self.aval_melhor, self.mi_pp, self.indice = None, MI_PP, None
        self.tf = {}
        self.tf_ultimo = None
        self.ultimo, self.ultima_estrutura = None, ""
        self.cfg, self.fen = dict(F.CFG_PADRAO), ""
        self.partida = {"inicio": FEN_INICIAL, "lances": [], "idx": 0}
        self.motor, self._trava_motor = None, threading.Lock()
        self.carregar()
        self.sm = ScreenManager(transition=NoTransition())
        for nome, cls in (("lista", TelaLista), ("edicao", TelaEdicao), ("texto", TelaTexto),
                          ("registrar", TelaRegistrar), ("registro", TelaRegistro),
                          ("posicao", TelaPosicao), ("config", TelaConfig), ("analise", TelaAnalise),
                          ("tf", TelaTF)):
            self.sm.add_widget(cls(name=nome))
        self.sm.current = "lista"
        return self.sm

    # ---- motor (iniciado na primeira análise, reaproveitado depois)
    def obter_motor(self):
        with self._trava_motor:
            if self.motor is None:
                caminho = F.caminho_stockfish()
                if caminho:
                    try:
                        self.motor = F.MotorVivo(caminho)
                    except Exception:
                        self.motor = None
            return self.motor

    def on_stop(self):
        if self.motor:
            self.motor.fechar()

    # ---- persistência
    def carregar(self):
        try:
            with open(self.arquivo, encoding="utf-8") as f:
                dados = json.load(f)
            self.aval_melhor = dados.get("aval_melhor")
            self.mi_pp = dados.get("mi_pp", MI_PP)
            self.tf = dados.get("tf", {})
            self.tf_ultimo = dados.get("tf_ultimo")
            self.cands = [Candidato.de_dict(d) for d in dados.get("cands", [])]
            self.registro = dados.get("registro", [])
            self.ultima_estrutura = dados.get("ultima_estrutura", "")
            self.cfg.update(dados.get("cfg", {}))
            self.fen = dados.get("fen", "")
            self.partida = dados.get("partida", self.partida)
        except (OSError, ValueError, TypeError):
            pass

    def salvar(self):
        try:
            with open(self.arquivo, "w", encoding="utf-8") as f:
                json.dump({"aval_melhor": self.aval_melhor, "mi_pp": self.mi_pp, "tf": self.tf, "tf_ultimo": self.tf_ultimo,
                           "cands": [c.para_dict() for c in self.cands],
                           "registro": self.registro, "ultima_estrutura": self.ultima_estrutura,
                           "cfg": self.cfg, "fen": self.fen, "partida": self.partida},
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
        aval = None if self.aval_melhor is None else self.aval_melhor * 100
        r = analisar(self.cands, aval, self.mi_pp)
        self.ultimo = r if "escolha" in r else None
        botoes = [("Voltar", lambda: self.ir("lista"), CINZA)]
        if self.ultimo:
            botoes.append(("Registrar", self.abrir_registrar, VERDE))
        self.sm.get_screen("texto").mostrar(relatorio(self.cands, aval, self.mi_pp, self.tf_ultimo), botoes)
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
