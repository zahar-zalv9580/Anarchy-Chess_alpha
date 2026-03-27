from modules.game.pieces import Piece

def coord_in_bounds(x,y):
    return 0 <= x < 8 and 0 <= y < 8

def coord_for_pixel(mx,my, board_origin, cell):
    bx,by = board_origin
    if mx < bx or my < by: return None
    rx = mx - bx
    ry = my - by
    if rx >= cell*8 or ry >= cell*8: return None
    return (rx // cell, ry // cell)

class Cell:
    def __init__(self):
        self.piece = None

class Board:
    def __init__(self):
        self.grid = [[None for _ in range(8)] for _ in range(8)]

    def get_piece(self, x,y):
        if not coord_in_bounds(x,y): return None
        return self.grid[y][x]

    def set_piece(self, x,y, piece):
        if not coord_in_bounds(x,y): return
        self.grid[y][x] = piece

    def move_piece(self, fr, to):
        fx,fy = fr
        tx,ty = to
        piece = self.get_piece(fx,fy)
        self.set_piece(fx,fy, None)
        # capture handled by overwrite
        self.set_piece(tx,ty, piece)
