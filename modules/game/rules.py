from modules.game.board import coord_in_bounds


def _sign(v):
    return (v > 0) - (v < 0)


def _piece_anchor(state, piece, fr):
    anchor = getattr(piece, "anchor", None)
    if anchor is not None:
        return tuple(anchor)
    if hasattr(state, "board") and hasattr(state.board, "find_piece_anchor"):
        found = state.board.find_piece_anchor(piece)
        if found is not None:
            return found
    return fr


def _giant_footprint(anchor):
    ax, ay = anchor
    return [(ax + dx, ay + dy) for dy in range(2) for dx in range(2)]


def _giant_wall_blocked(state, fr, to, direction):
    # check walls across the leading edge (between the current front row and the next row)
    ax, ay = fr
    edge_y = ay + (1 if direction == 1 else 0)
    next_y = edge_y + direction
    for col in (to[0], to[0] + 1):
        if _wall_between(state, (col, edge_y), (col, next_y)):
            return True
    return False


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
    anchor = _piece_anchor(state, piece, fr)
    if getattr(piece, "size", 1) > 1:
        fr = anchor

    if piece.ptype == "giant_pawn":
        if not coord_in_bounds(to[0], to[1]) or not coord_in_bounds(to[0] + 1, to[1] + 1):
            return False, "out_of_bounds"
        dx = to[0] - fr[0]
        dy = to[1] - fr[1]
        direction = 1 if color == "white" else -1
        if dy != 2 * direction or abs(dx) > 1:
            return False, "illegal_giant_move"
        if _giant_wall_blocked(state, fr, to, direction):
            return False, "blocked"
        dest_cells = _giant_footprint(to)
        if abs(dx) == 1:
            has_enemy = False
            for x, y in dest_cells:
                p = state.board.get_piece(x, y)
                if p:
                    if p.color == color:
                        return False, "dest_occupied"
                    has_enemy = True
            if not has_enemy:
                return False, "illegal_giant_capture"
        return True, None

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

    if piece.ptype == "amazon":
        if (adx, ady) in ((1, 2), (2, 1)):
            return True, None
        if ((dx == 0 or dy == 0) or (adx == ady)) and _clear_path(state, fr, to):
            return True, None
        return False, "illegal_amazon_move"

    if piece.ptype == "archbishop":
        if (adx, ady) in ((1, 2), (2, 1)):
            return True, None
        if adx == ady and _clear_path(state, fr, to):
            return True, None
        return False, "illegal_archbishop_move"

    if piece.ptype == "camel":
        if (adx, ady) in ((1, 3), (3, 1)):
            return True, None
        return False, "illegal_camel_move"

    if piece.ptype == "king":
        if adx <= 1 and ady <= 1:
            if _wall_between(state, fr, to):
                return False, "blocked"
            return True, None
        return False, "illegal_king_move"

    return False, "illegal_move"


def apply_move(state, fr, to):
    piece = state.board.get_piece(*fr)
    if piece is None:
        return [], False

    anchor = _piece_anchor(state, piece, fr)
    if getattr(piece, "size", 1) > 1:
        fr = anchor

    captured_positions = []

    def _move_mapping(mapping, frm, dst):
        if not mapping:
            return
        kf = f"{frm[0]},{frm[1]}"
        if kf in mapping:
            kt = f"{dst[0]},{dst[1]}"
            mapping[kt] = mapping.pop(kf)

    if piece.ptype == "giant_pawn":
        dx = to[0] - fr[0]
        dy = to[1] - fr[1]
        direction = 1 if piece.color == "white" else -1
        dest_cells = _giant_footprint(to)

        if dx == 0 and dy == 2 * direction:
            # trample: push pieces sideways if possible, otherwise capture
            for (x, y) in dest_cells:
                occ = state.board.get_piece(x, y)
                if not occ or occ is piece:
                    continue
                if getattr(occ, "size", 1) > 1:
                    state.board.clear_piece(x, y)
                    captured_positions.append((x, y))
                    continue
                push_x = x - 1 if x == to[0] else x + 1
                push_y = y
                if coord_in_bounds(push_x, push_y) and state.board.get_piece(push_x, push_y) is None:
                    state.board.set_piece(x, y, None)
                    state.board.set_piece(push_x, push_y, occ)
                    occ.anchor = (push_x, push_y)
                    _move_mapping(getattr(state, "chessplus_mutations", None), (x, y), (push_x, push_y))
                    _move_mapping(getattr(state, "chessplus_clones", None), (x, y), (push_x, push_y))
                else:
                    state.board.clear_piece(x, y)
                    captured_positions.append((x, y))
            state.board.clear_piece(fr[0], fr[1])
            state.board.place_piece(piece, to)
            return captured_positions, False

        if abs(dx) == 1 and dy == 2 * direction:
            for (x, y) in dest_cells:
                occ = state.board.get_piece(x, y)
                if occ and occ is not piece and occ.color != piece.color:
                    state.board.clear_piece(x, y)
                    captured_positions.append((x, y))
            state.board.clear_piece(fr[0], fr[1])
            state.board.place_piece(piece, to)
            return captured_positions, False

    captured = state.board.get_piece(*to)
    if captured:
        captured_positions = [to]
    state.board.move_piece(fr, to)

    promotion = False
    if piece and piece.ptype == "pawn":
        promotion_rank = 7 if piece.color == "white" else 0
        if to[1] == promotion_rank:
            piece.ptype = "queen"
            piece.is_royal = True
            if piece.color in state.royal_counts:
                state.royal_counts[piece.color] += 1
            promotion = True

    return captured_positions, promotion


def has_king(state, color):
    for y in range(8):
        for x in range(8):
            p = state.board.get_piece(x, y)
            if p and p.color == color and p.ptype == "king":
                return True
    return False
