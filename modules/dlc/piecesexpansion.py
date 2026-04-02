import random
from modules.game.board import coord_in_bounds
from modules.game.pieces import Piece, apply_piece_type, piece_size
from modules.dlc.chessplus import get_piece_pool

PIECE_TYPES = ["amazon", "archbishop", "camel", "giant_pawn"]
PIECE_NAMES = {
    "amazon": "Амазон",
    "archbishop": "Архієпископ",
    "camel": "Верблюд",
    "giant_pawn": "Гігантська пішака",
    "pawn": "Пішак",
    "knight": "Кінь",
    "bishop": "Слон",
    "rook": "Тура",
    "queen": "Ферзь",
}


def piece_display_name(ptype):
    return PIECE_NAMES.get(ptype, ptype)


def player_half_rows(color):
    return range(0, 4) if color == "white" else range(4, 8)


def _anchor_ok_in_half(color, anchor, size):
    ax, ay = anchor
    rows = player_half_rows(color)
    if ay not in rows:
        return False
    if ay + size - 1 not in rows:
        return False
    return True


def can_place_type(state, anchor, ptype, ignore_piece=None):
    size = piece_size(ptype)
    ax, ay = anchor
    if not coord_in_bounds(ax, ay) or not coord_in_bounds(ax + size - 1, ay + size - 1):
        return False
    for dy in range(size):
        for dx in range(size):
            nx, ny = ax + dx, ay + dy
            occ = state.board.get_piece(nx, ny)
            if occ and occ is not ignore_piece:
                return False
    return True


def available_anchors(state, color, size):
    anchors = []
    rows = player_half_rows(color)
    for y in rows:
        if y + size - 1 not in rows:
            continue
        for x in range(0, 8 - size + 1):
            ok = True
            for dy in range(size):
                for dx in range(size):
                    if state.board.get_piece(x + dx, y + dy) is not None:
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                anchors.append((x, y))
    return anchors


def spawn_random_piece(state, color):
    pool = list(get_piece_pool(state))
    random.shuffle(pool)
    for ptype in pool:
        size = piece_size(ptype)
        anchors = available_anchors(state, color, size)
        if not anchors:
            continue
        anchor = random.choice(anchors)
        piece = Piece(ptype, color, size=size, anchor=anchor)
        state.board.place_piece(piece, anchor)
        return {"ptype": ptype, "color": color, "pos": anchor}
    return None


def change_random_piece(state):
    candidates = []
    seen = set()
    for y in range(8):
        for x in range(8):
            p = state.board.get_piece(x, y)
            if not p or p.is_royal:
                continue
            key = getattr(p, "gid", None)
            if key is None:
                key = id(p)
            if key in seen:
                continue
            seen.add(key)
            anchor = state.board.find_piece_anchor(p) if hasattr(state.board, "find_piece_anchor") else (x, y)
            if anchor is None:
                anchor = (x, y)
            candidates.append((p, anchor))
    if not candidates:
        return None
    piece, anchor = random.choice(candidates)
    color = piece.color
    old_type = piece.ptype
    pool = list(get_piece_pool(state))
    if piece.ptype in pool and len(pool) > 1:
        pool = [p for p in pool if p != piece.ptype]
    random.shuffle(pool)
    new_type = None
    for ptype in pool:
        if ptype == "giant_pawn" and not can_place_type(state, anchor, ptype, ignore_piece=piece):
            continue
        new_type = ptype
        break
    if not new_type:
        return None
    state.board.clear_piece(anchor[0], anchor[1])
    apply_piece_type(piece, new_type, anchor=anchor)
    state.board.place_piece(piece, anchor)
    return {"from": old_type, "to": new_type, "color": color, "pos": anchor}
