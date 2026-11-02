#!/usr/bin/env bash
# Testes de tela do HED (Kivy sob xvfb). Uso: HED_STOCKFISH=/caminho/stockfish tests/rodar.sh
set -u
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
SAIDA="${SAIDA:-$RAIZ/tests/saida}"
mkdir -p "$SAIDA" "$SAIDA/home/.config"
export HOME="$SAIDA/home"
LC0_FALSO="$RAIZ/tests/fake_lc0.py"
chmod +x "$LC0_FALSO"
falhas=0
rodar() {   # nome, lc0, comando...
  local nome="$1" lc0="$2"; shift 2
  echo "::group::$nome"
  if HED_LC0="$lc0" timeout 420 xvfb-run -a -s "-screen 0 412x860x24" python3 "$@" > "$SAIDA/$nome.log" 2>&1; then
    echo "OK  $nome"
  else
    echo "FALHOU  $nome"; tail -40 "$SAIDA/$nome.log"; falhas=$((falhas + 1))
  fi
  echo "::endgroup::"
}
rodar ui        ""            "$RAIZ/tests/teste_ui.py"      "$RAIZ" "$SAIDA"
rodar fluxo     ""            "$RAIZ/tests/teste_ui2.py"     "$RAIZ" "$SAIDA"
rodar resumo    "$HED_STOCKFISH" "$RAIZ/tests/teste_resumo.py" "$RAIZ" "$SAIDA"
rodar vivo      "$LC0_FALSO"  "$RAIZ/tests/teste_vivo2.py"   "$RAIZ" "$SAIDA"
rodar classe    "$LC0_FALSO"  "$RAIZ/tests/teste_classe.py"  "$RAIZ" "$SAIDA"
rodar revisao   "$LC0_FALSO"  "$RAIZ/tests/teste_revisao.py" "$RAIZ" "$SAIDA" Stockfish
echo "Falhas: $falhas"
exit $falhas
