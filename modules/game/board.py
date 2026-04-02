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

    def iter_piece_cells(self, piece):
        if piece is None:
            return []
        gid = getattr(piece, "gid", None)
        coords = []
        for y in range(8):
            for x in range(8):
                p = self.grid[y][x]
                if p is None:
                    continue
                if p is piece:
                    coords.append((x, y))
                elif gid is not None and getattr(p, "gid", None) == gid:
                    coords.append((x, y))
        return coords

    def find_piece_anchor(self, piece):
        anchor = getattr(piece, "anchor", None)
        if anchor is not None:
            return tuple(anchor)
        coords = self.iter_piece_cells(piece)
        if not coords:
            return None
        return min(coords)

    def clear_piece(self, x, y):
        piece = self.get_piece(x, y)
        if piece is None:
            return None
        gid = getattr(piece, "gid", None)
        for yy in range(8):
            for xx in range(8):
                p = self.grid[yy][xx]
                if p is None:
                    continue
                if p is piece:
                    self.grid[yy][xx] = None
                elif gid is not None and getattr(p, "gid", None) == gid:
                    self.grid[yy][xx] = None
        return piece

    def place_piece(self, piece, anchor):
        if piece is None:
            return False
        ax, ay = anchor
        size = max(1, int(getattr(piece, "size", 1)))
        if not coord_in_bounds(ax, ay):
            return False
        if not coord_in_bounds(ax + size - 1, ay + size - 1):
            return False
        piece.anchor = (ax, ay)
        for dy in range(size):
            for dx in range(size):
                self.set_piece(ax + dx, ay + dy, piece)
        return True

    def move_piece(self, fr, to):
        fx,fy = fr
        tx,ty = to
        piece = self.get_piece(fx,fy)
        if piece is None:
            return
        size = max(1, int(getattr(piece, "size", 1)))
        if size > 1:
            self.clear_piece(fx, fy)
            self.place_piece(piece, (tx, ty))
            return
        self.set_piece(fx,fy, None)
        # capture handled by overwrite
        self.set_piece(tx,ty, piece)
        piece.anchor = (tx, ty)
