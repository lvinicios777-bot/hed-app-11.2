# HED 11.2 — app Android

Algoritmo de decisão enxadrística HED em Python (Kivy).
Mesma filosofia e pipeline do 11.1.1; o 11.2 muda só a camada de medição.

## Arquivos

| Arquivo | Função |
|---|---|
| 'hed_core.py' | Núcleo: filtro, faixas, MI, Pareto, TOP, MA, ATP, saídas, IFE, registro e PR/CC/AC/RP |
| 'main.py' | Interface Android (Kivy) |
| 'buildozer.spec' | Configuração do APK |
| '.github/workflows/android.yml' | Gera o APK no GitHub Actions |

## Gerar o APK pelo GitHub

1. Envie todos os arquivos para um repositório (incluindo a pasta '.github').
2. Aba **Actions** → workflow **Build APK** roda a cada push em 'main'.
3. Ao terminar (~20–30 min na 1ª vez): execução → **Artifacts** → 'hed-apk'.
4. Extraia o '.apk' no celular e instale.

## Tabuleiro / análise (estilo Lichess)

- Toque ou arraste as peças; pontos mostram os lances legais; promoção com escolha da peça.
- Stockfish ao vivo: barra de avaliação, avaliação no padrão do Lichess (+0.35, #3), 3 linhas e seta azul do melhor lance. Toque numa linha para jogar o lance.
- Navegação |< < > >|, Girar, lista de lances; jogar um lance no meio da partida cria a nova continuação.
- Explorador Masters/Lichess embaixo do tabuleiro (toque no lance para jogá-lo).
- Colar FEN ou PGN (exportado do Lichess), Copiar FEN, e **Enviar ao HED** (avalia os candidatos e importa para a decisão).

## Motor e banco de dados (tela "Posição (FEN)")

1. Cole o FEN da posição (no Lichess: menu > Compartilhar > FEN) e toque em **Analisar**.
2. O app consulta:
   - **Stockfish 19** rodando no próprio celular (avaliação + WDL, MultiPV) — compilado no build e embutido no APK;
   - **Lichess nuvem** como reserva (avaliação em cache, sem token);
   - **Banco Lichess Masters e Lichess** (jogos e pontuação por lance) — exige token pessoal.
3. Lances que aparecem no banco mas não no MultiPV também são avaliados pelo Stockfish.
4. Marque os lances e toque em **Importar marcados**: perda (vs melhor lance) e WDL são preenchidos sozinhos; você só dá as notas estratégicas.

Token: crie em lichess.org/account/oauth/token **sem marcar nenhuma permissão** e cole em Configurações.
A evidência dos bancos aparece no relatório, mas não altera a decisão (regra do HED: estatística não substitui avaliação objetiva).

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

Pesos e limites ficam no topo de 'hed_core.py'.
