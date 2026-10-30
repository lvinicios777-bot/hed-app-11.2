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
    "token": "",
    "motor": "Stockfish local",      # ou "Lichess nuvem"
    "tempo": 4.0,                    # segundos por busca
    "multipv": 5,
    "ratings": "2000,2200,2500",
    "speeds": "blitz,rapid,classical",
    "extras": 3,                     # lances do banco avaliados além do MultiPV
}


class FonteErro(Exception):
    pass


# ======================================================== estruturas
@dataclass
class Estat:
    n: int
    pts: float            # pontuação média de quem joga (0–1)
    rating: Optional[int] = None


@dataclass
class Opcao:
    uci: str
    san: str
    cp: Optional[int] = None              # POV de quem joga; mate convertido
    mate: Optional[int] = None
    wdl: Optional[tuple] = None           # (W, D, L) em ‰, POV de quem joga
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
            m = chess.Move.from_uci(u)
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
        res[mv["uci"]] = Estat(n, (vit + mv["draws"] / 2) / n, mv.get("averageRating"))
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


# ======================================================== coleta combinada
def coletar(fen: str, cfg: Dict, motor: Optional[Motor] = None, progresso=lambda s: None) -> Dict:
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
    return r


def melhor_cp(opcoes: List[Opcao]) -> Optional[int]:
    v = [o.cp for o in opcoes if o.cp is not None]
    return max(v) if v else None


def para_candidato(o: Opcao, ref_cp: int):
    """Converte uma Opcao em Candidato do HED (perda em peões vs melhor lance do motor)."""
    from hed_core import Candidato
    delta = round(max(0, ref_cp - o.cp) / 100, 2)
    w = d = l = None
    if o.wdl:
        w, d, l = (x / 10 for x in o.wdl)
    c = Candidato(lance=o.san, delta=delta, w=w, d=d, l=l)
    if o.masters:
        c.n_masters, c.pts_masters = o.masters.n, round(o.masters.pts, 3)
    if o.lichess:
        c.n_lichess, c.pts_lichess = o.lichess.n, round(o.lichess.pts, 3)
    return c


def linha_texto(o: Opcao, ref_cp: Optional[int]) -> str:
    if o.cp is None:
        av = "  sem aval."
    elif o.mate is not None:
        av = f"  M{o.mate:+d}"
    else:
        av = f"{o.cp / 100:+6.2f}"
    perda = f" perda {max(0, ref_cp - o.cp) / 100:.2f}" if (o.cp is not None and ref_cp is not None) else ""
    e = f" E{o.expectativa:4.0f}%" if o.expectativa is not None else ""
    m = f" | M {o.masters.n} {o.masters.pts:.0%}" if o.masters else ""
    li = f" | L {o.lichess.n} {o.lichess.pts:.0%}" if o.lichess else ""
    marca = "" if o.multipv else " (banco)"
    return f"{o.san}{marca}: {av}{perda}{e}{m}{li}"
