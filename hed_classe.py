"""Classificação de lances no estilo do chess.com (cores, símbolos e limiares de pontos esperados).

Limiares oficiais do chess.com (perda de pontos esperados, escala 0–1):
    Melhor 0 | Excelente ≤ 0,02 | Bom ≤ 0,05 | Imprecisão ≤ 0,10 | Erro ≤ 0,20 | Capivarada > 0,20
Especiais: Brilhante (bom sacrifício de peça), Ótimo (único lance bom), Teoria (lance de livro),
Perdeu a chance (não aproveitou a vantagem).

Aqui E está em % (0–100); perda = (E_melhor − E_lance) / 100.
"""
import math
from typing import Optional

import chess

# chave: (nome, símbolo, cor hex)
CLASSES = {
    "brilhante": ("Brilhante", "!!", "26c2a3"),
    "otimo": ("Ótimo", "!", "749bbf"),
    "melhor": ("Melhor", "★", "81b64c"),
    "excelente": ("Excelente", "✓", "96bc4b"),
    "bom": ("Bom", "✓", "95b776"),
    "livro": ("Teoria", "≡", "a88764"),
    "imprecisao": ("Imprecisão", "?!", "f7c045"),
    "erro": ("Erro", "?", "ffa459"),
    "perdeu": ("Perdeu a chance", "✗", "ff7769"),
    "capivarada": ("Capivarada", "??", "fa412d"),
}
LIMIARES = ((0.0005, "melhor"), (0.02, "excelente"), (0.05, "bom"), (0.10, "imprecisao"), (0.20, "erro"))
VALOR = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


def rgba(chave: str, alfa: float = 1.0):
    h = CLASSES[chave][2]
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (alfa,)


def e_de_cp(cp: Optional[float]) -> Optional[float]:
    """Pontos esperados (%) a partir da avaliação em centipeões (curva do Lichess)."""
    if cp is None:
        return None
    cp = max(-2000, min(2000, cp))
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def _en_prise(b: chess.Board, casa: int) -> bool:
    """A peça em `casa` pode ser capturada com ganho pelo lado que joga em `b`."""
    p = b.piece_at(casa)
    if p is None or p.piece_type == chess.KING:
        return False
    atac = [s for s in b.attackers(b.turn, casa) if b.piece_at(s)]
    if not atac:
        return False
    if not b.attackers(p.color, casa):
        return True
    return min(VALOR[b.piece_at(s).piece_type] for s in atac) < VALOR[p.piece_type]


def sacrificio(b: chess.Board, m: chess.Move) -> bool:
    """O lance deixa (de novo) uma peça de valor ≥ 3 capturável com ganho, sem ser uma troca."""
    cor = b.turn
    antes = {s for s, p in b.piece_map().items() if p.color == cor and VALOR[p.piece_type] >= 3}
    ja = {s for s in antes if _en_prise(_vez(b, not cor), s)}
    capt = b.piece_at(m.to_square)
    ganho = VALOR[capt.piece_type] if capt else (1 if b.is_en_passant(m) else 0)
    b2 = b.copy()
    b2.push(m)
    for s, p in b2.piece_map().items():
        if p.color != cor or VALOR[p.piece_type] < 3:
            continue
        origem = m.from_square if s == m.to_square else s
        if origem in ja:
            continue                                   # já estava pendurada antes: não é sacrifício novo
        if _en_prise(b2, s) and VALOR[p.piece_type] - ganho >= 2:
            return True
    return False


def _vez(b: chess.Board, cor: bool) -> chess.Board:
    x = b.copy(stack=False)
    x.turn = cor
    return x


def classificar(e_melhor: Optional[float], e_lance: Optional[float], *, eh_melhor: bool = False,
                segundo: Optional[float] = None, board: Optional[chess.Board] = None,
                move: Optional[chess.Move] = None, livro: bool = False) -> Optional[str]:
    """Classe do lance. e_melhor = E do melhor lance; e_lance = E depois deste lance (% de quem jogou)."""
    if e_melhor is None or e_lance is None:
        return None
    perda = max(0.0, (e_melhor - e_lance) / 100)
    if eh_melhor:
        perda = 0.0
    if livro and perda <= 0.05:
        return "livro"
    if perda <= 0.02 and board is not None and move is not None and e_lance >= 50 and e_melhor < 85:
        try:
            if sacrificio(board, move):
                return "brilhante"
        except Exception:
            pass
    if perda <= 0.0005 and segundo is not None and e_melhor - segundo >= 10 and e_melhor < 90:
        return "otimo"                                 # único lance bom: o 2º melhor perde ≥ 0,10
    if perda >= 0.10 and e_melhor >= 65 and e_lance <= 55:
        return "perdeu"                                # tinha vantagem e deixou escapar
    for lim, chave in LIMIARES:
        if perda <= lim:
            return chave
    return "capivarada"


def texto(chave: Optional[str]) -> str:
    return CLASSES[chave][0] if chave else ""


def _testes():
    assert classificar(55, 55) == "melhor"
    assert classificar(55, 53.5) == "excelente"
    assert classificar(55, 51) == "bom"
    assert classificar(55, 47) == "imprecisao"
    assert classificar(55, 40) == "erro"
    assert classificar(55, 20) == "capivarada"
    assert classificar(80, 50) == "perdeu"
    assert classificar(60, 60, segundo=45) == "otimo"
    assert classificar(52, 51, livro=True) == "livro"
    # Bxh7+ grego clássico: sacrifício de bispo
    b = chess.Board("r1bq1rk1/pppn1ppp/4p3/3pP3/1b1P4/2NB1N2/PPP2PPP/R1BQK2R w KQ - 0 8")
    assert sacrificio(b, b.parse_san("Bxh7+"))
    assert not sacrificio(b, b.parse_san("O-O"))
    # troca simples não é sacrifício
    b = chess.Board("rnbqkbnr/ppp2ppp/8/3pp3/3PP3/8/PPP2PPP/RNBQKBNR w KQkq - 0 3")
    assert not sacrificio(b, b.parse_san("exd5"))
    assert classificar(60, 60, board=chess.Board("r1bq1rk1/pppn1ppp/4p3/3pP3/1b1P4/2NB1N2/PPP2PPP/R1BQK2R w KQ - 0 8"),
                       move=chess.Move.from_uci("d3h7")) == "brilhante"
    assert abs(e_de_cp(0) - 50) < 1e-9 and e_de_cp(300) > 70
    print("hed_classe: testes OK")


if __name__ == "__main__":
    _testes()
