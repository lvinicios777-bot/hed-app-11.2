#!/usr/bin/env python3
"""Lc0 falso: discorda do Stockfish (prefere lances de borda), escreve roque como e1h1
e IGNORA roque em searchmoves (para testar o cálculo forçado e o lance a lance)."""
import sys, time, threading, zlib
import chess
b = chess.Board(); mpv = 1
def lc0_uci(board, m):
    if board.is_castling(m):
        return chess.square_name(m.from_square) + ("h1" if m.to_square == chess.G1 else "a1" if m.to_square == chess.C1 else "h8" if m.to_square == chess.G8 else "a8")
    return m.uci()
def wdl(board, m):
    h = zlib.crc32((board.fen() + m.uci()).encode()) % 200
    borda = chess.square_file(m.to_square) in (0, 7)
    w = 250 + h + (150 if borda else 0); l = 200; return (w, 1000 - w - l, l)
def go(args):
    moves = list(b.legal_moves)
    if "searchmoves" in args:
        alvo = args[args.index("searchmoves") + 1:]
        moves = [m for m in moves if m.uci() in alvo and not b.is_castling(m)]
    moves.sort(key=lambda m: -wdl(b, m)[0])
    time.sleep(0.6)
    for i, m in enumerate(moves[:mpv], 1):
        w, d, l = wdl(b, m)
        print(f"info depth 5 multipv {i} score cp {w - l} wdl {w} {d} {l} nodes 1000 pv {lc0_uci(b, m)}", flush=True)
    print(f"bestmove {lc0_uci(b, moves[0]) if moves else '0000'}", flush=True)
for linha in sys.stdin:
    t = linha.split()
    if not t: continue
    if t[0] == "uci": print("id name FakeLc0\nuciok", flush=True)
    elif t[0] == "isready": print("readyok", flush=True)
    elif t[0] == "setoption" and "MultiPV" in t: mpv = int(t[-1])
    elif t[0] == "position":
        b = chess.Board(" ".join(t[2:8])) if t[1] == "fen" else chess.Board()
    elif t[0] == "go": threading.Thread(target=go, args=(t,), daemon=True).start()
    elif t[0] == "quit": break
