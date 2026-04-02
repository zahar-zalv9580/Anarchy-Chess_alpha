import random
from modules.game.board import coord_in_bounds
from modules.game.pieces import Piece, apply_piece_type, piece_size

STANDARD_PIECES = ["pawn", "knight", "bishop", "rook", "queen"]


def _key(x, y):
    return f"{x},{y}"


def get_piece_pool(state):
    pool = list(STANDARD_PIECES)
    extra = getattr(state, "extra_piece_types", [])
    for p in extra:
        if p not in pool:
            pool.append(p)
    return pool


def get_cell_effect(state, x, y):
    cells = getattr(state, "chessplus_cells", None)
    if cells is None:
        return None
    if not coord_in_bounds(x, y):
        return None
    return cells[y][x]


def set_cell_effect(state, x, y, effect_id):
    if not coord_in_bounds(x, y):
        return False
    cells = getattr(state, "chessplus_cells", None)
    if cells is None:
        return False
    cells[y][x] = effect_id
    return True


def clear_cell_effect(state, x, y):
    if not coord_in_bounds(x, y):
        return False
    cells = getattr(state, "chessplus_cells", None)
    if cells is None:
        return False
    cells[y][x] = None
    return True


def find_cells(state, allow_occupied=False, allow_filled=False):
    cells = []
    grid = getattr(state, "chessplus_cells", None)
    if grid is None:
        return cells
    for y in range(8):
        for x in range(8):
            if not allow_filled and grid[y][x] is not None:
                continue
            if not allow_occupied and state.board.get_piece(x, y) is not None:
                continue
            cells.append((x, y))
    return cells


def spawn_cells(state, effect_id, count=1, allow_occupied=False, allow_filled=False):
    candidates = find_cells(state, allow_occupied=allow_occupied, allow_filled=allow_filled)
    if not candidates:
        return []
    sample = random.sample(candidates, min(count, len(candidates)))
    for x, y in sample:
        set_cell_effect(state, x, y, effect_id)
    return sample


def spawn_void(state):
    # allow on occupied cells for dramatic effect
    coords = spawn_cells(state, "void", count=1, allow_occupied=True, allow_filled=False)
    if not coords:
        return []
    x, y = coords[0]
    v = getattr(state, "chessplus_void", None)
    if v is None:
        state.chessplus_void = {"cells": [[x, y]], "next_expand": random.randint(1, 2)}
    else:
        cells = v.get("cells", [])
        if [x, y] not in cells:
            cells.append([x, y])
        v["cells"] = cells
        if not v.get("next_expand"):
            v["next_expand"] = random.randint(1, 2)
    return coords


def normalize_wall(a, b):
    ax, ay = a
    bx, by = b
    if (bx, by) < (ax, ay):
        ax, ay, bx, by = bx, by, ax, ay
    return (ax, ay, bx, by)


def wall_exists(state, a, b):
    walls = getattr(state, "chessplus_walls", [])
    if not walls:
        return False
    na = normalize_wall(a, b)
    for w in walls:
        if len(w) == 4:
            if tuple(w) == na:
                return True
        elif len(w) == 2:
            if normalize_wall(tuple(w[0]), tuple(w[1])) == na:
                return True
    return False


def spawn_wall(state):
    walls = getattr(state, "chessplus_walls", None)
    if walls is None:
        state.chessplus_walls = []
        walls = state.chessplus_walls
    candidates = []
    for y in range(8):
        for x in range(8):
            for dx, dy in ((1, 0), (0, 1)):
                nx, ny = x + dx, y + dy
                if not coord_in_bounds(nx, ny):
                    continue
                if wall_exists(state, (x, y), (nx, ny)):
                    continue
                candidates.append((x, y, nx, ny))
    if not candidates:
        return None
    x1, y1, x2, y2 = random.choice(candidates)
    walls.append([x1, y1, x2, y2])
    return (x1, y1, x2, y2)


def apply_pawn_mutations(state, count=2):
    pawns = []
    for y in range(8):
        for x in range(8):
            p = state.board.get_piece(x, y)
            if p and p.ptype == "pawn":
                pawns.append((x, y))
    if not pawns:
        return []
    sample = random.sample(pawns, min(count, len(pawns)))
    mutations = getattr(state, "chessplus_mutations", None)
    if mutations is None:
        state.chessplus_mutations = {}
        mutations = state.chessplus_mutations
    types = ["backstep", "longstep"]
    for x, y in sample:
        mutations[_key(x, y)] = random.choice(types)
    return sample


def mutate_piece_randomly(state, x, y):
    p = state.board.get_piece(x, y)
    if not p:
        return None
    pool = get_piece_pool(state)
    anchor = state.board.find_piece_anchor(p) if hasattr(state.board, "find_piece_anchor") else (x, y)
    if anchor is None:
        anchor = (x, y)

    filtered = []
    for t in pool:
        if t == "giant_pawn":
            size = piece_size(t)
            ax, ay = anchor
            if not coord_in_bounds(ax, ay) or not coord_in_bounds(ax + size - 1, ay + size - 1):
                continue
            ok = True
            for dy in range(size):
                for dx in range(size):
                    nx, ny = ax + dx, ay + dy
                    occ = state.board.get_piece(nx, ny)
                    if occ and occ is not p:
                        ok = False
                        break
                if not ok:
                    break
            if not ok:
                continue
        filtered.append(t)
    if not filtered:
        return None
    new_type = random.choice(filtered)
    # rebuild footprint if size changes
    state.board.clear_piece(anchor[0], anchor[1])
    apply_piece_type(p, new_type, anchor=anchor)
    state.board.place_piece(p, anchor)
    return new_type


def clone_piece(state, src, dst):
    sx, sy = src
    dx, dy = dst
    if not coord_in_bounds(dx, dy):
        return False
    p = state.board.get_piece(sx, sy)
    if not p:
        return False
    size = max(1, int(getattr(p, "size", 1)))
    if not coord_in_bounds(dx + size - 1, dy + size - 1):
        return False
    for yy in range(size):
        for xx in range(size):
            if state.board.get_piece(dx + xx, dy + yy) is not None:
                return False
    new_piece = Piece(p.ptype, p.color, size=size, anchor=(dx, dy))
    state.board.place_piece(new_piece, (dx, dy))
    return True
