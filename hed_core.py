"""
HED 11.1.2 — núcleo de decisão enxadrística (Python puro, sem dependências).

Unifica a 11.1, a 11.1.1 e a camada de medição da 11.2. Mesmas regras do documento HED 11.1.2.

Execução: Gerar (diagnóstico, candidatos na ordem da TF) -> Filtrar (filtro obrigatório,
pontuação esperada, admissão pela MI com preço λ e teto, conflito TF × Conversão)
-> Pontuar (núcleo -> FO e Robustez; FC e Assimetria -> ATP -> U)
-> Decidir (Pareto -> maior U -> empate < τ -> MA de Savage -> menor Δ; IFE; TOP como auditoria)
-> Aprender (registro: PR / CC / AC / RP).

O motor não roda aqui: cada candidato traz a perda em peões e, se houver, WDL e/ou a avaliação.
"""
from dataclasses import dataclass, asdict, fields
from datetime import date
from math import erf, exp, sqrt
from typing import List, Dict, Optional

VERSAO = "11.1.2"

ESTRATEGICOS = [
    "forcamento", "urgencia", "valor_opcao", "informacao",
    "reversibilidade", "eficiencia", "atividade", "estrutura",
]
DIRETOS = ["fc", "assimetria"]          # notas que só o jogador pode dar
NOTAS = ESTRATEGICOS + DIRETOS
ROTULOS = {
    "forcamento": "Forçamento", "urgencia": "Urgência",
    "valor_opcao": "Valor de opção", "informacao": "Baixo compromisso",
    "reversibilidade": "Reversibilidade", "eficiencia": "Eficiência",
    "atividade": "Atividade", "estrutura": "Estrutura/solidez",
    "fo": "FO", "fc": "FC", "robustez": "Robustez", "assimetria": "Assimetria",
}

# ---- Pesos (regra RP: só alterar após padrão em ~5–10 posições comparáveis).
# Cada critério alimenta UM agregado só (sem dupla contagem).
PESOS_FO = {"forcamento": 0.30, "urgencia": 0.20, "atividade": 0.30, "eficiencia": 0.20}
PESOS_ROB = {"estrutura": 0.40, "valor_opcao": 0.30, "flexibilidade": 0.30}
FLEX = ("reversibilidade", "informacao")   # Flexibilidade = média destes dois
PESOS_ATP = {"fo": 0.40, "fc": 0.30, "robustez": 0.20, "assimetria": 0.10}

# ---- Regras objetivas (pontuação esperada, em pontos percentuais)
K_LICHESS = 0.00368208       # curva centipeão -> probabilidade do Lichess
MI_PP = 1.0                  # Margem de Incerteza (≈ 0,10 peão perto da igualdade)
LAMBDA = 1.0                 # ATP cobrado por pp de perda além da MI
EXTRA_MAX_PP = 2.0           # teto: eliminado se Δ > MI + EXTRA_MAX_PP
SIGMA_NOTA = 1.0             # ruído típico de uma nota subjetiva (0–10)
FAIXAS_PP = [(1.0, "equivalente"), (2.0, "excelente"), (3.0, "boa"), (5.5, "inferior")]
MI_CP = 0.10                 # mantido só para compatibilidade com dados salvos da 11.2


def pontuacao_cp(cp: float) -> float:
    """Avaliação em centipeões (ponto de vista de quem joga) -> pontuação esperada em %."""
    cp = max(-2000.0, min(2000.0, cp))
    return 100.0 / (1.0 + exp(-K_LICHESS * cp))


def _phi(z: float) -> float:
    return 0.5 * (1.0 + erf(z / sqrt(2.0)))


def sigma_diferenca(sigma_nota: float = SIGMA_NOTA) -> float:
    """Desvio-padrão da diferença de ATP entre dois candidatos causado só pelo ruído das notas."""
    pesos = [PESOS_ATP["fo"] * v for v in PESOS_FO.values()]
    pesos.append(PESOS_ATP["fc"])
    pesos.append(PESOS_ATP["robustez"] * PESOS_ROB["estrutura"])
    pesos.append(PESOS_ATP["robustez"] * PESOS_ROB["valor_opcao"])
    pesos += [PESOS_ATP["robustez"] * PESOS_ROB["flexibilidade"] / len(FLEX)] * len(FLEX)
    pesos.append(PESOS_ATP["assimetria"])
    return sqrt(2.0) * sigma_nota * sqrt(sum(p * p for p in pesos))


TAU = sigma_diferenca()      # ≈ 0,55: diferença de U abaixo disso é empate


@dataclass
class Candidato:
    lance: str
    delta: float = 0.0               # perda vs melhor lance do motor, em peões
    filtro_ok: bool = True
    # Notas 0–10. None = não avaliada (nenhum padrão neutro: evita o ATP falso de 5,00)
    forcamento: Optional[float] = None
    urgencia: Optional[float] = None
    valor_opcao: Optional[float] = None
    informacao: Optional[float] = None   # Baixo compromisso (10 = revela pouco, flexível)
    reversibilidade: Optional[float] = None
    eficiencia: Optional[float] = None
    atividade: Optional[float] = None
    estrutura: Optional[float] = None
    fc: Optional[float] = None
    assimetria: Optional[float] = None
    w: Optional[float] = None        # WDL (%), opcional
    d: Optional[float] = None
    l: Optional[float] = None
    aval_cp: Optional[float] = None  # avaliação do lance em cp (quem joga), se vier do motor
    # Evidência externa (banco de partidas do Lichess) — só informa, não decide
    n_masters: Optional[int] = None
    pts_masters: Optional[float] = None
    n_lichess: Optional[int] = None
    pts_lichess: Optional[float] = None

    # ---- notas
    def faltando(self) -> List[str]:
        return [k for k in NOTAS if getattr(self, k) is None]

    @property
    def completo(self) -> bool:
        return not self.faltando()

    # ---- derivados (None enquanto faltar nota)
    @property
    def flexibilidade(self) -> Optional[float]:
        v = [getattr(self, k) for k in FLEX]
        return None if None in v else sum(v) / len(v)

    @property
    def fo(self) -> Optional[float]:
        v = {k: getattr(self, k) for k in PESOS_FO}
        return None if None in v.values() else sum(p * v[k] for k, p in PESOS_FO.items())

    @property
    def robustez(self) -> Optional[float]:
        v = {"estrutura": self.estrutura, "valor_opcao": self.valor_opcao,
             "flexibilidade": self.flexibilidade}
        return None if None in v.values() else sum(p * v[k] for k, p in PESOS_ROB.items())

    @property
    def atp(self) -> Optional[float]:
        v = {"fo": self.fo, "fc": self.fc, "robustez": self.robustez, "assimetria": self.assimetria}
        return None if None in v.values() else sum(p * v[k] for k, p in PESOS_ATP.items())

    @property
    def media_estrategica(self) -> Optional[float]:
        v = [getattr(self, k) for k in ESTRATEGICOS]
        return None if None in v else sum(v) / len(v)

    @property
    def escore(self) -> Optional[float]:
        """Pontuação esperada pelo WDL: E = W + D/2 (em %)."""
        if self.w is None or self.d is None:
            return None
        total = (self.w or 0) + (self.d or 0) + (self.l or 0)
        if total <= 0:
            return None
        return 100.0 * (self.w + self.d / 2) / total

    def para_dict(self) -> Dict:
        return asdict(self)

    @staticmethod
    def de_dict(d: Dict) -> "Candidato":
        validos = {f.name for f in fields(Candidato)}
        return Candidato(**{k: v for k, v in d.items() if k in validos})


def faixa(delta_pp: float) -> str:
    for lim, nome in FAIXAS_PP:
        if delta_pp <= lim + 1e-9:
            return nome
    return "descartar"


def sugestoes(san: str) -> Dict[str, float]:
    """Pré-preenchimento pelo próprio lance (valores iniciais para o jogador ajustar)."""
    s, lance = {}, (san or "").strip()
    if not lance:
        return s
    peao = lance[0] in "abcdefgh"
    captura = "x" in lance
    if peao or captura:
        s["reversibilidade"] = 3.0          # irreversível por regra
    if "+" in lance or "#" in lance:
        s["forcamento"] = 8.0
    elif captura:
        s["forcamento"] = 6.0
    return s


def aplicar_sugestoes(c: Candidato) -> Candidato:
    for k, v in sugestoes(c.lance).items():
        if getattr(c, k) is None:
            setattr(c, k, v)
    return c


# ======================================================== TF × Eficiência de Conversão
def limiar_tf(tranq_cp: float, fim_cp: float, falha_cp: float) -> Dict:
    """p*: confiança mínima no cálculo para a TF valer mais que o lance tranquilo."""
    e_t, e_f, e_x = (pontuacao_cp(v) for v in (tranq_cp, fim_cp, falha_cp))
    if e_f <= e_t:
        p = 1.0
    elif e_x >= e_t:
        p = 0.0
    else:
        p = (e_t - e_x) / (e_f - e_x)
    return {"e_tranq": e_t, "e_fim": e_f, "e_falha": e_x, "p_estrela": p}


def tf_vale(p: float, tranq_cp: float, fim_cp: float, falha_cp: float) -> bool:
    return p > limiar_tf(tranq_cp, fim_cp, falha_cp)["p_estrela"]


# ======================================================== decisão
def _domina(a: List[float], b: List[float]) -> bool:
    return all(x >= y for x, y in zip(a, b)) and any(x > y for x, y in zip(a, b))


def _nivel_ife(conf: float) -> str:
    for lim, n in ((98, "A+"), (93, "A"), (85, "B"), (70, "C")):
        if conf >= lim:
            return n
    return "D"


def analisar(cands: List[Candidato], aval_melhor_cp: Optional[float] = None,
             mi_pp: float = MI_PP) -> Dict:
    res: Dict = {"eliminados": [], "avisos": []}

    # 1. Filtro obrigatório (checklist do jogador)
    ativos = []
    for c in cands:
        if c.filtro_ok:
            ativos.append(c)
        else:
            res["eliminados"].append((c.lance, "falhou no filtro obrigatório"))
    if not ativos:
        res["avisos"].append("Nenhum candidato passou no filtro.")
        return res

    # 2. Pontuação esperada: WDL se todos têm; senão avaliação do motor; senão perda + aval. do melhor
    if all(c.escore is not None for c in ativos):
        modo = "WDL (E = W + D/2)"
        E = {c.lance: c.escore for c in ativos}
    elif all(c.aval_cp is not None for c in ativos):
        modo = "avaliação do motor (curva do Lichess)"
        E = {c.lance: pontuacao_cp(c.aval_cp) for c in ativos}
    else:
        base = 0.0 if aval_melhor_cp is None else aval_melhor_cp
        if aval_melhor_cp is None:
            res["avisos"].append("Avaliação do melhor lance não informada: assumida 0,00.")
        modo = f"perda em peões + avaliação do melhor ({base / 100:+.2f})"
        E = {c.lance: pontuacao_cp(base - 100.0 * c.delta) for c in ativos}
    e_max = max(E.values())
    rel = {k: round(e_max - v, 2) for k, v in E.items()}
    if min(c.delta for c in ativos) > 0.10 + 1e-9:
        res["avisos"].append(f"O melhor lance do motor não está entre os candidatos "
                             f"(menor perda informada: {min(c.delta for c in ativos):.2f} peão).")
    res.update(modo=modo, mi=mi_pp, E=E, rel=rel, unidade="pp")

    # 3. Admissão: dentro da MI é livre; além dela paga λ por pp, até o teto
    teto = mi_pp + EXTRA_MAX_PP
    admit = []
    for c in ativos:
        if rel[c.lance] > teto + 1e-9:
            res["eliminados"].append((c.lance, f"perda {rel[c.lance]:.2f} pp > teto {teto:.1f} pp"))
        else:
            admit.append(c)
    res["equivalentes"] = [c.lance for c in admit if rel[c.lance] <= mi_pp + 1e-9]
    res["ativos"] = admit
    if not admit:
        res["avisos"].append("Nenhum candidato dentro do teto.")
        return res

    # Notas obrigatórias: sem elas não há decisão
    incompletos = {c.lance: c.faltando() for c in admit if not c.completo}
    if incompletos:
        res["incompletos"] = incompletos
        res["avisos"].append("Faltam notas — avalie antes de decidir: " + "; ".join(
            f"{l} ({len(f)})" for l, f in incompletos.items()))
        return res

    excesso = {c.lance: max(0.0, rel[c.lance] - mi_pp) for c in admit}
    U = {c.lance: c.atp - LAMBDA * excesso[c.lance] for c in admit}
    res["U"] = U

    # 4. Pareto: diferenças de Δ dentro da MI não contam (ruído do motor)
    def vetor(c):
        return [-excesso[c.lance], c.fo, c.fc, c.robustez, c.assimetria]

    nao_dom = [c for c in admit if not any(_domina(vetor(o), vetor(c)) for o in admit if o is not c)]
    res["dominados"] = [c.lance for c in admit if c not in nao_dom]

    # 5. Maior U; empate (< τ) -> MA de Savage -> menor Δ
    nao_dom.sort(key=lambda c: U[c.lance], reverse=True)
    topo = U[nao_dom[0].lance]
    empatados = [c for c in nao_dom if topo - U[c.lance] < TAU - 1e-9]
    dims = (("FO", lambda c: c.fo), ("FC", lambda c: c.fc),
            ("Rob", lambda c: c.robustez), ("Assim", lambda c: c.assimetria))
    melhor_d = {n: max(f(c) for c in nao_dom) for n, f in dims}
    res["ma"] = {c.lance: round(max(melhor_d[n] - f(c) for n, f in dims), 2) for c in nao_dom}
    if len(empatados) > 1:
        escolha = min(empatados, key=lambda c: (res["ma"][c.lance], rel[c.lance]))
        res["motivo"] = (f"empate de U (< {TAU:.2f}) entre {', '.join(c.lance for c in empatados)}"
                         f" -> menor arrependimento (MA {res['ma'][escolha.lance]:.2f}) -> menor perda")
    else:
        escolha = nao_dom[0]
        res["motivo"] = "maior U"
    res["escolha"] = escolha.lance
    res["empate"] = [c.lance for c in empatados] if len(empatados) > 1 else []

    # 6. IFE: probabilidade de a ordem 1º > 2º não ser ruído das notas
    outros = [U[c.lance] for c in nao_dom if c is not escolha]
    margem = U[escolha.lance] - max(outros) if outros else None
    conf = 100.0 if margem is None else 100.0 * _phi(max(margem, 0.0) / TAU)
    res["ife"] = (_nivel_ife(conf), None if margem is None else round(margem, 2), round(conf))

    # 7. TOP como auditoria: onde a escolha perde para cada rival (não vota)
    nomes = ("perda além da MI", "FO", "FC", "Robustez", "Assimetria")
    res["auditoria"] = []
    for o in nao_dom:
        if o is escolha:
            continue
        perde = [n for n, a, b in zip(nomes, vetor(escolha), vetor(o)) if a < b - 1e-9]
        if perde:
            res["auditoria"].append(f"{escolha.lance} perde para {o.lance} em: {', '.join(perde)}")

    # 8. Saídas separadas
    def melhor_por(f, conj=admit):
        return max(conj, key=f).lance

    saidas = {"Melhor objetivo": melhor_por(lambda c: -rel[c.lance])}
    if all(c.l is not None for c in admit):
        saidas["Melhor WDL (menos derrota)"] = melhor_por(lambda c: -c.l)
    saidas.update({
        "Melhor estratégico": melhor_por(lambda c: c.media_estrategica),
        "Mais forçante": melhor_por(lambda c: c.forcamento),
        "Mais robusto": melhor_por(lambda c: c.robustez),
        "Mais prático": melhor_por(lambda c: c.forcamento + c.atividade),
        "Maior FC": melhor_por(lambda c: c.fc),
        "Maior FO": melhor_por(lambda c: c.fo),
        "Maior ATP": melhor_por(lambda c: c.atp),
        "Escolha final HED": escolha.lance,
    })
    res["saidas"] = saidas
    return res


def relatorio(cands: List[Candidato], aval_melhor_cp: Optional[float] = None,
              mi_pp: float = MI_PP) -> str:
    r = analisar(cands, aval_melhor_cp, mi_pp)
    L = [f"HED {VERSAO} — RELATÓRIO", ""]
    for a in r["avisos"]:
        L.append(f"! {a}")
    if r["avisos"]:
        L.append("")
    if r["eliminados"]:
        L.append("ELIMINADOS")
        L += [f"  {l}: {m}" for l, m in r["eliminados"]]
        L.append("")
    if "incompletos" in r:
        L.append("NOTAS QUE FALTAM")
        for l, falta in r["incompletos"].items():
            L.append(f"  {l}: " + ", ".join(ROTULOS[k] for k in falta))
        return "\n".join(L)
    if "escolha" not in r:
        return "\n".join(L)

    L.append(f"Perda medida em pp de pontuação esperada, via {r['modo']}")
    L.append(f"MI {r['mi']:.1f} pp (livre) | teto {r['mi'] + EXTRA_MAX_PP:.1f} pp | "
             f"preço {LAMBDA:.1f} ATP por pp além da MI")
    L.append("")
    L.append("CANDIDATOS")
    for c in sorted(r["ativos"], key=lambda c: r["rel"][c.lance]):
        d = r["rel"][c.lance]
        L.append(f"  {c.lance}: perda {d:.2f} pp ({faixa(d)}) | E {r['E'][c.lance]:.1f}% | "
                 f"{c.delta:.2f} peão")
        L.append(f"     FO {c.fo:.2f}* FC {c.fc:.1f} Rob {c.robustez:.2f}* Assim {c.assimetria:.1f}"
                 f" -> ATP {c.atp:.2f} -> U {r['U'][c.lance]:.2f}")
    L.append("     (* calculados a partir do núcleo estratégico)")
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
    L.append("Dentro da MI: " + (", ".join(r["equivalentes"]) or "—"))
    L.append("Dominados (Pareto): " + (", ".join(r["dominados"]) or "nenhum"))
    L.append("MA (menor = melhor): " + ", ".join(f"{k} {v:.2f}" for k, v in r["ma"].items()))
    L.append(f"Decisão: {r['motivo']}")
    L.append("")
    L.append("SAÍDA FINAL")
    for k, v in r["saidas"].items():
        L.append(f"  {k}: {v}")
    nivel, margem, conf = r["ife"]
    if margem is None:
        txt_m = "candidato único"
    elif r["empate"]:
        txt_m = f"empate de U, decidido pelo MA"
    else:
        txt_m = f"vantagem de U {margem:+.2f}"
    L.append(f"  IFE: {nivel} ({conf}%, {txt_m})")
    if nivel == "D":
        L.append("  -> lances equivalentes para as suas notas: jogue o de menor perda e poupe o relógio.")
    if r["auditoria"]:
        L.append("")
        L.append("AUDITORIA (TOP — não vota)")
        L += [f"  {a}" for a in r["auditoria"]]
    L.append("")
    L.append("Lembrete: TF (xeques -> capturas -> ameaças -> passados -> transformações ->")
    L.append("defesa ativa -> defesa direta) verificada até o fim antes de pontuar.")
    return "\n".join(L)


def relatorio_tf(tranq_cp: float, fim_cp: float, falha_cp: float, p: Optional[float]) -> str:
    t = limiar_tf(tranq_cp, fim_cp, falha_cp)
    L = ["TF × EFICIÊNCIA DE CONVERSÃO", "",
         f"Lance tranquilo: {tranq_cp / 100:+.2f} -> E {t['e_tranq']:.1f}%",
         f"TF se o cálculo estiver certo: {fim_cp / 100:+.2f} -> E {t['e_fim']:.1f}%",
         f"TF se o cálculo estiver errado: {falha_cp / 100:+.2f} -> E {t['e_falha']:.1f}%", ""]
    ps = t["p_estrela"]
    if ps >= 1.0:
        L.append("A TF não supera o lance tranquilo nem dando certo: Conversão.")
    elif ps <= 0.0:
        L.append("Mesmo errando, a TF não fica pior que o lance tranquilo: TF.")
    else:
        L.append(f"Confiança mínima no cálculo (p*): {ps:.0%}")
        if p is not None:
            L.append(f"Sua confiança: {p:.0%} -> " + ("TF vale a pena." if p > ps else
                                                      "fique com a Conversão (lance tranquilo)."))
        L.append("")
        L.append("Com motor (linha verificada), p = 100%.")
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
        "versao": VERSAO,
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
    por_ife: Dict[str, List[float]] = {}
    for r in com_res:
        if r["jogado"] == r["hed"]:
            por_ife.setdefault(r.get("ife", "?"), []).append(r["resultado"])
    if por_ife:
        L.append("  Pontos seguindo o HED, por IFE: " + " | ".join(
            f"{k} {_fmt(_media(v))} (n={len(v)})" for k, v in sorted(por_ife.items())))
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
            L.append(f"  {est}: dados insuficientes ({len(cr)}/{minimo_rp} com resultado) -> manter pesos")
            continue
        ps = [r["resultado"] for r in cr if r["jogado"] == r["hed"]]
        pd = [r["resultado"] for r in cr if r["jogado"] != r["hed"]]
        if len(ps) >= 2 and len(pd) >= 2 and _media(pd) - _media(ps) >= 0.15:
            L.append(f"  {est}: desviar rende mais ({_fmt(_media(pd))} × {_fmt(_media(ps))})"
                     " -> rever pesos nesta estrutura")
        else:
            L.append(f"  {est}: sem padrão contra o HED -> manter pesos")
    total = len(com_res)
    L.append("")
    L.append(f"Calibração de λ e τ: {total}/30 posições com resultado"
             + (" -> já dá para revisar." if total >= 30 else " (revisar a partir de 30–50)."))
    return "\n".join(L)


# ======================================================== testes (rodam no build)
def _testes():
    def notas(**kw):
        base = {k: 5.0 for k in NOTAS}
        base.update(kw)
        return base

    # 1. Tudo em 5: empate total, IFE D, vence a menor perda
    r = analisar([Candidato("e6", 0.00, **notas()), Candidato("e5", 0.01, **notas()),
                  Candidato("Ng4", 0.04, **notas())], aval_melhor_cp=30)
    assert r["escolha"] == "e6" and r["ife"][0] == "D" and r["ife"][2] == 50, r

    # 2. Notas ausentes bloqueiam a decisão
    r = analisar([Candidato("e6", 0.0), Candidato("e5", 0.01, **notas())], aval_melhor_cp=30)
    assert "escolha" not in r and "e6" in r["incompletos"], r

    # 3. Teto elimina, λ cobra
    r = analisar([Candidato("a", 0.0, **notas()), Candidato("h6", 0.60, **notas(fc=10))],
                 aval_melhor_cp=30)
    assert any(l == "h6" for l, _ in r["eliminados"]), r

    # 4. ATP do print da 11.2 (VO 3, resto 5) = 4,88
    c = Candidato("x", **notas(valor_opcao=3))
    assert abs(c.robustez - 4.40) < 1e-9 and abs(c.atp - 4.88) < 1e-9

    # 5. Vencedor claro com IFE alto
    r = analisar([Candidato("Rd1", 0.0, **notas(fc=9, atividade=8, estrutura=8, assimetria=7)),
                  Candidato("h3", 0.02, **notas(fc=3, atividade=3))], aval_melhor_cp=0)
    assert r["escolha"] == "Rd1" and r["ife"][0] == "A+", r

    # 6. WDL tem prioridade; limiar TF do documento (72%)
    r = analisar([Candidato("Rd1", 0.0, w=30, d=60, l=10, **notas(fc=7)),
                  Candidato("Qe2", 0.0, w=34, d=50, l=16, **notas(forcamento=8))])
    assert r["modo"].startswith("WDL") and "Melhor WDL (menos derrota)" in r["saidas"]
    assert round(limiar_tf(200, 400, -200)["p_estrela"], 2) == 0.72
    assert not tf_vale(0.6, 200, 400, -200) and tf_vale(0.8, 200, 400, -200)

    # 7. Sugestões só preenchem o que falta
    c = aplicar_sugestoes(Candidato("exd5+"))
    assert c.reversibilidade == 3.0 and c.forcamento == 8.0 and c.fc is None
    return True


if __name__ == "__main__":
    assert _testes()
    print("Testes do núcleo: OK\n")
    demo = [
        Candidato("Rd1", 0.00, forcamento=6, urgencia=7, valor_opcao=8, informacao=7,
                  reversibilidade=8, eficiencia=7, atividade=7, estrutura=8, fc=9.0, assimetria=7.0),
        Candidato("e5", 0.08, forcamento=9, urgencia=8, valor_opcao=6, informacao=5,
                  reversibilidade=4, eficiencia=8, atividade=9, estrutura=7, fc=9.6, assimetria=9.8),
        Candidato("h4", 0.30, forcamento=7, urgencia=4, valor_opcao=5, informacao=4,
                  reversibilidade=3, eficiencia=5, atividade=8, estrutura=4, fc=6.0, assimetria=9.0),
        Candidato("Qxb7??", 0.0, filtro_ok=False),
    ]
    print(relatorio(demo, aval_melhor_cp=20))
    print("\n" + "=" * 60 + "\n")
    print(relatorio_tf(200, 400, -200, 0.8))
    print("\n" + "=" * 60 + "\n")
    r = analisar(demo, aval_melhor_cp=20)
    regs = [novo_registro(r, "IQP", j, res) for j, res in
            [("Rd1", 1.0), ("Rd1", 0.5), ("Rd1", 1.0), ("e5", 0.0), ("Rd1", 0.5), ("e5", 1.0)]]
    regs.append(novo_registro(r, "Carlsbad", "e5"))
    print(analise_registro(regs))
