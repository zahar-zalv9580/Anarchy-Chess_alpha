from modules.game.board import coord_in_bounds


def _sign(v):
    return (v > 0) - (v < 0)


def _wall_between(state, fr, to):
    walls = getattr(state, "chessplus_walls", [])
    if not walls:
        return False
    ax, ay = fr
    bx, by = to
    for w in walls:
        if len(w) == 4:
            x1, y1, x2, y2 = w
        elif len(w) == 2:
            (x1, y1), (x2, y2) = w
        else:
            continue
        if (x1, y1) == (ax, ay) and (x2, y2) == (bx, by):
            return True
        if (x2, y2) == (ax, ay) and (x1, y1) == (bx, by):
            return True
    return False


def _clear_path(state, fr, to):
    fx, fy = fr
    tx, ty = to
    dx = _sign(tx - fx)
    dy = _sign(ty - fy)
    x = fx + dx
    y = fy + dy
    while (x, y) != (tx, ty):
        if _wall_between(state, (x - dx, y - dy), (x, y)):
            return False
        if state.board.get_piece(x, y) is not None:
            return False
        x += dx
        y += dy
    if _wall_between(state, (tx - dx, ty - dy), (tx, ty)):
        return False
    return True


def validate_move(state, fr, to, color):
    if not coord_in_bounds(*fr) or not coord_in_bounds(*to):
        return False, "out_of_bounds"
    if fr == to:
        return False, "same_square"
    piece = state.board.get_piece(*fr)
    if piece is None:
        return False, "no_piece"
    if piece.color != color:
        return False, "not_your_piece"
    dest = state.board.get_piece(*to)
    if dest and dest.color == color:
        return False, "dest_occupied"

    dx = to[0] - fr[0]
    dy = to[1] - fr[1]
    adx = abs(dx)
    ady = abs(dy)

    if piece.ptype == "pawn":
        direction = 1 if color == "white" else -1
        start_rank = 1 if color == "white" else 6
        # forward move
        if dx == 0 and dy == direction and dest is None:
            if _wall_between(state, fr, to):
                return False, "blocked"
            return True, None
        # double move from start
        if dx == 0 and dy == 2 * direction and fr[1] == start_rank and dest is None:
            mid = (fr[0], fr[1] + direction)
            if state.board.get_piece(*mid) is None:
                if _wall_between(state, fr, mid) or _wall_between(state, mid, to):
                    return False, "blocked"
                return True, None
            return False, "blocked"
        # capture
        if adx == 1 and dy == direction and dest is not None and dest.color != color:
            if _wall_between(state, fr, to):
                return False, "blocked"
            return True, None
        # pawn mutations (Chess+)
        mutations = getattr(state, "chessplus_mutations", {})
        mut = mutations.get(f"{fr[0]},{fr[1]}") if mutations else None
        if mut == "backstep":
            if dx == 0 and dy == -direction and dest is None:
                if _wall_between(state, fr, to):
                    return False, "blocked"
                return True, None
        if mut == "longstep":
            if dx == 0 and dy == 2 * direction and dest is None:
                mid = (fr[0], fr[1] + direction)
                if state.board.get_piece(*mid) is None:
                    if _wall_between(state, fr, mid) or _wall_between(state, mid, to):
                        return False, "blocked"
                    return True, None
        return False, "illegal_pawn_move"

    if piece.ptype == "knight":
        if (adx, ady) in ((1, 2), (2, 1)):
            return True, None
        return False, "illegal_knight_move"

    if piece.ptype == "bishop":
        if adx == ady and _clear_path(state, fr, to):
            return True, None
        return False, "illegal_bishop_move"

    if piece.ptype == "rook":
        if (dx == 0 or dy == 0) and _clear_path(state, fr, to):
            return True, None
        return False, "illegal_rook_move"

    if piece.ptype == "queen":
        if ((dx == 0 or dy == 0) or (adx == ady)) and _clear_path(state, fr, to):
            return True, None
        return False, "illegal_queen_move"

    if piece.ptype == "king":
        if adx <= 1 and ady <= 1:
            if _wall_between(state, fr, to):
                return False, "blocked"
            return True, None
        return False, "illegal_king_move"

    return False, "illegal_move"


def apply_move(state, fr, to):
    piece = state.board.get_piece(*fr)
    captured = state.board.get_piece(*to)
    state.board.move_piece(fr, to)

    promotion = False
    if piece and piece.ptype == "pawn":
        promotion_rank = 7 if piece.color == "white" else 0
        if to[1] == promotion_rank:
            piece.ptype = "queen"
            piece.is_royal = True
            promotion = True

    return captured, promotion


def has_king(state, color):
    for y in range(8):
        for x in range(8):
            p = state.board.get_piece(x, y)
            if p and p.color == color and p.ptype == "king":
                return True
    return False
