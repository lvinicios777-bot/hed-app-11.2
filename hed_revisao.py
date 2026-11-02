"""Revisão de partida inteira (estilo chess.com): classe de cada lance e precisão de cada lado.

Para cada posição da partida:
  • Stockfish (MultiPV 2): melhor lance, 2º melhor e avaliação → E pela curva do Lichess.
  • Lc0 (opcional, se a classificação for pelo Lc0): calcula à força o melhor do Stockfish, o 2º e o
    lance jogado (searchmoves) → E = V + Emp/2 de cada um, na mesma busca.
  • Lance jogado fora das linhas do Stockfish: E = 100 − E do melhor lance na posição seguinte.

Precisão por lance (fórmula do Lichess): 103,1668·e^(−0,04354·perda) − 3,1669, perda em pontos %.
Precisão da partida: média entre a média aritmética e a harmônica dos lances (pune os erros grandes).
"""
import math
from typing import Callable, Dict, List, Optional

import chess

import hed_classe as KC


def precisao_lance(e_antes: float, e_depois: float) -> float:
    perda = max(0.0, e_antes - e_depois)
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * perda) - 3.1669))


def precisao_partida(v: List[float]) -> Optional[float]:
    if not v:
        return None
    arit = sum(v) / len(v)
    harm = len(v) / sum(1.0 / max(x, 1.0) for x in v)
    return (arit + harm) / 2


def _aval_sf(motor, nuvem, b: chess.Board, tempo: float):
    """[(uci, E%)] do Stockfish em ordem (até 2), do ponto de vista de quem joga."""
    if motor is not None:
        ops, _ = motor.buscar(b, 2, tempo)
    elif nuvem is not None:
        ops, _ = nuvem(b, 2)
    else:
        ops = []
    return [(o.uci, KC.e_de_cp(o.cp)) for o in ops if o.cp is not None]


def revisar(inicio: str, lances: List[str], motor=None, nuvem=None, lc0=None, ajustes_lc0=None,
            tempo: float = 0.4, nos_lc0: int = 3000, livro: Optional[Callable] = None,
            progresso: Callable = lambda i, n: None, cancelado: Callable = lambda: False) -> Dict:
    """Revisa a partida. `ajustes_lc0(cor)` devolve os setoption de rating/estilo do lado `cor`."""
    b = chess.Board(inicio)
    pos = [b.copy()]
    for u in lances:
        b.push(b.parse_uci(u))
        pos.append(b.copy())
    n = len(lances)
    sf: List[List] = []
    for i, p in enumerate(pos):
        if cancelado():
            return {"cancelado": True}
        progresso(i, n + 1)
        sf.append([] if p.is_game_over() else _aval_sf(motor, nuvem, p, tempo))

    no_livro = True
    out, acc = [], {chess.WHITE: [], chess.BLACK: []}
    for i, u in enumerate(lances):
        if cancelado():
            return {"cancelado": True}
        p, q = pos[i], pos[i + 1]
        m = p.parse_uci(u)
        san = p.san(m)
        linhas = sf[i]
        e_best = linhas[0][1] if linhas else None
        segundo = linhas[1][1] if len(linhas) > 1 else None
        melhor_uci = linhas[0][0] if linhas else None
        e_lance = dict(linhas).get(u)
        if e_lance is None:
            if q.is_checkmate():
                e_lance = 100.0
            elif q.is_game_over():
                e_lance = 50.0
            elif sf[i + 1]:
                e_lance = 100.0 - sf[i + 1][0][1]
        fonte = "Stockfish"
        if lc0 is not None and linhas:
            alvo = list(dict.fromkeys([x[0] for x in linhas] + [u]))
            try:
                lops, _ = lc0.buscar(p, len(alvo), 2.0, alvo, antes=ajustes_lc0(p.turn) if ajustes_lc0 else None,
                                     nos=nos_lc0)
                le = {o.uci: o.expectativa for o in lops if o.wdl}
                if u in le and le:
                    ordem = sorted(le.values(), reverse=True)
                    e_best, e_lance = ordem[0], le[u]
                    segundo = ordem[1] if len(ordem) > 1 else None
                    melhor_uci = max(le, key=le.get)
                    fonte = "Lc0"
            except Exception:
                pass
        eh_livro = False
        if no_livro and livro is not None and p.fullmove_number <= 12:
            try:
                eh_livro = bool(livro(p, u))
            except Exception:
                eh_livro = False
            no_livro = eh_livro
        classe = KC.classificar(e_best, e_lance, eh_melhor=(u == melhor_uci), segundo=segundo,
                                board=p, move=m, livro=eh_livro)
        melhor_san = p.san(p.parse_uci(melhor_uci)) if melhor_uci else None
        if e_best is not None and e_lance is not None:
            acc[p.turn].append(precisao_lance(e_best, e_lance))
        out.append({"ply": i + 1, "uci": u, "san": san, "cor": "brancas" if p.turn else "pretas",
                    "num": p.fullmove_number, "classe": classe, "e_melhor": e_best, "e_lance": e_lance,
                    "melhor": melhor_san, "fonte": fonte})
    contagem = {lado: {k: 0 for k in KC.CLASSES} for lado in ("brancas", "pretas")}
    for x in out:
        if x["classe"]:
            contagem[x["cor"]][x["classe"]] += 1
    return {"lances": out, "contagem": contagem, "inicio": inicio, "ucis": list(lances),
            "precisao": {"brancas": precisao_partida(acc[chess.WHITE]),
                         "pretas": precisao_partida(acc[chess.BLACK])}}


def _testes():
    assert abs(precisao_lance(50, 50) - 100) < 0.01
    assert 40 < precisao_lance(60, 40) < 45
    assert precisao_partida([100, 100]) > 99.9 and precisao_partida([]) is None
    assert precisao_partida([100, 10]) < 55        # a harmônica pune o erro grande

    class Falso:
        """Motor de teste: avaliação = material de quem joga (centipeões)."""
        def buscar(self, b, multipv, tempo, searchmoves=None, antes=None, nos=None):
            from hed_fontes import Opcao
            res = []
            for m in b.legal_moves:
                x = b.copy()
                x.push(m)
                mat = sum((1 if p.color == b.turn else -1) * KC.VALOR[p.piece_type] * 100
                          for p in x.piece_map().values())
                res.append(Opcao(m.uci(), b.san(m), cp=mat))
            res.sort(key=lambda o: -o.cp)
            return res[:multipv], 1
    # 1.e4 e5 2.Qh5 Nc6 3.Qxe5+?? (dama pendurada? não: troca dama por peão defendido) — usa motor falso
    r = revisar(chess.STARTING_FEN, ["e2e4", "e7e5", "d1h5", "b8c6", "h5e5", "c6e5"], motor=Falso())
    cl = [x["classe"] for x in r["lances"]]
    assert cl[4] == "capivarada", cl                 # Qxe5+ entrega a dama por um peão
    assert r["precisao"]["brancas"] < r["precisao"]["pretas"], r["precisao"]
    assert r["contagem"]["brancas"]["capivarada"] == 1
    print("hed_revisao: testes OK")


if __name__ == "__main__":
    _testes()
