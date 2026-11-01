"""
HED 11.1.2 — livro de aberturas do jogador (EPUB, ex.: FCO — Fundamental Chess Openings).

O app NÃO traz o livro: o jogador carrega o próprio EPUB no celular e este módulo o indexa
ali mesmo. Para cada capítulo, a linha principal (parágrafos de lances como "5 f4 0-0" ou
"6 . . . c5") é reproduzida num tabuleiro; cada posição alcançada fica ligada à seção e aos
parágrafos que o livro escreve logo depois dela.

Na análise, o HED procura a posição de cada candidato (e da continuação do motor) no índice e
traz: capítulo/seção, o tom do livro (quem está melhor), planos citados e os trechos — como
uma fonte a mais, ao lado do motor e das estatísticas do Lichess, nunca como única.
"""
import html
import json
import os
import re
import zipfile
from typing import Dict, List, Optional

import chess

LINHA = re.compile(r"^(\d+)\s+(?:(\.\s*\.\s*\.)|(?!\(D\))(\S+))(?:\s+(?!\(D\))(\S+))?\s*(?:\(D\))?\s*$")
ANOT = re.compile(r"[!?]+$")

# palavras do livro (inglês) -> plano em português
PLANOS = [
    (r"minority attack", "ataque das minorias"),
    (r"pawn[- ]storm", "avanço de peões contra o rei (pawn-storm)"),
    (r"(kingside attack|attack on the kingside|attack against the king)", "ataque na ala do rei"),
    (r"queenside (play|expansion|attack|majority)", "jogo na ala da dama"),
    (r"isolated (queen'?s )?pawn|isolani|IQP", "estrutura de peão isolado"),
    (r"bishop pair|two bishops", "par de bispos"),
    (r"outpost", "posto avançado para uma peça"),
    (r"blockad", "bloqueio de peões"),
    (r"(pressure|play) (on|against) the centre|central (pressure|play)", "pressão no centro"),
    (r"space advantage|more space|gain(s|ing)? space", "ganho de espaço"),
    (r"initiative", "iniciativa"),
    (r"counterplay", "contrajogo"),
    (r"open (c|d|e|f)-file|half-open", "coluna aberta/semiaberta"),
    (r"(favourable|better) endgame", "simplificar para um final favorável"),
    (r"hanging pawns", "peões pendurados"),
    (r"passed pawn", "peão passado"),
]
RUPTURA = re.compile(r"(?:break|lever|thrust|advance|push)[^.]{0,40}?((?:\.\.\.)?[a-h][2-7])|"
                     r"((?:\.\.\.)?[a-h][2-7])[^.]{0,20}?(?:break|lever|thrust)", re.I)

# tom do livro: pistas de quem está melhor
TOM = [
    (r"white (is|stands) (slightly |clearly )?better|advantage for white|white has the (better|upper)", "brancas"),
    (r"black (is|stands) (slightly |clearly )?better|advantage for black|black has the (better|upper)", "pretas"),
    (r"(black|white) (has|is) (fully )?equali[sz]ed|is fine for (black|white)|equal|balanced|level", "igual"),
    (r"unclear|double-edged|complicated|sharp|chaos|complications", "incerto"),
    (r"dubious|risky|questionable|not (very )?good", "duvidoso"),
]


def _chave(b: chess.Board) -> str:
    return " ".join(b.fen().split()[:4])


def _limpa(t: str) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    return re.sub(r"\s+", " ", t.replace("\xa0", " ")).strip()


def _blocos(x: str):
    for m in re.finditer(r"<(h\d|p)\b[^>]*>(.*?)</\1>", x, re.S):
        yield m.group(1), _limpa(m.group(2))


def _lance(b: chess.Board, san: str) -> Optional[chess.Move]:
    san = ANOT.sub("", san.replace("(D)", "").strip())
    if not san:
        return None
    try:
        return b.parse_san(san.replace("0-0-0", "O-O-O").replace("0-0", "O-O"))
    except ValueError:
        return None


def indexar_epub(caminho: str, progresso=lambda s: None) -> Dict:
    """Lê o EPUB e devolve o índice {chave_fen: {capitulo, secao, linha, textos}}."""
    z = zipfile.ZipFile(caminho)
    nomes = z.namelist()
    toc = next((n for n in nomes if n.endswith(".ncx")), None)
    capitulos = []
    if toc:
        x = z.read(toc).decode("utf-8", "ignore")
        for titulo, src in re.findall(r"<text>(.*?)</text>\s*</navLabel>\s*<content src=\"(.*?)\"", x, re.S):
            arq = src.split("#")[0]
            base = os.path.dirname(toc)
            arq = os.path.normpath(os.path.join(base, arq)).replace("\\", "/") if base else arq
            if arq in nomes:
                capitulos.append((_limpa(titulo), arq))
    if not capitulos:
        capitulos = [(n, n) for n in sorted(nomes) if n.endswith((".html", ".xhtml"))]

    indice: Dict[str, Dict] = {}
    lidos, falhas = 0, 0
    for i, (titulo, arq) in enumerate(capitulos):
        progresso(f"Lendo {titulo} ({i + 1}/{len(capitulos)})…")
        x = z.read(arq).decode("utf-8", "ignore")
        linha: List[str] = []
        secao = titulo
        atual: Optional[Dict] = None
        for tag, t in _blocos(x):
            if not t:
                continue
            if tag != "p":
                secao = t if tag != "h1" else titulo
                continue
            m = LINHA.match(t)
            if m and len(t) < 40:
                n = int(m.group(1))
                branco, preto = m.group(3), m.group(4)
                ply = 2 * (n - 1) + (1 if m.group(2) else 0)
                nova = linha[:ply]
                b = chess.Board()
                ok = True
                for s in nova:
                    b.push_san(s)
                for san in ([branco] if branco else []) + ([preto] if preto else []):
                    mv = _lance(b, san)
                    if mv is None:
                        ok = False
                        break
                    nova.append(b.san(mv))
                    b.push(mv)
                if not ok or len(nova) <= ply:
                    falhas += 1
                    continue
                linha = nova
                lidos += 1
                k = _chave(b)
                atual = indice.setdefault(k, {"capitulo": titulo, "secao": secao, "linha": _num(linha),
                                              "textos": []})
                continue
            if atual is not None and len(t) > 60 and len(atual["textos"]) < 6:
                atual["textos"].append(t)
    return {"posicoes": indice, "lances_lidos": lidos, "falhas": falhas, "capitulos": len(capitulos)}


def _num(sans: List[str]) -> str:
    out = []
    for i, s in enumerate(sans):
        out.append(f"{i // 2 + 1}.{s}" if i % 2 == 0 else s)
    return " ".join(out)


# ======================================================== uso na análise
_CACHE: Dict[str, Dict] = {}


def carregar_indice(caminho_json: str) -> Optional[Dict]:
    if caminho_json in _CACHE:
        return _CACHE[caminho_json]
    try:
        with open(caminho_json, encoding="utf-8") as f:
            _CACHE[caminho_json] = json.load(f)
        return _CACHE[caminho_json]
    except (OSError, ValueError):
        return None


def salvar_indice(indice: Dict, caminho_json: str) -> None:
    with open(caminho_json, "w", encoding="utf-8") as f:
        json.dump(indice, f, ensure_ascii=False)
    _CACHE[caminho_json] = indice


def ler_trecho(textos: List[str]) -> Dict:
    """Planos, rupturas e tom extraídos dos parágrafos do livro sobre a posição."""
    junto = " ".join(textos)
    planos = [pt for padrao, pt in PLANOS if re.search(padrao, junto, re.I)]
    rups = []
    for m in RUPTURA.finditer(junto):
        r = m.group(1) or m.group(2)
        if r and r not in rups:
            rups.append(r)
    tom: Dict[str, int] = {}
    for padrao, rot in TOM:
        tom[rot] = len(re.findall(padrao, junto, re.I))
    principal = max(tom, key=tom.get) if any(tom.values()) else None
    return {"planos": planos, "rupturas": rups[:4], "tom": principal}


def consultar(indice: Optional[Dict], b: chess.Board, linha_san: List[str], max_plies: int = 6) -> Optional[Dict]:
    """Procura no livro a linha (posição atual, candidato e continuação do motor).

    Seção = a posição mais adiantada encontrada; planos, rupturas e tom = tudo o que o livro
    comenta ao longo da linha encontrada (o comentário costuma vir um lance antes ou depois).
    """
    if not indice:
        return None
    pos = indice.get("posicoes", {})
    c = b.copy(stack=False)
    achados = []
    e = pos.get(_chave(c))
    if e:
        achados.append((0, e))
    for i, san in enumerate(linha_san[:max_plies]):
        try:
            c.push_san(san)
        except ValueError:
            break
        e = pos.get(_chave(c))
        if e:
            achados.append((i + 1, e))
    if not achados:
        return None
    prof, fundo = achados[-1]
    textos = []
    for _, e in reversed(achados):                      # mais específico primeiro
        for t in e["textos"]:
            if t not in textos:
                textos.append(t)
    lido = ler_trecho(textos)
    return {"capitulo": fundo["capitulo"], "secao": fundo["secao"], "linha": fundo["linha"],
            "depois_de": prof, "planos": lido["planos"], "rupturas": lido["rupturas"],
            "tom": lido["tom"], "trechos": textos[:3]}


def texto_tom(tom: Optional[str]) -> str:
    return {"brancas": "brancas melhor", "pretas": "pretas melhor", "igual": "equilibrado",
            "incerto": "incerto/afiado", "duvidoso": "linha duvidosa"}.get(tom or "", "sem veredito")


# ======================================================== testes (EPUB sintético, sem texto de livro)
def _testes():
    import tempfile
    capitulo = """<html><body><h1>Teste</h1>
    <p>1 d4 Nf6</p><p>2 c4 g6</p>
    <h3>3 Nc3</h3><p>3 Nc3 Bg7</p><p>4 e4 (D)</p><p>4 . . . d6 (D)</p>
    <p>Black prepares the ...e5 break while White gains space; a pawn-storm on the kingside follows.
    White is slightly better in most lines.</p>
    <h3>Outra</h3><p>4 . . . d5</p>
    <p>This position is unclear and double-edged, with pressure on the centre for Black.</p>
    </body></html>"""
    ncx = """<ncx><navMap><navPoint><navLabel><text>Teste</text></navLabel>
    <content src="c1.html"/></navPoint></navMap></ncx>"""
    with tempfile.TemporaryDirectory() as d:
        ep = os.path.join(d, "t.epub")
        with zipfile.ZipFile(ep, "w") as z:
            z.writestr("toc.ncx", ncx)
            z.writestr("c1.html", capitulo)
        ind = indexar_epub(ep)
        assert ind["lances_lidos"] == 6 and ind["falhas"] == 0, ind
        js = os.path.join(d, "i.json")
        salvar_indice(ind, js)
        _CACHE.clear()
        ind = carregar_indice(js)
    b = chess.Board()
    for s in ("d4", "Nf6", "c4", "g6", "Nc3", "Bg7"):
        b.push_san(s)
    r = consultar(ind, b, ["e4", "d6"])
    assert r and r["secao"] == "3 Nc3" and r["depois_de"] == 2, r
    assert "avanço de peões contra o rei (pawn-storm)" in r["planos"] and "...e5" in r["rupturas"], r
    assert r["tom"] == "brancas", r
    r2 = consultar(ind, b, ["e4", "d5"])
    assert r2["secao"] == "Outra" and r2["tom"] == "incerto" and "pressão no centro" in r2["planos"], r2
    assert consultar(ind, chess.Board(), ["a4"]) is None
    assert consultar(None, b, ["e4"]) is None
    return True


if __name__ == "__main__":
    assert _testes()
    print("Testes do livro: OK")
