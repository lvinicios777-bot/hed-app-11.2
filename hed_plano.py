"""
HED 11.1.2 — análise da continuação de cada lance (antes da nota final).

Para cada candidato, o HED joga a linha principal do motor até o fim e compara a posição
resultante com a atual, dos dois lados:

- estrutura de peões que fica (isolados, dobrados, passados, ilhas, maiorias, colunas abertas);
- qualidade de cada peça (mobilidade segura, centralização, posto avançado, torre em coluna
  aberta/7ª, bispo ruim) e a pior peça de cada lado;
- espaço (casas centrais seguras no próprio campo, como no Stockfish clássico);
- planos que a estrutura oferece (regras de estruturas típicas).

O resultado ajusta Estrutura, Atividade, Valor de opção, Eficiência e Assimetria.
São regras explícitas, não compreensão de mestre: servem para orientar e para o Registro
mostrar onde erram.
"""
from typing import Dict, List, Optional

import chess

NOMES = {chess.KNIGHT: "C", chess.BISHOP: "B", chess.ROOK: "T", chess.QUEEN: "D"}
MOB_MAX = {chess.KNIGHT: 8, chess.BISHOP: 13, chess.ROOK: 14, chess.QUEEN: 27}
COLUNAS = "abcdefgh"


def _lim(x: float) -> float:
    return round(max(0.0, min(10.0, x)) * 2) / 2


def _rel(rank: int, cor: bool) -> int:
    """Fileira relativa (0 = primeira fileira de quem tem a cor)."""
    return rank if cor == chess.WHITE else 7 - rank


# ======================================================== posição no fim da linha
def fim_da_linha(b: chess.Board, pv_san: List[str], max_lances: int = 8,
                 ucis: Optional[List[str]] = None) -> (chess.Board, List[str]):
    c = b.copy()
    jogados, capturas = [], []
    for san in pv_san[:max_lances]:
        try:
            m = c.parse_san(san)
        except ValueError:
            break
        capturas.append(c.is_capture(m))
        if ucis is not None:
            ucis.append(m.uci())
        c.push(m)
        jogados.append(san)
        if c.is_game_over():
            break
    # não parar no meio de uma troca: volta até a última posição tranquila
    while len(jogados) > 1 and capturas[-1] and not c.is_game_over():
        c.pop()
        jogados.pop()
        capturas.pop()
        if ucis is not None:
            ucis.pop()
    return c, jogados


# ======================================================== estrutura de peões
def estrutura(b: chess.Board, cor: bool) -> Dict:
    nossos = b.pieces(chess.PAWN, cor)
    deles = b.pieces(chess.PAWN, not cor)
    col = sorted(chess.square_file(s) for s in nossos)
    colset = set(col)
    isolados = [s for s in nossos if (chess.square_file(s) - 1) not in colset
                and (chess.square_file(s) + 1) not in colset]
    dobrados = sum(col.count(f) - 1 for f in colset)
    passados = []
    for s in nossos:
        f, r = chess.square_file(s), chess.square_rank(s)
        frente = [x for x in deles if abs(chess.square_file(x) - f) <= 1 and
                  ((chess.square_rank(x) > r) if cor == chess.WHITE else (chess.square_rank(x) < r))]
        if not frente:
            passados.append(s)
    ilhas = 0
    anterior = None
    for f in sorted(colset):
        if anterior is None or f != anterior + 1:
            ilhas += 1
        anterior = f
    dama = sum(1 for s in nossos if chess.square_file(s) <= 3)
    rei = len(nossos) - dama
    dama_d = sum(1 for s in deles if chess.square_file(s) <= 3)
    rei_d = len(deles) - dama_d
    abertas = [COLUNAS[f] for f in range(8) if not (b.pieces(chess.PAWN, chess.WHITE) |
                                                     b.pieces(chess.PAWN, chess.BLACK)) & chess.BB_FILES[f]]
    semi = [COLUNAS[f] for f in range(8) if not nossos & chess.BB_FILES[f] and deles & chess.BB_FILES[f]]
    iqp = (len(isolados) >= 1 and any(chess.square_file(s) == 3 for s in isolados))
    dob_info = []
    for f in sorted(colset):
        if col.count(f) > 1:
            dob_info.append({"coluna": COLUNAS[f],
                             "isolado": (f - 1) not in colset and (f + 1) not in colset})
    return {"isolados": [chess.square_name(s) for s in isolados], "dobrados": dobrados,
            "passados": [chess.square_name(s) for s in passados], "ilhas": ilhas,
            "maioria_dama": dama - dama_d, "maioria_rei": rei - rei_d,
            "abertas": abertas, "semiabertas": semi, "iqp": iqp, "n": len(nossos),
            "dobrados_info": dob_info}


def compensacoes(b: chess.Board, cor: bool, e: Dict) -> List[str]:
    """O que compensa peões dobrados ou isolados nesta posição."""
    comp = []
    if e["dobrados_info"]:
        if len(b.pieces(chess.BISHOP, cor)) == 2 and len(b.pieces(chess.BISHOP, not cor)) < 2:
            comp.append("par de bispos")
        semi = set(e["semiabertas"]) | set(e["abertas"])
        for d in e["dobrados_info"]:
            f = COLUNAS.index(d["coluna"])
            viz = [COLUNAS[x] for x in (f - 1, f + 1) if 0 <= x < 8 and COLUNAS[x] in semi]
            if viz:
                comp.append(f"coluna {viz[0]} semiaberta")
                break
        centro = (chess.D4, chess.E4, chess.D5, chess.E5)
        if any(any(c in b.attacks(p) for c in centro) for p in b.pieces(chess.PAWN, cor)
               if COLUNAS[chess.square_file(p)] in [d["coluna"] for d in e["dobrados_info"]]):
            comp.append("controle do centro")
    if e["iqp"] and b.pieces(chess.QUEEN, chess.WHITE) and b.pieces(chess.QUEEN, chess.BLACK):
        comp.append("IQP dinâmico (damas no tabuleiro)")
    return list(dict.fromkeys(comp))


def nota_estrutura(e: Dict, comp: Optional[List[str]] = None) -> float:
    """Saúde da estrutura de um lado (maior = melhor), em contexto.

    Dobrado e isolado é fraqueza real (−0,8); dobrado com vizinhos pesa menos (−0,4), e cada
    compensação (par de bispos, coluna semiaberta, centro) desconta 0,3 dessa penalidade.
    O IQP com damas no tabuleiro pesa metade (é dinâmico).
    """
    comp = comp or []
    pen_dob = sum(0.8 if d["isolado"] else 0.4 for d in e["dobrados_info"])
    alivio = 0.3 * len([c for c in comp if not c.startswith("IQP")])
    pen_dob = max(0.0, pen_dob - alivio) if e["dobrados_info"] else 0.0
    pen_iso = 0.0
    for s in e["isolados"]:
        pen_iso += 0.5 if (e["iqp"] and s[0] == "d" and any(c.startswith("IQP") for c in comp)) else 1.0
    return 6 - pen_iso - pen_dob - 0.5 * max(0, e["ilhas"] - 2) + 1.0 * len(e["passados"])


# ======================================================== peças
def _posto_avancado(b: chess.Board, sq: int, cor: bool) -> bool:
    """Casa no campo adversário, defendida por peão nosso e que nenhum peão inimigo pode atacar."""
    r = _rel(chess.square_rank(sq), cor)
    if r < 3 or r > 5:
        return False
    if not any(b.piece_at(a) and b.piece_at(a).piece_type == chess.PAWN
               for a in b.attackers(cor, sq)):
        return False
    f = chess.square_file(sq)
    for x in b.pieces(chess.PAWN, not cor):
        if abs(chess.square_file(x) - f) == 1:
            rx = _rel(chess.square_rank(x), cor)
            if rx > r:                     # peão inimigo ainda à frente pode descer e atacar
                return False
    return True


def qualidade_peca(b: chess.Board, sq: int) -> float:
    p = b.piece_at(sq)
    cor, t = p.color, p.piece_type
    ataques_peao = chess.SquareSet()
    for x in b.pieces(chess.PAWN, not cor):
        ataques_peao |= b.attacks(x)
    seguras = [s for s in b.attacks(sq)
               if s not in ataques_peao and not (b.piece_at(s) and b.piece_at(s).color == cor)]
    q = 3 + 5 * min(1.0, len(seguras) / MOB_MAX[t])
    f, r = chess.square_file(sq), chess.square_rank(sq)
    if t in (chess.KNIGHT, chess.BISHOP):
        dist = max(abs(f - 3.5), abs(r - 3.5))
        q += 1.0 - 0.4 * dist                      # centralização
        if _posto_avancado(b, sq, cor):
            q += 2.0
        if _rel(r, cor) == 0:
            q -= 1.0                               # ainda na primeira fileira
    if t == chess.BISHOP:
        cor_casa = (f + r) % 2
        mesmos = sum(1 for x in b.pieces(chess.PAWN, cor)
                     if (chess.square_file(x) + chess.square_rank(x)) % 2 == cor_casa)
        if mesmos >= 5:
            q -= 1.5                               # bispo ruim
    if t == chess.ROOK:
        arq = chess.BB_FILES[f]
        if not (b.pieces(chess.PAWN, cor) & arq):
            q += 1.5 if not (b.pieces(chess.PAWN, not cor) & arq) else 0.75
        if _rel(r, cor) == 6:
            q += 1.0
    return max(0.0, min(10.0, q))


def pecas(b: chess.Board, cor: bool) -> Dict:
    lista = []
    for t in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        for sq in b.pieces(t, cor):
            lista.append((qualidade_peca(b, sq), f"{NOMES[t]}{chess.square_name(sq)}"))
    if not lista:
        return {"media": 5.0, "pior": None, "pior_q": None, "melhor": None}
    lista.sort()
    return {"media": sum(q for q, _ in lista) / len(lista), "pior": lista[0][1], "pior_q": lista[0][0],
            "melhor": lista[-1][1]}


def rota_ideal(b: chess.Board, sq: int) -> Optional[Dict]:
    """Melhor casa alcançável pela peça em até 2 lances (sem considerar respostas): a 'posição ideal'."""
    p = b.piece_at(sq)
    if not p:
        return None
    cor = p.color
    base = b.copy(stack=False)
    base.turn = cor
    base.ep_square = None
    atual = qualidade_peca(base, sq)
    um, dois = (atual, []), (atual, [])
    for m1 in [m for m in base.legal_moves if m.from_square == sq and not base.is_capture(m)]:
        b1 = base.copy(stack=False)
        b1.push(m1)
        b1.turn = cor
        if b1.is_attacked_by(not cor, m1.to_square):
            continue                                     # não dá para parar (nem passar) numa casa atacada
        q1 = qualidade_peca(b1, m1.to_square)
        if q1 > um[0]:
            um = (q1, [m1.to_square])
        for m2 in [m for m in b1.legal_moves if m.from_square == m1.to_square and not b1.is_capture(m)]:
            if m2.to_square == sq:
                continue
            b2 = b1.copy(stack=False)
            b2.push(m2)
            b2.turn = cor
            if b2.is_attacked_by(not cor, m2.to_square):
                continue
            q2 = qualidade_peca(b2, m2.to_square)
            if q2 > dois[0]:
                dois = (q2, [m1.to_square, m2.to_square])
    # caminho mais curto, salvo se o de 2 lances for claramente melhor
    if dois[1] and dois[0] > um[0] + 0.6:
        melhor = dois
    elif um[1] and um[0] > atual + 0.3:
        melhor = um
    else:
        return None
    melhor = (melhor[0], None, melhor[1])
    nome = f"{NOMES[p.piece_type]}{chess.square_name(sq)}"
    caminho = "–".join(chess.square_name(x) for x in [sq] + melhor[2])
    return {"peca": nome, "caminho": caminho, "de": round(atual, 1), "para": round(melhor[0], 1)}


def rupturas(b: chess.Board, cor: bool) -> List[str]:
    """Avanços de peão que entram em contato com peões adversários (abrem o jogo)."""
    c = b.copy(stack=False)
    c.turn = cor
    c.ep_square = None
    out = []
    for m in c.legal_moves:
        p = c.piece_at(m.from_square)
        if not p or p.piece_type != chess.PAWN or c.is_capture(m):
            continue
        d = c.copy(stack=False)
        d.push(m)
        alvo = [x for x in d.attacks(m.to_square)
                if d.piece_at(x) == chess.Piece(chess.PAWN, not cor)]
        if alvo and not d.is_attacked_by(not cor, m.to_square) or (alvo and d.attackers(cor, m.to_square)):
            out.append(("" if cor == chess.WHITE else "...") + chess.square_name(m.to_square))
    return out[:3]


# ======================================================== espaço
def espaco(b: chess.Board, cor: bool) -> int:
    """Casas seguras nas colunas c–f, fileiras 2–4 do próprio campo; atrás dos próprios peões contam 2."""
    ataques_peao = chess.SquareSet()
    for x in b.pieces(chess.PAWN, not cor):
        ataques_peao |= b.attacks(x)
    total = 0
    for f in range(2, 6):
        for rr in (1, 2, 3):
            r = rr if cor == chess.WHITE else 7 - rr
            s = chess.square(f, r)
            if s in ataques_peao:
                continue
            p = b.piece_at(s)
            if p and p.piece_type == chess.PAWN:
                continue
            total += 1
            frente = range(r + 1, 8) if cor == chess.WHITE else range(r - 1, -1, -1)
            if any(b.piece_at(chess.square(f, k)) == chess.Piece(chess.PAWN, cor) for k in list(frente)[:3]):
                total += 1
    return total


# ======================================================== planos
def _rei_lado(b: chess.Board, cor: bool) -> Optional[str]:
    k = b.king(cor)
    if k is None:
        return None
    f = chess.square_file(k)
    return "rei" if f >= 5 else ("dama" if f <= 2 else None)


def planos(b: chess.Board, cor: bool) -> List[str]:
    e, d = estrutura(b, cor), estrutura(b, not cor)
    nos, eles = pecas(b, cor), pecas(b, not cor)
    out = []
    if e["passados"]:
        out.append(f"empurrar o peão passado de {e['passados'][-1]}")
    if e["iqp"]:
        out.append("jogo ativo de peças e ruptura com o peão isolado (d4–d5 / d5–d4)")
    elif d["iqp"]:
        out.append("bloquear e pressionar o peão isolado adversário")
    if e["maioria_dama"] > 0 and not e["iqp"]:
        out.append("criar peão passado com a maioria na ala da dama")
    elif e["maioria_dama"] < 0 and "c" in e["semiabertas"]:
        # assinatura da Carlsbad: minoria na ala da dama com a coluna c semiaberta
        out.append("ataque das minorias na ala da dama (b4–b5)")
    elif e["maioria_rei"] > 0 and not e["iqp"]:
        out.append("avançar a maioria da ala do rei")
    lados = (_rei_lado(b, cor), _rei_lado(b, not cor))
    if None not in lados and lados[0] != lados[1]:
        out.append("avanço de peões contra o rei adversário (roques opostos)")
    abertas = [c for c in e["semiabertas"] + e["abertas"]]
    torres = [chess.square_file(s) for s in b.pieces(chess.ROOK, cor)]
    livres = [c for c in abertas if COLUNAS.index(c) not in torres]
    if livres:
        out.append(f"ocupar a coluna {livres[0]} com as torres")
    fracos = [s for s in d["isolados"]]
    if fracos and not d["iqp"]:
        out.append(f"atacar o peão fraco de {fracos[0]}")
    if espaco(b, cor) >= espaco(b, not cor) + 4:
        out.append("usar a vantagem de espaço: restringir e preparar ruptura")
    if nos["pior"] and (nos["pior_q"] or 10) < 4.5:
        out.append(f"melhorar a pior peça ({nos['pior']})")
    vistos, unicos = set(), []
    for p in out:
        if p not in vistos:
            unicos.append(p)
            vistos.add(p)
    return unicos[:4]


# ======================================================== análise completa de um candidato
def analise_continuacao(b: chess.Board, pv_san: List[str]) -> Dict:
    nos = b.turn
    ucis: List[str] = []
    fim, linha = fim_da_linha(b, pv_san, ucis=ucis)
    e0, e1 = estrutura(b, nos), estrutura(fim, nos)
    d1 = estrutura(fim, not nos)
    p0, p1, q1 = pecas(b, nos), pecas(fim, nos), pecas(fim, not nos)
    s1, s1d = espaco(fim, nos), espaco(fim, not nos)
    pl = planos(fim, nos)
    VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}

    def material(x):
        return sum(VAL[t] * (len(x.pieces(t, nos)) - len(x.pieces(t, not nos))) for t in VAL)
    dif_material = material(fim) - material(b)

    comp1, comp_d = compensacoes(fim, nos, e1), compensacoes(fim, not nos, d1)
    comp0 = compensacoes(b, nos, e0)
    saldo_estrutura = nota_estrutura(e1, comp1) - nota_estrutura(d1, comp_d)
    mudou_estrutura = nota_estrutura(e1, comp1) - nota_estrutura(e0, comp0)
    melhorou_pior = (p0["pior_q"] is not None and p1["pior_q"] is not None
                     and p1["pior_q"] > p0["pior_q"] + 0.5)

    txt_est = []
    if e1["isolados"]:
        txt_est.append("isolado " + ",".join(e1["isolados"]))
    if e1["dobrados"]:
        cols = ",".join(d["coluna"] for d in e1["dobrados_info"])
        if comp1 and not any(d["isolado"] for d in e1["dobrados_info"]):
            txt_est.append(f"dobrados na coluna {cols} — aceitável: {', '.join(comp1)}")
        elif comp1:
            txt_est.append(f"dobrados e isolados na coluna {cols} — fraqueza, em parte compensada: {', '.join(comp1)}")
        else:
            txt_est.append(f"dobrados na coluna {cols} — fraqueza sem compensação")
    elif comp1:
        txt_est.append("compensação: " + ", ".join(comp1))
    if e1["passados"]:
        txt_est.append("passado " + ",".join(e1["passados"]))
    if d1["isolados"] or d1["dobrados"]:
        txt_est.append("adversário com " + ", ".join(
            (["isolado " + ",".join(d1["isolados"])] if d1["isolados"] else [])
            + ([f"{d1['dobrados']} dobrado(s)"] if d1["dobrados"] else [])))
    veredito = ("melhora" if mudou_estrutura > 0.4 else "piora" if mudou_estrutura < -0.4 else "mantém")

    # posição ideal das duas piores peças e rupturas de peão
    lista = sorted(((qualidade_peca(fim, s), s) for t in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
                    for s in fim.pieces(t, nos)))
    rotas = [r for r in (rota_ideal(fim, s) for _, s in lista[:2]) if r]
    rup = rupturas(fim, nos)

    # balanço: o que se ganha e o que se cede com este lance
    pro, contra = [], []
    if dif_material >= 1:
        pro.append(f"ganha material (+{dif_material})")
    elif dif_material <= -1:
        contra.append(f"cede material ({dif_material}) — verificar a compensação")
    if saldo_estrutura > 0.4:
        pro.append("estrutura melhor que a do adversário")
    elif saldo_estrutura < -0.4:
        contra.append("estrutura pior que a do adversário")
    abertura = b.fullmove_number <= 12
    if abertura and abs(s1 - s1d) >= 3:
        pass        # na abertura, ceder espaço pode ser o plano (aberturas hipermodernas): só informativo
    elif s1 - s1d >= 3:
        pro.append(f"mais espaço ({s1} × {s1d})")
    elif s1d - s1 >= 3:
        contra.append(f"menos espaço ({s1} × {s1d})")
    if p1["media"] - q1["media"] >= 0.4:
        pro.append("peças mais ativas")
    elif q1["media"] - p1["media"] >= 0.4:
        contra.append("peças menos ativas")
    if e1["passados"]:
        pro.append("peão passado " + ",".join(e1["passados"]))
    if d1["passados"]:
        contra.append("passado adversário " + ",".join(d1["passados"]))
    for d in e1["dobrados_info"]:
        if not (comp1 and not d["isolado"]):            # dobrado aceitável é neutro
            contra.append(f"dobrados na coluna {d['coluna']}" + (" e isolados" if d["isolado"] else ""))
    if comp1:
        pro += [c for c in comp1 if c not in pro]
    if pl:
        pro.append(f"{len(pl)} plano(s) claro(s)")
    else:
        contra.append("sem plano estrutural claro")
    compensa = len(pro) - len(contra)
    resumo = ("compensa" if compensa >= 2 else "equilibrado" if compensa >= 0 else "não compensa")
    return {
        "linha": " ".join(linha),
        "estrutura": (", ".join(txt_est) or "sem fraquezas de peões") + f" (estrutura {veredito})",
        "saldo_estrutura": round(saldo_estrutura, 2),
        "pecas": f"média {p1['media']:.1f} × {q1['media']:.1f} do adversário; melhor {p1['melhor']}, "
                 f"pior {p1['pior']}" + (" (pior peça melhorou)" if melhorou_pior else ""),
        "saldo_pecas": round(p1["media"] - q1["media"], 2),
        "melhorou_pior": melhorou_pior,
        "espaco": f"{s1} × {s1d}" + (" (na abertura: informativo)" if b.fullmove_number <= 12 else ""),
        "saldo_espaco": s1 - s1d,
        "planos": pl,
        "material": dif_material,
        "rotas": [f"{r['peca']}: {r['caminho']} (qualidade {r['de']} → {r['para']})" for r in rotas],
        "rupturas": rup,
        "pro": pro, "contra": contra, "balanco": resumo,
        "linha_uci": ucis,
        "desequilibrio": int(bool(e1["passados"]) or bool(d1["passados"]) or e1["iqp"] or d1["iqp"]
                             or e1["maioria_dama"] != 0),
    }


def ajustar_notas(notas: Dict[str, float], a: Dict) -> Dict[str, float]:
    """Mistura (50/50) as notas do lance imediato com o que a continuação mostra."""
    alvo = {
        "estrutura": 6 + 0.8 * a["saldo_estrutura"],
        "atividade": 5 + 1.5 * a["saldo_pecas"] + a["saldo_espaco"] / 4,
        "valor_opcao": 3 + 1.5 * len(a["planos"]),
        "eficiencia": notas["eficiencia"] + (2 if a["melhorou_pior"] else 0),
        "assimetria": notas["assimetria"] + 1.5 * a["desequilibrio"],
    }
    out = dict(notas)
    for k, v in alvo.items():
        out[k] = _lim((notas[k] + v) / 2)
    return out


def texto(a: Dict) -> str:
    L = [f"Linha: {a['linha']}", f"Estrutura: {a['estrutura']}", f"Peças: {a['pecas']}",
         f"Espaço: {a['espaco']}"]
    L.append("Planos: " + ("; ".join(a["planos"]) if a["planos"] else "sem plano estrutural claro"))
    return "\n".join(L)


def texto_planos(lance: str, a: Dict) -> str:
    """Ficha completa para a tela Planos."""
    L = [f"{lance} — {a.get('balanco', '').upper()}", f"Linha: {a['linha']}", ""]
    L.append("A FAVOR")
    L += [f"  + {x}" for x in a.get("pro", [])] or ["  —"]
    L.append("CONTRA")
    L += [f"  - {x}" for x in a.get("contra", [])] or ["  —"]
    L.append("")
    L.append(f"Estrutura: {a['estrutura']}")
    L.append(f"Espaço (casas seguras): {a['espaco']}")
    L.append(f"Peças: {a['pecas']}")
    L.append("")
    L.append("PLANOS")
    L += [f"  {i}. {p}" for i, p in enumerate(a["planos"], 1)] or ["  sem plano estrutural claro"]
    if a.get("rotas"):
        L.append("CASA IDEAL DAS PIORES PEÇAS")
        L += [f"  {r}" for r in a["rotas"]]
    if a.get("rupturas"):
        L.append("RUPTURAS DE PEÃO: " + ", ".join(a["rupturas"]))
    f = a.get("fco")
    if f:
        L.append("")
        L.append(f"LIVRO (FCO): {f['capitulo']} — {f['secao']}")
        L.append(f"  Linha do livro: {f['linha']}")
        L.append(f"  Tom do livro: {a.get('fco_tom', '—')}")
        if f.get("trechos"):
            L.append("  O que o livro diz:")
            for t in f["trechos"][:2]:
                L.append("  « " + (t if len(t) <= 600 else t[:600] + "…") + " »")
    elif "fco" in a:
        L.append("")
        L.append("LIVRO (FCO): linha não encontrada no livro.")
    return "\n".join(L)


# ======================================================== testes
def _testes():
    # IQP branco (estrutura típica): plano de ruptura e peão isolado detectados
    b = chess.Board("r1bq1rk1/pp2bppp/2n1pn2/8/3P4/2NB1N2/PP3PPP/R1BQ1RK1 w - - 0 10")
    e = estrutura(b, chess.WHITE)
    assert e["iqp"] and "d4" in e["isolados"], e
    assert any("isolado" in p for p in planos(b, chess.WHITE))
    assert any("isolado" in p for p in planos(b, chess.BLACK))
    # Carlsbad (brancas com minoria na ala da dama)
    c = chess.Board("r1bq1rk1/pp2bppp/2p1pn2/3p4/2PP4/2N1PN2/PP3PPP/R2QKB1R w KQ - 0 9")
    assert estrutura(c, chess.WHITE)["maioria_dama"] == 0
    carl = chess.Board("r1bq1rk1/pp2bppp/2p2n2/3p4/3P4/2NBPN2/PP3PPP/R2QK2R w KQ - 0 10")   # após cxd5 exd5
    assert any("minorias" in p for p in planos(carl, chess.WHITE)), planos(carl, chess.WHITE)
    assert not any("maioria na ala da dama" in p for p in planos(b, chess.WHITE))         # IQP não é maioria
    # posto avançado: cavalo branco em e5 apoiado por d4, sem peões pretos em d/f que o ataquem
    p = chess.Board("6k1/pp4pp/8/4N3/3P4/8/PP3PPP/6K1 w - - 0 1")
    assert not _posto_avancado(chess.Board("6k1/pp3ppp/8/4N3/3P4/8/PP3PPP/6K1 w - - 0 1"), chess.E5, chess.WHITE)
    assert _posto_avancado(p, chess.E5, chess.WHITE)
    # torre em coluna aberta vale mais que fechada
    t = chess.Board("6k1/pp3ppp/8/8/8/8/PP3PPP/2R2RK1 w - - 0 1")
    assert qualidade_peca(t, chess.C1) > qualidade_peca(t, chess.F1)
    # peão dobrado em contexto: Espanhola das Trocas (…dxc6) tem par de bispos e coluna d → aceitável
    trocas = chess.Board("r1bqk1nr/1pp1bppp/p1p5/4p3/4P3/5N2/PPPP1PPP/RNBQ1RK1 w kq - 0 6")
    e = estrutura(trocas, chess.BLACK)
    comp = compensacoes(trocas, chess.BLACK, e)
    assert "par de bispos" in comp and any("semiaberta" in c for c in comp), comp
    sem = {**e, "dobrados_info": [{"coluna": "c", "isolado": False}]}
    assert nota_estrutura(e, comp) > nota_estrutura(sem, [])
    # dobrado e isolado pesa mais que dobrado com vizinhos
    iso = {**e, "dobrados_info": [{"coluna": "c", "isolado": True}]}
    assert nota_estrutura(iso, []) < nota_estrutura(sem, [])
    # rota ideal: cavalo mal colocado encontra casa melhor
    r = rota_ideal(chess.Board("6k1/pp3ppp/8/8/3P4/8/PP3PPP/N5K1 w - - 0 1"), chess.A1)
    assert r and r["para"] > r["de"], r
    iqp_fim = chess.Board("2rq1rk1/pb2bp1p/1pn1pnp1/8/3P4/P1NQ1N2/1PB2PPP/R1B1R1K1 w - - 0 14")
    assert rota_ideal(iqp_fim, chess.C1)["caminho"] == "c1–f4"           # direto, sem desvio por h6
    # análise da continuação na Espanhola
    esp = chess.Board("r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3")
    a = analise_continuacao(esp, ["a6", "Ba4", "Nf6", "O-O", "Be7", "Re1"])
    assert a["linha"].startswith("a6 Ba4") and isinstance(a["planos"], list)
    # linha que termina numa captura sem recaptura: a análise volta à posição tranquila
    _, jog = fim_da_linha(esp, ["Nf6", "O-O", "Nxe4", "Re1", "Nd6", "Nxe5", "Be7", "Bf1", "Nxe5"])
    assert jog[-1] == "Bf1", jog
    assert a["linha_uci"][:2] == ["a7a6", "b5a4"] and a["balanco"] in ("compensa", "equilibrado", "não compensa")
    assert "A FAVOR" in texto_planos("a6", a)
    n = ajustar_notas({"estrutura": 6, "atividade": 5, "valor_opcao": 7, "eficiencia": 4,
                       "assimetria": 3}, a)
    assert all(0 <= v <= 10 for v in n.values())
    return True


if __name__ == "__main__":
    assert _testes()
    print("Testes da análise da continuação: OK")
