"""
HED 11.1.2 — automação: notas estimadas pela posição e TF × Conversão pelo motor.

Tudo aqui é ESTIMATIVA para o jogador ajustar. As regras são simples e explícitas, para que
o Registro (PR/CC/AC/RP) possa mostrar depois onde elas erram.

Depende só de python-chess. O motor (opcional) é qualquer objeto com
buscar(board, multipv, tempo) -> (List[Opcao], profundidade), como hed_fontes.MotorVivo.
"""
from typing import Dict, List, Optional

import chess

from hed_core import pontuacao_cp, limiar_tf

VALOR = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
CENTRO = (chess.D4, chess.E4, chess.D5, chess.E5)
P_POR_LANCE = 0.90     # confiança provisória por lance a calcular, até o Registro ter dados


def _lim(x: float) -> float:
    return round(max(0.0, min(10.0, x)) * 2) / 2      # 0–10, passo 0,5 (como os controles)


# ======================================================== auxiliares de posição
def pendurados(b: chess.Board, cor: bool) -> int:
    """Maior ganho material imediato do adversário contra peças de `cor` (estático)."""
    melhor = 0
    for sq, peca in b.piece_map().items():
        if peca.color != cor or peca.piece_type == chess.KING:
            continue
        atac = b.attackers(not cor, sq)
        if not atac:
            continue
        menor = min(VALOR[b.piece_at(a).piece_type] or 100 for a in atac)
        ganho = VALOR[peca.piece_type] if not b.attackers(cor, sq) else VALOR[peca.piece_type] - menor
        melhor = max(melhor, ganho)
    return melhor


def _mobilidade(b: chess.Board, cor: bool) -> int:
    c = b.copy(stack=False)
    c.turn = cor
    c.ep_square = None
    return c.pseudo_legal_moves.count()


def _estrutura(b: chess.Board, cor: bool) -> (int, int):
    peoes = b.pieces(chess.PAWN, cor)
    colunas = [chess.square_file(s) for s in peoes]
    dobrados = sum(colunas.count(f) - 1 for f in set(colunas))
    isolados = sum(1 for f in colunas if (f - 1) not in colunas and (f + 1) not in colunas)
    return isolados, dobrados


def _rei_rocado(b: chess.Board, cor: bool) -> Optional[int]:
    k = b.king(cor)
    if k is None:
        return None
    f, r = chess.square_file(k), chess.square_rank(k)
    if r == (0 if cor == chess.WHITE else 7) and f in (0, 1, 2, 6, 7):
        return f
    return None


def eh_forcante(b: chess.Board, m: chess.Move) -> bool:
    """Xeque, captura ou ameaça direta a peça de valor maior ou indefesa."""
    if b.is_capture(m) or b.gives_check(m):
        return True
    a = b.copy(stack=False)
    a.push(m)
    alvo = pendurados(a, a.turn)          # peças do adversário (quem joga agora) penduradas
    return alvo >= 2 and any(sq in a.attacks(m.to_square) for sq in
                             (s for s, p in a.piece_map().items() if p.color == a.turn))


# ======================================================== notas estimadas
def estimar_notas(b: chess.Board, m: chess.Move, wdl: Optional[tuple] = None,
                  mate: Optional[int] = None) -> Dict[str, float]:
    """Estima as 10 notas do HED para o lance `m` na posição `b` (ponto de vista de quem joga)."""
    nos = b.turn
    peca = b.piece_at(m.from_square)
    tipo = peca.piece_type if peca else chess.PAWN
    captura, xeque, roque = b.is_capture(m), b.gives_check(m), b.is_castling(m)
    peao = tipo == chess.PAWN

    a = b.copy(stack=False)
    a.push(m)
    respostas = a.legal_moves.count()

    # ameaça nova: peças adversárias penduradas depois do lance, atacadas pela peça que moveu
    pend_adv_antes = pendurados(b, not nos)
    pend_adv_depois = pendurados(a, not nos)
    ataca = a.attacks(m.to_square)
    ameaca = pend_adv_depois > pend_adv_antes and any(
        a.piece_at(s) and a.piece_at(s).color != nos for s in ataca)

    # --- Forçamento: restringe as respostas
    forc = 2 + 4 * xeque + 2 * captura + 2 * ameaca + 2 * max(0.0, 1 - respostas / 30)
    if mate is not None and mate > 0:
        forc = 10

    # --- Urgência: resolve o que estava pendurado / o xeque
    nossas_antes, nossas_depois = pendurados(b, nos), pendurados(a, nos)
    if b.is_check():
        urg = 9
    elif nossas_antes == 0:
        urg = 3
    else:
        urg = 3 + 7 * max(0.0, min(1.0, (nossas_antes - nossas_depois) / nossas_antes))

    # --- Valor de opção: quantos lances úteis continuam disponíveis
    vo = _mobilidade(a, nos) / 4

    # --- Baixo compromisso (nota alta = revela/fixa pouco)
    if peao:
        bc = 3
    elif roque:
        bc = 4
    elif captura:
        bc = 5
    elif xeque:
        bc = 6
    else:
        bc = 8

    # --- Reversibilidade
    if peao or captura:
        rev = 3
    elif roque:
        rev = 2
    else:
        volta = a.copy(stack=False)
        volta.turn = nos
        rev = 8 if chess.Move(m.to_square, m.from_square) in volta.pseudo_legal_moves else 6

    # --- Eficiência: quantas funções o lance cumpre
    ult = 0 if nos == chess.WHITE else 7
    funcoes = 0
    funcoes += tipo in (chess.KNIGHT, chess.BISHOP) and chess.square_rank(m.from_square) == ult
    funcoes += ameaca
    funcoes += nossas_antes > nossas_depois
    funcoes += any(s in ataca for s in CENTRO)
    funcoes += xeque or captura
    funcoes += roque
    efic = 2 + 2 * funcoes

    # --- Atividade: alcance da peça e pressão no campo adversário
    alcance_antes = len(b.attacks(m.from_square))
    alcance_depois = len(ataca)
    metade = [s for s in ataca if (chess.square_rank(s) >= 4) == (nos == chess.WHITE)]
    ativ = 5 + (alcance_depois - alcance_antes) / 2 + len(metade) / 3
    if tipo == chess.KING and not roque and len(b.piece_map()) > 12:
        ativ -= 3

    # --- Estrutura/solidez
    iso_a, dob_a = _estrutura(b, nos)
    iso_d, dob_d = _estrutura(a, nos)
    est = 6 - 1.5 * (iso_d - iso_a) - 1.5 * (dob_d - dob_a)
    kf = _rei_rocado(b, nos)
    if peao and kf is not None and abs(chess.square_file(m.from_square) - kf) <= 1:
        est -= 2                                        # mexe no abrigo do rei
    est -= min(3.0, nossas_depois / 1.5)                # deixa peça pendurada
    est += 2 * roque

    # --- FC (clareza) e Assimetria: pelo WDL quando houver
    if wdl:
        w, d, l = (x / 10 for x in wdl)                 # ‰ -> %
        fc = 3 + 0.06 * d + 0.03 * w - 0.08 * l
        empate = d
    else:
        fc, empate = 6, None
    if forc >= 8:
        fc -= 1                                         # linha forçada exige cálculo
    desequilibrio = 0
    for t in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        desequilibrio += len(a.pieces(t, chess.WHITE)) != len(a.pieces(t, chess.BLACK))
    rb, rp = _rei_rocado(a, chess.WHITE), _rei_rocado(a, chess.BLACK)
    rocados_opostos = rb is not None and rp is not None and (rb >= 4) != (rp >= 4)
    colunas_dif = sum(1 for f in range(8)
                      if bool(a.pieces(chess.PAWN, chess.WHITE) & chess.BB_FILES[f])
                      != bool(a.pieces(chess.PAWN, chess.BLACK) & chess.BB_FILES[f]))
    assim = 2 + desequilibrio + 2 * rocados_opostos + colunas_dif / 2
    if empate is not None:
        assim += (100 - empate) / 20

    return {"forcamento": _lim(forc), "urgencia": _lim(urg), "valor_opcao": _lim(vo),
            "informacao": _lim(bc), "reversibilidade": _lim(rev), "eficiencia": _lim(efic),
            "atividade": _lim(ativ), "estrutura": _lim(est), "fc": _lim(fc), "assimetria": _lim(assim)}


# ======================================================== TF × Conversão automática
def _forcantes_na_pv(b: chess.Board, pv_san: List[str]) -> int:
    """Quantos lances NOSSOS seguidos, desde o início da PV, são forçantes."""
    c = b.copy(stack=False)
    n = 0
    for i, san in enumerate(pv_san):
        try:
            m = c.parse_san(san)
        except ValueError:
            break
        if i % 2 == 0:
            if not eh_forcante(c, m):
                break
            n += 1
        c.push(m)
    return max(n, 1)


def tf_auto(b: chess.Board, opcoes: list, motor=None, tempo: float = 2.0,
            p_registro: Optional[float] = None) -> Optional[Dict]:
    """Compara o melhor lance forçante (TF) com o melhor lance tranquilo, ambos pelo motor.

    - fim: avaliação do motor para a TF (linha verificada até a profundidade da busca);
    - falha: o que sobra se, depois da resposta esperada, você não achar a continuação certa
      (2º melhor lance do motor nessa posição);
    - p: sua chance de achar a linha inteira sem motor = P_POR_LANCE ^ (lances a calcular − 1),
      substituída pela sua taxa real quando o Registro tiver dados.
    """
    com_aval = [o for o in opcoes if o.cp is not None]
    if len(com_aval) < 2:
        return None
    forc = [o for o in com_aval if eh_forcante(b, chess.Move.from_uci(o.uci))]
    tranq = [o for o in com_aval if o not in forc]
    if not forc or not tranq:
        return {"situacao": "sem conflito",
                "texto": "Todos os candidatos são " + ("forçantes" if forc else "tranquilos")
                         + ": não há escolha entre TF e Conversão nesta posição."}
    tf = max(forc, key=lambda o: o.cp)
    tq = max(tranq, key=lambda o: o.cp)
    r = {"situacao": "conflito", "tf": tf.san, "tranquilo": tq.san, "fim_cp": tf.cp, "tranq_cp": tq.cp,
         "pv": tf.pv[:6], "falha_cp": None, "fonte_falha": None}

    # custo de errar: após TF + resposta esperada, o 2º melhor lance nosso
    if motor is not None and len(tf.pv) >= 2:
        c = b.copy(stack=False)
        try:
            c.push_san(tf.pv[0])
            c.push_san(tf.pv[1])
            if not c.is_game_over() and c.legal_moves.count() >= 2:
                ops, _ = motor.buscar(c, 2, tempo)
                aval = [o.cp for o in ops if o.cp is not None]
                if len(aval) >= 2:
                    r["falha_cp"] = sorted(aval)[-2]
                    r["fonte_falha"] = f"2º melhor lance após {tf.pv[0]} {tf.pv[1]}"
        except (ValueError, Exception):
            pass

    n = _forcantes_na_pv(b, tf.pv)
    if p_registro is not None:
        p, fonte_p = p_registro, "sua taxa de acerto no Registro"
    else:
        p, fonte_p = P_POR_LANCE ** (n - 1), f"provisório: {P_POR_LANCE:.0%} por lance, {n} lance(s) a calcular"
    r.update(lances=n, p=p, fonte_p=fonte_p)

    if tf.cp <= tq.cp:
        r["veredito"] = "conversao"
        r["texto"] = (f"O motor já prefere o lance tranquilo {tq.san} ({tq.cp / 100:+.2f}) "
                      f"à TF {tf.san} ({tf.cp / 100:+.2f}): Conversão.")
        return r
    if r["falha_cp"] is None:
        r["veredito"] = "tf_sem_custo"
        r["texto"] = (f"TF {tf.san} ({tf.cp / 100:+.2f}) supera {tq.san} ({tq.cp / 100:+.2f}), "
                      "mas sem o motor local não deu para medir o custo de errar a linha.")
        return r
    t = limiar_tf(tq.cp, tf.cp, r["falha_cp"])
    r.update(t)
    if t["p_estrela"] <= 0:
        r["veredito"] = "tf"
        r["texto"] = (f"TF {tf.san}: mesmo errando a continuação (E {t['e_falha']:.1f}%) você não fica pior "
                      f"que com o lance tranquilo {tq.san} (E {t['e_tranq']:.1f}%) → jogue a TF.")
        return r
    r["veredito"] = "tf" if p > t["p_estrela"] else "conversao"
    r["texto"] = (f"TF {tf.san}: E {t['e_fim']:.1f}% se acertar a linha, {t['e_falha']:.1f}% se errar; "
                  f"tranquilo {tq.san}: E {t['e_tranq']:.1f}%. "
                  f"Precisa de {t['p_estrela']:.0%} de acerto; estimado {p:.0%} → "
                  + ("jogue a TF." if r["veredito"] == "tf" else "fique com a Conversão."))
    return r


def taxa_acerto_tf(registro: List[Dict], minimo: int = 5) -> Optional[float]:
    """Taxa real de acerto em linhas forçadas, quando o Registro tiver ao menos `minimo` casos."""
    casos = [r["tf_acertou"] for r in registro if r.get("tf_acertou") is not None]
    return sum(casos) / len(casos) if len(casos) >= minimo else None


# ======================================================== testes (rodam no build, sem motor)
def _testes():
    from hed_fontes import Opcao
    b = chess.Board("r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3")
    n = estimar_notas(b, b.parse_san("a6"), (8, 903, 89))
    assert set(n) == {"forcamento", "urgencia", "valor_opcao", "informacao", "reversibilidade",
                      "eficiencia", "atividade", "estrutura", "fc", "assimetria"}
    assert all(0 <= v <= 10 for v in n.values())
    assert n["reversibilidade"] == 3 and eh_forcante(b, b.parse_san("a6"))      # ataca o Bb5
    assert not eh_forcante(b, b.parse_san("Nf6"))
    # TF sem motor: mede o conflito, mas não o custo de errar
    b2 = chess.Board("r1bq1rk1/pppn1ppp/4p3/3pP3/1b1P4/2NB1N2/PPP2PPP/R1BQK2R w KQ - 0 8")
    ops = [Opcao("d3h7", "Bxh7+", cp=614, pv=["Bxh7+", "Kxh7", "Ng5+", "Kg8"], multipv=1),
           Opcao("e1g1", "O-O", cp=583, pv=["O-O"], multipv=2)]
    t = tf_auto(b2, ops)
    assert t["situacao"] == "conflito" and t["tf"] == "Bxh7+" and t["veredito"] == "tf_sem_custo"
    assert t["lances"] == 2 and abs(t["p"] - 0.9) < 1e-9
    assert taxa_acerto_tf([{"tf_acertou": True}] * 4) is None
    assert taxa_acerto_tf([{"tf_acertou": True}] * 3 + [{"tf_acertou": False}] * 2) == 0.6
    return True


if __name__ == "__main__":
    assert _testes()
    print("Testes da automação: OK")
