import copy
from modules.game.board import Board
from modules.game.pieces import starting_setup
import time

class GameState:
    def __init__(self):
        self.board = Board()
        self.turn = 'white'
        self.move_history = []
        self.move_count = 0
        self.game_id = 0
        self.players = {"white": None, "black": None}
        self.mines = [[0]*8 for _ in range(8)]
        self.revealed = [[0]*8 for _ in range(8)]
        self.adj_counts = [[0]*8 for _ in range(8)]
        self.active_dlc = {}  # e.g. {'minesweeper': {'active':True,'turns_alive':0}}
        self.timer = {'white_ms': 10*60*1000, 'black_ms': 10*60*1000, 'match_ms': 10*60*1000, 'match_running': False}
        self.royal_counts = {'white':2, 'black':2}
        self.craters = set()  # set of (x,y) where explosion occured
        self.dlc_packs = []
        self.inventory = {"white": [None]*9, "black": [None]*9}
        self.temp_reveal = {"cells": [], "remaining_moves": 0}
        self.mine_vision = {"white": 0, "black": 0}
        self.chessplus_cells = [[None]*8 for _ in range(8)]
        self.chessplus_bombs = {}
        self.chessplus_burning = {}
        self.chessplus_void = {"cells": [], "next_expand": 0}
        self.chessplus_walls = []
        self.chessplus_mutations = {}
        self.chessplus_clones = {}
        self.chessplus_nukes = []
        self.nuke_event_id = 0
        self.chaos = 0
        self.extra_piece_types = []

    def setup_starting_position(self):
        starting_setup(self.board)

    def to_dict(self):
        # minimal serialization
        board_serial = []
        for y in range(8):
            row = []
            for x in range(8):
                p = self.board.get_piece(x,y)
                if p:
                    cell = {"ptype": p.ptype, "color": p.color}
                    gid = getattr(p, "gid", None)
                    if gid is not None:
                        cell["gid"] = gid
                    size = getattr(p, "size", None)
                    if size is not None and int(size) > 1:
                        cell["size"] = int(size)
                    anchor = getattr(p, "anchor", None)
                    if anchor is not None:
                        cell["anchor"] = [int(anchor[0]), int(anchor[1])]
                    row.append(cell)
                else:
                    row.append(None)
            board_serial.append(row)
        return {
            "turn": self.turn,
            "move_count": self.move_count,
            "game_id": self.game_id,
            "players": self.players,
            "board": board_serial,
            "mines": self.mines,
            "revealed": self.revealed,
            "adj_counts": self.adj_counts,
            "active_dlc": self.active_dlc,
            "timer": self.timer,
            "royal_counts": self.royal_counts,
            "craters": [[x, y] for (x, y) in self.craters],
            "dlc_packs": self.dlc_packs,
            "inventory": self.inventory,
            "temp_reveal": self.temp_reveal,
            "mine_vision": self.mine_vision,
            "chessplus_cells": self.chessplus_cells,
            "chessplus_bombs": self.chessplus_bombs,
            "chessplus_burning": self.chessplus_burning,
            "chessplus_void": self.chessplus_void,
            "chessplus_walls": self.chessplus_walls,
            "chessplus_mutations": self.chessplus_mutations,
            "chessplus_clones": self.chessplus_clones,
            "chessplus_nukes": self.chessplus_nukes,
            "nuke_event_id": self.nuke_event_id,
            "chaos": self.chaos,
            "extra_piece_types": self.extra_piece_types,
        }

    @staticmethod
    def from_dict(d):
        s = GameState()
        s.turn = d.get('turn','white')
        s.move_count = d.get('move_count', 0)
        s.game_id = d.get('game_id', 0)
        s.players = d.get('players', {"white": None, "black": None})
        # board
        b = d.get('board', [])
        pieces_by_gid = {}
        for y in range(8):
            for x in range(8):
                cell = b[y][x]
                if cell:
                    from modules.game.pieces import Piece
                    gid = cell.get("gid") if isinstance(cell, dict) else None
                    if gid is not None and gid in pieces_by_gid:
                        p = pieces_by_gid[gid]
                    else:
                        p = Piece(
                            cell.get("ptype"),
                            cell.get("color"),
                            pid=gid,
                            size=cell.get("size"),
                            anchor=cell.get("anchor"),
                        )
                        if gid is not None:
                            pieces_by_gid[gid] = p
                    s.board.set_piece(x, y, p)
        s.mines = d.get('mines', [[0]*8 for _ in range(8)])
        s.revealed = d.get('revealed', [[0]*8 for _ in range(8)])
        s.adj_counts = d.get('adj_counts', [[0]*8 for _ in range(8)])
        s.active_dlc = d.get('active_dlc', {})
        s.timer = d.get('timer', {'white_ms':600000,'black_ms':600000,'match_ms':600000,'match_running': False})
        s.royal_counts = d.get('royal_counts', {'white':2,'black':2})
        s.craters = set(tuple(p) for p in d.get('craters', []))
        s.dlc_packs = d.get('dlc_packs', [])
        s.inventory = d.get('inventory', {"white":[None]*9, "black":[None]*9})
        s.temp_reveal = d.get('temp_reveal', {"cells": [], "remaining_moves": 0})
        s.mine_vision = d.get('mine_vision', {"white": 0, "black": 0})
        s.chessplus_cells = d.get('chessplus_cells', [[None]*8 for _ in range(8)])
        s.chessplus_bombs = d.get('chessplus_bombs', {})
        s.chessplus_burning = d.get('chessplus_burning', {})
        s.chessplus_void = d.get('chessplus_void', {"cells": [], "next_expand": 0})
        s.chessplus_walls = d.get('chessplus_walls', [])
        s.chessplus_mutations = d.get('chessplus_mutations', {})
        s.chessplus_clones = d.get('chessplus_clones', {})
        s.chessplus_nukes = d.get('chessplus_nukes', [])
        s.nuke_event_id = d.get('nuke_event_id', 0)
        s.chaos = d.get('chaos', 0)
        s.extra_piece_types = d.get('extra_piece_types', [])
        return s
