"""
HED — tela de análise com tabuleiro (no estilo do app do Lichess).

Tabuleiro (tocar ou arrastar), barra de avaliação, linhas do Stockfish ao vivo,
seta do melhor lance, navegação pelos lances, explorador Masters/Lichess,
colar FEN/PGN e envio da posição ao HED.
"""
import threading
import time

import chess
from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Ellipse, Line, Rectangle, Triangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

import hed_fontes as F

CLARA, ESCURA = (0.941, 0.851, 0.710, 1), (0.710, 0.533, 0.388, 1)      # cores do Lichess
DESTAQUE = (0.61, 0.78, 0.0, 0.41)
SETA = (0.0, 0.19, 0.53, 0.75)
CHEIO = {"k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟"}
CONTORNO = {"k": "♔", "q": "♕", "r": "♖", "b": "♗", "n": "♘", "p": "♙"}
CINZA, AZUL, VERDE = (0.35, 0.35, 0.35, 1), (0.25, 0.45, 0.75, 1), (0.2, 0.6, 0.35, 1)
_texturas = {}


def textura(txt, tam, fonte="DejaVuSans"):
    chave = (txt, int(tam), fonte)
    if chave not in _texturas:
        lb = CoreLabel(text=txt, font_size=int(tam), font_name=fonte)
        lb.refresh()
        _texturas[chave] = lb.texture
    return _texturas[chave]


def botao(texto, acao, cor=AZUL, **kw):
    b = Button(text=texto, background_normal="", background_color=cor, **kw)
    b.bind(on_release=lambda *_: acao())
    return b


def ascii_(txt):
    for a, b in (("→", "->"), ("…", "..."), ("–", "-")):
        txt = txt.replace(a, b)
    return txt


# ================================================================ Tabuleiro
VERDE_PLANO = (0.10, 0.55, 0.20, 0.85)
VERMELHO_PLANO = (0.80, 0.15, 0.15, 0.80)


class Tabuleiro(Widget):
    def __init__(self, ao_lance, **kw):
        super().__init__(**kw)
        self.ao_lance = ao_lance
        self.board = chess.Board()
        self.girado = False
        self.sel = None
        self.arraste = None          # (casa, x, y)
        self.ultimo = None
        self.seta = None
        self.setas_extra = []        # [(uci, rgba, número ou None)] — setas do plano
        self.marcas = []             # [(casa, rgba)] — casas destacadas (alvos)
        self.bind(pos=self.desenhar, size=self.desenhar)

    # ---- geometria
    @property
    def lado(self):
        return min(self.width, self.height) / 8

    def _origem(self):
        return self.x + (self.width - 8 * self.lado) / 2, self.y + (self.height - 8 * self.lado) / 2

    def _xy(self, casa):
        f, r = chess.square_file(casa), chess.square_rank(casa)
        if self.girado:
            f, r = 7 - f, 7 - r
        ox, oy = self._origem()
        return ox + f * self.lado, oy + r * self.lado

    def _casa(self, x, y):
        ox, oy = self._origem()
        f, r = int((x - ox) // self.lado), int((y - oy) // self.lado)
        if not (0 <= f < 8 and 0 <= r < 8):
            return None
        if self.girado:
            f, r = 7 - f, 7 - r
        return chess.square(f, r)

    def _alvos(self):
        if self.sel is None:
            return set()
        return {m.to_square for m in self.board.legal_moves if m.from_square == self.sel}

    # ---- desenho
    def desenhar(self, *_):
        L = self.lado
        self.canvas.clear()
        with self.canvas:
            for casa in chess.SQUARES:
                x, y = self._xy(casa)
                clara = (chess.square_file(casa) + chess.square_rank(casa)) % 2 == 1
                Color(*(CLARA if clara else ESCURA))
                Rectangle(pos=(x, y), size=(L, L))
            marcadas = set()
            if self.ultimo:
                marcadas |= {self.ultimo.from_square, self.ultimo.to_square}
            if self.sel is not None:
                marcadas.add(self.sel)
            for casa in marcadas:
                Color(*DESTAQUE)
                Rectangle(pos=self._xy(casa), size=(L, L))
            if self.board.is_check():
                rei = self.board.king(self.board.turn)
                x, y = self._xy(rei)
                Color(0.9, 0.1, 0.1, 0.55)
                Ellipse(pos=(x + L * 0.05, y + L * 0.05), size=(L * 0.9, L * 0.9))
            # coordenadas
            for i in range(8):
                f = chess.square(i, 0 if not self.girado else 7)
                x, y = self._xy(f)
                t = textura(chess.FILE_NAMES[i], L * 0.2, "Roboto")
                Color(*(ESCURA if (i % 2 == (1 if not self.girado else 0)) else CLARA))
                Rectangle(texture=t, pos=(x + L - t.width - 2, y + 1), size=t.size)
                c = chess.square(0 if not self.girado else 7, i)
                x, y = self._xy(c)
                t = textura(str(i + 1), L * 0.2, "Roboto")
                Color(*(CLARA if (i % 2 == (1 if not self.girado else 0)) else ESCURA))
                Rectangle(texture=t, pos=(x + 2, y + L - t.height - 1), size=t.size)
            # peças
            for casa, peca in self.board.piece_map().items():
                if self.arraste and self.arraste[0] == casa:
                    continue
                x, y = self._xy(casa)
                self._peca(peca, x, y, L)
            # lances legais
            for alvo in self._alvos():
                x, y = self._xy(alvo)
                Color(0.08, 0.33, 0.12, 0.5)
                if self.board.piece_at(alvo):
                    Line(circle=(x + L / 2, y + L / 2, L * 0.46), width=L * 0.05)
                else:
                    Ellipse(pos=(x + L * 0.37, y + L * 0.37), size=(L * 0.26, L * 0.26))
            # seta do melhor lance
            if self.seta and not self.arraste:
                self._desenhar_seta(self.seta, L)
            # plano: casas-alvo e setas numeradas
            for casa, cor in self.marcas:
                x, y = self._xy(casa)
                Color(*cor)
                Line(rectangle=(x + 2, y + 2, L - 4, L - 4), width=L * 0.05)
            for uci, cor, num in self.setas_extra:
                self._desenhar_seta(uci, L, cor, num)
            if self.arraste:
                casa, ax, ay = self.arraste
                peca = self.board.piece_at(casa)
                if peca:
                    self._peca(peca, ax - L * 0.6, ay - L * 0.6, L * 1.2)

    def _peca(self, peca, x, y, L):
        s = peca.symbol().lower()
        cheio, cont = textura(CHEIO[s], L * 0.86), textura(CONTORNO[s], L * 0.86)
        px, py = x + (L - cheio.width) / 2, y + (L - cheio.height) / 2
        if peca.color == chess.WHITE:
            Color(1, 1, 1, 1)
            Rectangle(texture=cheio, pos=(px, py), size=cheio.size)
            Color(0, 0, 0, 1)
            Rectangle(texture=cont, pos=(px, py), size=cont.size)
        else:
            Color(0.1, 0.1, 0.1, 1)
            Rectangle(texture=cheio, pos=(px, py), size=cheio.size)

    def _desenhar_seta(self, uci, L, cor=None, num=None):
        import math
        try:
            m = chess.Move.from_uci(uci)
        except ValueError:
            return
        x1, y1 = self._xy(m.from_square)
        x2, y2 = self._xy(m.to_square)
        x1, y1, x2, y2 = x1 + L / 2, y1 + L / 2, x2 + L / 2, y2 + L / 2
        ang = math.atan2(y2 - y1, x2 - x1)
        cab = L * 0.42
        bx, by = x2 - cab * math.cos(ang), y2 - cab * math.sin(ang)
        Color(*(cor or SETA))
        Line(points=[x1, y1, bx, by], width=L * 0.08)
        p = ang + math.pi / 2
        w = L * 0.24
        Triangle(points=[x2, y2, bx + w * math.cos(p), by + w * math.sin(p),
                         bx - w * math.cos(p), by - w * math.sin(p)])
        if num is not None:                       # número do passo no início da seta
            r = L * 0.22
            Color(*(cor or SETA))
            Ellipse(pos=(x1 - r, y1 - r), size=(2 * r, 2 * r))
            t = textura(str(num), L * 0.3, "Roboto")
            Color(1, 1, 1, 1)
            Rectangle(texture=t, pos=(x1 - t.width / 2, y1 - t.height / 2), size=t.size)

    # ---- toque
    def on_touch_down(self, t):
        if not self.collide_point(*t.pos):
            return False
        casa = self._casa(*t.pos)
        if casa is None:
            return False
        if self.sel is not None and casa in self._alvos():
            self._jogar(self.sel, casa)
            return True
        peca = self.board.piece_at(casa)
        if peca and peca.color == self.board.turn:
            self.sel = casa
            self.arraste = (casa, t.x, t.y)
            t.grab(self)
        else:
            self.sel = None
        self.desenhar()
        return True

    def on_touch_move(self, t):
        if t.grab_current is self and self.arraste:
            self.arraste = (self.arraste[0], t.x, t.y)
            self.desenhar()
            return True
        return False

    def on_touch_up(self, t):
        if t.grab_current is not self:
            return False
        t.ungrab(self)
        origem = self.arraste[0] if self.arraste else None
        self.arraste = None
        destino = self._casa(*t.pos)
        if origem is not None and destino is not None and destino != origem and destino in self._alvos():
            self._jogar(origem, destino)
        else:
            self.desenhar()
        return True

    def _jogar(self, de, para):
        peca = self.board.piece_at(de)
        promo = (peca and peca.piece_type == chess.PAWN and chess.square_rank(para) in (0, 7))
        self.sel = None
        if promo:
            self._escolher_promocao(de, para)
        else:
            self.ao_lance(chess.Move(de, para))

    def _escolher_promocao(self, de, para):
        mv = ModalView(size_hint=(None, None), size=(dp(300), dp(90)), background_color=(0, 0, 0, 0.6))
        caixa = BoxLayout(spacing=dp(4), padding=dp(4))
        branco = self.board.turn == chess.WHITE
        for tipo, s in ((chess.QUEEN, "q"), (chess.ROOK, "r"), (chess.BISHOP, "b"), (chess.KNIGHT, "n")):
            b = Button(text=CHEIO[s], font_name="DejaVuSans", font_size="44sp", background_normal="",
                       background_color=CLARA, color=(1, 1, 1, 1) if branco else (0.1, 0.1, 0.1, 1))

            def escolher(_b, tipo=tipo):
                mv.dismiss()
                self.ao_lance(chess.Move(de, para, promotion=tipo))
            b.bind(on_release=escolher)
            caixa.add_widget(b)
        mv.add_widget(caixa)
        mv.bind(on_dismiss=lambda *_: self.desenhar())
        mv.open()


class BarraAval(Widget):
    """Barra horizontal: parte branca = chance das brancas (curva do Lichess)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.frac = 0.5
        self.bind(pos=self.desenhar, size=self.desenhar)

    def definir(self, frac):
        if abs(frac - self.frac) > 0.002:
            self.frac = frac
            self.desenhar()

    def desenhar(self, *_):
        self.canvas.clear()
        with self.canvas:
            Color(0.25, 0.25, 0.25, 1)
            Rectangle(pos=self.pos, size=self.size)
            Color(0.95, 0.95, 0.95, 1)
            Rectangle(pos=self.pos, size=(self.width * self.frac, self.height))
            Color(0.9, 0.3, 0.2, 1)
            Rectangle(pos=(self.x + self.width / 2 - 1, self.y), size=(2, self.height))


# ================================================================ Tela de análise
class TelaAnalise(Screen):
    def on_enter(self, *_):
        if not getattr(self, "montada", False):
            self.montar()
        self.motor_ligado = getattr(self, "motor_ligado", True)
        self._gen = getattr(self, "_gen", 0)
        self._cache_exp = getattr(self, "_cache_exp", {})
        self._evento = Clock.schedule_interval(self._tique, 0.25)
        app = App.get_running_app()
        if app.cfg.get("motor") == "Stockfish local" and app.motor is None:
            self.status.text = "Iniciando o Stockfish..."

            def iniciar():
                m = app.obter_motor()

                def pronto(dt):
                    erro = getattr(app, "motor_erro", "")
                    self.status.text = "" if m else ("Stockfish indisponível: usando a nuvem do Lichess."
                                                     + (f" ({erro})" if erro else ""))
                    self.atualizar()
                Clock.schedule_once(pronto)
            threading.Thread(target=iniciar, daemon=True).start()
        self.atualizar()

    def on_leave(self, *_):
        if getattr(self, "_evento", None):
            self._evento.cancel()
        app = App.get_running_app()
        if app.motor:
            app.motor.parar()
        self._gen = getattr(self, "_gen", 0) + 1         # encerra as tarefas do Lc0 desta tela
        self._parar_lc0()

    # ---- partida
    def _board(self):
        p = App.get_running_app().partida
        b = chess.Board(p["inicio"])
        for u in p["lances"][: p["idx"]]:
            b.push_uci(u)
        return b

    def jogar(self, mv: chess.Move):
        app = App.get_running_app()
        p = app.partida
        b = self._board()
        if mv not in b.legal_moves:
            return
        if p["idx"] < len(p["lances"]) and p["lances"][p["idx"]] == mv.uci():
            p["idx"] += 1                                  # mesmo lance da linha: só avança
        else:
            p["lances"] = p["lances"][: p["idx"]] + [mv.uci()]
            p["idx"] += 1
        app.salvar()
        self.atualizar()

    def ir_para(self, idx):
        p = App.get_running_app().partida
        p["idx"] = max(0, min(len(p["lances"]), idx))
        self.atualizar()

    # ---- montagem
    def montar(self):
        app = App.get_running_app()
        self.montada = True
        self.clear_widgets()
        raiz = BoxLayout(orientation="vertical", padding=(dp(4), dp(4)), spacing=dp(3))

        topo = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(4))
        self.l_aval = Label(text="", markup=True, font_size="20sp", size_hint_x=0.32)
        self.l_info = Label(text="", font_size="12sp", halign="left", valign="middle", size_hint_x=0.4)
        self.l_info.bind(size=lambda w, s: setattr(w, "text_size", s))
        self.b_motor = botao("Motor: ON", self.alternar_motor, VERDE, size_hint_x=0.28, font_size="13sp")
        for w in (self.l_aval, self.l_info, self.b_motor):
            topo.add_widget(w)
        raiz.add_widget(topo)

        self.barra = BarraAval(size_hint_y=None, height=dp(8))
        raiz.add_widget(self.barra)
        self.l_lc0 = Label(text="", markup=True, font_size="12sp", size_hint_y=None, height=dp(20),
                           halign="left", valign="middle")
        self.l_lc0.bind(size=lambda w, s: setattr(w, "text_size", s))
        raiz.add_widget(self.l_lc0)
        self.tab = Tabuleiro(self.jogar, size_hint_y=None)
        raiz.bind(width=lambda w, v: setattr(self.tab, "height", v - dp(8)))
        raiz.add_widget(self.tab)

        nav = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(3))
        for txt, acao in (("|<", lambda: self.ir_para(0)),
                          ("<", lambda: self.ir_para(app.partida["idx"] - 1)),
                          (">", lambda: self.ir_para(app.partida["idx"] + 1)),
                          (">|", lambda: self.ir_para(len(app.partida["lances"]))),
                          ("Girar", self.girar)):
            nav.add_widget(botao(txt, acao, CINZA, font_size="16sp"))
        raiz.add_widget(nav)

        corpo = GridLayout(cols=1, spacing=dp(3), size_hint_y=None, padding=(dp(2), 0))
        corpo.bind(minimum_height=corpo.setter("height"))
        self.status = Label(text="", markup=True, font_size="12sp", size_hint_y=None, height=dp(18),
                            halign="left", valign="middle", color=(1, 0.8, 0.4, 1))
        self.status.bind(size=lambda w, s: setattr(w, "text_size", s))
        corpo.add_widget(self.status)
        self.caixa_linhas = GridLayout(cols=1, spacing=dp(2), size_hint_y=None)
        self.caixa_linhas.bind(minimum_height=self.caixa_linhas.setter("height"))
        corpo.add_widget(self.caixa_linhas)
        self.l_lances = Label(text="", markup=True, font_size="13sp", size_hint_y=None,
                              halign="left", valign="top")
        self.l_lances.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
                           texture_size=lambda w, s: setattr(w, "height", s[1] + dp(4)))
        corpo.add_widget(self.l_lances)

        abas = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(3))
        self.base = "masters"
        self.b_masters = botao("Masters", lambda: self.trocar_base("masters"), AZUL, font_size="13sp")
        self.b_lichess = botao("Lichess", lambda: self.trocar_base("lichess"), CINZA, font_size="13sp")
        abas.add_widget(self.b_masters)
        abas.add_widget(self.b_lichess)
        corpo.add_widget(abas)
        self.l_abertura = Label(text="", font_size="12sp", size_hint_y=None, height=dp(18),
                                halign="left", valign="middle")
        self.l_abertura.bind(size=lambda w, s: setattr(w, "text_size", s))
        corpo.add_widget(self.l_abertura)
        self.caixa_exp = GridLayout(cols=1, spacing=dp(2), size_hint_y=None)
        self.caixa_exp.bind(minimum_height=self.caixa_exp.setter("height"))
        corpo.add_widget(self.caixa_exp)
        sv = ScrollView()
        sv.add_widget(corpo)
        raiz.add_widget(sv)

        baixo = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(3))
        baixo.add_widget(botao("Voltar", lambda: app.ir("lista"), CINZA, font_size="13sp"))
        baixo.add_widget(botao("Posição...", self.abrir_posicao, (0.25, 0.45, 0.75, 1), font_size="13sp"))
        baixo.add_widget(botao("Copiar FEN", self.copiar, CINZA, font_size="13sp"))
        baixo.add_widget(botao("Enviar ao HED", self.enviar_hed, (0.7, 0.45, 0.15, 1), font_size="13sp"))
        raiz.add_widget(baixo)
        self.add_widget(raiz)
        self._ultimas = None
        self._limpar_estado_lc0()
        self._lc0_trava = threading.Lock()

    # ---- ações
    def alternar_motor(self):
        self.motor_ligado = not self.motor_ligado
        self.b_motor.text = "Motor: ON" if self.motor_ligado else "Motor: OFF"
        self.b_motor.background_color = VERDE if self.motor_ligado else CINZA
        app = App.get_running_app()
        if not self.motor_ligado and app.motor:
            app.motor.parar()
        if not self.motor_ligado:
            self._parar_lc0()
        self.atualizar()

    def girar(self):
        self.tab.girado = not self.tab.girado
        self.tab.desenhar()

    def trocar_base(self, base):
        self.base = base
        self.b_masters.background_color = AZUL if base == "masters" else CINZA
        self.b_lichess.background_color = AZUL if base == "lichess" else CINZA
        self._explorador()

    def colar(self):
        app = App.get_running_app()
        try:
            inicio, lances = F.ler_partida(Clipboard.paste() or "")
        except Exception as e:
            self.status.text = f"Não consegui ler: {e}"
            return
        app.partida = {"inicio": inicio, "lances": lances, "idx": len(lances)}
        app.salvar()
        self.status.text = f"Carregado: {'PGN com ' + str(len(lances)) + ' lances' if lances else 'FEN'}"
        self.atualizar()

    def abrir_posicao(self):
        """Escolher qualquer posição: colar FEN/PGN, digitar, ou voltar à inicial."""
        app = App.get_running_app()
        mv = ModalView(size_hint=(0.94, None), height=dp(330), auto_dismiss=True)
        caixa = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        caixa.add_widget(Label(text="[b]Nova posição[/b]", markup=True, size_hint_y=None, height=dp(26)))
        campo = TextInput(text=self._board().fen(), multiline=True, font_size="13sp",
                          hint_text="FEN ou PGN (lances)")
        caixa.add_widget(campo)
        aviso = Label(text="", font_size="12sp", size_hint_y=None, height=dp(20), color=(1, 0.8, 0.4, 1))
        caixa.add_widget(aviso)

        def usar(texto):
            try:
                inicio, lances = F.ler_partida(texto or "")
            except Exception as e:
                aviso.text = f"Não consegui ler: {e}"
                return
            app.partida = {"inicio": inicio, "lances": lances, "idx": len(lances)}
            app.partida_backup = None
            app.salvar()
            mv.dismiss()
            self.status.text = f"Posição carregada{' (PGN com ' + str(len(lances)) + ' lances)' if lances else ''}."
            self.atualizar()

        def colar():
            campo.text = Clipboard.paste() or ""

        l1 = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        l1.add_widget(botao("Colar", colar, CINZA, font_size="14sp"))
        l1.add_widget(botao("Limpar", lambda: setattr(campo, "text", ""), CINZA, font_size="14sp"))
        l1.add_widget(botao("Inicial", lambda: usar(chess.STARTING_FEN), CINZA, font_size="14sp"))
        caixa.add_widget(l1)
        l2 = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        l2.add_widget(botao("Cancelar", mv.dismiss, CINZA, font_size="14sp"))
        l2.add_widget(botao("Usar esta posição", lambda: usar(campo.text), VERDE, font_size="14sp"))
        caixa.add_widget(l2)
        mv.add_widget(caixa)
        mv.open()

    def copiar(self):
        Clipboard.copy(self._board().fen())
        self.status.text = "FEN copiado."

    def enviar_hed(self):
        app = App.get_running_app()
        b = self._board()
        if b.is_game_over():
            self.status.text = "A partida terminou nesta posição."
            return
        app.fen = b.fen()
        tela = app.sm.get_screen("posicao")
        if not getattr(tela, "montada", False):
            tela.montar()
        tela.fen.text = b.fen()
        app.ir("posicao")
        tela.analisar()

    # ---- atualização
    def atualizar(self, *_):
        app = App.get_running_app()
        p = app.partida
        b = self._board()
        self.tab.board = b
        self.tab.sel = None
        self.tab.ultimo = chess.Move.from_uci(p["lances"][p["idx"] - 1]) if p["idx"] > 0 else None
        self.tab.seta = None
        self._gen += 1
        self._ultimas = None
        self._limpar_estado_lc0()
        self.l_lc0.text = ""
        self.caixa_linhas.clear_widgets()
        self.l_aval.text = ""
        self.l_info.text = ""
        if b.is_game_over():
            res = b.result()
            self.l_aval.text = res
            self.l_info.text = "Fim de jogo"
            self.barra.definir(1.0 if res == "1-0" else 0.0 if res == "0-1" else 0.5)
        elif self.motor_ligado:
            if self._usa_local():
                app.motor.vivo(b, 3, int(app.cfg.get("prof_vivo", 24)))
            else:
                if app.motor:
                    app.motor.parar()
                self._nuvem(b, self._gen)
            self._iniciar_lc0(b, self._gen)
        else:
            self._parar_lc0()
        self.tab.desenhar()
        self._lista_lances()
        self._explorador()

    def _lista_lances(self):
        p = App.get_running_app().partida
        b = chess.Board(p["inicio"])
        partes = []
        for i, u in enumerate(p["lances"]):
            m = chess.Move.from_uci(u)
            num = (f"{b.fullmove_number}. " if b.turn == chess.WHITE else
                   (f"{b.fullmove_number}... " if i == 0 else ""))
            san = b.san(m)
            b.push(m)
            txt = f"{num}{san}"
            partes.append(f"[b][color=ffcc66]{txt}[/color][/b]" if i == p["idx"] - 1 else txt)
        self.l_lances.text = " ".join(partes) if partes else "[color=888888]Toque ou arraste as peças para jogar.[/color]"

    def _usa_local(self):
        app = App.get_running_app()
        return bool(app.motor) and app.cfg.get("motor") == "Stockfish local"

    def _tique(self, dt):
        app = App.get_running_app()
        if not self.motor_ligado:
            return
        if self._usa_local():
            ops, prof = app.motor.linhas()
            chave = (prof, tuple((o.uci, o.cp, o.mate) for o in ops))
            if ops and chave != self._ultimas:
                self._ultimas = chave
                self._sf = (ops, prof, app.motor.nome, app.motor.pensando)
                self._sf_fen = self.tab.board.fen()
                self._sf_desde = self._sf_desde or time.time()
                self._mostrar_linhas(*self._sf)
                return
        # Lc0: redesenha no máximo ~2x por segundo, sem recriar os botões
        if self._lc0_ver != self._lc0_ver_vista and time.time() - self._lc0_quando > 0.5:
            self._lc0_ver_vista, self._lc0_quando = self._lc0_ver, time.time()
            self._atualizar_textos()

    # ---- Lc0 ao vivo: WDL forçado nos lances do Stockfish (searchmoves) + a opinião própria do Lc0
    def _limpar_estado_lc0(self):
        self._sf, self._sf_fen, self._sf_desde = None, None, None
        self._lc0_res, self._lc0_final = {}, set()       # uci -> Opcao (com WDL); ucis calculados "a fundo"
        self._lc0_proprio = None                          # lance preferido pelo Lc0 (busca livre)
        self._lc0_estado = ""
        self._lc0_ver, self._lc0_ver_vista, self._lc0_quando = 0, -1, 0.0
        self._lc0_tok = object()                          # identifica a posição atual (tarefas velhas não gravam)
        self._botoes = []

    def _quer_lc0(self):
        return App.get_running_app().cfg.get("wdl", "Lc0") == "Lc0"

    def _iniciar_lc0(self, b, gen):
        if not self._quer_lc0() or b.is_game_over():
            return
        self._lc0_estado = "iniciando" if App.get_running_app().lc0 is None else "calculando"
        self._lc0_ver += 1
        threading.Thread(target=self._trabalho_lc0, args=(b.copy(), gen, self._lc0_tok), daemon=True).start()

    def _parar_lc0(self):
        app = App.get_running_app()
        if getattr(app, "lc0", None):
            threading.Thread(target=app.lc0.parar, daemon=True).start()

    def _alvos_sf(self, fen):
        """Lances do Stockfish (até 3) para esta posição, quando a busca dele já se firmou."""
        if not self._sf or self._sf_fen != fen:
            return None
        ops, prof, _, pensando = self._sf
        if self._usa_local() and pensando and prof < 12 and time.time() - (self._sf_desde or 0) < 4:
            return None                                   # Stockfish ainda oscilando nos primeiros lances
        return [o.uci for o in ops[:3]]

    def _trabalho_lc0(self, b, gen, tok):
        app = App.get_running_app()
        fen = b.fen()

        def vale():
            return gen == self._gen and tok is self._lc0_tok and self.motor_ligado and self._quer_lc0()

        m = app.obter_lc0()
        if m is None:
            if vale():
                erro = getattr(app, "lc0_erro", "")
                self._lc0_estado = f"indisponível{': ' + erro if erro else ''}"
                self._lc0_ver += 1
            return
        nos = int(app.cfg.get("nos_lc0_vivo", 50000))

        def iniciar(go, multipv):
            with self._lc0_trava:                         # não deixa uma tarefa velha sobrepor a nova
                if not vale():
                    return False
                m.vivo(b, multipv, go=go)
                return True

        def acompanhar(final):
            """Lê as linhas enquanto o Lc0 pensa; guarda o WDL de cada lance."""
            while True:
                time.sleep(0.4)
                if not vale():
                    return False
                if m.fen_atual() == fen:
                    ops, _ = m.linhas()
                    res = dict(self._lc0_res)
                    for o in ops:
                        if o.wdl:
                            res[o.uci] = o
                    self._lc0_res = res
                    self._lc0_ver += 1
                if not m.pensando:
                    if m.fen_atual() == fen:
                        self._lc0_final |= set(final) & set(self._lc0_res)
                    return True

        # 1. opinião própria (busca livre, curta)
        self._lc0_estado = "calculando"
        if not iniciar(f"go nodes {max(800, nos // 20)}", 4) or not acompanhar([]):
            return
        if self._lc0_res:
            self._lc0_proprio = max(self._lc0_res.values(), key=lambda o: o.expectativa).uci
        # 2. força o Lc0 a calcular os lances do Stockfish (e o dele), mesmo que discorde
        while vale():
            alvo = self._alvos_sf(fen)
            if alvo is None:
                time.sleep(0.3)
                continue
            if self._lc0_proprio and self._lc0_proprio not in alvo:
                alvo = alvo + [self._lc0_proprio]
            faltam = [u for u in alvo if u not in self._lc0_final]
            if not faltam:
                self._lc0_estado = "pronto"
                self._lc0_ver += 1
                time.sleep(0.5)                           # espera o Stockfish mudar de ideia
                continue
            self._lc0_estado = "calculando"
            self._lc0_ver += 1
            if not iniciar(f"go nodes {nos} searchmoves {' '.join(alvo)}", len(alvo)):
                return
            if not acompanhar(alvo):
                return
            # o que o Lc0 não devolveu (ex.: roque em formato que ele não aceite): posição depois do lance
            for u in [u for u in alvo if u not in self._lc0_final]:
                with self._lc0_trava:
                    if not vale():
                        return
                    try:
                        wdl = F.wdl_depois(m, b, u, 1.5)
                    except Exception:
                        wdl = None
                if wdl:
                    mv = b.parse_uci(u)
                    o = F.Opcao(u, b.san(mv), wdl=wdl)
                    o.fonte_wdl = "Lc0"
                    res = dict(self._lc0_res)
                    res[u] = o
                    self._lc0_res = res
                self._lc0_final.add(u)                    # não tenta de novo nesta posição
                self._lc0_ver += 1

    def _resumo_lc0(self):
        """Linha abaixo da barra: o que o Lc0 acha do melhor lance do Stockfish."""
        app = App.get_running_app()
        est = self._lc0_estado
        if est.startswith("indisponível"):
            self.l_lc0.text = f"[color=ffcc66]Lc0 {est}[/color]"
            return
        res = {u: o for u, o in self._lc0_res.items() if u in self._lc0_final} or dict(self._lc0_res)
        if not res:
            self.l_lc0.text = f"[color=999999]Lc0: {est or 'calculando'}...[/color]" if est else ""
            return
        pens = " ..." if est in ("calculando", "iniciando") else ""
        top = max(res.values(), key=lambda o: o.expectativa)
        melhor_sf = self._sf[0][0] if self._sf else None
        if melhor_sf is None:
            self.l_lc0.text = f"Lc0{pens}: prefere [b]{top.san}[/b] (E {top.expectativa:.0f}%)"
            return
        e_sf = res.get(melhor_sf.uci)
        if melhor_sf.uci == top.uci:
            self.l_lc0.text = (f"[color=77dd77]Lc0{pens}: concorda com o Stockfish "
                               f"({top.san}, E {top.expectativa:.0f}%)[/color]")
        elif e_sf and top.expectativa - e_sf.expectativa < 1.0:      # diferença < 1 pp: mesma coisa
            self.l_lc0.text = (f"[color=77dd77]Lc0{pens}: {melhor_sf.san} e {top.san} equivalentes "
                               f"(E {e_sf.expectativa:.0f}%)[/color]")
        else:
            extra = f"; {melhor_sf.san} tem E {e_sf.expectativa:.0f}%" if e_sf else ""
            self.l_lc0.text = (f"[color=ffcc66]Lc0{pens}: prefere [b]{top.san}[/b] "
                               f"(E {top.expectativa:.0f}%){extra}[/color]")

    def _nuvem(self, b, gen):
        self.l_info.text = "Nuvem do Lichess..."

        def tarefa():
            try:
                ops, prof = F.nuvem(b, 3)
                msg = None if ops else "Posição fora da nuvem do Lichess."
            except F.FonteErro as e:
                ops, prof, msg = [], 0, str(e)

            def ui(dt):
                if gen != self._gen:
                    return
                if ops:
                    self._sf = (ops, prof, "Lichess nuvem", False)
                    self._sf_fen, self._sf_desde = b.fen(), time.time()
                    self._mostrar_linhas(*self._sf)
                else:
                    self.l_info.text = msg or ""
            Clock.schedule_once(ui)
        threading.Thread(target=tarefa, daemon=True).start()

    def _mostrar_linhas(self, ops, prof, fonte, pensando):
        b = self.tab.board
        branco = b.turn == chess.WHITE
        o1 = ops[0]
        self.l_aval.text = f"[b]{F.texto_aval(o1, branco)}[/b]"
        cp_b = (o1.cp if branco else -o1.cp) if o1.cp is not None else None
        self.barra.definir(F.chance_brancas(cp_b))
        self.l_info.text = f"{fonte}\nprof. {prof}{' ...' if pensando else ''}"
        if self.tab.seta != o1.uci:
            self.tab.seta = o1.uci
            self.tab.desenhar()
        if [o.uci for o, _ in self._botoes] != [o.uci for o in ops]:
            self.caixa_linhas.clear_widgets()
            self._botoes = []
            for o in ops:
                bt = Button(text="", markup=True, font_name="RobotoMono-Regular", font_size="12sp",
                            size_hint_y=None, height=dp(46), halign="left", valign="middle",
                            background_normal="", background_color=(0.17, 0.18, 0.21, 1))
                bt.bind(size=lambda w, s: setattr(w, "text_size", (s[0] - dp(8), s[1])))
                bt.bind(on_release=lambda _b, u=o.uci: self.jogar(chess.Move.from_uci(u)))
                self.caixa_linhas.add_widget(bt)
                self._botoes.append((o, bt))
        else:
            self._botoes = [(o, bt) for o, (_, bt) in zip(ops, self._botoes)]
        self._atualizar_textos()

    def _atualizar_textos(self):
        """Só troca os textos das linhas (Stockfish + Lc0); os botões continuam os mesmos."""
        self._resumo_lc0()
        b = self.tab.board
        if b is None:
            return
        branco = b.turn == chess.WHITE
        usa_lc0 = self._quer_lc0()
        res = self._lc0_res
        for o, bt in self._botoes:
            num = f"{b.fullmove_number}." if branco else f"{b.fullmove_number}..."
            txt = f"[b]{F.texto_aval(o, branco):>6}[/b]  {num} {' '.join(o.pv[:8])}"
            x = res.get(o.uci)
            if x and x.wdl:
                w, d, l = (round(v / 10) for v in x.wdl)
                marca = "" if o.uci in self._lc0_final else " ..."
                txt += (f"\n[color=99ccff]        Lc0: V {w}% | Emp {d}% | D {l}% "
                        f"-> E {x.expectativa:.0f}%{marca}[/color]")
            elif usa_lc0:
                txt += "\n[color=888888]        Lc0: calculando...[/color]"
            elif o.wdl:
                txt += f"\n[color=888888]        WDL Stockfish: E {o.expectativa:.0f}%[/color]"
            bt.text = ascii_(txt)

    def _explorador(self):
        app = App.get_running_app()
        self.caixa_exp.clear_widgets()
        token = app.cfg.get("token", "").strip()
        if not token:
            self.l_abertura.text = "Explorador: coloque o token do Lichess em Configurações."
            return
        b = self.tab.board
        chave = (b.fen(), self.base)
        if chave in self._cache_exp:
            self._mostrar_exp(*self._cache_exp[chave])
            return
        self.l_abertura.text = "Consultando o explorador..."
        gen = self._gen

        def tarefa():
            try:
                est, nome, total = F.banco(b, self.base, token, app.cfg)
                res = (est, nome, total, None)
            except F.FonteErro as e:
                res = ({}, None, 0, str(e))

            def ui(dt):
                if res[3] is None:
                    self._cache_exp[chave] = res[:3]
                if gen == self._gen and (b.fen(), self.base) == chave:
                    if res[3]:
                        self.l_abertura.text = f"Explorador: {res[3]}"
                    else:
                        self._mostrar_exp(*res[:3])
            Clock.schedule_once(ui)
        threading.Thread(target=tarefa, daemon=True).start()

    def _mostrar_exp(self, est, nome, total):
        self.caixa_exp.clear_widgets()
        self.l_abertura.text = f"{nome or 'Abertura sem nome'}  |  {total} jogos"
        if not est:
            self.caixa_exp.add_widget(Label(text="Nenhum jogo nesta posição.", font_size="12sp",
                                            size_hint_y=None, height=dp(24)))
            return
        cab = Label(text=ascii_(f"{'Lance':<7}{'Jogos':>9}   Brancas/Empate/Pretas"), font_name="RobotoMono-Regular",
                    font_size="11sp", size_hint_y=None, height=dp(18), halign="left", valign="middle",
                    color=(0.7, 0.7, 0.7, 1))
        cab.bind(size=lambda w, s: setattr(w, "text_size", s))
        self.caixa_exp.add_widget(cab)
        for uci, s in sorted(est.items(), key=lambda kv: -kv[1].n):
            pb, pe, pp = (100 * x / s.n for x in (s.brancas, s.empates, s.pretas))
            txt = f"{(s.san or uci):<7}{s.n:>9}   {pb:3.0f}% / {pe:3.0f}% / {pp:3.0f}%"
            bt = Button(text=txt, font_name="RobotoMono-Regular", font_size="12sp", size_hint_y=None,
                        height=dp(30), halign="left", valign="middle", background_normal="",
                        background_color=(0.17, 0.18, 0.21, 1))
            bt.bind(size=lambda w, sz: setattr(w, "text_size", (sz[0] - dp(8), sz[1])))
            bt.bind(on_release=lambda _b, u=uci: self.jogar(chess.Move.from_uci(u)))
            self.caixa_exp.add_widget(bt)


class TabuleiroPlano(Tabuleiro):
    """Tabuleiro só para ver: posição do plano com setas verdes (seus passos) e vermelhas (dele)."""

    def __init__(self, **kw):
        super().__init__(lambda *_: None, **kw)

    def mostrar(self, fen, passos, cuidado, girado=False):
        self.board = chess.Board(fen)
        self.girado = girado
        self.setas_extra, self.marcas = [], []
        for i, p in enumerate(passos, 1):
            cam = p.get("caminho") or []
            if len(cam) == 3:                       # rota em 2 lances: duas setas (b8→a6, a6→b4)
                self.setas_extra.append((cam[0] + cam[1], VERDE_PLANO, i))
                self.setas_extra.append((cam[1] + cam[2], VERDE_PLANO, None))
            elif p.get("seta"):
                self.setas_extra.append((p["seta"], VERDE_PLANO, i))
            elif p.get("casa"):
                self.marcas.append((chess.parse_square(p["casa"]), VERDE_PLANO))
        for p in cuidado:
            if p.get("seta"):
                self.setas_extra.append((p["seta"], VERMELHO_PLANO, None))
        self.desenhar()

    def on_touch_down(self, t):
        return False

    def on_touch_move(self, t):
        return False

    def on_touch_up(self, t):
        return False
