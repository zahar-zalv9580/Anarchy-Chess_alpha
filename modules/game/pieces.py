ROYAL_TYPES = {"king", "queen", "amazon"}
PIECE_SIZES = {"giant_pawn": 2}


def piece_size(ptype):
    return PIECE_SIZES.get(ptype, 1)


def is_royal_type(ptype):
    return ptype in ROYAL_TYPES


def apply_piece_type(piece, ptype, anchor=None):
    piece.ptype = ptype
    piece.is_royal = is_royal_type(ptype)
    piece.size = piece_size(ptype)
    if anchor is not None:
        piece.anchor = tuple(anchor)
    elif piece.size == 1:
        piece.anchor = piece.anchor or None


_gid_next = 1


def _next_gid():
    global _gid_next
    gid = _gid_next
    _gid_next += 1
    return gid


def ensure_gid_at_least(value):
    global _gid_next
    try:
        v = int(value)
    except Exception:
        return
    if v >= _gid_next:
        _gid_next = v + 1


class Piece:
    def __init__(self, ptype, color, pid=None, size=None, anchor=None):
        self.ptype = ptype
        self.color = color
        self.gid = _next_gid() if pid is None else pid
        if pid is not None:
            ensure_gid_at_least(pid)
        self.id = self.gid
        self.size = piece_size(ptype) if size is None else size
        self.anchor = tuple(anchor) if anchor is not None else None
        self.is_royal = is_royal_type(ptype)


def starting_setup(board):
    # place pawns
    for x in range(8):
        board.set_piece(x,1, Piece('pawn','white'))
        board.set_piece(x,6, Piece('pawn','black'))
    # rooks
    board.set_piece(0,0, Piece('rook','white'))
    board.set_piece(7,0, Piece('rook','white'))
    board.set_piece(0,7, Piece('rook','black'))
    board.set_piece(7,7, Piece('rook','black'))
    # knights
    board.set_piece(1,0, Piece('knight','white'))
    board.set_piece(6,0, Piece('knight','white'))
    board.set_piece(1,7, Piece('knight','black'))
    board.set_piece(6,7, Piece('knight','black'))
    # bishops
    board.set_piece(2,0, Piece('bishop','white'))
    board.set_piece(5,0, Piece('bishop','white'))
    board.set_piece(2,7, Piece('bishop','black'))
    board.set_piece(5,7, Piece('bishop','black'))
    # queens and kings
    board.set_piece(3,0, Piece('king','white'))
    board.set_piece(4,0, Piece('queen','white'))
    board.set_piece(3,7, Piece('king','black'))
    board.set_piece(4,7, Piece('queen','black'))
