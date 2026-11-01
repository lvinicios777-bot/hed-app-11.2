# Motores incluídos no APK

## Lc0 (Leela Chess Zero) v0.33.0-rc0 — `liblc0.so` (arm64-v8a)

- Binário extraído, sem modificação, do APK oficial para Android da versão v0.33.0-rc0.
- Licença: GNU GPL v3. Código-fonte: https://github.com/LeelaChessZero/lc0 (tag v0.33.0-rc0).
- A rede neural NÃO está neste repositório: o jogador carrega a própria rede (ex.: LD2, `.pb.gz`)
  em Configurações → Carregar rede do Lc0; o app passa `WeightsFile` para o motor.

## Stockfish 19

- Compilado no workflow a partir do código oficial (https://github.com/official-stockfish/Stockfish, tag sf_19),
  licença GNU GPL v3.
