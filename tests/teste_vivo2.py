import os, sys, time
sys.path.insert(0, sys.argv[1]); OUT = sys.argv[2]
os.environ["KIVY_NO_ARGS"] = "1"
from kivy.config import Config
Config.set("graphics", "width", "412"); Config.set("graphics", "height", "860")
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.button import Button
from kivy.uix.modalview import ModalView
from kivy.uix.textinput import TextInput
import chess
import main as M
erros = []
ITAL = "r1bqk1nr/pppp1ppp/2n5/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"
class T(M.HEDApp):
    def on_start(self):
        self.cfg.update(motor="Stockfish local", wdl="Lc0", token="", prof_vivo=14, nos_lc0_vivo=5000)
        self.partida = {"inicio": chess.STARTING_FEN, "lances": [], "idx": 0}
        t = None
        passos = []
        def esperar_lc0(nome, exigir_oo=False):
            def f():
                ini = time.time()
                def chk(dt):
                    txts = [bt.text for _, bt in t._botoes]
                    ok = txts and all("Lc0: V" in x and "..." not in x.split("Lc0:")[1] for x in txts)
                    if ok or time.time() - ini > 40:
                        Window.screenshot(name=os.path.join(OUT, nome + ".png"))
                        print(nome, "|", t.l_lc0.text); print("\n".join(txts))
                        if not ok: erros.append(nome)
                        if exigir_oo and not any("O-O" in x for x in txts): print("(O-O não estava entre as 3 do SF)")
                        Clock.schedule_once(prox, 0.3)
                    else:
                        Clock.schedule_once(chk, 0.5)
                Clock.schedule_once(chk, 1)
                return "esperando"
            return f
        def entrar():
            nonlocal t
            self.ir("analise"); t = self.sm.get_screen("analise")
        def nova_posicao():
            t.abrir_posicao()
            mv = [w for w in Window.children if isinstance(w, ModalView)][0]
            campo = [w for w in mv.walk() if isinstance(w, TextInput)][0]
            campo.text = ITAL
            usar = [w for w in mv.walk() if isinstance(w, Button) and w.text == "Usar esta posição"][0]
            usar.dispatch("on_release")
            assert t.tab.board.fen() == ITAL, t.tab.board.fen()
        def jogar_varios():
            for u in ("e1g1", "g8f6", "d2d3"):
                t.jogar(chess.Move.from_uci(u))
        def inicial():
            t.abrir_posicao()
            mv = [w for w in Window.children if isinstance(w, ModalView)][0]
            [w for w in mv.walk() if isinstance(w, Button) and w.text == "Inicial"][0].dispatch("on_release")
            assert t.tab.board.fen() == chess.STARTING_FEN
        passos += [entrar, esperar_lc0("vivo_inicial"), nova_posicao, esperar_lc0("vivo_italiana", True),
                   jogar_varios, esperar_lc0("vivo_depois"), inicial, esperar_lc0("vivo_volta_inicial")]
        def prox(dt=None, i=[0]):
            if i[0] >= len(passos):
                self.ir("lista"); Clock.schedule_once(lambda dt: self.stop(), 1); return
            f = passos[i[0]]; i[0] += 1
            try: r = f()
            except Exception as e:
                import traceback; traceback.print_exc(); erros.append(e); self.stop(); return
            if r != "esperando": Clock.schedule_once(prox, 0.5)
        Clock.schedule_once(prox, 1)
T().run(); print("VIVO2 OK" if not erros else erros); sys.exit(1 if erros else 0)
