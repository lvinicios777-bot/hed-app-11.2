# HED 11.1.2 — app Android

Algoritmo de decisão enxadrística HED em Python (Kivy).
Versão 11.1.2: 11.1 + 11.1.1 + medição da 11.2, com regras de decisão fechadas em fórmula.

## Arquivos

| Arquivo | Função |
|---|---|
| 'hed_core.py' | Núcleo: filtro, pontuação esperada, MI/λ/teto, Pareto, U, τ, MA, IFE, TOP (auditoria), TF × Conversão, registro e PR/CC/AC/RP |
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
4. Marque os lances e toque em **Importar marcados**: perda, avaliação e WDL são preenchidos sozinhos, e Reversibilidade/Forçamento vêm sugeridos pelo lance; você dá as demais notas.

Token: crie em lichess.org/account/oauth/token **sem marcar nenhuma permissão** e cole em Configurações.
A evidência dos bancos aparece no relatório, mas não altera a decisão (regra do HED: estatística não substitui avaliação objetiva).

## O que mudou na 11.1.2

A 11.1.2 unifica a 11.1, a 11.1.1 e a camada de medição da 11.2. O app segue as mesmas regras do documento HED 11.1.2.

| Antes (11.2) | Agora (11.1.2) |
|---|---|
| Notas começavam em 5,0 (ATP falso de 5,00) | Nota sem valor = "—"; o relatório lista o que falta e não decide |
| Perda em pp só com WDL de todos | Sempre em pp: WDL, senão avaliação do motor, senão perda + "Aval. melhor" (curva do Lichess) |
| Faixas "excelente/boa" sem regra | Dentro da MI (1 pp) livre; além dela paga λ = 1 ATP por pp; teto de 3 pp |
| Estrutura no FO e na Robustez; Urgência e Baixo compromisso fora do ATP | Cada critério entra em um só agregado |
| TOP votava junto com MA | Cadeia fixa: Pareto → maior U → empate (< τ 0,55) → MA de Savage → menor perda; TOP só audita |
| IFE por faixas de margem | IFE = Φ(margem/σ) em letra e % |
| — | Tela TF × Conversão (limiar p*) |
| — | Saídas "Melhor WDL" e "Mais forçante"; sugestão de Reversibilidade/Forçamento pelo lance importado |

## Fórmulas

- FO = 0,30·Forçamento + 0,20·Urgência + 0,30·Atividade + 0,20·Eficiência
- Flexibilidade = média(Reversibilidade, Baixo compromisso)
- Robustez = 0,40·Estrutura + 0,30·Valor de opção + 0,30·Flexibilidade
- ATP = 0,40·FO + 0,30·FC + 0,20·Robustez + 0,10·Assimetria (inalterada)
- E = W + D/2 (WDL) ou E = 100 / (1 + e^(−0,00368208·cp))
- U = ATP − λ·max(0, Δ − MI), com Δ ≤ MI + 2 pp
- τ = desvio da diferença de ATP com ruído de 1 ponto por nota ≈ 0,55
- MA (Savage): maior distância até o melhor valor em FO, FC, Robustez e Assimetria; vence o menor
- IFE = Φ((U₁ − U₂)/τ): A+ ≥ 98%, A ≥ 93%, B ≥ 85%, C ≥ 70%, D abaixo
- TF × Conversão: p* = (E_tranq − E_falha) / (E_fim − E_falha); a TF vale se p > p*

| Faixa | Perda perto de 0,00 | Papel |
|---|---|---|
| Equivalente | ≤ 1 pp | livre (MI) |
| Excelente | ≤ 2 pp | paga λ |
| Boa | ≤ 3 pp | paga λ (teto) |
| Inferior / descartar | > 3 pp | eliminado |

Valores de λ, teto, τ e pesos ficam no topo de `hed_core.py`; revisar só com 30–50 posições no Registro (RP).

## Registro (PR / CC / AC / RP)

Após analisar: **Registrar** → estrutura, lance jogado, resultado (pode preencher depois tocando na linha).

- **PR**: % de vezes que seguiu o HED e pontos seguindo × desviando
- **CC**: o mesmo, por estrutura
- **AC**: alerta quando você contradiz o próprio padrão (≥3 posições anteriores na estrutura)
- **RP**: só sugere rever pesos com ≥5 posições com resultado na estrutura e desvio rendendo ≥0,15 ponto a mais

Pesos e limites ficam no topo de 'hed_core.py'.
