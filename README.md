# HED 11.2 — app Android

Algoritmo de decisão enxadrística HED em Python (Kivy).
Mesma filosofia e pipeline do 11.1.1; o 11.2 muda só a camada de medição.

## Arquivos

| Arquivo | Função |
|---|---|
| `hed_core.py` | Núcleo: filtro, faixas, MI, Pareto, TOP, MA, ATP, saídas, IFE, registro e PR/CC/AC/RP |
| `main.py` | Interface Android (Kivy) |
| `buildozer.spec` | Configuração do APK |
| `.github/workflows/android.yml` | Gera o APK no GitHub Actions |

## Gerar o APK pelo GitHub

1. Envie todos os arquivos para um repositório (incluindo a pasta `.github`).
2. Aba **Actions** → workflow **Build APK** roda a cada push em `main`.
3. Ao terminar (~20–30 min na 1ª vez): execução → **Artifacts** → `hed-apk`.
4. Extraia o `.apk` no celular e instale.

## O que mudou do 11.1.1 para o 11.2

| Problema | Solução |
|---|---|
| Precisão falsa | MIS: ΔATP < 0,5 = empate prático → decide MA, depois TOP |
| Estratégico fora da decisão / dupla contagem | FO e Robustez derivados do núcleo |
| MI fixa em peões | MI em pontuação esperada (WDL) quando todos os candidatos têm WDL |
| IFE com % não calibrada | Só letras A+ a D |
| PR/CC/AC sem dados | Registro de posições no app |
| Polaridade ambígua | "Informação/compromisso" → "Baixo compromisso" (10 = flexível) |

## Fórmulas

- FO = 0,30·Atividade + 0,30·Estrutura + 0,20·Forçamento + 0,20·Eficiência
- Robustez = 0,40·Reversibilidade + 0,30·Valor de opção + 0,30·Estrutura
- ATP = 0,40·FO + 0,30·FC + 0,20·Robustez + 0,10·Assimetria (inalterada)
- Pontuação esperada: E = W + D/2

| Faixa | Peões | Pontuação esperada |
|---|---|---|
| Equivalente | ≤ 0,10 | ≤ 1 pp |
| Excelente | ≤ 0,20 | ≤ 2 pp |
| Boa | ≤ 0,35 | ≤ 3,5 pp |
| Inferior | ≤ 0,60 | ≤ 5,5 pp |
| Descartar | > 0,60 | > 5,5 pp |

- MA: arrependimento máximo entre "leitura correta" (ATP) e "leitura errada" (ATP × Robustez/10), com penalidade fora da MI (5 ATP/peão ou 0,5 ATP/pp)
- IFE: margem de ATP sobre o 2º colocado — ≥1,5 A+ · ≥1,0 A · ≥0,5 B · ≥0,25 C · abaixo D; cai um nível se a escolha estiver fora da MI

## Registro (PR / CC / AC / RP)

Após analisar: **Registrar** → estrutura, lance jogado, resultado (pode preencher depois tocando na linha).

- **PR**: % de vezes que seguiu o HED e pontos seguindo × desviando
- **CC**: o mesmo, por estrutura
- **AC**: alerta quando você contradiz o próprio padrão (≥3 posições anteriores na estrutura)
- **RP**: só sugere rever pesos com ≥5 posições com resultado na estrutura e desvio rendendo ≥0,15 ponto a mais

Pesos e limites ficam no topo de `hed_core.py`.
