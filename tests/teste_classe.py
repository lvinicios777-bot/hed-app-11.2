import os, sys, time
sys.path.insert(0, sys.argv[1]); OUT = sys.argv[2]
os.environ["KIVY_NO_ARGS"] = "1"
from kivy.config import Config
Config.set("graphics", "width", "412"); Config.set("graphics", "height", "860")
from kivy.clock import Clock
from kivy.core.window import Window
import chess, main as M
erros = []
LANCES = ["f2f3", "e7e5", "g2g4"]
class T(M.HEDApp):
    def on_start(self):
        self.cfg.update(motor="Stockfish local", wdl="Lc0", token="", prof_vivo=14, nos_lc0_vivo=3000)
        self.partida = {"inicio": chess.STARTING_FEN, "lances": [], "idx": 0}
        Clock.schedule_once(lambda dt: self.ir("analise"), 0.5)
        estado = {"i": 0, "t": time.time()}
        def tique(dt):
            t = self.sm.get_screen("analise")
            d = getattr(t, "_hist", {}).get(t.tab.board.fen())
            pronto = d and t._sf and t._sf[1] >= 12
            if pronto or time.time() - estado["t"] > 20:
                i = estado["i"]
                if i > 0:
                    print(LANCES[i - 1], "->", t.tab.selo)
                if i == len(LANCES):
                    Window.screenshot(name=os.path.join(OUT, "classe_vivo.png"))
                    if not t.tab.selo or t.tab.selo[1] != "capivarada": erros.append(("g4", t.tab.selo))
                    self.stop(); return
                t.jogar(chess.Move.from_uci(LANCES[i])); estado["i"] += 1; estado["t"] = time.time()
            Clock.schedule_once(tique, 0.5)
        Clock.schedule_once(tique, 3)
T().run(); print("CLASSE OK" if not erros else erros); sys.exit(1 if erros else 0)
