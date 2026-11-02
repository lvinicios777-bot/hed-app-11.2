import os, sys, time
sys.path.insert(0, sys.argv[1]); OUT = sys.argv[2]; FONTE = sys.argv[3] if len(sys.argv) > 3 else "Stockfish"
os.environ["KIVY_NO_ARGS"] = "1"
from kivy.config import Config
Config.set("graphics", "width", "412"); Config.set("graphics", "height", "860")
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.button import Button
import chess, main as M
erros = []
PGN = "1. e4 e5 2. Nf3 Nc6 3. Bc4 Nd4 4. Nxe5 Qg5 5. Nxf7 Qxg2 6. Rf1 Qxe4+ 7. Be2 Nf3#"
class T(M.HEDApp):
    def on_start(self):
        self.cfg.update(motor="Stockfish local", wdl="Lc0", token="", classificar=FONTE, tempo=2)
        ini, lances = M.F.ler_partida(PGN)
        self.partida = {"inicio": ini, "lances": lances, "idx": len(lances)}
        self.revisao = None
        def a(dt):
            self.ir("analise")
            Clock.schedule_once(lambda dt: self.sm.get_screen("analise").abrir_revisao(), 1)
            t0 = time.time()
            def chk(dt):
                r = self.revisao
                if r or time.time() - t0 > 200:
                    if not r: erros.append("sem revisão"); self.stop(); return
                    Clock.schedule_once(lambda dt: fotos(r), 1)
                else:
                    Clock.schedule_once(chk, 1)
            Clock.schedule_once(chk, 2)
        def fotos(r):
            Window.screenshot(name=os.path.join(OUT, f"revisao_{FONTE}.png"))
            print("precisão", {k: round(v, 1) for k, v in r["precisao"].items() if v})
            print(" ".join(f"{x['san']}:{x['classe']}" for x in r["lances"]))
            cl = {x["san"]: x["classe"] for x in r["lances"]}
            if cl.get("Nxe5") not in ("erro", "capivarada", "imprecisao", "perdeu"): erros.append(("Nxe5", cl.get("Nxe5")))
            self.sm.get_screen("revisao").ver(7)       # 4.Nxe5
            Clock.schedule_once(lambda dt: fim(), 2)
        def fim():
            t = self.sm.get_screen("analise")
            print("selo no tabuleiro:", t.tab.selo)
            if not t.tab.selo: erros.append("sem selo")
            Window.screenshot(name=os.path.join(OUT, f"revisao_tab_{FONTE}.png"))
            self.ir("lista"); Clock.schedule_once(lambda dt: self.stop(), 1)
        Clock.schedule_once(a, 0.5)
T().run(); print("REVISAO OK" if not erros else erros); sys.exit(1 if erros else 0)
