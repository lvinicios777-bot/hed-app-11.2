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
import hed_livro as LV
from hed_tabuleiro import TelaAnalise, TabuleiroPlano

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


def escolher_epub(pasta_destino, ao_terminar, nome="livro.epub"):
    """Abre o seletor de arquivos do Android e copia o arquivo escolhido para a pasta do app."""
    try:
        from jnius import autoclass
        from android import activity
    except ImportError:
        ao_terminar(None, "seletor disponível só no Android; use o campo de caminho")
        return
    Intent = autoclass("android.content.Intent")
    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    pedido = 7341
    destino = os.path.join(pasta_destino, nome)

    def resultado(codigo, resposta, dados):
        if codigo != pedido:
            return
        activity.unbind(on_activity_result=resultado)
        if resposta != -1 or dados is None:
            Clock.schedule_once(lambda dt: ao_terminar(None, "nenhum arquivo escolhido"))
            return
        try:
            uri = dados.getData()
            entrada = PythonActivity.mActivity.getContentResolver().openInputStream(uri)
            versao = autoclass("android.os.Build$VERSION").SDK_INT
            if versao >= 29:
                saida = autoclass("java.io.FileOutputStream")(destino)
                autoclass("android.os.FileUtils").copy(entrada, saida)
                saida.close()
            else:
                Paths = autoclass("java.nio.file.Paths")
                Files = autoclass("java.nio.file.Files")
                Opcao = autoclass("java.nio.file.StandardCopyOption")
                Files.copy(entrada, Paths.get(destino, []), [Opcao.REPLACE_EXISTING])
            entrada.close()
            Clock.schedule_once(lambda dt: ao_terminar(destino, None))
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            Clock.schedule_once(lambda dt: ao_terminar(None, msg))

    activity.bind(on_activity_result=resultado)
    intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
    intent.addCategory(Intent.CATEGORY_OPENABLE)
    intent.setType("*/*")
    PythonActivity.mActivity.startActivityForResult(intent, pedido)


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
                lc0 = app.obter_lc0() if app.cfg.get("wdl", "Lc0") == "Lc0" else None
                r = F.coletar(fen, app.cfg, motor, progresso, A.taxa_acerto_tf(app.registro), lc0)
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
        if r.get("fonte_wdl"):
            cab.append(f"WDL: {r['fonte_wdl']}")
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
        livro = app.livro()
        app.cands = [F.para_candidato(o, ref, board, livro) for o in ops]
        app.tf_ultimo = self.resultado.get("tf")
        app.salvar()
        app.ir("lista")


# ---------------------------------------------------------------- Resumo (tela principal do resultado)
CONFIANCA = {"A+": ("muito alta", (0.2, 0.6, 0.35, 1)), "A": ("alta", (0.2, 0.6, 0.35, 1)),
             "B": ("boa", (0.25, 0.45, 0.75, 1)), "C": ("média", (0.75, 0.55, 0.15, 1)),
             "D": ("baixa", (0.6, 0.2, 0.2, 1))}
SELO = {"recomendado": ("RECOMENDADO", (0.2, 0.6, 0.35, 1)), "alternativa": ("BOA ALTERNATIVA", (0.25, 0.45, 0.75, 1)),
        "possivel": ("POSSÍVEL", (0.35, 0.35, 0.35, 1)), "inferior": ("INFERIOR", (0.55, 0.45, 0.2, 1)),
        "evitar": ("EVITAR", (0.6, 0.2, 0.2, 1))}


def texto_quebrado(txt, tamanho="15sp", **kw):
    lb = Label(text=txt, size_hint_y=None, halign="left", valign="top", font_size=tamanho, markup=True, **kw)
    lb.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
            texture_size=lambda w, t: setattr(w, "height", t[1] + dp(4)))
    return lb


class TelaResumo(Screen):
    def mostrar(self, r):
        app = App.get_running_app()
        self.clear_widgets()
        raiz = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        corpo = GridLayout(cols=1, spacing=dp(8))
        if "escolha" not in r:
            corpo.add_widget(titulo("Ainda não dá para decidir"))
            for a in r.get("avisos", []):
                corpo.add_widget(texto_quebrado(seguro("• " + a)))
        else:
            nivel = r["ife"][0]
            conf, cor = CONFIANCA[nivel]
            corpo.add_widget(Label(text="JOGUE", font_size="16sp", size_hint_y=None, height=dp(24)))
            corpo.add_widget(Label(text=f"[b]{r['escolha']}[/b]", markup=True, font_size="44sp",
                                   size_hint_y=None, height=dp(60)))
            caixa = Button(text=f"Confiança {conf}", background_normal="", background_color=cor,
                           size_hint_y=None, height=dp(36), font_size="15sp")
            corpo.add_widget(caixa)
            corpo.add_widget(texto_quebrado(seguro(self._porque(r))))
            corpo.add_widget(Label(text="[b]Os lances analisados[/b]", markup=True, size_hint_y=None,
                                   height=dp(30)))
            for c, selo, motivo in self._cartoes(r):
                corpo.add_widget(self._cartao(c, selo, motivo))
        raiz.add_widget(rolavel(corpo))
        acoes = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(6))
        acoes.add_widget(botao("Voltar", lambda: app.ir("lista"), CINZA))
        acoes.add_widget(botao("Detalhes", app.mostrar_detalhes, AZUL))
        if "escolha" in r:
            acoes.add_widget(botao("Registrar", app.abrir_registrar, VERDE))
        raiz.add_widget(acoes)
        self.add_widget(raiz)

    def _porque(self, r):
        app = App.get_running_app()
        esc = next(c for c in app.cands if c.lance == r["escolha"])
        if r.get("empate"):
            outros = [x for x in r["empate"] if x != esc.lance]
            base = (f"{esc.lance} e {', '.join(outros)} ficaram praticamente empatados; "
                    f"{esc.lance} é o de menor risco se a sua leitura estiver errada.")
        elif r["ife"][1] is None:
            base = f"{esc.lance} foi o único lance que passou em todos os critérios."
        else:
            base = f"{esc.lance} tem a melhor combinação entre a avaliação do motor e o seu estilo."
        a = esc.analise or {}
        pros = [x for x in a.get("pro", []) if "plano(s) claro(s)" not in x]
        if pros:
            base += " A favor: " + ", ".join(pros[:2]) + "."
        if a.get("fco"):
            base += f" Livro: {a['fco']['capitulo']} ({a.get('fco_tom', '')})."
        if r["ife"][0] == "D":
            base += " Os lances empatados são equivalentes na prática: não gaste relógio aqui."
        return base

    def _cartoes(self, r):
        app = App.get_running_app()
        elim = dict(r.get("eliminados", []))
        empat = set(r.get("empate", []))
        dom = set(r.get("dominados", []))
        U = r.get("U", {})
        ordem = sorted(app.cands, key=lambda c: (c.lance != r["escolha"], c.lance in elim, -U.get(c.lance, -99)))
        out = []
        def util(lista):
            return [x for x in lista if "plano(s) claro(s)" not in x]

        for c in ordem:
            a = dict(c.analise or {})
            a["pro"], a["contra"] = util(a.get("pro", [])), util(a.get("contra", []))
            if c.lance == r["escolha"]:
                selo, motivo = "recomendado", (a.get("pro") or ["melhor no conjunto"])[0]
            elif c.lance in elim:
                selo, motivo = "evitar", elim[c.lance]
            elif c.lance in dom:
                selo, motivo = "inferior", "outro lance é melhor ou igual em tudo"
            elif c.lance in empat:
                selo, motivo = "alternativa", (a.get("pro") or ["praticamente igual ao recomendado"])[0]
            else:
                selo, motivo = "possivel", (a.get("contra") or ["um pouco abaixo no conjunto"])[0]
            out.append((c, selo, motivo))
        return out

    def _cartao(self, c, selo, motivo):
        app = App.get_running_app()
        nome, cor = SELO[selo]
        caixa = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(112), spacing=dp(2))
        topo = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(6))
        topo.add_widget(Label(text=f"[b]{c.lance}[/b]", markup=True, font_size="20sp", size_hint_x=0.3))
        topo.add_widget(Button(text=nome, background_normal="", background_color=cor, font_size="13sp",
                               size_hint_x=0.7))
        caixa.add_widget(topo)
        perda = "igual ao melhor do motor" if c.delta < 0.005 else f"{c.delta:.2f} peão abaixo do melhor do motor"
        caixa.add_widget(texto_quebrado(seguro(f"{perda} · {motivo}"), "13sp"))
        if c.analise:
            caixa.add_widget(botao(f"Ver o plano com {c.lance}", lambda c=c: app.mostrar_plano(c), AZUL))
        return caixa


# ---------------------------------------------------------------- Plano de jogo de um lance
class TelaPlano(Screen):
    def mostrar(self, c):
        import chess
        from hed_plano import plano_de_jogo
        app = App.get_running_app()
        self.clear_widgets()
        a = c.analise
        b = chess.Board(a["fen"])
        pl = plano_de_jogo(b, a["linha"].split(), a)
        raiz = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        corpo = GridLayout(cols=1, spacing=dp(6))
        corpo.add_widget(titulo(f"Plano com {c.lance}"))
        corpo.add_widget(texto_quebrado(seguro(f"Depois de: {a['linha']}"), "12sp"))
        tab = TabuleiroPlano(size_hint_y=None, height=min(Window.width - dp(16), Window.height * 0.5))
        tab.mostrar(pl["fen"], pl["passos"], pl["cuidado"], girado=(b.turn == chess.BLACK))
        corpo.add_widget(tab)
        corpo.add_widget(texto_quebrado(seguro(f"[b]Objetivo:[/b] {pl['objetivo']}"), "16sp"))
        if pl["passos"]:
            corpo.add_widget(texto_quebrado("[b][color=33cc55]Como fazer (setas verdes)[/color][/b]", "15sp"))
            for i, p in enumerate(pl["passos"], 1):
                corpo.add_widget(texto_quebrado(seguro(f"[b]{i}.[/b] {p['texto']}"), "14sp"))
        else:
            corpo.add_widget(texto_quebrado("[b][color=33cc55]Como fazer[/color][/b]", "15sp"))
            corpo.add_widget(texto_quebrado("Sem passo concreto claro nesta posição: siga a linha do motor "
                                            "(botão Linha no tabuleiro) e reavalie depois.", "14sp"))
        if pl["cuidado"]:
            corpo.add_widget(texto_quebrado("[b][color=ff5555]Vigie (setas vermelhas)[/color][/b]", "15sp"))
            for p in pl["cuidado"]:
                corpo.add_widget(texto_quebrado(seguro("• " + p["texto"]), "14sp"))
        f = a.get("fco")
        if f:
            ideias = (" Ideias do livro: " + ", ".join(pl["ideias_livro"]) + ".") if pl["ideias_livro"] else ""
            corpo.add_widget(texto_quebrado(seguro(
                f"[b]Livro:[/b] {f['capitulo']} — {f['secao']} (tom: {a.get('fco_tom', '—')}).{ideias}"), "14sp"))
            self.trecho = texto_quebrado("", "13sp")
            corpo.add_widget(botao("Ler o trecho do livro", lambda: self._trecho(f), CINZA))
            corpo.add_widget(self.trecho)
        raiz.add_widget(rolavel(corpo))
        acoes = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(6))
        acoes.add_widget(botao("Voltar", lambda: app.ir("resumo"), CINZA))
        acoes.add_widget(botao("Linha no tabuleiro", lambda: app.sm.get_screen("planos").ver_linha(c), AZUL))
        raiz.add_widget(acoes)
        self.add_widget(raiz)

    def _trecho(self, f):
        if self.trecho.text:
            self.trecho.text = ""
        else:
            self.trecho.text = seguro("\n\n".join("« " + t + " »" for t in f.get("trechos", [])[:2]))


# ---------------------------------------------------------------- Planos
class TelaPlanos(Screen):
    """Ficha de cada lance: a favor × contra, planos, casa ideal das peças, rupturas; linha no tabuleiro."""

    def mostrar(self):
        from hed_plano import texto_planos
        app = App.get_running_app()
        self.clear_widgets()
        raiz = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        raiz.add_widget(titulo("Planos de cada lance"))
        lista = GridLayout(cols=1, spacing=dp(10))
        cands = [c for c in app.cands if c.analise]
        if not cands:
            lista.add_widget(rotulo("Importe lances do motor (Tabuleiro → Enviar ao HED) para ver os planos."))
        for c in cands:
            lb = Label(text=seguro(texto_planos(c.lance, c.analise)), size_hint_y=None, halign="left",
                       valign="top", font_name="RobotoMono-Regular", font_size="13sp")
            lb.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
                    texture_size=lambda w, t: setattr(w, "height", t[1] + dp(6)))
            lista.add_widget(lb)
            lista.add_widget(botao(f"Ver a linha de {c.lance} no tabuleiro", lambda c=c: self.ver_linha(c), AZUL))
        raiz.add_widget(rolavel(lista))
        acoes = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(8))
        acoes.add_widget(botao("Voltar", app.mostrar_relatorio, CINZA))
        if app.partida_backup:
            acoes.add_widget(botao("Restaurar minha partida", self.restaurar, (0.7, 0.45, 0.15, 1)))
        raiz.add_widget(acoes)
        self.add_widget(raiz)

    def ver_linha(self, c):
        """Abre a linha no tabuleiro, logo após o lance candidato; > avança pela continuação."""
        import copy
        app = App.get_running_app()
        if not app.partida_backup:
            app.partida_backup = copy.deepcopy(app.partida)    # guarda a sua partida
        app.partida = {"inicio": c.analise["fen"], "lances": list(c.analise.get("linha_uci", [])), "idx": 1}
        app.salvar()
        app.ir("analise")

    def restaurar(self):
        app = App.get_running_app()
        app.partida, app.partida_backup = app.partida_backup, None
        app.salvar()
        app.ir("analise")


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
        corpo.add_widget(rotulo(f"Stockfish no aparelho: {'encontrado' if sf else 'não encontrado'}"
                                + (f" — último erro: {app.motor_erro}" if app.motor_erro else ""),
                                font_size="12sp"))
        corpo.add_widget(botao("Testar Stockfish", self.testar_motor, AZUL))

        corpo.add_widget(Label(text="[b]Lc0 (WDL dos lances)[/b]", markup=True, size_hint_y=None, height=dp(36)))
        corpo.add_widget(rotulo("WDL usado na decisão:"))
        self.fonte_wdl = Spinner(text=c.get("wdl", "Lc0"), values=["Lc0", "Stockfish"], size_hint_y=None,
                                 height=ALTURA)
        corpo.add_widget(self.fonte_wdl)
        rede = app.arquivo_rede_lc0
        self.status_lc0 = rotulo(
            ("Rede carregada: " + f"{os.path.getsize(rede) / 1e6:.1f} MB") if os.path.isfile(rede)
            else "Nenhuma rede carregada (ex.: LD2.pb.gz).", font_size="12sp")
        corpo.add_widget(self.status_lc0)
        if app.lc0_erro:
            corpo.add_widget(rotulo(f"Último erro do Lc0: {app.lc0_erro}", font_size="12sp"))
        corpo.add_widget(botao("Carregar rede do Lc0 (.pb.gz)", self.escolher_rede, AZUL))
        corpo.add_widget(botao("Testar Lc0", self.testar_lc0, AZUL))

        corpo.add_widget(Label(text="[b]Livro de aberturas (EPUB, ex.: FCO)[/b]", markup=True,
                               size_hint_y=None, height=dp(36)))
        ind = app.livro()
        self.status_livro = rotulo(
            f"Carregado: {len(ind['posicoes'])} posições indexadas" if ind else "Nenhum livro carregado.",
            font_size="12sp")
        corpo.add_widget(self.status_livro)
        corpo.add_widget(botao("Carregar livro (escolher EPUB)", self.escolher_livro, AZUL))
        self.caminho_livro = campo("")
        self.caminho_livro.hint_text = "ou o caminho do arquivo .epub"
        corpo.add_widget(self.caminho_livro)
        corpo.add_widget(botao("Usar este caminho", lambda: self.indexar_livro(self.caminho_livro.text.strip()),
                               CINZA))
        nota = Label(text="O livro fica só neste celular: o app lê o seu arquivo e guarda um índice local.",
                     font_size="12sp", size_hint_y=None, height=dp(36), halign="left", valign="middle")
        nota.bind(size=lambda w, s: setattr(w, "text_size", s))
        corpo.add_widget(nota)

        raiz = BoxLayout(orientation="vertical")
        raiz.add_widget(rolavel(corpo))
        acoes = BoxLayout(size_hint_y=None, height=ALTURA, spacing=dp(8), padding=(dp(10), 0))
        acoes.add_widget(botao("Cancelar", lambda: app.ir("lista"), CINZA))
        acoes.add_widget(botao("Salvar", self.salvar, VERDE))
        raiz.add_widget(acoes)
        self.add_widget(raiz)

    def escolher_rede(self):
        app = App.get_running_app()
        self.status_lc0.text = "Abrindo o seletor de arquivos…"

        def pronto(caminho, erro):
            if caminho:
                app.fechar_lc0()                       # reinicia o Lc0 com a rede nova
                self.status_lc0.text = f"Rede carregada: {os.path.getsize(caminho) / 1e6:.1f} MB"
            else:
                self.status_lc0.text = f"Não carregada: {erro}"
        escolher_epub(app.user_data_dir, pronto, nome="lc0_rede.pb.gz")

    def testar_lc0(self):
        app = App.get_running_app()
        tela = app.sm.get_screen("texto")
        tela.mostrar("Testando o Lc0… (até 90 s)", [("Voltar", lambda: app.ir("config"), CINZA)])
        app.ir("texto")

        def trabalho():
            app.fechar_lc0()
            txt = F.diagnostico_lc0(app.arquivo_rede_lc0)
            Clock.schedule_once(lambda dt: tela.mostrar(txt, [("Voltar", lambda: app.ir("config"), CINZA)]))
        threading.Thread(target=trabalho, daemon=True).start()

    def escolher_livro(self):
        app = App.get_running_app()
        self.status_livro.text = "Abrindo o seletor de arquivos…"
        escolher_epub(app.user_data_dir, lambda caminho, erro: (
            self.indexar_livro(caminho) if caminho else setattr(self.status_livro, "text", f"Não carregado: {erro}")))

    def indexar_livro(self, caminho):
        app = App.get_running_app()
        if not caminho or not os.path.isfile(caminho):
            self.status_livro.text = "Arquivo não encontrado."
            return
        self.status_livro.text = "Indexando o livro…"

        def trabalho():
            try:
                ind = LV.indexar_epub(caminho, lambda t: Clock.schedule_once(
                    lambda dt: setattr(self.status_livro, "text", t)))
                LV.salvar_indice(ind, app.arquivo_livro)
                txt = (f"Carregado: {len(ind['posicoes'])} posições indexadas "
                       f"({ind['lances_lidos']} lances lidos).")
            except Exception as e:
                txt = f"Não consegui ler o livro: {type(e).__name__}: {e}"
            Clock.schedule_once(lambda dt: setattr(self.status_livro, "text", txt))
        threading.Thread(target=trabalho, daemon=True).start()

    def testar_motor(self):
        app = App.get_running_app()
        tela = app.sm.get_screen("texto")
        tela.mostrar("Testando o Stockfish… (até 40 s)", [("Voltar", lambda: app.ir("config"), CINZA)])
        app.ir("texto")

        def trabalho():
            txt = F.diagnostico_stockfish()
            Clock.schedule_once(lambda dt: tela.mostrar(txt, [("Voltar", lambda: app.ir("config"), CINZA)]))
        threading.Thread(target=trabalho, daemon=True).start()

    def salvar(self):
        app = App.get_running_app()
        app.cfg.update(wdl=self.fonte_wdl.text, token=self.token.text.strip(), motor=self.motor.text,
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
        self.arquivo_livro = os.path.join(self.user_data_dir, "livro_indice.json")
        self.arquivo_rede_lc0 = os.path.join(self.user_data_dir, "lc0_rede.pb.gz")
        self.cands, self.registro = [], []
        self.aval_melhor, self.mi_pp, self.indice = None, MI_PP, None
        self.tf = {}
        self.tf_ultimo = None
        self.partida_backup = None
        self.ultimo, self.ultima_estrutura = None, ""
        self.cfg, self.fen = dict(F.CFG_PADRAO), ""
        self.partida = {"inicio": FEN_INICIAL, "lances": [], "idx": 0}
        self.motor, self._trava_motor = None, threading.Lock()
        self.motor_erro = ""
        self.lc0, self.lc0_erro, self._trava_lc0 = None, "", threading.Lock()
        self.carregar()
        self.sm = ScreenManager(transition=NoTransition())
        for nome, cls in (("lista", TelaLista), ("edicao", TelaEdicao), ("texto", TelaTexto),
                          ("registrar", TelaRegistrar), ("registro", TelaRegistro),
                          ("posicao", TelaPosicao), ("config", TelaConfig), ("analise", TelaAnalise),
                          ("tf", TelaTF), ("planos", TelaPlanos), ("resumo", TelaResumo),
                          ("plano", TelaPlano)):
            self.sm.add_widget(cls(name=nome))
        self.sm.current = "lista"
        return self.sm

    # ---- motor (iniciado na primeira análise, reaproveitado depois)
    def obter_motor(self):
        with self._trava_motor:
            if self.motor is None:
                caminho = F.caminho_stockfish()
                if not caminho:
                    self.motor_erro = "binário não encontrado (veja Configurações → Testar Stockfish)"
                else:
                    try:
                        self.motor = F.MotorVivo(caminho)
                        self.motor_erro = ""
                    except Exception as e:
                        self.motor = None
                        self.motor_erro = f"{type(e).__name__}: {e}"
            return self.motor

    def obter_lc0(self):
        """Lc0 com a rede do jogador (WeightsFile); None se faltar binário ou rede."""
        with self._trava_lc0:
            if self.lc0 is None:
                caminho = F.caminho_lc0()
                if not caminho:
                    self.lc0_erro = "binário do Lc0 não encontrado"
                elif not os.path.isfile(self.arquivo_rede_lc0):
                    self.lc0_erro = "rede não carregada (Configurações → Carregar rede do Lc0)"
                else:
                    try:
                        self.lc0 = F.MotorVivo(caminho, nome="Lc0",
                                               opcoes={"WeightsFile": self.arquivo_rede_lc0, "Threads": "2"})
                        self.lc0_erro = ""
                    except Exception as e:
                        self.lc0, self.lc0_erro = None, f"{type(e).__name__}: {e}"
            return self.lc0

    def fechar_lc0(self):
        with self._trava_lc0:
            if self.lc0:
                self.lc0.fechar()
            self.lc0 = None

    def on_stop(self):
        if self.motor:
            self.motor.fechar()
        self.fechar_lc0()

    def livro(self):
        """Índice do livro do jogador (None se nenhum livro foi carregado)."""
        return LV.carregar_indice(self.arquivo_livro) if os.path.isfile(self.arquivo_livro) else None

    # ---- persistência
    def carregar(self):
        try:
            with open(self.arquivo, encoding="utf-8") as f:
                dados = json.load(f)
            self.aval_melhor = dados.get("aval_melhor")
            self.mi_pp = dados.get("mi_pp", MI_PP)
            self.tf = dados.get("tf", {})
            self.tf_ultimo = dados.get("tf_ultimo")
            self.partida_backup = dados.get("partida_backup")
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
                json.dump({"aval_melhor": self.aval_melhor, "mi_pp": self.mi_pp, "tf": self.tf, "tf_ultimo": self.tf_ultimo, "partida_backup": self.partida_backup,
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
        """Resultado da análise: primeiro o Resumo (claro e curto); os números ficam em Detalhes."""
        aval = None if self.aval_melhor is None else self.aval_melhor * 100
        r = analisar(self.cands, aval, self.mi_pp)
        self.ultimo = r if "escolha" in r else None
        self.sm.get_screen("resumo").mostrar(r)
        self.ir("resumo")

    def mostrar_plano(self, c):
        self.sm.get_screen("plano").mostrar(c)
        self.ir("plano")

    def mostrar_detalhes(self):
        aval = None if self.aval_melhor is None else self.aval_melhor * 100
        r = analisar(self.cands, aval, self.mi_pp)
        self.ultimo = r if "escolha" in r else None
        botoes = [("Voltar", lambda: self.ir("resumo"), CINZA)]
        if any(c.analise for c in self.cands):
            botoes.append(("Planos", self.mostrar_planos, AZUL))
        if self.ultimo:
            botoes.append(("Registrar", self.abrir_registrar, VERDE))
        self.sm.get_screen("texto").mostrar(relatorio(self.cands, aval, self.mi_pp, self.tf_ultimo), botoes)
        self.ir("texto")

    def mostrar_planos(self):
        self.sm.get_screen("planos").mostrar()
        self.ir("planos")

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
