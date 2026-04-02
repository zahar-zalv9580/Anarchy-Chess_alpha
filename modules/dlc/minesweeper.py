import random
from collections import deque
from modules.game.board import coord_in_bounds

MINES_DEFAULT = 8

def count_adjacent(x,y,mines):
    c = 0
    for nx in range(x-1, x+2):
        for ny in range(y-1, y+2):
            if nx==x and ny==y: continue
            if 0 <= nx < 8 and 0 <= ny < 8:
                if mines[ny][nx] == 1:
                    c += 1
    return c

def compute_adj_counts(state):
    for y in range(8):
        for x in range(8):
            state.adj_counts[y][x] = count_adjacent(x,y,state.mines)

def add_temp_reveal(state, cells, duration_moves=2):
    if not cells:
        return
    temp = getattr(state, "temp_reveal", None)
    if not isinstance(temp, dict):
        state.temp_reveal = {"cells": [], "remaining_moves": duration_moves}
        temp = state.temp_reveal
    existing = set(tuple(c) for c in temp.get("cells", []))
    for x, y in cells:
        existing.add((x, y))
    temp["cells"] = [[x, y] for (x, y) in existing]
    temp["remaining_moves"] = max(int(temp.get("remaining_moves", 0)), duration_moves)


def reveal_numbers_under_pieces(state, duration_moves=2):
    revealed = []
    for y in range(8):
        for x in range(8):
            piece = state.board.get_piece(x, y)
            if not piece:
                continue
            if state.mines[y][x] == 0 and state.adj_counts[y][x] > 0 and state.revealed[y][x] == 0:
                revealed.append((x, y))
    add_temp_reveal(state, revealed, duration_moves=duration_moves)
    return revealed

def clear_reveal_on_mine(state, x, y):
    state.revealed[y][x] = 0
    temp = getattr(state, "temp_reveal", None)
    if temp and temp.get("cells"):
        temp["cells"] = [c for c in temp["cells"] if c != [x, y]]

def place_mine(state, x, y):
    if not coord_in_bounds(x, y):
        return False
    if state.board.get_piece(x, y) is not None:
        return False
    if state.mines[y][x] == 1:
        return False
    state.mines[y][x] = 1
    clear_reveal_on_mine(state, x, y)
    compute_adj_counts(state)
    reveal_numbers_under_pieces(state, duration_moves=2)
    return True

def spawn_mines(state, count=MINES_DEFAULT):
    # choose only empty cells (no piece)
    empty = [(x,y) for x in range(8) for y in range(8) if state.board.get_piece(x,y) is None and state.mines[y][x] == 0]
    sample = random.sample(empty, min(count, len(empty)))
    for x,y in sample:
        state.mines[y][x] = 1
        clear_reveal_on_mine(state, x, y)
    compute_adj_counts(state)
    reveal_numbers_under_pieces(state, duration_moves=2)
    return sample

def reveal_numbers(state):
    for y in range(8):
        for x in range(8):
            if state.mines[y][x] == 0:
                state.revealed[y][x] = 1

def temp_reveal_numbers(state, percent=0.5, duration_moves=2):
    candidates = []
    for y in range(8):
        for x in range(8):
            if state.mines[y][x] == 0 and state.adj_counts[y][x] > 0:
                candidates.append((x, y))
    if not candidates:
        state.temp_reveal = {"cells": [], "remaining_moves": 0}
        return []
    count = max(1, int(len(candidates) * percent))
    sample = random.sample(candidates, min(count, len(candidates)))
    state.temp_reveal = {"cells": [[x, y] for (x, y) in sample], "remaining_moves": duration_moves}
    return sample

def reveal_cell(state, x, y):
    """Reveal cell when a player steps on it (called after move).
    If there's a mine -> triggers explosion; else reveals adjacent number."""
    if not coord_in_bounds(x,y): return
    state.revealed[y][x] = 1
    if state.mines[y][x] == 1:
        trigger_mine(state, x, y)


def trigger_mine(state, x, y):
    """3x3 explosion centered on (x,y). Chain reaction: if other mine in radius -> add to queue."""
    q = deque()
    q.append((x,y))
    exploded = set()
    removed = set()
    while q:
        cx, cy = q.popleft()
        if (cx,cy) in exploded: 
            continue
        exploded.add((cx,cy))
        # apply 3x3 damage
        for nx in range(cx-1, cx+2):
            for ny in range(cy-1, cy+2):
                if 0 <= nx < 8 and 0 <= ny < 8:
                    piece = state.board.get_piece(nx, ny)
                    if piece:
                        gid = getattr(piece, "gid", None)
                        key = gid if gid is not None else id(piece)
                        if key in removed:
                            continue
                        removed.add(key)
                        # if piece is royal adjust counts
                        if piece.is_royal:
                            if piece.color in state.royal_counts:
                                state.royal_counts[piece.color] -= 1
                        # remove piece
                        if hasattr(state.board, "clear_piece"):
                            state.board.clear_piece(nx, ny)
                        else:
                            state.board.set_piece(nx, ny, None)
        # chain: add adjacent mines (including diagonals)
        for nx in range(cx-1, cx+2):
            for ny in range(cy-1, cy+2):
                if 0 <= nx < 8 and 0 <= ny < 8:
                    if state.mines[ny][nx] == 1 and (nx,ny) not in exploded:
                        q.append((nx,ny))
        # remove mine marker
        if 0 <= cx < 8 and 0 <= cy < 8:
            state.mines[cy][cx] = 0
    # record craters for UI visuals
    for (ex,ey) in exploded:
        state.craters.add((ex,ey))
    # recompute adjacent counts
    compute_adj_counts(state)
