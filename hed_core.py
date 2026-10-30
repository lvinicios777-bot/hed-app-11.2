"""
HED 11.2 — núcleo de decisão enxadrística (Python puro, sem dependências).

Mesma filosofia e pipeline do 11.1.1:
Filtros -> faixa objetiva -> MI -> Estratégia -> Pareto -> TOP -> MA -> FO/FC -> ATP -> decisão -> IFE
                                                                            -> registro -> PR/CC/AC/RP

Mudanças do 11.2 (só na camada de medição):
- MIS: margem de incerteza subjetiva (ΔATP < 0,5 = empate prático).
- FO e Robustez são derivados do núcleo estratégico (sem dupla contagem).
- MI em pontuação esperada E = W + D/2 quando todos os candidatos têm WDL;
  centipawns como reserva.
- IFE só em letras (sem % até haver calibração).
- "Informação/compromisso" -> "Baixo compromisso" (10 = revela pouco, flexível).
- Registro de posições alimenta PR, CC, AC e RP.

O motor não roda aqui: você informa a perda (peões) e, se tiver, o WDL de cada lance.
TF, transposições e evidência externa são checados antes de pontuar.
"""
from dataclasses import dataclass, asdict, fields
from datetime import date
from typing import List, Dict, Optional

VERSAO = "11.2"

ESTRATEGICOS = [
    "forcamento", "urgencia", "valor_opcao", "informacao",
    "reversibilidade", "eficiencia", "atividade", "estrutura",
]
DIRETOS = ["fc", "assimetria"]          # notas que só o jogador pode dar
ROTULOS = {
    "forcamento": "Forçamento", "urgencia": "Urgência",
    "valor_opcao": "Valor de opção", "informacao": "Baixo compromisso",
    "reversibilidade": "Reversibilidade", "eficiencia": "Eficiência",
    "atividade": "Atividade", "estrutura": "Estrutura/solidez",
    "fo": "FO", "fc": "FC", "robustez": "Robustez", "assimetria": "Assimetria",
}

# ---- Pesos (regra RP: só alterar após padrão em ~5–10 posições comparáveis)
PESOS_FO = {"atividade": 0.30, "estrutura": 0.30, "forcamento": 0.20, "eficiencia": 0.20}
PESOS_ROB = {"reversibilidade": 0.40, "valor_opcao": 0.30, "estrutura": 0.30}
PESOS_ATP = {"fo": 0.40, "fc": 0.30, "robustez": 0.20, "assimetria": 0.10}

# ---- Faixas objetivas: (limite, nome). Acima do último limite = descartar.
FAIXAS_CP = [(0.10, "equivalente"), (0.20, "excelente"), (0.35, "boa"), (0.60, "inferior")]
FAIXAS_PP = [(1.0, "equivalente"), (2.0, "excelente"), (3.5, "boa"), (5.5, "inferior")]
MI_CP = 0.10        # peões
MI_PP = 1.0         # pontos percentuais de pontuação esperada
MIS = 0.5           # margem de incerteza subjetiva (escala 0–10)
PEN_CP = 5.0        # ATP perdido por peão fora da MI (MA)
PEN_PP = 0.5        # ATP perdido por pp fora da MI (MA)


@dataclass
class Candidato:
    lance: str
    delta: float = 0.0               # perda vs melhor lance do motor, em peões
    filtro_ok: bool = True
    forcamento: float = 5
    urgencia: float = 5
    valor_opcao: float = 5
    informacao: float = 5            # Baixo compromisso
    reversibilidade: float = 5
    eficiencia: float = 5
    atividade: float = 5
    estrutura: float = 5
    fc: float = 5
    assimetria: float = 5
    w: Optional[float] = None        # WDL (%), opcional
    d: Optional[float] = None
    l: Optional[float] = None
    # Evidência externa (banco de partidas do Lichess) — só informa, não decide
    n_masters: Optional[int] = None
    pts_masters: Optional[float] = None
    n_lichess: Optional[int] = None
    pts_lichess: Optional[float] = None

    # ---- derivados
    @property
    def fo(self) -> float:
        return sum(p * getattr(self, k) for k, p in PESOS_FO.items())

    @property
    def robustez(self) -> float:
        return sum(p * getattr(self, k) for k, p in PESOS_ROB.items())

    @property
    def atp(self) -> float:
        return sum(p * getattr(self, k) for k, p in PESOS_ATP.items())

    @property
    def total_estrategico(self) -> float:
        return sum(getattr(self, k) for k in ESTRATEGICOS)

    @property
    def media_estrategica(self) -> float:
        return self.total_estrategico / len(ESTRATEGICOS)

    @property
    def escore(self) -> Optional[float]:
        """Pontuação esperada E = W + D/2 (em %)."""
        if self.w is None or self.d is None:
            return None
        return self.w + self.d / 2

    def para_dict(self) -> Dict:
        return asdict(self)

    @staticmethod
    def de_dict(d: Dict) -> "Candidato":
        validos = {f.name for f in fields(Candidato)}
        return Candidato(**{k: v for k, v in d.items() if k in validos})


def faixa(valor: float, modo: str = "cp") -> str:
    for lim, nome in (FAIXAS_PP if modo == "pp" else FAIXAS_CP):
        if valor <= lim + 1e-9:
            return nome
    return "descartar"


def _domina(a: List[float], b: List[float]) -> bool:
    return all(x >= y for x, y in zip(a, b)) and any(x > y for x, y in zip(a, b))


def analisar(cands: List[Candidato], mi_cp: float = MI_CP, mi_pp: float = MI_PP) -> Dict:
    res: Dict = {"eliminados": [], "avisos": []}

    # 1. Filtro obrigatório
    ativos = []
    for c in cands:
        (ativos if c.filtro_ok else res["eliminados"]).append(
            c if c.filtro_ok else (c.lance, "falhou no filtro obrigatório"))
    if not ativos:
        res["avisos"].append("Nenhum candidato passou no filtro.")
        return res

    # 2. Faixa objetiva: pontuação esperada se todos têm WDL; senão centipawns
    if all(c.escore is not None for c in ativos):
        modo, mi, pen, corte = "pp", mi_pp, PEN_PP, FAIXAS_PP[-1][0]
        melhor = max(c.escore for c in ativos)
        rel = {c.lance: round(melhor - c.escore, 3) for c in ativos}
    else:
        modo, mi, pen, corte = "cp", mi_cp, PEN_CP, FAIXAS_CP[-1][0]
        if any(c.escore is not None for c in ativos):
            res["avisos"].append("WDL incompleto: usada a perda em peões para todos.")
        melhor = min(c.delta for c in ativos)
        rel = {c.lance: round(c.delta - melhor, 3) for c in ativos}
    if min(c.delta for c in ativos) > mi_cp + 1e-9:
        res["avisos"].append(f"O melhor lance do motor não está entre os candidatos "
                             f"(menor perda informada: {min(c.delta for c in ativos):.2f} peão).")
    res.update(modo=modo, mi=mi, rel=rel, unidade="pp" if modo == "pp" else "peões")

    sobrev = []
    for c in ativos:
        if rel[c.lance] > corte + 1e-9:
            res["eliminados"].append((c.lance, f"perda {rel[c.lance]:.2f} {res['unidade']} > {corte}"))
        else:
            sobrev.append(c)
    ativos = sobrev

    # 3. MI
    equivalentes = [c for c in ativos if rel[c.lance] <= mi + 1e-9]
    res["equivalentes"] = [c.lance for c in equivalentes]

    # 4. Pareto (dentro da MI o objetivo empata; FO/Rob ficam fora: já estão no núcleo)
    def vetor(c):
        obj = 0.0 if rel[c.lance] <= mi + 1e-9 else -rel[c.lance]
        return [obj] + [getattr(c, k) for k in ESTRATEGICOS + DIRETOS]

    nao_dom = [c for c in ativos
               if not any(_domina(vetor(o), vetor(c)) for o in ativos if o is not c)]
    res["dominados"] = [c.lance for c in ativos if c not in nao_dom]

    # 5. TOP — duelos com tolerância (MI no objetivo, MIS no subjetivo)
    dims = [
        ("objetivo", lambda c: -rel[c.lance], mi),
        ("forçamento", lambda c: c.forcamento, MIS),
        ("opções", lambda c: c.valor_opcao, MIS),
        ("robustez", lambda c: c.robustez, MIS),
        ("clareza (FC)", lambda c: c.fc, MIS),
    ]
    top = {c.lance: 0.0 for c in nao_dom}
    duelos = []
    for i, a in enumerate(nao_dom):
        for b in nao_dom[i + 1:]:
            va = sum(1 for _, f, t in dims if f(a) - f(b) > t + 1e-9)
            vb = sum(1 for _, f, t in dims if f(b) - f(a) > t + 1e-9)
            if va > vb:
                top[a.lance] += 1
            elif vb > va:
                top[b.lance] += 1
            else:
                top[a.lance] += 0.5
                top[b.lance] += 0.5
            duelos.append(f"{a.lance} × {b.lance}: {va}–{vb}")
    res["top"], res["duelos"] = top, duelos

    # 6. MA — leitura correta (ATP) × leitura parcialmente errada (ATP·Rob/10)
    def penal(c):
        return pen * max(0.0, rel[c.lance] - mi)

    ok = {c.lance: c.atp - penal(c) for c in nao_dom}
    err = {c.lance: c.atp * c.robustez / 10 - penal(c) for c in nao_dom}
    b_ok, b_err = max(ok.values()), max(err.values())
    res["ma"] = {k: round(max(b_ok - ok[k], b_err - err[k]), 2) for k in ok}

    # 7. Decisão: dentro da MI, maior ATP; empate por MIS -> menor MA -> TOP
    grupo = [c for c in nao_dom if c in equivalentes]
    if not grupo:
        menor = min(rel[c.lance] for c in nao_dom)
        grupo = [c for c in nao_dom if rel[c.lance] == menor]
        res["avisos"].append("Nenhum não-dominado dentro da MI; usado o de menor perda objetiva.")
    melhor_atp = max(c.atp for c in grupo)
    disputa = [c for c in grupo if melhor_atp - c.atp < MIS]
    escolha = min(disputa, key=lambda c: (res["ma"][c.lance], -top.get(c.lance, 0)))
    res["escolha"] = escolha.lance
    res["empate_mis"] = [c.lance for c in disputa] if len(disputa) > 1 else []

    # 8. Saídas separadas
    def melhor_por(f):
        return max(ativos, key=f).lance

    res["saidas"] = {
        "Melhor objetivo": melhor_por(lambda c: -rel[c.lance]),
        "Melhor estratégico": melhor_por(lambda c: c.media_estrategica),
        "Mais robusto": melhor_por(lambda c: c.robustez),
        "Mais prático": melhor_por(lambda c: c.forcamento + c.atividade),
        "Maior FC": melhor_por(lambda c: c.fc),
        "Maior FO": melhor_por(lambda c: c.fo),
        "Maior ATP": melhor_por(lambda c: c.atp),
        "Escolha final HED": escolha.lance,
    }

    # 9. IFE em letras: margem de ATP sobre o 2º não-dominado, medida em MIS
    outros = [c.atp for c in nao_dom if c is not escolha]
    margem = escolha.atp - max(outros) if outros else None
    if margem is None:
        nivel = "A"            # candidato único após filtros: confiança vem só do objetivo
    else:
        nivel = next(n for lim, n in [(3 * MIS, "A+"), (2 * MIS, "A"), (MIS, "B"),
                                      (MIS / 2, "C"), (-99, "D")] if margem >= lim)
    if escolha not in equivalentes:
        ordem = ["A+", "A", "B", "C", "D"]
        nivel = ordem[min(ordem.index(nivel) + 1, 4)]
    res["ife"] = (nivel, None if margem is None else round(margem, 2))
    res["ativos"] = ativos
    return res


def relatorio(cands: List[Candidato], mi_cp: float = MI_CP, mi_pp: float = MI_PP) -> str:
    r = analisar(cands, mi_cp, mi_pp)
    L = [f"HED {VERSAO} — RELATÓRIO", ""]
    for a in r["avisos"]:
        L.append(f"⚠ {a}")
    if r["eliminados"]:
        L.append("ELIMINADOS")
        L += [f"  {l}: {m}" for l, m in r["eliminados"]]
        L.append("")
    if "ativos" not in r:
        return "\n".join(L)

    u = r["unidade"]
    L.append(f"Faixa objetiva em: {'pontuação esperada (WDL)' if r['modo'] == 'pp' else 'peões'}")
    L.append("")
    L.append("CANDIDATOS")
    for c in sorted(r["ativos"], key=lambda c: r["rel"][c.lance]):
        d = r["rel"][c.lance]
        e = f" | E {c.escore:.1f}%" if c.escore is not None else ""
        L.append(f"  {c.lance}: perda {d:.2f} {u} ({faixa(d, r['modo'])}){e}")
        L.append(f"     Estrat. média {c.media_estrategica:.2f}")
        L.append(f"     FO {c.fo:.1f}* FC {c.fc:.1f} Rob {c.robustez:.1f}* Assim {c.assimetria:.1f}"
                 f" → ATP {c.atp:.2f}")
    L.append("     (* derivados do núcleo estratégico)")
    L.append("")
    ev = [c for c in r["ativos"] if c.n_masters or c.n_lichess]
    if ev:
        L.append("EVIDÊNCIA EXTERNA (pontos de quem joga; não altera a decisão)")
        for c in ev:
            partes = []
            if c.n_masters:
                partes.append(f"Masters {c.n_masters} jogos {c.pts_masters:.0%}"
                              + (" (amostra pequena)" if c.n_masters < 20 else ""))
            if c.n_lichess:
                partes.append(f"Lichess {c.n_lichess} jogos {c.pts_lichess:.0%}"
                              + (" (amostra pequena)" if c.n_lichess < 50 else ""))
            L.append(f"  {c.lance}: " + " | ".join(partes))
        L.append("")
    L.append(f"MI ({r['mi']} {u}): " + (", ".join(r["equivalentes"]) or "—"))
    L.append("Dominados (Pareto): " + (", ".join(r["dominados"]) or "nenhum"))
    if r["duelos"]:
        L.append("TOP: " + " | ".join(r["duelos"]))
    L.append("MA (menor = melhor): " + ", ".join(f"{k} {v:.2f}" for k, v in r["ma"].items()))
    if r["empate_mis"]:
        L.append(f"Empate prático por MIS (ΔATP < {MIS}): {', '.join(r['empate_mis'])}"
                 " → decidido por MA/TOP")
    L.append("")
    L.append("SAÍDA FINAL")
    for k, v in r["saidas"].items():
        L.append(f"  {k}: {v}")
    nivel, margem = r["ife"]
    txt_m = "candidato único" if margem is None else f"margem ATP {margem:+.2f}"
    L.append(f"  IFE: {nivel} ({txt_m})")
    L.append("")
    L.append("Lembrete: TF (xeques → capturas → ameaças → passados → transformações),")
    L.append("transposições e evidência externa são checados antes de pontuar.")
    return "\n".join(L)


# ======================================================== Registro e PR/CC/AC/RP
RESULTADOS = {"—": None, "1": 1.0, "½": 0.5, "0": 0.0}


def novo_registro(r: Dict, estrutura: str, jogado: str, resultado: Optional[float] = None) -> Dict:
    return {
        "data": date.today().isoformat(),
        "estrutura": (estrutura or "").strip() or "geral",
        "hed": r["escolha"],
        "motor": r["saidas"]["Melhor objetivo"],
        "jogado": jogado,
        "ife": r["ife"][0],
        "resultado": resultado,
    }


def _media(v):
    return sum(v) / len(v) if v else None


def _fmt(x):
    return "—" if x is None else f"{x:.2f}"


def analise_registro(regs: List[Dict], minimo_rp: int = 5) -> str:
    if not regs:
        return "Registro vazio. Analise uma posição e toque em Registrar."
    L = [f"HED {VERSAO} — PR / CC / AC / RP", f"Posições registradas: {len(regs)}", ""]

    seguiu = [r for r in regs if r["jogado"] == r["hed"]]
    com_res = [r for r in regs if r.get("resultado") is not None]
    pts_s = _media([r["resultado"] for r in com_res if r["jogado"] == r["hed"]])
    pts_d = _media([r["resultado"] for r in com_res if r["jogado"] != r["hed"]])
    motor = sum(1 for r in regs if r["jogado"] == r["motor"])

    L.append("PR — PREFERÊNCIA REVELADA")
    L.append(f"  Seguiu o HED: {len(seguiu)}/{len(regs)} ({100 * len(seguiu) / len(regs):.0f}%)")
    L.append(f"  Jogou o lance do motor: {motor}/{len(regs)}")
    L.append(f"  Pontos/partida seguindo: {_fmt(pts_s)} | desviando: {_fmt(pts_d)}")
    L.append("")

    L.append("CC — CALIBRAÇÃO CONTEXTUAL (por estrutura)")
    grupos: Dict[str, List[Dict]] = {}
    for r in regs:
        grupos.setdefault(r["estrutura"], []).append(r)
    for est, rs in sorted(grupos.items(), key=lambda x: -len(x[1])):
        s = sum(1 for r in rs if r["jogado"] == r["hed"])
        cr = [r for r in rs if r.get("resultado") is not None]
        ps = _media([r["resultado"] for r in cr if r["jogado"] == r["hed"]])
        pd = _media([r["resultado"] for r in cr if r["jogado"] != r["hed"]])
        L.append(f"  {est}: n={len(rs)} | seguiu {s}/{len(rs)} | pts seguindo {_fmt(ps)}"
                 f" × desviando {_fmt(pd)}")
    L.append("")

    L.append("AC — AUDITORIA DE CONTRADIÇÃO")
    alertas = []
    hist: Dict[str, List[bool]] = {}
    for i, r in enumerate(regs, 1):
        h = hist.setdefault(r["estrutura"], [])
        seg = r["jogado"] == r["hed"]
        if len(h) >= 3:
            taxa = sum(h) / len(h)
            if taxa >= 0.7 and not seg:
                alertas.append(f"  #{i} ({r['data']}, {r['estrutura']}): desviou do HED "
                               f"({r['jogado']} em vez de {r['hed']}); costuma seguir {taxa:.0%}")
            elif taxa <= 0.3 and seg:
                alertas.append(f"  #{i} ({r['data']}, {r['estrutura']}): seguiu o HED, "
                               f"mas costuma desviar ({1 - taxa:.0%})")
        h.append(seg)
    L += alertas or ["  Nenhuma contradição com o padrão anterior."]
    L.append("")

    L.append(f"RP — REGULARIZAÇÃO (mínimo {minimo_rp} posições comparáveis)")
    for est, rs in sorted(grupos.items(), key=lambda x: -len(x[1])):
        cr = [r for r in rs if r.get("resultado") is not None]
        if len(cr) < minimo_rp:
            L.append(f"  {est}: dados insuficientes ({len(cr)}/{minimo_rp} com resultado) → manter pesos")
            continue
        ps = [r["resultado"] for r in cr if r["jogado"] == r["hed"]]
        pd = [r["resultado"] for r in cr if r["jogado"] != r["hed"]]
        if len(ps) >= 2 and len(pd) >= 2 and _media(pd) - _media(ps) >= 0.15:
            L.append(f"  {est}: desviar rende mais ({_fmt(_media(pd))} × {_fmt(_media(ps))})"
                     " → rever pesos nesta estrutura")
        else:
            L.append(f"  {est}: sem padrão contra o HED → manter pesos")
    return "\n".join(L)


if __name__ == "__main__":
    demo = [
        Candidato("Rd1", 0.00, forcamento=6, urgencia=7, valor_opcao=8, informacao=7,
                  reversibilidade=8, eficiencia=7, atividade=7, estrutura=8, fc=9.0, assimetria=7.0),
        Candidato("e5", 0.08, forcamento=9, urgencia=8, valor_opcao=6, informacao=5,
                  reversibilidade=4, eficiencia=8, atividade=9, estrutura=7, fc=9.6, assimetria=9.8),
        Candidato("h4", 0.42, forcamento=7, urgencia=4, valor_opcao=5, informacao=4,
                  reversibilidade=3, eficiencia=5, atividade=8, estrutura=4, fc=6.0, assimetria=9.0),
        Candidato("Qxb7??", 0.0, filtro_ok=False),
    ]
    print(relatorio(demo))
    print("\n" + "=" * 60 + "\n")
    # mesmo conjunto com WDL -> faixa em pontuação esperada
    for c, wdl in zip(demo, [(40, 50, 10), (44, 42, 14), (38, 44, 18)]):
        c.w, c.d, c.l = wdl
    print(relatorio(demo))
    print("\n" + "=" * 60 + "\n")
    r = analisar(demo)
    regs = [novo_registro(r, "IQP", j, res) for j, res in
            [("Rd1", 1.0), ("Rd1", 0.5), ("Rd1", 1.0), ("e5", 0.0), ("Rd1", 0.5), ("e5", 1.0)]]
    regs.append(novo_registro(r, "Carlsbad", "e5"))
    print(analise_registro(regs))
