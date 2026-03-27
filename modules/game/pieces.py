import itertools

class Piece:
    def __init__(self, ptype, color, pid=None):
        self.ptype = ptype  
        self.color = color
        self.id = pid
        self.is_royal = (ptype in ('king','queen'))


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
