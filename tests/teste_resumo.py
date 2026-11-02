import os, sys, time
sys.path.insert(0, sys.argv[1]); OUT = sys.argv[2]; EPUB = sys.argv[3] if len(sys.argv) > 3 else ""
os.environ["KIVY_NO_ARGS"] = "1"
from kivy.config import Config
Config.set("graphics", "width", "412"); Config.set("graphics", "height", "860")
from kivy.clock import Clock
from kivy.core.window import Window
import main as M
FENS = {"kid": "rnbqkb1r/pppppp1p/5np1/8/2PP4/2N5/PP2PPPP/R1BQKBNR b KQkq - 1 3",
        "esp": "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"}
erros = []
def foto(n): Window.screenshot(name=os.path.join(OUT, n + ".png"))
class T(M.HEDApp):
    def on_start(self):
        self.cands, self.registro = [], []
        self.cfg.update(motor="Stockfish local", tempo=2, multipv=3, token="", wdl="Lc0")
        passos = []
        def livro():
            self.ir("config"); t = self.sm.get_screen("config"); t.montar(); t.indexar_livro(EPUB)
            return lambda: "Carregado" in t.status_livro.text
        def analisar(n):
            def f():
                t = self.sm.get_screen("posicao"); self.ir("posicao")
                if not getattr(t, "montada", False): t.montar()
                t.fen.text = FENS[n]; t.analisar()
                return lambda: t.resultado is not None and t.resultado["fen"].startswith(FENS[n][:20]) and not t.b_analisar.disabled
            return f
        def resumo(n):
            def f():
                foto(f"{n}_posicao")
                r = self.sm.get_screen("posicao").resultado
                assert r.get("motores") and str(r.get("fonte_wdl", "")).startswith("Lc0"), (r.get("motores"), r.get("fonte_wdl"), r["avisos"])
                self.sm.get_screen("posicao").importar()
                assert all(c.motores.get("wdl_fonte") == "Lc0" and c.motores.get("sf_rank") for c in self.cands), [c.motores for c in self.cands]
                print(n, r["motores"]); self.mostrar_relatorio()
                assert self.sm.current == "resumo"
            return f
        def foto_resumo(n):
            def f():
                foto(f"{n}_resumo"); self.mostrar_plano(self.cands[0] if self.ultimo is None else
                                                       next(c for c in self.cands if c.lance == self.ultimo["escolha"]))
            return f
        def foto_plano(n, i):
            def f():
                from kivy.uix.label import Label
                t = self.sm.get_screen("plano")
                txt = "\n".join(w.text for w in t.walk() if isinstance(w, Label))
                open(os.path.join(OUT, f"{n}_plano{i}.txt"), "w").write(txt)
                assert "Objetivo" in txt and "Como fazer" in txt, txt[:300]
                foto(f"{n}_plano{i}")
                outros = [c for c in self.cands if c.lance != self.ultimo["escolha"] and c.analise]
                if outros and i == 1: self.mostrar_plano(outros[0])
            return f
        def detalhes():
            self.mostrar_detalhes(); assert self.sm.current == "texto"
        passos += [livro] if EPUB and os.path.isfile(EPUB) else []
        passos += [analisar("kid"), resumo("kid"), foto_resumo("kid"), foto_plano("kid", 1), foto_plano("kid", 2),
                   analisar("esp"), resumo("esp"), foto_resumo("esp"), foto_plano("esp", 1), detalhes]
        def prox(dt=None, i=[0]):
            if i[0] >= len(passos): print("RESUMO OK"); self.stop(); return
            f = passos[i[0]]; i[0] += 1
            try: cond = f()
            except Exception as e:
                import traceback; traceback.print_exc(); erros.append(e); self.stop(); return
            if callable(cond):
                ini = time.time()
                def chk(dt):
                    if cond(): Clock.schedule_once(prox, 0.4)
                    elif time.time() - ini > 90: erros.append("tempo"); print("tempo"); self.stop()
                    else: Clock.schedule_once(chk, 0.5)
                Clock.schedule_once(chk, 0.5)
            else: Clock.schedule_once(prox, 0.8)
        Clock.schedule_once(prox, 0.8)
T().run(); sys.exit(1 if erros else 0)
