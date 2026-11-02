"""
HED — fontes externas de evidência.

- Stockfish local (UCI): avaliação + WDL em MultiPV; lances extras via "searchmoves".
- Lichess Cloud Eval (sem token): avaliação em cache, até 5 linhas.
- Lichess Opening Explorer (token pessoal): bases Masters e Lichess.

Tudo é convertido para o ponto de vista de QUEM JOGA na posição.
"""
import json
import os
import shutil
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import chess

UA = "HED-app/11.2 (+github.com/lvinicios777-bot/hed-app-11.2)"
MATE_CP = 10000
CFG_PADRAO = {
    "wdl": "Lc0",
    "token": "",
    "motor": "Stockfish local",      # ou "Lichess nuvem"
    "tempo": 4.0,                    # segundos por busca
    "multipv": 5,
    "ratings": "2000,2200,2500",
    "speeds": "blitz,rapid,classical",
    "extras": 3,                     # lances do banco avaliados além do MultiPV
    "prof_vivo": 24,                 # profundidade da análise ao vivo no tabuleiro
    "forca_wdl": "normal",           # normal (força do Lc0) | meu (meu rating) | digitar
    "meu_rating": 2075,
    "elo_digitado": 2000,
    "estilo": "normal",              # normal | solido | agressivo
    "classificar": "Lc0",            # fonte da classificação dos lances: Lc0 | Stockfish
    "carga_lc0": "Normal",           # Rápido | Normal | Profundo (nós do Lc0 ao vivo)
}

NOS_LC0 = {"Rápido": 10000, "Normal": 50000, "Profundo": 200000}


def elo_wdl(cfg: Dict) -> int:
    """Elo usado para calibrar o WDL do Lc0 (0 = sem calibração, a força do próprio Lc0)."""
    modo = cfg.get("forca_wdl", "normal")
    try:
        if modo == "meu":
            return int(float(cfg.get("meu_rating", 0)))
        if modo == "digitar":
            return int(float(cfg.get("elo_digitado", 0)))
    except (TypeError, ValueError):
        return 0
    return 0


def lc0_ajustes(cfg: Dict, cor: bool) -> List[str]:
    """Comandos UCI de calibração e estilo para o Lc0, do ponto de vista de `cor` (quem vai jogar).

    WDLCalibrationElo: WDL como o de jogadores desse Elo (ritmo rápido); 0 = WDL do próprio Lc0.
    Contempt + ContemptMode: o estilo (agressivo = joga para ganhar; sólido = aceita a igualdade).
    """
    from hed_core import ESTILOS
    cont = ESTILOS.get(cfg.get("estilo", "normal"), ESTILOS["normal"])["contempt"]
    modo = "disable" if not cont else ("white_side_analysis" if cor == chess.WHITE else "black_side_analysis")
    return [f"setoption name WDLCalibrationElo value {elo_wdl(cfg)}",
            f"setoption name ContemptMode value {modo}",
            f"setoption name Contempt value {cont}"]


class FonteErro(Exception):
    pass


# ======================================================== estruturas
@dataclass
class Estat:
    n: int
    pts: float            # pontuação média de quem joga (0–1)
    rating: Optional[int] = None
    brancas: int = 0      # vitórias das brancas / empates / vitórias das pretas
    empates: int = 0
    pretas: int = 0
    san: str = ""


@dataclass
class Opcao:
    uci: str
    san: str
    cp: Optional[int] = None              # POV de quem joga; mate convertido
    mate: Optional[int] = None
    wdl: Optional[tuple] = None           # (W, D, L) em ‰, POV de quem joga
    wdl_sf: Optional[tuple] = None        # WDL do Stockfish, guardado quando o do Lc0 o substitui
    fonte_wdl: Optional[str] = None       # "Lc0" ou "Stockfish"
    cp_lc0: Optional[int] = None          # avaliação do Lc0 (só informa)
    rank_sf: Optional[int] = None         # posição no ranking do Stockfish (pela avaliação)
    rank_lc0: Optional[int] = None        # posição no ranking do Lc0 (pela pontuação esperada)
    pv: List[str] = field(default_factory=list)
    multipv: Optional[int] = None         # posição no ranking do motor (None = extra)
    masters: Optional[Estat] = None
    lichess: Optional[Estat] = None

    @property
    def expectativa(self) -> Optional[float]:
        """E = W + D/2 em %."""
        if self.wdl:
            w, d, _ = self.wdl
            return (w + d / 2) / 10
        return None


# ======================================================== rede
def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _get(url: str, token: str = "", timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token.strip()}")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if e.code == 401:
            raise FonteErro("token do Lichess inválido ou ausente")
        if e.code == 429:
            raise FonteErro("Lichess pediu pausa (limite de requisições); tente em 1 minuto")
        raise FonteErro(f"Lichess respondeu HTTP {e.code}")
    except (urllib.error.URLError, OSError) as e:
        raise FonteErro(f"sem conexão ({getattr(e, 'reason', e)})")


# ======================================================== conversões
def _pov(valor: Optional[int], board: chess.Board) -> Optional[int]:
    """Valores do Lichess vêm do ponto de vista das brancas."""
    if valor is None:
        return None
    return valor if board.turn == chess.WHITE else -valor


def mate_para_cp(mate: int) -> int:
    return (MATE_CP - abs(mate)) * (1 if mate > 0 else -1)


def _san_pv(board: chess.Board, ucis: List[str], n: int = 6) -> List[str]:
    b = board.copy()
    out = []
    for u in ucis[:n]:
        try:
            m = b.parse_uci(u)              # aceita roque como "rei captura torre" (e1h1), como o Lc0 escreve
            if m not in b.legal_moves:
                break
            out.append(b.san(m))
            b.push(m)
        except ValueError:
            break
    return out


def validar_fen(fen: str) -> chess.Board:
    fen = " ".join(fen.strip().split())
    try:
        b = chess.Board(fen)
    except ValueError:
        raise FonteErro("FEN inválido")
    if not b.is_valid():
        raise FonteErro("posição ilegal")
    if b.is_game_over():
        raise FonteErro("a partida já terminou nessa posição")
    return b


# ======================================================== Lichess
def nuvem(board: chess.Board, multipv: int = 5) -> (List[Opcao], int):
    q = urllib.parse.urlencode({"fen": board.fen(), "multiPv": min(multipv, 5)})
    dados = _get(f"https://lichess.org/api/cloud-eval?{q}")
    if not dados:
        return [], 0
    ops = []
    for i, pv in enumerate(dados.get("pvs", []), 1):
        ucis = pv.get("moves", "").split()
        if not ucis:
            continue
        m = chess.Move.from_uci(ucis[0])
        mate = _pov(pv.get("mate"), board)
        cp = mate_para_cp(mate) if mate is not None else _pov(pv.get("cp"), board)
        ops.append(Opcao(ucis[0], board.san(m), cp=cp, mate=mate,
                         pv=_san_pv(board, ucis), multipv=i))
    return ops, dados.get("depth", 0)


def banco(board: chess.Board, base: str, token: str, cfg: Dict) -> (Dict[str, Estat], Optional[str], int):
    if base == "masters":
        q = {"fen": board.fen(), "moves": 15, "topGames": 0}
    else:
        q = {"variant": "standard", "fen": board.fen(), "moves": 15, "topGames": 0,
             "recentGames": 0, "speeds": cfg["speeds"], "ratings": cfg["ratings"]}
    dados = _get(f"https://explorer.lichess.org/{base}?{urllib.parse.urlencode(q)}", token)
    if not dados:
        return {}, None, 0
    branco = board.turn == chess.WHITE
    res = {}
    for mv in dados.get("moves", []):
        n = mv["white"] + mv["draws"] + mv["black"]
        if n == 0:
            continue
        vit = mv["white"] if branco else mv["black"]
        res[mv["uci"]] = Estat(n, (vit + mv["draws"] / 2) / n, mv.get("averageRating"),
                               mv["white"], mv["draws"], mv["black"], mv.get("san", ""))
    total = dados["white"] + dados["draws"] + dados["black"]
    nome = (dados.get("opening") or {}).get("name")
    return res, nome, total


# ======================================================== Stockfish
def caminho_stockfish() -> Optional[str]:
    cands = []
    if os.environ.get("HED_STOCKFISH"):
        cands.append(os.environ["HED_STOCKFISH"])
    try:  # Android: o binário vem empacotado como biblioteca nativa
        from jnius import autoclass
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        cands.append(os.path.join(act.getApplicationInfo().nativeLibraryDir, "libstockfish.so"))
    except Exception:
        pass
    try:
        with open("/proc/self/maps") as f:
            for linha in f:
                p = linha.split()[-1]
                if p.endswith(("libmain.so", "libSDL2.so", "libpython3.11.so")):
                    cands.append(os.path.join(os.path.dirname(p), "libstockfish.so"))
                    break
    except Exception:
        pass
    for nome in ("stockfish", "/usr/games/stockfish"):
        w = shutil.which(nome) or (nome if os.path.exists(nome) else None)
        if w:
            cands.append(w)
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def diagnostico_stockfish() -> str:
    """Relatório do que acontece ao procurar e iniciar o Stockfish (para a tela Configurações)."""
    import time
    L = ["DIAGNÓSTICO DO STOCKFISH", ""]
    caminho = caminho_stockfish()
    nativo = None
    try:
        from jnius import autoclass
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        nativo = act.getApplicationInfo().nativeLibraryDir
        L.append(f"Pasta de bibliotecas: {nativo}")
        try:
            L.append("Arquivos: " + ", ".join(sorted(os.listdir(nativo))))
        except OSError as e:
            L.append(f"Não consegui listar a pasta: {e}")
    except Exception as e:
        L.append(f"(fora do Android ou jnius indisponível: {e})")
    alvo = caminho or (os.path.join(nativo, "libstockfish.so") if nativo else None)
    if not alvo:
        L.append("Stockfish: não encontrado em nenhum caminho.")
        return "\n".join(L)
    L.append(f"Caminho: {alvo}")
    L.append(f"Existe: {os.path.isfile(alvo)} | executável: {os.access(alvo, os.X_OK)}"
             + (f" | {os.path.getsize(alvo) / 1e6:.1f} MB" if os.path.isfile(alvo) else ""))
    if not os.path.isfile(alvo):
        return "\n".join(L)
    try:
        with open(alvo, "rb") as f:
            cab = f.read(18)
        tipo = int.from_bytes(cab[16:18], "little")
        L.append(f"Formato ELF: {'PIE (correto)' if tipo == 3 else 'estático não-PIE' if tipo == 2 else tipo}")
    except OSError as e:
        L.append(f"Não consegui ler o arquivo: {e}")
    L.append("")
    L.append("Iniciando o motor…")
    try:
        ini = time.time()
        p = subprocess.Popen([alvo], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True)
        out, err = p.communicate("uci\nisready\nquit\n", timeout=40)
        linhas = [x for x in out.splitlines() if x.startswith(("id name", "uciok", "readyok"))]
        L.append(f"Código de saída: {p.returncode} | {time.time() - ini:.1f}s")
        L.append("Resposta: " + (" / ".join(linhas) or "(nenhuma)"))
        if err.strip():
            L.append("Erro do motor: " + err.strip()[:400])
        L.append("RESULTADO: " + ("OK, o Stockfish funciona." if "uciok" in out else "FALHOU."))
    except Exception as e:
        L.append(f"RESULTADO: FALHOU ao executar — {type(e).__name__}: {e}")
    return "\n".join(L)


def caminho_lc0() -> Optional[str]:
    """Lc0 empacotado como biblioteca nativa (liblc0.so) ou indicado por HED_LC0."""
    cands = []
    if os.environ.get("HED_LC0"):
        cands.append(os.environ["HED_LC0"])
    try:
        from jnius import autoclass
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        cands.append(os.path.join(act.getApplicationInfo().nativeLibraryDir, "liblc0.so"))
    except Exception:
        pass
    sf = caminho_stockfish()
    if sf and sf.endswith("libstockfish.so"):
        cands.append(os.path.join(os.path.dirname(sf), "liblc0.so"))
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def diagnostico_lc0(rede: Optional[str], cfg: Optional[Dict] = None) -> str:
    """Inicia o Lc0 com a rede escolhida e calcula 1 posição: confirma que motor e rede funcionam."""
    import threading
    import time
    L = ["DIAGNÓSTICO DO LC0", ""]
    alvo = caminho_lc0()
    L.append(f"Binário: {alvo or 'não encontrado'}")
    L.append(f"Rede: {rede if rede and os.path.isfile(rede) else 'não carregada (Configurações → Carregar rede)'}")
    if not alvo or not rede or not os.path.isfile(rede):
        return "\n".join(L)
    linhas: List[str] = []
    try:
        p = subprocess.Popen([alvo], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1)

        def ler():
            for x in p.stdout:
                linhas.append(x.strip())
        threading.Thread(target=ler, daemon=True).start()
        ini = time.time()
        cfg = {**CFG_PADRAO, **(cfg or {})}
        ajustes = lc0_ajustes(cfg, chess.WHITE)
        for cmd in ("uci", f"setoption name WeightsFile value {rede}", "setoption name UCI_ShowWDL value true",
                    *ajustes, "isready", "position startpos", "go nodes 40"):
            p.stdin.write(cmd + "\n")
            p.stdin.flush()
        while time.time() - ini < 90 and not any(x.startswith("bestmove") for x in linhas):
            time.sleep(0.3)
        p.stdin.write("quit\n")
        p.stdin.flush()
        nome = next((x[8:] for x in linhas if x.startswith("id name")), "?")
        wdl = [x for x in linhas if " wdl " in x]
        L.append(f"Motor: {nome} | {time.time() - ini:.1f}s")
        if wdl:
            t = wdl[-1].split()
            i = t.index("wdl")
            L.append(f"WDL da posição inicial: {t[i + 1]}/{t[i + 2]}/{t[i + 3]} (‰)")
        opcs = {" ".join(x.split()[2:x.split().index("type")]) for x in linhas
                if x.startswith("option name") and " type " in x}
        from hed_core import ESTILOS
        elo = elo_wdl(cfg)
        L.append(f"Calibração do WDL: {'Elo ' + str(elo) if elo else 'normal (força do Lc0)'} — "
                 f"{'suportada' if 'WDLCalibrationElo' in opcs else 'NÃO suportada por este Lc0'}")
        L.append(f"Estilo: {ESTILOS.get(cfg['estilo'], ESTILOS['normal'])['nome']} — "
                 f"{'suportado' if 'Contempt' in opcs and 'ContemptMode' in opcs else 'NÃO suportado (vale só no HED)'}")
        erros = [x for x in linhas if "rror" in x or "xception" in x]
        if erros:
            L.append("Mensagens: " + " | ".join(erros[:3]))
        L.append("RESULTADO: " + ("OK, o Lc0 funciona com esta rede." if any(x.startswith("bestmove") for x in linhas)
                                  else "FALHOU."))
    except Exception as e:
        L.append(f"RESULTADO: FALHOU ao executar — {type(e).__name__}: {e}")
    return "\n".join(L)


class Motor:
    def __init__(self, caminho: str, hash_mb: int = 64):
        self.caminho = caminho
        self.p = subprocess.Popen([caminho], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.nome = "Stockfish"
        self._env("uci")
        for linha in self._ate("uciok"):
            if linha.startswith("id name"):
                self.nome = linha[8:].strip()
        threads = max(1, min(4, (os.cpu_count() or 2) - 1))
        self._env("setoption name UCI_ShowWDL value true")
        self._env(f"setoption name Threads value {threads}")
        self._env(f"setoption name Hash value {hash_mb}")
        self._pronto()

    def _env(self, cmd):
        self.p.stdin.write(cmd + "\n")
        self.p.stdin.flush()

    def _ate(self, prefixo):
        linhas = []
        while True:
            linha = self.p.stdout.readline()
            if not linha:
                raise FonteErro("o Stockfish fechou inesperadamente")
            linha = linha.strip()
            linhas.append(linha)
            if linha.startswith(prefixo):
                return linhas

    def _pronto(self):
        self._env("isready")
        self._ate("readyok")

    def buscar(self, board: chess.Board, multipv: int, tempo: float,
               searchmoves: Optional[List[str]] = None) -> (List[Opcao], int):
        self._env(f"setoption name MultiPV value {multipv}")
        self._env(f"position fen {board.fen()}")
        cmd = f"go movetime {int(tempo * 1000)}"
        if searchmoves:
            cmd += " searchmoves " + " ".join(searchmoves)
        self._env(cmd)
        ult: Dict[int, dict] = {}
        for linha in self._ate("bestmove"):
            t = linha.split()
            if not t or t[0] != "info" or "pv" not in t or "score" not in t:
                continue
            if "lowerbound" in t or "upperbound" in t:
                continue
            d = {"depth": int(t[t.index("depth") + 1]) if "depth" in t else 0}
            k = t.index("score")
            d[t[k + 1]] = int(t[k + 2])
            if "wdl" in t:
                w = t.index("wdl")
                d["wdl"] = (int(t[w + 1]), int(t[w + 2]), int(t[w + 3]))
            d["pv"] = t[t.index("pv") + 1:]
            mpv = int(t[t.index("multipv") + 1]) if "multipv" in t else 1
            ult[mpv] = d
        ops, prof = [], 0
        for mpv in sorted(ult):
            d = ult[mpv]
            m = chess.Move.from_uci(d["pv"][0])
            mate = d.get("mate")
            cp = mate_para_cp(mate) if mate is not None else d.get("cp")
            ops.append(Opcao(d["pv"][0], board.san(m), cp=cp, mate=mate, wdl=d.get("wdl"),
                             pv=_san_pv(board, d["pv"]), multipv=mpv))
            prof = max(prof, d["depth"])
        self._pronto()
        return ops, prof

    def fechar(self):
        try:
            self._env("quit")
            self.p.wait(timeout=2)
        except Exception:
            self.p.kill()


class MotorVivo:
    """Stockfish com leitura contínua: análise ao vivo (como no Lichess) e busca pontual.

    Uma única instância (um processo) serve o tabuleiro e o HED.
    """

    def __init__(self, caminho: str, hash_mb: int = 64, opcoes: Optional[Dict[str, str]] = None,
                 nome: str = "Stockfish"):
        import threading
        self.caminho = caminho
        self.nome = nome
        self.p = subprocess.Popen([caminho], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self._trava = threading.RLock()
        self._dados = threading.Lock()
        self._uciok, self._pronto_ev, self._fim = threading.Event(), threading.Event(), threading.Event()
        self._fim.set()
        self._info: Dict[int, dict] = {}
        self._board: Optional[chess.Board] = None
        self.suportadas = set()                 # opções que o motor anunciou em "uci"
        self._ajustes: List[str] = []           # últimos setoption enviados (evita repetir)
        self.ativo = True
        threading.Thread(target=self._ler, daemon=True).start()
        self._env("uci")
        if not self._uciok.wait(30):
            raise FonteErro(f"o {nome} não respondeu")
        self._env("setoption name UCI_ShowWDL value true")
        if opcoes is None:
            threads = max(1, min(4, (os.cpu_count() or 2) - 1))
            opcoes = {"Threads": str(threads), "Hash": str(hash_mb)}
        for k, v in opcoes.items():
            self._env(f"setoption name {k} value {v}")
        self._sincronizar()

    # ---- baixo nível
    def _env(self, cmd):
        self.p.stdin.write(cmd + "\n")
        self.p.stdin.flush()

    def _ler(self):
        for linha in self.p.stdout:
            t = linha.split()
            if not t:
                continue
            if t[0] == "info" and "pv" in t and "score" in t and "lowerbound" not in t and "upperbound" not in t:
                d = {"depth": int(t[t.index("depth") + 1]) if "depth" in t else 0}
                k = t.index("score")
                d[t[k + 1]] = int(t[k + 2])
                if "wdl" in t:
                    w = t.index("wdl")
                    d["wdl"] = (int(t[w + 1]), int(t[w + 2]), int(t[w + 3]))
                if "nodes" in t:
                    d["nodes"] = int(t[t.index("nodes") + 1])
                d["pv"] = t[t.index("pv") + 1:]
                mpv = int(t[t.index("multipv") + 1]) if "multipv" in t else 1
                with self._dados:
                    self._info[mpv] = d
            elif t[0] == "bestmove":
                self._fim.set()
            elif t[0] == "readyok":
                self._pronto_ev.set()
            elif t[0] == "uciok":
                self._uciok.set()
            elif t[0] == "option" and "name" in t and "type" in t:
                self.suportadas.add(" ".join(t[t.index("name") + 1:t.index("type")]))
            elif t[0] == "id" and len(t) > 2 and t[1] == "name":
                self.nome = " ".join(t[2:])
        self.ativo = False
        self._fim.set()

    def _sincronizar(self):
        self._pronto_ev.clear()
        self._env("isready")
        self._pronto_ev.wait(10)

    def _parar(self):
        if not self._fim.is_set():
            self._env("stop")
            self._fim.wait(5)

    def _iniciar(self, board: chess.Board, multipv: int, go: str, antes: Optional[List[str]] = None):
        self._parar()
        with self._dados:
            self._info = {}
            self._board = board.copy()
        cmds = [c for c in (antes or []) if self.aceita(c)]
        if cmds and cmds != self._ajustes:
            for c in cmds:
                self._env(c)
            self._ajustes = cmds
        self._env(f"setoption name MultiPV value {multipv}")
        self._env(f"position fen {board.fen()}")
        self._sincronizar()
        self._fim.clear()
        self._env(go)

    # ---- uso
    def aceita(self, cmd: str) -> bool:
        """True se o setoption é de uma opção que o motor conhece."""
        if not cmd.startswith("setoption name "):
            return True
        resto = cmd[len("setoption name "):]
        nome = resto.split(" value ")[0]
        return nome in self.suportadas

    def vivo(self, board: chess.Board, multipv: int = 3, profundidade: int = 24, go: Optional[str] = None,
             antes: Optional[List[str]] = None):
        """Começa (ou reinicia) a análise ao vivo da posição; não bloqueia."""
        if not self.ativo or board.is_game_over():
            self.parar()
            return
        with self._trava:
            self._iniciar(board, multipv, go or f"go depth {int(profundidade)}", antes)

    def parar(self):
        with self._trava:
            self._parar()

    @property
    def pensando(self) -> bool:
        return not self._fim.is_set()

    def fen_atual(self) -> Optional[str]:
        with self._dados:
            return self._board.fen() if self._board is not None else None

    def linhas(self) -> (List[Opcao], int):
        with self._dados:
            info, board = dict(self._info), self._board
        if board is None:
            return [], 0
        ops, prof = [], 0
        for mpv in sorted(info):
            d = info[mpv]
            try:
                m = board.parse_uci(d["pv"][0])   # normaliza o roque do Lc0 (e1h1 -> e1g1)
                san = board.san(m)
            except (ValueError, IndexError, AssertionError):
                continue
            mate = d.get("mate")
            cp = mate_para_cp(mate) if mate is not None else d.get("cp")
            ops.append(Opcao(m.uci(), san, cp=cp, mate=mate, wdl=d.get("wdl"),
                             pv=_san_pv(board, d["pv"], 10), multipv=mpv))
            prof = max(prof, d["depth"])
        return ops, prof

    def buscar(self, board: chess.Board, multipv: int, tempo: float,
               searchmoves: Optional[List[str]] = None, antes: Optional[List[str]] = None,
               nos: Optional[int] = None) -> (List[Opcao], int):
        cmd = f"go nodes {int(nos)}" if nos else f"go movetime {int(tempo * 1000)}"
        if searchmoves:
            cmd += " searchmoves " + " ".join(searchmoves)
        with self._trava:
            self._iniciar(board, multipv, cmd, antes)
            self._fim.wait(tempo + 15 if not nos else 120)
            return self.linhas()

    def fechar(self):
        try:
            self.parar()
            self._env("quit")
            self.p.wait(timeout=2)
        except Exception:
            self.p.kill()


def chance_brancas(cp_brancas: Optional[int]) -> float:
    """Fração (0–1) para a barra de avaliação, com a mesma curva de win% do Lichess."""
    import math
    if cp_brancas is None:
        return 0.5
    cp = max(-1000, min(1000, cp_brancas))
    return 0.5 + 0.5 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def texto_aval(o: Opcao, branco_joga: bool) -> str:
    """Avaliação no padrão do Lichess (ponto de vista das brancas): +0.35, -1.20, #3, #-2."""
    sinal = 1 if branco_joga else -1
    if o.mate is not None:
        return f"#{o.mate * sinal}"
    if o.cp is None:
        return "?"
    return f"{o.cp * sinal / 100:+.2f}"


def ler_partida(texto: str) -> (str, List[str]):
    """Aceita FEN ou PGN (como o Lichess exporta). Devolve (FEN inicial, lances UCI)."""
    texto = (texto or "").strip()
    if not texto:
        raise FonteErro("nada para carregar")
    try:
        return validar_fen(texto).fen(), []
    except FonteErro:
        pass
    import io
    import chess.pgn
    jogo = chess.pgn.read_game(io.StringIO(texto))
    if jogo is None or (not jogo.headers.get("FEN") and not list(jogo.mainline_moves())):
        raise FonteErro("não reconheci FEN nem PGN")
    inicio = jogo.board()
    return inicio.fen(), [m.uci() for m in jogo.mainline_moves()]


# ======================================================== coleta combinada
def coletar(fen: str, cfg: Dict, motor: Optional[Motor] = None, progresso=lambda s: None,
            p_registro: Optional[float] = None, lc0=None) -> Dict:
    cfg = {**CFG_PADRAO, **(cfg or {})}
    board = validar_fen(fen)
    r = {"fen": board.fen(), "lado": "brancas" if board.turn else "pretas",
         "abertura": None, "avisos": [], "fonte": None, "prof": 0, "opcoes": []}

    # 1. Banco de partidas
    est = {"masters": {}, "lichess": {}}
    if cfg["token"].strip():
        for base in ("masters", "lichess"):
            progresso(f"Consultando banco {base}…")
            try:
                est[base], nome, total = banco(board, base, cfg["token"], cfg)
                r["abertura"] = r["abertura"] or nome
                r[f"total_{base}"] = total
            except FonteErro as e:
                r["avisos"].append(f"Banco {base}: {e}")
    else:
        r["avisos"].append("Sem token do Lichess: banco de partidas desligado (veja Configurações).")

    # 2. Motor
    ops: List[Opcao] = []
    if cfg["motor"] == "Stockfish local" and motor is not None:
        progresso(f"Stockfish pensando {cfg['tempo']:.0f}s…")
        ops, r["prof"] = motor.buscar(board, int(cfg["multipv"]), float(cfg["tempo"]))
        r["fonte"] = motor.nome
        vistos = {o.uci for o in ops}
        extras = []
        for base in ("masters", "lichess"):
            ordem = sorted(est[base].items(), key=lambda kv: -kv[1].n)
            extras += [u for u, _ in ordem[: int(cfg["extras"])] if u not in vistos and u not in extras]
        extras = [u for u in extras if chess.Move.from_uci(u) in board.legal_moves]
        if extras:
            progresso(f"Avaliando {len(extras)} lance(s) do banco…")
            mais, _ = motor.buscar(board, len(extras), float(cfg["tempo"]), extras)
            for o in mais:
                o.multipv = None
            ops += mais
    else:
        if cfg["motor"] == "Stockfish local":
            r["avisos"].append("Stockfish local indisponível: usando a nuvem do Lichess.")
        progresso("Consultando avaliação na nuvem do Lichess…")
        try:
            ops, r["prof"] = nuvem(board, int(cfg["multipv"]))
            r["fonte"] = "Lichess nuvem"
            if not ops:
                r["avisos"].append("Posição fora da nuvem do Lichess: sem avaliação do motor.")
        except FonteErro as e:
            r["avisos"].append(f"Nuvem: {e}")
        vistos = {o.uci for o in ops}
        for base in ("masters", "lichess"):
            for u in est[base]:
                if u not in vistos and chess.Move.from_uci(u) in board.legal_moves:
                    ops.append(Opcao(u, board.san(chess.Move.from_uci(u))))
                    vistos.add(u)

    for o in ops:
        o.masters = est["masters"].get(o.uci)
        o.lichess = est["lichess"].get(o.uci)
    r["opcoes"] = ops

    # 2b. Divisão de trabalho: Stockfish escolhe os lances e julga a tática (avaliação, perda);
    #     o Lc0 dá as chances (WDL), que entram na pontuação esperada E.
    for o in ops:
        o.fonte_wdl = "Stockfish" if o.wdl else None
    r["fonte_wdl"] = "Stockfish" if any(o.wdl for o in ops) else None
    if lc0 is not None and ops:
        try:
            progresso("Lc0 calculando as chances (WDL) dos lances…")
            ucis = [o.uci for o in ops][:12]
            ajustes = lc0_ajustes(cfg, board.turn)
            lops, _ = lc0.buscar(board, len(ucis), float(cfg["tempo"]), ucis, antes=ajustes)
            por = {o.uci: o for o in lops if o.wdl}
            for o in ops:
                x = por.get(o.uci)
                if x:
                    o.wdl_sf, o.wdl, o.fonte_wdl, o.cp_lc0 = o.wdl, x.wdl, "Lc0", x.cp
            # os que o Lc0 não cobriu: avalia a posição depois do lance (WDL do adversário, invertido)
            faltam = [o for o in ops if o.fonte_wdl != "Lc0"][:6]
            if faltam:
                progresso(f"Lc0 completando {len(faltam)} lance(s)…")
            t1 = max(0.5, min(1.5, float(cfg["tempo"]) / 2))
            for o in faltam:
                wdl = wdl_depois(lc0, board, o.uci, t1, antes=ajustes)
                if wdl:
                    o.wdl_sf, o.wdl, o.fonte_wdl = o.wdl, wdl, "Lc0"
                    por[o.uci] = o
            n = sum(1 for o in ops if o.fonte_wdl == "Lc0")
            if n:
                r["fonte_wdl"] = f"Lc0 ({n}/{len(ops)} lances)"
            else:
                r["avisos"].append("Lc0 não devolveu WDL: usado o do Stockfish.")
        except Exception as e:
            r["avisos"].append(f"Lc0 indisponível ({e}): usado o WDL do Stockfish.")
    comparar_motores(ops, r)

    # 3. TF × Conversão automática (nunca derruba a análise)
    r["tf"] = None
    try:
        from hed_auto import tf_auto
        local = motor if (cfg["motor"] == "Stockfish local" and motor is not None) else None
        if local:
            progresso("Medindo o custo de errar a linha forçada…")
        r["tf"] = tf_auto(board, ops, local, min(2.0, float(cfg["tempo"])), p_registro)
    except Exception as e:
        r["avisos"].append(f"TF automática indisponível: {e}")
    return r


def wdl_depois(motor, board: chess.Board, uci: str, tempo: float,
               antes: Optional[List[str]] = None) -> Optional[tuple]:
    """WDL de quem joga, calculado na posição depois do lance (ponto de vista do adversário, invertido).

    `antes` deve ser calculado para quem jogou o lance (o estilo continua sendo o dele)."""
    b2 = board.copy()
    b2.push(board.parse_uci(uci))
    if b2.is_game_over():
        r = b2.result()
        if r == "1/2-1/2":
            return (0, 1000, 0)
        return (1000, 0, 0)                      # quem acabou de jogar deu mate
    ops, _ = motor.buscar(b2, 1, tempo, antes=antes)
    if ops and ops[0].wdl:
        w, d, l = ops[0].wdl
        return (l, d, w)
    return None


def comparar_motores(ops: List[Opcao], r: Dict) -> None:
    """Ranking de cada motor e se concordam no melhor lance.

    Stockfish: ordena pela avaliação (cp). Lc0: ordena pela pontuação esperada do WDL dele.
    """
    com_cp = sorted((o for o in ops if o.cp is not None), key=lambda o: -o.cp)
    for i, o in enumerate(com_cp, 1):
        o.rank_sf = i
    lc = sorted((o for o in ops if o.fonte_wdl == "Lc0"), key=lambda o: -o.expectativa)
    for i, o in enumerate(lc, 1):
        o.rank_lc0 = i
    r["sf_melhor"] = com_cp[0].san if com_cp else None
    r["lc0_melhor"] = lc[0].san if lc else None
    if r["sf_melhor"] and r["lc0_melhor"]:
        if r["sf_melhor"] == r["lc0_melhor"]:
            r["motores"] = f"Stockfish e Lc0 concordam: {r['sf_melhor']}"
        else:
            r["motores"] = f"Stockfish prefere {r['sf_melhor']} · Lc0 prefere {r['lc0_melhor']}"
    else:
        r["motores"] = None


def texto_wdl(wdl: Optional[tuple]) -> str:
    """(W, D, L) em ‰ → 'vence 32% · empata 55% · perde 13%'."""
    if not wdl:
        return "sem WDL"
    w, d, l = (round(x / 10) for x in wdl)
    return f"vence {w}% · empata {d}% · perde {l}%"


def melhor_cp(opcoes: List[Opcao]) -> Optional[int]:
    v = [o.cp for o in opcoes if o.cp is not None]
    return max(v) if v else None


def para_candidato(o: Opcao, ref_cp: int, board: Optional[chess.Board] = None, livro: Optional[Dict] = None):
    """Converte uma Opcao em Candidato do HED (perda em peões vs melhor lance do motor).

    Leva a avaliação (para a pontuação esperada) e o WDL. Com a posição (`board`), as 10 notas
    vêm estimadas automaticamente (hed_auto) e ficam marcadas como 'auto' até o jogador ajustar;
    sem ela, só Reversibilidade/Forçamento são sugeridas pelo próprio lance.
    """
    from hed_core import Candidato, aplicar_sugestoes
    delta = round(max(0, ref_cp - o.cp) / 100, 2)
    w = d = l = None
    if o.wdl:
        w, d, l = (x / 10 for x in o.wdl)
    c = Candidato(lance=o.san, delta=delta, w=w, d=d, l=l, aval_cp=o.cp)
    c.motores = {"sf_cp": o.cp, "sf_mate": o.mate, "sf_rank": o.rank_sf, "wdl": list(o.wdl) if o.wdl else None,
                 "wdl_fonte": o.fonte_wdl, "lc0_rank": o.rank_lc0, "lc0_cp": o.cp_lc0}
    if board is not None:
        try:
            from hed_auto import estimar_notas, conversao, filtro_auto
            m = chess.Move.from_uci(o.uci)
            notas = estimar_notas(board, m, o.wdl, o.mate)
            if o.pv:
                # olha o fim da linha do motor: estrutura, peças, espaço e planos ajustam as notas
                from hed_plano import analise_continuacao, ajustar_notas
                c.analise = analise_continuacao(board, o.pv)
                c.analise["fen"] = board.fen()
                if livro:
                    _juntar_livro(c.analise, board, o.pv, livro)
                notas = ajustar_notas(notas, c.analise)
            for k, v in notas.items():
                setattr(c, k, v)
                c.auto.append(k)
                c.auto_orig[k] = v
            c.conversao = conversao(board, m)
            c.auto.append("conversao")
            f = filtro_auto(board, o, delta)
            if f is not None:
                c.filtro = f
                c.atualizar_filtro()
                c.auto.append("filtro")
        except Exception:
            aplicar_sugestoes(c)
    else:
        aplicar_sugestoes(c)
    if o.masters:
        c.n_masters, c.pts_masters = o.masters.n, round(o.masters.pts, 3)
    if o.lichess:
        c.n_lichess, c.pts_lichess = o.lichess.n, round(o.lichess.pts, 3)
    return c


def _juntar_livro(analise: Dict, board: chess.Board, pv: List[str], livro: Dict) -> None:
    """Acrescenta o que o livro do jogador (ex.: FCO) diz da linha: planos, rupturas e tom."""
    from hed_livro import consultar, texto_tom
    fco = consultar(livro, board, pv)
    analise["fco"] = fco
    if not fco:
        return
    for p in fco["planos"]:
        rot = f"{p} (FCO)"
        if rot not in analise["planos"]:
            analise["planos"].append(rot)
    for r in fco["rupturas"]:
        if r not in analise.get("rupturas", []):
            analise.setdefault("rupturas", []).append(r)
    lado = "brancas" if board.turn == chess.WHITE else "pretas"
    contra_lado = "pretas" if lado == "brancas" else "brancas"
    if fco["tom"] == lado:
        analise.setdefault("pro", []).append("o livro (FCO) vê esta linha melhor para você")
    elif fco["tom"] == contra_lado:
        analise.setdefault("contra", []).append("o livro (FCO) vê o adversário melhor nesta linha")
    elif fco["tom"] == "duvidoso":
        analise.setdefault("contra", []).append("o livro (FCO) considera a linha duvidosa")
    pro, contra = len(analise.get("pro", [])), len(analise.get("contra", []))
    analise["balanco"] = ("compensa" if pro - contra >= 2 else "equilibrado" if pro - contra >= 0
                          else "não compensa")
    analise["fco_tom"] = texto_tom(fco["tom"])


def linha_texto(o: Opcao, ref_cp: Optional[int]) -> str:
    """Linha 1: Stockfish (avaliação, ranking, perda). Linha 2: chances (WDL) e de qual motor."""
    if o.cp is None:
        av = "sem aval."
    elif o.mate is not None:
        av = f"M{o.mate:+d}"
    else:
        av = f"{o.cp / 100:+.2f}"
    perda = f" perda {max(0, ref_cp - o.cp) / 100:.2f}" if (o.cp is not None and ref_cp is not None) else ""
    rk = f" ({o.rank_sf}º)" if o.rank_sf else ""
    m = f" | M {o.masters.n} {o.masters.pts:.0%}" if o.masters else ""
    li = f" | L {o.lichess.n} {o.lichess.pts:.0%}" if o.lichess else ""
    marca = "" if o.multipv else " (banco)"
    l1 = f"{o.san}{marca}  SF {av}{rk}{perda}{m}{li}"
    if o.wdl:
        quem = o.fonte_wdl or "WDL"
        rk2 = f" ({o.rank_lc0}º)" if o.rank_lc0 else ""
        w, d, l = (round(x / 10) for x in o.wdl)
        l2 = f"  {quem}: V {w}% · Emp {d}% · D {l}% → E {o.expectativa:.0f}%{rk2}"
    else:
        l2 = "  sem WDL"
    return l1 + "\n" + l2