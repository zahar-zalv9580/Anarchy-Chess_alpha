import socket, threading, json, time, sys, random
from pathlib import Path

# Allow running this file directly without "python -m".
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from modules.game.state import GameState
from modules.game.rules import validate_move, apply_move
from modules.dlc.minesweeper import reveal_cell, trigger_mine, place_mine
from modules.dlc.chessplus import mutate_piece_randomly, clone_piece
from modules.dlc.packs import (
    PACK_DEFS,
    build_pack_states,
    activate_pack,
    choose_effect,
    make_item,
    apply_effect,
    get_pack_def,
)
import settings as cfg

HOST = cfg.SERVER_HOST
PORT = cfg.SERVER_PORT
GAME_DATA_PATH = PROJECT_ROOT / "data" / "game.json"
MATCH_LOG_DIR = PROJECT_ROOT / "data" / "match_logs"

def load_game_id():
    if not GAME_DATA_PATH.exists():
        save_game_id(0)
        return 0
    try:
        with GAME_DATA_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return int(data.get("game_id", 0))
    except Exception:
        return 0

def save_game_id(game_id):
    GAME_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with GAME_DATA_PATH.open("w", encoding="utf-8") as f:
        json.dump({"game_id": game_id}, f, ensure_ascii=False, indent=2)

def count_royals(state):
    counts = {"white": 0, "black": 0}
    seen = set()
    for y in range(8):
        for x in range(8):
            p = state.board.get_piece(x, y)
            if p and p.ptype in cfg.ROYAL_TYPES:
                key = getattr(p, "gid", None)
                if key is None:
                    key = id(p)
                if key in seen:
                    continue
                seen.add(key)
                counts[p.color] += 1
    return counts

def material_score(state, color):
    score = 0
    seen = set()
    for y in range(8):
        for x in range(8):
            p = state.board.get_piece(x, y)
            if p and p.color == color:
                key = getattr(p, "gid", None)
                if key is None:
                    key = id(p)
                if key in seen:
                    continue
                seen.add(key)
                score += cfg.PIECE_VALUES.get(p.ptype, 0)
    return score

def evaluate_timer_winner(state):
    royals = count_royals(state)
    if royals["white"] != royals["black"]:
        winner = "white" if royals["white"] > royals["black"] else "black"
        return winner, "timer_royal"
    white_mat = material_score(state, "white")
    black_mat = material_score(state, "black")
    if white_mat != black_mat:
        winner = "white" if white_mat > black_mat else "black"
        return winner, "timer_material"
    return random.choice(["white", "black"]), "timer_random"

def check_royal_elimination(state):
    royals = count_royals(state)
    if royals["white"] == 0 and royals["black"] == 0:
        return random.choice(["white", "black"]), "royal_both"
    if royals["white"] == 0:
        return "black", "royal_captured"
    if royals["black"] == 0:
        return "white", "royal_captured"
    return None, None

def send_json(conn, obj):
    data = json.dumps(obj).encode('utf-8')
    conn.sendall(len(data).to_bytes(4, 'big') + data)

def recv_json(conn):
    # receive 4-byte length then payload
    length_bytes = conn.recv(4)
    if not length_bytes:
        return None
    length = int.from_bytes(length_bytes, 'big')
    data = b''
    while len(data) < length:
        chunk = conn.recv(length - len(data))
        if not chunk:
            return None
        data += chunk
    return json.loads(data.decode('utf-8'))

class Room:
    def __init__(self):
        self.clients = []  # list of (conn, addr, name, color)
        self.lock = threading.Lock()
        self.state = GameState()
        self.move_count = 0
        self.running = False
        self.match_start_time = None
        self.timer_thread = None
        self.enabled_pack_ids = [p.get("id") for p in PACK_DEFS]
        self.pack_defs = [p for p in PACK_DEFS]
        self.pack_def_by_id = {p.get("id"): p for p in self.pack_defs}
        self.next_pack_activation = 5
        self.next_pack_index = 0
        self.state.dlc_packs = build_pack_states(self.pack_defs)
        self.state.inventory = {"white": [None]*9, "black": [None]*9}
        self.log_lock = threading.Lock()
        self.match_log = None
        self.log_path = None
        self.active_move_no = None
        self.active_move_info = None
        self.last_move_info = None
        self.pending_log_entries = []
        self.pending_pack_events = []
        self.pending_event_summaries = []
        self.pending_chaos = None

    def coord_to_alg(self, pos):
        if pos is None:
            return "??"
        x, y = pos
        if not (0 <= x < 8 and 0 <= y < 8):
            return f"{x},{y}"
        return f"{chr(ord('a') + x)}{y + 1}"

    def piece_short(self, piece):
        if piece is None:
            return "??"
        letters = {
            "pawn": "P",
            "knight": "N",
            "bishop": "B",
            "rook": "R",
            "queen": "Q",
            "king": "K",
            "amazon": "A",
            "archbishop": "H",
            "camel": "C",
            "giant_pawn": "G",
        }
        return f"{piece.color[0]}{letters.get(piece.ptype, piece.ptype[:1].upper())}"

    def piece_ref(self, pos, piece=None):
        if piece is None and pos is not None:
            piece = self.state.board.get_piece(pos[0], pos[1])
        if piece is None:
            return self.coord_to_alg(pos)
        return f"{self.piece_short(piece)}@{self.coord_to_alg(pos)}"

    def init_match_log(self):
        MATCH_LOG_DIR.mkdir(parents=True, exist_ok=True)
        game_id = int(self.state.game_id or 0)
        self.log_path = MATCH_LOG_DIR / f"game_{game_id}.json"
        self.match_log = {
            "game_id": game_id,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "players": dict(self.state.players),
            "events": [],
        }
        self.write_log()

    def write_log(self):
        if self.match_log is None or self.log_path is None:
            return
        with self.log_lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("w", encoding="utf-8") as f:
                json.dump(self.match_log, f, ensure_ascii=False, indent=2)

    def append_log(self, entry):
        if self.match_log is None:
            return
        entry = self.repair_strings(dict(entry))
        entry.setdefault("ts", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        if self.active_move_no is not None:
            entry.setdefault("move", self.active_move_no)
        self.match_log["events"].append(entry)
        self.write_log()

    def fix_mojibake(self, value):
        if not isinstance(value, str):
            return value
        try:
            repaired = value.encode("cp1251").decode("utf-8")
        except Exception:
            return value
        if "\ufffd" in repaired:
            return value
        return repaired if repaired != value else value

    def repair_strings(self, obj):
        if isinstance(obj, dict):
            return {k: self.repair_strings(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.repair_strings(v) for v in obj]
        if isinstance(obj, str):
            return self.fix_mojibake(obj)
        return obj

    def begin_chaos_action(self):
        self.pending_chaos = {
            "capture": False,
            "explosions": 0,
            "item_used": 0,
            "effects": False,
            "other": 0,
        }

    def mark_chaos_capture(self):
        if self.pending_chaos is not None:
            self.pending_chaos["capture"] = True

    def mark_chaos_item(self):
        if self.pending_chaos is not None:
            self.pending_chaos["item_used"] += 1
            self.pending_chaos["effects"] = True

    def mark_chaos_effect(self, kind=None):
        if self.pending_chaos is None:
            return
        self.pending_chaos["effects"] = True
        if kind == "explosion":
            self.pending_chaos["explosions"] += 1
        elif kind == "other":
            self.pending_chaos["other"] += 1

    def apply_chaos_after_action(self, action_type="move"):
        if self.pending_chaos is None:
            return
        chaos = int(getattr(self.state, "chaos", 0))
        delta = 0
        if self.pending_chaos["capture"]:
            delta += 2
        if self.pending_chaos["explosions"] > 0:
            delta += 3
        if self.pending_chaos["explosions"] >= 2:
            delta += 5
        if self.pending_chaos["item_used"] > 0:
            delta += 4
        delta += min(self.pending_chaos["other"], 3)
        if action_type == "move":
            if (not self.pending_chaos["capture"] and self.pending_chaos["explosions"] == 0
                    and self.pending_chaos["item_used"] == 0 and not self.pending_chaos["effects"]):
                delta -= 2
        chaos = max(0, min(100, chaos + delta))
        self.state.chaos = chaos
        self.pending_chaos = None

    def chaos_level(self):
        return int(getattr(self.state, "chaos", 0))

    def pack_activation_step(self):
        chaos = self.chaos_level()
        if chaos >= 80:
            return 1
        if chaos >= 60:
            return 2
        if chaos >= 40:
            return 3
        if chaos >= 20:
            return 4
        return 5

    def ensure_min_active_packs(self, target_active):
        if target_active <= 0 or not self.state.dlc_packs:
            return []
        active = [p for p in self.state.dlc_packs if p.get("active")]
        if len(active) >= target_active:
            return []
        newly = []
        for _ in range(target_active - len(active)):
            inactive = [p for p in self.state.dlc_packs if not p.get("active")]
            pack_state = random.choice(inactive) if inactive else None
            if not pack_state:
                break
            pack_def = self.pack_def_by_id.get(pack_state.get("id")) or get_pack_def(pack_state.get("id"))
            if pack_def:
                activate_pack(pack_state, pack_def)
                if self.chaos_level() >= 60:
                    pack_state["next_effect_in"] = 1
                newly.append(pack_state.get("id"))
                self.broadcast_popup(pack_state.get("name"), "Активація", pack_state.get("id"))
                self.note_pack_event(pack_state.get("name"), "Активація", pack_id=pack_state.get("id"))
        return newly

    def refresh_extra_piece_types(self):
        extras = []
        for pack_state in self.state.dlc_packs:
            if not pack_state.get("active"):
                continue
            pack_def = self.pack_def_by_id.get(pack_state.get("id")) or get_pack_def(pack_state.get("id"))
            if not pack_def:
                continue
            extras.extend(pack_def.get("piece_types", []))
        seen = set()
        ordered = []
        for t in extras:
            if t in seen:
                continue
            seen.add(t)
            ordered.append(t)
        self.state.extra_piece_types = ordered

    def serialize_position(self):
        board_serial = []
        for y in range(8):
            row = []
            for x in range(8):
                p = self.state.board.get_piece(x, y)
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
            "board": board_serial,
            "mines": self.state.mines,
            "revealed": self.state.revealed,
            "adj_counts": self.state.adj_counts,
            "craters": [[x, y] for (x, y) in self.state.craters],
            "chessplus_cells": self.state.chessplus_cells,
            "chessplus_walls": self.state.chessplus_walls,
            "chessplus_bombs": self.state.chessplus_bombs,
            "chessplus_void": self.state.chessplus_void,
            "chessplus_mutations": self.state.chessplus_mutations,
            "chessplus_clones": self.state.chessplus_clones,
            "chessplus_nukes": self.state.chessplus_nukes,
        }

    def build_final_score(self):
        royals = count_royals(self.state)
        material = {
            "white": material_score(self.state, "white"),
            "black": material_score(self.state, "black"),
        }
        return {"royals": royals, "material": material}

    def reason_text(self, reason):
        mapping = {
            "royal_captured": "Знищені всі королівські фігури суперника",
            "royal_both": "Обидва гравці втратили королівські фігури",
            "timer_royal": "Таймер: більше королівських фігур",
            "timer_material": "Таймер: більше матеріалу",
            "timer_random": "Таймер: випадковий вибір",
            "opponent_left": "Суперник вийшов",
        }
        return mapping.get(reason, reason)

    def build_game_over_comment(self, reason, winner, final_score):
        reason_txt = self.reason_text(reason)
        winner_txt = None
        if winner == "white":
            winner_txt = "білий"
        elif winner == "black":
            winner_txt = "чорний"
        royals = final_score.get("royals", {})
        material = final_score.get("material", {})
        base = f"Кінець гри: {reason_txt}."
        if winner_txt:
            base += f" Переможець: {winner_txt}."
        base += (
            f" Рахунок: королівські {royals.get('white', 0)}-{royals.get('black', 0)}, "
            f"матеріал {material.get('white', 0)}-{material.get('black', 0)}."
        )
        return base

    def log_game_over(self, reason, winner=None):
        final_score = self.build_final_score()
        final_position = self.serialize_position()
        final_move = self.move_count
        final_move_text = self.last_move_info.get("text") if self.last_move_info else None
        comment = self.build_game_over_comment(reason, winner, final_score)
        self.append_log({
            "type": "game_over",
            "reason": reason,
            "winner": winner,
            "final_move": final_move,
            "final_move_text": final_move_text,
            "final_position": final_position,
            "final_score": final_score,
            "comment": comment,
            "text": f"Game over: {reason}" + (f" ({winner})" if winner else ""),
        })

    def queue_log_entry(self, entry):
        if self.active_move_no is None:
            self.append_log(entry)
        else:
            self.pending_log_entries.append(entry)

    def begin_move_log(self, move_no, piece, frm, to):
        self.active_move_no = move_no
        self.active_move_info = {"piece": piece, "from": frm, "to": to}
        self.pending_log_entries = []
        self.pending_pack_events = []
        self.pending_event_summaries = []
        self.begin_chaos_action()

    def finalize_move_log(self):
        if self.active_move_no is None or not self.active_move_info:
            return
        piece = self.active_move_info.get("piece")
        frm = self.active_move_info.get("from")
        to = self.active_move_info.get("to")
        pack_info = "; ".join(self.pending_pack_events) if self.pending_pack_events else "ні"
        event_info = ", ".join(self.pending_event_summaries) if self.pending_event_summaries else "—"
        move_text = (
            f"[Move] №{self.active_move_no} {self.piece_short(piece)} "
            f"{self.coord_to_alg(frm)} -> {self.coord_to_alg(to)}; "
            f"pack/effect: {pack_info}; events: {event_info}"
        )
        self.append_log({
            "type": "move",
            "text": move_text,
            "piece": self.piece_short(piece),
            "from": list(frm),
            "to": list(to),
            "pack_effects": list(self.pending_pack_events),
            "events": list(self.pending_event_summaries),
        })
        self.last_move_info = {
            "move": self.active_move_no,
            "piece": self.piece_short(piece),
            "from": list(frm),
            "to": list(to),
            "text": move_text,
        }
        for entry in self.pending_log_entries:
            self.append_log(entry)
        self.active_move_no = None
        self.active_move_info = None
        self.pending_log_entries = []
        self.pending_pack_events = []
        self.pending_event_summaries = []

    def note_pack_event(self, pack_name, action, pack_id=None, effect_id=None):
        if not pack_name and pack_id:
            pack_name = self.pack_title(pack_id)
        label = f"{pack_name}: {action}" if pack_name else action
        if self.active_move_no is not None:
            self.pending_pack_events.append(label)
        self.mark_chaos_effect("other")
        entry = {
            "type": "pack",
            "pack": pack_name,
            "pack_id": pack_id,
            "action": action,
            "effect_id": effect_id,
            "text": label,
        }
        self.queue_log_entry(entry)

    def log_event(self, name, etype, target=None, extra=None):
        summary = f"{name} ({etype}"
        if target:
            summary += f" {target}"
        if extra:
            summary += f" {extra}"
        summary += ")"
        if self.active_move_no is not None:
            self.pending_event_summaries.append(summary)
        if name == "Explosion":
            self.mark_chaos_effect("explosion")
        else:
            self.mark_chaos_effect("other")
        entry = {
            "type": "event",
            "name": name,
            "event_type": etype,
            "target": target,
            "extra": extra,
            "text": summary,
        }
        self.queue_log_entry(entry)

    def maybe_promote_pawn_at(self, x, y, reason=None):
        piece = self.state.board.get_piece(x, y)
        if not piece or piece.ptype != "pawn":
            return False
        promotion_rank = 7 if piece.color == "white" else 0
        if y != promotion_rank:
            return False
        piece.ptype = "queen"
        if not piece.is_royal:
            piece.is_royal = True
            if piece.color in self.state.royal_counts:
                self.state.royal_counts[piece.color] += 1
        if reason:
            self.log_event("Promotion", "piece", self.piece_ref((x, y), piece), extra=reason)
        return True

    def trigger_mine_event(self, x, y, source=None):
        extra = source or "mine"
        self.log_event("Explosion", "tile", self.coord_to_alg((x, y)), extra=extra)
        trigger_mine(self.state, x, y)

    def broadcast_state(self):
        self.update_timer_state()
        payload = {"type":"state_update", "state": self.state.to_dict()}
        with self.lock:
            for c in self.clients:
                try:
                    send_json(c['conn'], payload)
                except Exception as e:
                    print("Broadcast error:", e)

    def end_game(self, reason, winner=None):
        self.log_game_over(reason, winner)
        payload = {"type":"game_over", "reason": reason}
        if winner:
            payload["winner"] = winner
        with self.lock:
            for c in self.clients:
                try:
                    send_json(c['conn'], payload)
                except Exception:
                    pass
        self.running = False

    def broadcast_popup(self, title, message=None, theme=None):
        payload = {"type": "popup", "title": title, "message": message or ""}
        if theme:
            payload["theme"] = theme
        with self.lock:
            for c in self.clients:
                try:
                    send_json(c['conn'], payload)
                except Exception:
                    pass

    def send_popup_to_client(self, conn, title, message=None, theme=None):
        payload = {"type": "popup", "title": title, "message": message or ""}
        if theme:
            payload["theme"] = theme
        try:
            send_json(conn, payload)
        except Exception:
            pass

    def start_game(self):
        self.running = True
        print("Game starting. Broadcasting initial state.")
        self.init_match_log()
        self.append_log({
            "type": "game_start",
            "text": "Game started",
            "players": dict(self.state.players),
        })
        self.broadcast_state()

    def reset_game_state(self):
        self.state = GameState()
        self.state.setup_starting_position()
        self.state.dlc_packs = build_pack_states(self.pack_defs)
        self.state.inventory = {"white": [None]*9, "black": [None]*9}
        self.state.extra_piece_types = []
        self.refresh_extra_piece_types()
        self.move_count = 0
        self.match_start_time = None
        self.timer_thread = None
        self.next_pack_activation = 5
        self.next_pack_index = 0
        self.match_log = None
        self.log_path = None
        self.active_move_no = None
        self.active_move_info = None
        self.pending_log_entries = []
        self.pending_pack_events = []
        self.pending_event_summaries = []

    def set_enabled_packs(self, pack_ids):
        if not isinstance(pack_ids, list):
            return
        valid = [p.get("id") for p in PACK_DEFS]
        selected = [pid for pid in pack_ids if pid in valid]
        self.enabled_pack_ids = selected
        self.pack_defs = [p for p in PACK_DEFS if p.get("id") in self.enabled_pack_ids]
        self.pack_def_by_id = {p.get("id"): p for p in self.pack_defs}

    def update_timer_state(self):
        total_ms = int(cfg.MATCH_TIME_SECONDS * 1000)
        if self.match_start_time is None:
            remaining_ms = total_ms
        else:
            elapsed_ms = int((time.time() - self.match_start_time) * 1000)
            remaining_ms = max(0, total_ms - elapsed_ms)
        self.state.timer["match_ms"] = remaining_ms
        self.state.timer["match_running"] = self.match_start_time is not None

    def start_match_timer(self):
        if self.match_start_time is not None:
            return
        self.match_start_time = time.time()
        def timer_fn():
            remaining = cfg.MATCH_TIME_SECONDS - (time.time() - self.match_start_time)
            if remaining > 0:
                time.sleep(remaining)
            with self.lock:
                if not self.running:
                    return
            winner, reason = evaluate_timer_winner(self.state)
            self.broadcast_state()
            self.end_game(reason, winner=winner)
        self.timer_thread = threading.Thread(target=timer_fn, daemon=True)
        self.timer_thread.start()

    def handle_client(self, client):
        conn = client['conn']
        color = client['color']
        try:
            while self.running:
                msg = recv_json(conn)
                if msg is None:
                    print(f"Клієнт {color} від'єднався.")
                    break
                mtype = msg.get('type')
                if mtype == 'move':
                    frm = tuple(msg.get('from',[]))
                    to = tuple(msg.get('to',[]))
                    if color != self.state.turn:
                        send_json(conn, {"type":"error","msg":"not_your_turn"})
                        continue

                    ok, reason = validate_move(self.state, frm, to, color)
                    if not ok:
                        send_json(conn, {"type":"error","msg":reason or "illegal_move"})
                        continue

                    moving_piece = self.state.board.get_piece(*frm)
                    moving_cells_before = []
                    if moving_piece and hasattr(self.state.board, "iter_piece_cells"):
                        moving_cells_before = self.state.board.iter_piece_cells(moving_piece)
                        anchor = self.state.board.find_piece_anchor(moving_piece) if hasattr(self.state.board, "find_piece_anchor") else None
                        if anchor is not None:
                            frm = anchor

                    # apply move (basic legality)
                    captured_positions, promoted = apply_move(self.state, frm, to)
                    if captured_positions:
                        self.mark_chaos_capture()
                    # clear statuses on captured piece
                    if captured_positions:
                        for cx, cy in captured_positions:
                            self.clear_positional(self.state.chessplus_mutations, (cx, cy))
                            self.clear_positional(self.state.chessplus_clones, (cx, cy))
                            self.clear_positional(self.state.chessplus_burning, (cx, cy))
                    else:
                        self.clear_positional(self.state.chessplus_mutations, to)
                        self.clear_positional(self.state.chessplus_clones, to)
                        self.clear_positional(self.state.chessplus_burning, to)
                    # moving piece carries some statuses
                    if moving_cells_before:
                        for cx, cy in moving_cells_before:
                            self.clear_positional(self.state.chessplus_burning, (cx, cy))
                    else:
                        self.clear_positional(self.state.chessplus_burning, frm)
                    self.move_positional(self.state.chessplus_mutations, frm, to)
                    self.move_positional(self.state.chessplus_clones, frm, to)

                    # update move_count
                    self.move_count += 1
                    self.state.move_count = self.move_count
                    self.begin_move_log(self.move_count, moving_piece, frm, to)
                    if promoted:
                        self.log_event("Promotion", "piece", self.piece_ref(to))
                    if self.move_count == 1:
                        self.start_match_timer()
                    self.advance_temporary_effects()
                    full_move_completed = (self.move_count % 2 == 0)
                    self.advance_chessplus_effects(full_move_completed)
                    moving_cells_after = []
                    if moving_piece and hasattr(self.state.board, "iter_piece_cells"):
                        moving_cells_after = self.state.board.iter_piece_cells(moving_piece)
                    if not moving_cells_after:
                        moving_cells_after = [to]
                    for cx, cy in moving_cells_after:
                        self.apply_chessplus_cell_effects(cx, cy)
                    if self.is_pack_active("minesweeper"):
                        for cx, cy in moving_cells_after:
                            if self.state.board.get_piece(cx, cy) is not None:
                                if self.state.mines[cy][cx] == 1:
                                    self.log_event("Explosion", "tile", self.coord_to_alg((cx, cy)), extra="mine")
                                reveal_cell(self.state, cx, cy)

                    newly_activated = self.check_activate_packs()
                    self.advance_pack_lifetimes(full_move_completed)
                    self.advance_pack_effects(current_color=color, skip_pack_ids=newly_activated)
                    self.apply_chaos_after_action(action_type="move")
                    winner, reason = check_royal_elimination(self.state)
                    if winner:
                        self.broadcast_state()
                        self.finalize_move_log()
                        self.end_game(reason, winner=winner)
                        break
                    # toggle turn after legal move
                    self.state.turn = 'black' if self.state.turn == 'white' else 'white'
                    # broadcast
                    self.broadcast_state()
                    self.finalize_move_log()
                elif mtype == 'use_item_request':
                    slot = msg.get('slot')
                    self.handle_item_request(conn, color, slot)
                elif mtype == 'use_item':
                    slot = msg.get('slot')
                    target = msg.get('target')
                    self.handle_item_use(conn, color, slot, target)
                elif mtype == 'use_item_target':
                    slot = msg.get('slot')
                    target = msg.get('target')
                    self.handle_item_use(conn, color, slot, target)
                elif mtype == 'join':
                    # handled at connection time
                    pass
                elif mtype == 'left':
                    print("Client sent left.")
                    break
        except Exception as e:
            print("Client handler exception:", e)
        finally:
            # on disconnect -> end game, notify other
            with self.lock:
                # remove this client
                self.clients = [c for c in self.clients if c['conn'] != conn]
                if self.running:
                    self.running = False
                    winner = self.clients[0]["color"] if self.clients else None
                    self.log_game_over("opponent_left", winner=winner)
                    for c in self.clients:
                        try:
                            send_json(c['conn'], {"type":"game_over","reason":"opponent_left"})
                        except:
                            pass
                if len(self.clients) == 0:
                    # reset room for a new game
                    self.state = GameState()
                    self.state.dlc_packs = build_pack_states(self.pack_defs)
                    self.state.inventory = {"white": [None]*9, "black": [None]*9}
                    self.move_count = 0
                    self.match_start_time = None
                    self.timer_thread = None
                    self.next_pack_activation = 5
                    self.next_pack_index = 0
            conn.close()

    def is_pack_active(self, pack_id):
        for pack in self.state.dlc_packs:
            if pack.get("id") == pack_id:
                return bool(pack.get("active"))
        return False

    def check_activate_packs(self):
        newly = []
        if self.move_count % 2 != 0:
            return newly
        full_moves = self.move_count // 2
        if not self.state.dlc_packs:
            return newly
        while full_moves >= self.next_pack_activation:
            inactive = [p for p in self.state.dlc_packs if not p.get("active")]
            pack_state = random.choice(inactive) if inactive else None
            if pack_state:
                pack_def = self.pack_def_by_id.get(pack_state.get("id")) or get_pack_def(pack_state.get("id"))
                if pack_def:
                    activate_pack(pack_state, pack_def)
                    if self.chaos_level() >= 60:
                        pack_state["next_effect_in"] = 1
                    newly.append(pack_state.get("id"))
                    self.broadcast_popup(pack_state.get("name"), "Активація", pack_state.get("id"))
                    self.note_pack_event(pack_state.get("name"), "Активація", pack_id=pack_state.get("id"))
            self.next_pack_activation += self.pack_activation_step()
        if self.chaos_level() >= 40:
            newly += self.ensure_min_active_packs(2)
        if newly:
            self.refresh_extra_piece_types()
        return newly

    def advance_pack_lifetimes(self, full_move_completed=False):
        if not full_move_completed:
            return
        changed = False
        for pack_state in self.state.dlc_packs:
            if not pack_state.get("active"):
                continue
            pack_state["active_moves"] = int(pack_state.get("active_moves", 0)) + 1
            if pack_state["active_moves"] >= 10:
                pack_state["active"] = False
                pack_state["next_effect_in"] = None
                self.broadcast_popup(pack_state.get("name"), "Деактивація", pack_state.get("id"))
                self.note_pack_event(pack_state.get("name"), "Деактивація", pack_id=pack_state.get("id"))
                changed = True
        if changed:
            self.refresh_extra_piece_types()

    def advance_pack_effects(self, current_color, skip_pack_ids=None):
        if skip_pack_ids is None:
            skip_pack_ids = set()
        else:
            skip_pack_ids = set(skip_pack_ids)
        chaos = self.chaos_level()
        min_interval = 1 if chaos >= 60 else None
        for pack_state in self.state.dlc_packs:
            if not pack_state.get("active"):
                continue
            if pack_state.get("id") in skip_pack_ids:
                continue
            next_in = pack_state.get("next_effect_in")
            if next_in is None:
                continue
            next_in -= 1
            if next_in > 0:
                pack_state["next_effect_in"] = next_in
                continue
            pack_def = self.pack_def_by_id.get(pack_state.get("id")) or get_pack_def(pack_state.get("id"))
            if not pack_def:
                pack_state["next_effect_in"] = min_interval or random.randint(1, 2)
                continue
            eff_def, eff_state = choose_effect(pack_state, pack_def, chaos=chaos)
            if not eff_def or not eff_state:
                pack_state["next_effect_in"] = None
                continue
            eff_state["remaining"] = max(0, (eff_state.get("remaining") or 0) - 1)
            pack_state["next_effect_in"] = min_interval or random.randint(1, 2)

            if eff_def.get("is_item"):
                item = make_item(eff_def)
                added, slot_idx = self.add_item_to_inventory(current_color, item)
                if added:
                    self.broadcast_popup(pack_state.get("name"), item["name"], pack_state.get("id"))
                    self.note_pack_event(pack_state.get("name"), item["name"], pack_id=pack_state.get("id"), effect_id=eff_def.get("id"))
                else:
                    self.note_pack_event(pack_state.get("name"), f"{item.get('name')} (не додано)", pack_id=pack_state.get("id"), effect_id=eff_def.get("id"))
                    conn = self.get_conn_by_color(current_color)
                    if conn:
                        self.send_popup_to_client(conn, "Інвентар заповнений", "Предмет не додано")
            else:
                result = apply_effect(eff_def, self.state, current_color=current_color)
                popup_text = eff_def.get("name")
                if isinstance(result, dict) and result.get("popup"):
                    popup_text = result.get("popup")
                self.broadcast_popup(pack_state.get("name"), popup_text, pack_state.get("id"))
                self.note_pack_event(pack_state.get("name"), popup_text, pack_id=pack_state.get("id"), effect_id=eff_def.get("id"))
                if isinstance(result, dict):
                    event = result.get("event")
                    if isinstance(event, dict):
                        name = event.get("name") or "Effect"
                        etype = event.get("etype") or "board"
                        target = event.get("target")
                        extra = event.get("extra")
                        if isinstance(target, (list, tuple)) and len(target) == 2 and isinstance(target[0], int):
                            target = self.coord_to_alg((target[0], target[1]))
                        elif isinstance(target, list):
                            coords = []
                            for item in target:
                                if isinstance(item, (list, tuple)) and len(item) == 2:
                                    coords.append(self.coord_to_alg((item[0], item[1])))
                            if coords:
                                target = ",".join(coords)
                        self.log_event(name, etype, target, extra)

    def get_conn_by_color(self, color):
        for c in self.clients:
            if c.get("color") == color:
                return c.get("conn")
        return None

    def pack_title(self, pack_id):
        if not pack_id:
            return ""
        pack_def = self.pack_def_by_id.get(pack_id) or get_pack_def(pack_id)
        if pack_def:
            return pack_def.get("name", pack_id)
        return pack_id

    def add_item_to_inventory(self, color, item):
        inv = self.state.inventory.get(color)
        if inv is None:
            return False, None
        for i in range(len(inv)):
            if inv[i] is None:
                inv[i] = item
                return True, i
        return False, None

    def choose_random_item_def(self):
        items = []
        for pack_def in self.pack_defs:
            for eff in pack_def.get("effects", []):
                if eff.get("is_item"):
                    items.append(eff)
        if not items:
            return None
        return random.choice(items)

    def pos_key(self, x, y):
        return f"{x},{y}"

    def parse_key(self, key):
        try:
            sx, sy = key.split(",")
            return int(sx), int(sy)
        except Exception:
            return None

    def clear_positional(self, mapping, pos):
        if mapping is None:
            return
        x, y = pos
        k = self.pos_key(x, y)
        if k in mapping:
            del mapping[k]

    def move_positional(self, mapping, fr, to):
        if mapping is None:
            return
        kf = self.pos_key(fr[0], fr[1])
        if kf in mapping:
            kt = self.pos_key(to[0], to[1])
            mapping[kt] = mapping.pop(kf)

    def swap_positional(self, mapping, a, b):
        if mapping is None:
            return
        ka = self.pos_key(a[0], a[1])
        kb = self.pos_key(b[0], b[1])
        va = mapping.get(ka)
        vb = mapping.get(kb)
        if va is not None:
            mapping[kb] = va
        else:
            mapping.pop(kb, None)
        if vb is not None:
            mapping[ka] = vb
        else:
            mapping.pop(ka, None)

    def remove_piece_at(self, x, y):
        piece = self.state.board.get_piece(x, y)
        if piece is None:
            return False
        cells = []
        if hasattr(self.state.board, "iter_piece_cells"):
            cells = self.state.board.iter_piece_cells(piece)
        if piece.is_royal:
            if piece.color in self.state.royal_counts:
                self.state.royal_counts[piece.color] -= 1
        if hasattr(self.state.board, "clear_piece"):
            self.state.board.clear_piece(x, y)
        else:
            self.state.board.set_piece(x, y, None)
        for cx, cy in cells or [(x, y)]:
            self.clear_positional(self.state.chessplus_mutations, (cx, cy))
            self.clear_positional(self.state.chessplus_clones, (cx, cy))
            self.clear_positional(self.state.chessplus_burning, (cx, cy))
        return True

    def get_cell_effect(self, x, y):
        if not (0 <= x < 8 and 0 <= y < 8):
            return None
        return self.state.chessplus_cells[y][x]

    def wall_between(self, fr, to):
        walls = getattr(self.state, "chessplus_walls", [])
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

    def set_cell_effect(self, x, y, effect_id):
        if not (0 <= x < 8 and 0 <= y < 8):
            return
        self.state.chessplus_cells[y][x] = effect_id

    def clear_cell_effect(self, x, y):
        if not (0 <= x < 8 and 0 <= y < 8):
            return
        self.state.chessplus_cells[y][x] = None

    def advance_temporary_effects(self):
        temp = getattr(self.state, "temp_reveal", None)
        if temp and temp.get("remaining_moves", 0) > 0:
            temp["remaining_moves"] = max(0, int(temp.get("remaining_moves", 0)) - 1)
            if temp["remaining_moves"] == 0:
                temp["cells"] = []
        vision = getattr(self.state, "mine_vision", None)
        if vision:
            for color in ("white", "black"):
                if vision.get(color, 0) > 0:
                    vision[color] = max(0, int(vision.get(color, 0)) - 1)

    def iter_pos_map(self, mapping):
        if not mapping:
            return []
        items = []
        for k, v in mapping.items():
            pos = self.parse_key(k)
            if pos:
                items.append((pos, v))
        return items

    def apply_chessplus_cell_effects(self, x, y):
        effect = self.get_cell_effect(x, y)
        if not effect:
            return
        if effect == "void":
            self.log_event("Void", "tile", self.coord_to_alg((x, y)))
            self.remove_piece_at(x, y)
            void_state = getattr(self.state, "chessplus_void", None)
            if void_state is not None:
                void_state["next_expand"] = max(int(void_state.get("next_expand", 0)), 2)
            return
        if effect == "dice":
            piece = self.state.board.get_piece(x, y)
            if not piece:
                return
            before_type = piece.ptype
            roll = random.random()
            if roll < 0.2:
                self.log_event("Dice", "piece", self.piece_ref((x, y), piece), extra="removed")
                self.remove_piece_at(x, y)
                self.broadcast_popup(self.pack_title("chessplus"), "Кубик", "chessplus")
            elif roll < 0.4:
                item_def = self.choose_random_item_def()
                if item_def:
                    item = make_item(item_def)
                    added, slot_idx = self.add_item_to_inventory(piece.color, item)
                    if added:
                        self.log_event("Dice", "piece", self.piece_ref((x, y), piece), extra=f"item:{item.get('name')}")
                        self.broadcast_popup(self.pack_title("chessplus"), item["name"], "chessplus")
                    else:
                        self.log_event("Dice", "piece", self.piece_ref((x, y), piece), extra="item_failed")
                        conn = self.get_conn_by_color(piece.color)
                        if conn:
                            self.send_popup_to_client(conn, "Інвентар заповнений", "Предмет не додано")
            else:
                new_type = mutate_piece_randomly(self.state, x, y)
                self.log_event("Dice", "piece", self.piece_ref((x, y)), extra=f"{before_type}->{new_type}")
            self.clear_positional(self.state.chessplus_mutations, (x, y))
            return
        if effect == "fire":
            self.state.chessplus_burning[self.pos_key(x, y)] = 2
            self.log_event("Fire", "tile", self.coord_to_alg((x, y)))
            return
        if effect == "bomb":
            k = self.pos_key(x, y)
            current = int(self.state.chessplus_bombs.get(k, 0)) if self.state.chessplus_bombs else 0
            self.state.chessplus_bombs[k] = max(current, 1)
            self.log_event("Bomb", "tile", self.coord_to_alg((x, y)), extra="armed")
            return
        if effect == "swap":
            result = self.trigger_swap()
            if result:
                a = result.get("a")
                b = result.get("b")
                if a and b:
                    target = f"{self.coord_to_alg(a)}<->{self.coord_to_alg(b)}"
                else:
                    target = None
                extra = None
                if result.get("pa") or result.get("pb"):
                    extra = f"{self.piece_short(result.get('pa'))}<->{self.piece_short(result.get('pb'))}"
                self.log_event("Swap", "board", target, extra)
            self.clear_cell_effect(x, y)
            return
        if effect == "toxic":
            outcome = self.apply_toxic(x, y)
            extra = outcome or None
            self.log_event("Toxic", "tile", self.coord_to_alg((x, y)), extra=extra)
            return

    def apply_toxic(self, x, y):
        if random.random() < 0.5:
            self.remove_piece_at(x, y)
            return "removed"
        else:
            mutate_piece_randomly(self.state, x, y)
            return "mutated"

    def trigger_swap(self):
        pieces = []
        seen = set()
        for y in range(8):
            for x in range(8):
                p = self.state.board.get_piece(x, y)
                if not p:
                    continue
                key = getattr(p, "gid", None)
                if key is None:
                    key = id(p)
                if key in seen:
                    continue
                seen.add(key)
                if getattr(p, "size", 1) > 1:
                    continue
                anchor = self.state.board.find_piece_anchor(p) if hasattr(self.state.board, "find_piece_anchor") else (x, y)
                if anchor is None:
                    anchor = (x, y)
                pieces.append((anchor, p))
        if len(pieces) < 2:
            return None
        (a, pa), (b, pb) = random.sample(pieces, 2)
        self.state.board.set_piece(a[0], a[1], pb)
        self.state.board.set_piece(b[0], b[1], pa)
        self.swap_positional(self.state.chessplus_mutations, a, b)
        self.swap_positional(self.state.chessplus_clones, a, b)
        # burning depends on standing on fire tiles, reset for swapped cells
        self.clear_positional(self.state.chessplus_burning, a)
        self.clear_positional(self.state.chessplus_burning, b)
        if self.get_cell_effect(a[0], a[1]) == "fire" and self.state.board.get_piece(*a):
            self.state.chessplus_burning[self.pos_key(a[0], a[1])] = 2
        if self.get_cell_effect(b[0], b[1]) == "fire" and self.state.board.get_piece(*b):
            self.state.chessplus_burning[self.pos_key(b[0], b[1])] = 2
        promo_a = self.maybe_promote_pawn_at(a[0], a[1], reason="swap")
        promo_b = self.maybe_promote_pawn_at(b[0], b[1], reason="swap")
        return {
            "a": a,
            "b": b,
            "pa": pa,
            "pb": pb,
            "promo_a": promo_a,
            "promo_b": promo_b,
        }

    def explode_area(self, cx, cy, radius=1):
        for x in range(cx - radius, cx + radius + 1):
            for y in range(cy - radius, cy + radius + 1):
                if 0 <= x < 8 and 0 <= y < 8:
                    self.remove_piece_at(x, y)

    def detonate_bomb_chain(self, start_positions):
        queue = list(start_positions)
        seen = set()
        while queue:
            cx, cy = queue.pop(0)
            if (cx, cy) in seen:
                continue
            seen.add((cx, cy))
            # remove bomb marker
            self.state.chessplus_bombs.pop(self.pos_key(cx, cy), None)
            if self.get_cell_effect(cx, cy) == "bomb":
                self.clear_cell_effect(cx, cy)
            # explosion
            self.log_event("Explosion", "tile", self.coord_to_alg((cx, cy)), extra="bomb")
            self.explode_area(cx, cy, radius=1)
            self.state.craters.add((cx, cy))
            # chain mines
            for x in range(cx - 1, cx + 2):
                for y in range(cy - 1, cy + 2):
                    if 0 <= x < 8 and 0 <= y < 8:
                        if self.state.mines[y][x] == 1:
                            self.trigger_mine_event(x, y, source="bomb_chain")
            # chain bombs
            for x in range(cx - 1, cx + 2):
                for y in range(cy - 1, cy + 2):
                    if 0 <= x < 8 and 0 <= y < 8:
                        if self.get_cell_effect(x, y) == "bomb" and (x, y) not in seen:
                            queue.append((x, y))

    def trigger_nuke(self, center):
        cx, cy = center
        radius = 2
        self.log_event("Nuke", "board", self.coord_to_alg((cx, cy)), extra="detonate")
        for x in range(cx - radius, cx + radius + 1):
            for y in range(cy - radius, cy + radius + 1):
                if 0 <= x < 8 and 0 <= y < 8:
                    self.remove_piece_at(x, y)
        # main crater + extra for visual weight
        self.state.craters.add((cx, cy))
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < 8 and 0 <= ny < 8:
                self.state.craters.add((nx, ny))
        # chain mines & bombs
        for x in range(cx - radius, cx + radius + 1):
            for y in range(cy - radius, cy + radius + 1):
                if 0 <= x < 8 and 0 <= y < 8:
                    if self.state.mines[y][x] == 1:
                        self.trigger_mine_event(x, y, source="nuke_chain")
                    if self.pos_key(x, y) in self.state.chessplus_bombs:
                        self.state.chessplus_bombs.pop(self.pos_key(x, y), None)
                    if self.get_cell_effect(x, y) == "bomb":
                        self.clear_cell_effect(x, y)
        # toxic fallout
        for x in range(cx - radius, cx + radius + 1):
            for y in range(cy - radius, cy + radius + 1):
                if 0 <= x < 8 and 0 <= y < 8:
                    if self.get_cell_effect(x, y) == "void":
                        continue
                    if random.random() < 0.5:
                        self.set_cell_effect(x, y, "toxic")

    def advance_chessplus_effects(self, full_move_completed=False):
        # fire spread / extinguish (every move)
        fire_cells = [(x, y) for y in range(8) for x in range(8) if self.get_cell_effect(x, y) == "fire"]
        new_fire = []
        remove_fire = []
        for x, y in fire_cells:
            if random.random() < 0.3:
                remove_fire.append((x, y))
            if random.random() < 0.5:
                neighbors = [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
                candidates = [(nx, ny) for (nx, ny) in neighbors if 0 <= nx < 8 and 0 <= ny < 8 and self.get_cell_effect(nx, ny) is None]
                if candidates:
                    new_fire.append(random.choice(candidates))
        for x, y in remove_fire:
            if self.get_cell_effect(x, y) == "fire":
                self.clear_cell_effect(x, y)
        for x, y in new_fire:
            if self.get_cell_effect(x, y) is None:
                self.set_cell_effect(x, y, "fire")

        if not full_move_completed:
            return

        # burning damage
        for (pos, remaining) in list(self.iter_pos_map(self.state.chessplus_burning)):
            x, y = pos
            if self.state.board.get_piece(x, y) is None or self.get_cell_effect(x, y) != "fire":
                self.clear_positional(self.state.chessplus_burning, (x, y))
                continue
            remaining = int(remaining) - 1
            if remaining <= 0:
                victim = self.piece_ref((x, y))
                self.remove_piece_at(x, y)
                self.clear_positional(self.state.chessplus_burning, (x, y))
                self.log_event("Burn", "piece", victim)
            else:
                self.state.chessplus_burning[self.pos_key(x, y)] = remaining

        # bomb timers
        for (pos, remaining) in list(self.iter_pos_map(self.state.chessplus_bombs)):
            x, y = pos
            remaining = int(remaining) - 1
            if remaining <= 0:
                self.state.chessplus_bombs.pop(self.pos_key(x, y), None)
                self.detonate_bomb_chain([(x, y)])
            else:
                self.state.chessplus_bombs[self.pos_key(x, y)] = remaining

        # void expansion
        void_state = getattr(self.state, "chessplus_void", None)
        if void_state and void_state.get("cells"):
            next_expand = int(void_state.get("next_expand", 0))
            if next_expand <= 0:
                cells = [tuple(c) for c in void_state.get("cells", [])]
                neighbors = set()
                for vx, vy in cells:
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = vx + dx, vy + dy
                        if 0 <= nx < 8 and 0 <= ny < 8 and (nx, ny) not in cells:
                            neighbors.add((nx, ny))
                if neighbors:
                    nx, ny = random.choice(list(neighbors))
                    self.set_cell_effect(nx, ny, "void")
                    void_state["cells"].append([nx, ny])
                    self.remove_piece_at(nx, ny)
                    self.log_event("Void", "tile", self.coord_to_alg((nx, ny)), extra="expand")
                void_state["next_expand"] = random.randint(1, 2)
            else:
                void_state["next_expand"] = max(0, next_expand - 1)

        # clone TTL
        for (pos, remaining) in list(self.iter_pos_map(self.state.chessplus_clones)):
            x, y = pos
            remaining = int(remaining) - 1
            if remaining <= 0:
                clone_ref = self.piece_ref((x, y))
                self.remove_piece_at(x, y)
                self.clear_positional(self.state.chessplus_clones, (x, y))
                self.log_event("Clone", "piece", clone_ref, extra="expired")
            else:
                self.state.chessplus_clones[self.pos_key(x, y)] = remaining

        # nukes
        nukes = getattr(self.state, "chessplus_nukes", [])
        remaining_nukes = []
        for entry in nukes:
            timer = int(entry.get("timer", 0)) - 1
            if timer <= 0:
                center = entry.get("center")
                if center and len(center) == 2:
                    self.trigger_nuke((center[0], center[1]))
                    self.state.nuke_event_id = int(getattr(self.state, "nuke_event_id", 0)) + 1
            else:
                entry["timer"] = timer
                remaining_nukes.append(entry)
        self.state.chessplus_nukes = remaining_nukes

    def get_inventory_item(self, color, slot):
        inv = self.state.inventory.get(color)
        if inv is None:
            return None
        if slot is None or not isinstance(slot, int):
            return None
        if slot < 0 or slot >= len(inv):
            return None
        return inv[slot]

    def consume_item(self, color, slot):
        inv = self.state.inventory.get(color)
        if inv is None:
            return
        item = inv[slot]
        if not item:
            return
        item["uses"] = max(0, int(item.get("uses", 1)) - 1)
        if item["uses"] <= 0:
            inv[slot] = None

    def handle_item_request(self, conn, color, slot):
        if color != self.state.turn:
            send_json(conn, {"type":"error", "msg":"not_your_turn"})
            return
        item = self.get_inventory_item(color, slot)
        if not item:
            send_json(conn, {"type":"error", "msg":"item_missing"})
            return
        if item.get("target") != "mine":
            return
        targets = [(x, y) for y in range(8) for x in range(8) if self.state.mines[y][x] == 1]
        if not targets:
            send_json(conn, {"type":"error", "msg":"invalid_target"})
            return
        self.state.mine_vision[color] = 2
        self.broadcast_state()
        send_json(conn, {"type":"item_target", "slot": slot, "targets": targets, "mode": "mine"})

    def handle_item_use(self, conn, color, slot, target):
        if color != self.state.turn:
            send_json(conn, {"type":"error", "msg":"not_your_turn"})
            return
        item = self.get_inventory_item(color, slot)
        if not item:
            send_json(conn, {"type":"error", "msg":"item_missing"})
            return
        effect_id = item.get("effect_id")
        self.begin_chaos_action()
        if effect_id == "ms_item_place_mine":
            if not target or len(target) != 2:
                send_json(conn, {"type":"error", "msg":"item_requires_target"})
                return
            x, y = target
            if not place_mine(self.state, x, y):
                send_json(conn, {"type":"error", "msg":"invalid_target"})
                return
            self.log_event("PlaceMine", "tile", self.coord_to_alg((x, y)))
            self.consume_item(color, slot)
            self.send_popup_to_client(conn, self.pack_title("minesweeper"), item.get("name"), "minesweeper")
            self.mark_chaos_item()
            self.apply_chaos_after_action(action_type="item")
            self.broadcast_state()
            return
        if effect_id == "ms_item_reveal_explode":
            if not target or len(target) != 2:
                send_json(conn, {"type":"error", "msg":"item_requires_target"})
                return
            x, y = target
            if not (0 <= x < 8 and 0 <= y < 8) or self.state.mines[y][x] != 1:
                send_json(conn, {"type":"error", "msg":"invalid_target"})
                return
            self.trigger_mine_event(x, y, source="item")
            self.state.mine_vision[color] = 0
            self.consume_item(color, slot)
            self.send_popup_to_client(conn, self.pack_title("minesweeper"), item.get("name"), "minesweeper")
            self.mark_chaos_item()
            self.apply_chaos_after_action(action_type="item")
            winner, reason = check_royal_elimination(self.state)
            if winner:
                self.broadcast_state()
                self.end_game(reason, winner=winner)
                return
            self.broadcast_state()
            return
        if effect_id == "cp_item_teleport":
            if not isinstance(target, dict):
                send_json(conn, {"type":"error", "msg":"item_requires_target"})
                return
            src = target.get("from")
            dst = target.get("to")
            if not src or not dst or len(src) != 2 or len(dst) != 2:
                send_json(conn, {"type":"error", "msg":"item_requires_target"})
                return
            sx, sy = src
            tx, ty = dst
            if not (0 <= sx < 8 and 0 <= sy < 8 and 0 <= tx < 8 and 0 <= ty < 8):
                send_json(conn, {"type":"error", "msg":"invalid_target"})
                return
            piece = self.state.board.get_piece(sx, sy)
            if not piece or piece.color != color:
                send_json(conn, {"type":"error", "msg":"invalid_target"})
                return
            anchor = self.state.board.find_piece_anchor(piece) if hasattr(self.state.board, "find_piece_anchor") else (sx, sy)
            if anchor is not None:
                sx, sy = anchor
            size = max(1, int(getattr(piece, "size", 1)))
            if not (0 <= tx < 8 and 0 <= ty < 8 and 0 <= tx + size - 1 < 8 and 0 <= ty + size - 1 < 8):
                send_json(conn, {"type":"error", "msg":"invalid_target"})
                return
            for yy in range(size):
                for xx in range(size):
                    if self.state.board.get_piece(tx + xx, ty + yy) is not None:
                        send_json(conn, {"type":"error", "msg":"invalid_target"})
                        return
            teleport_ref = f"{self.piece_short(piece)} {self.coord_to_alg((sx, sy))}->{self.coord_to_alg((tx, ty))}"
            self.clear_positional(self.state.chessplus_burning, (sx, sy))
            self.move_positional(self.state.chessplus_mutations, (sx, sy), (tx, ty))
            self.move_positional(self.state.chessplus_clones, (sx, sy), (tx, ty))
            self.state.board.move_piece((sx, sy), (tx, ty))
            self.log_event("Teleport", "piece", teleport_ref)
            moved_cells = []
            if hasattr(self.state.board, "iter_piece_cells"):
                moved_cells = self.state.board.iter_piece_cells(piece)
            if not moved_cells:
                moved_cells = [(tx, ty)]
            for cx, cy in moved_cells:
                self.apply_chessplus_cell_effects(cx, cy)
            if self.is_pack_active("minesweeper"):
                for cx, cy in moved_cells:
                    if self.state.board.get_piece(cx, cy) is not None:
                        if self.state.mines[cy][cx] == 1:
                            self.log_event("Explosion", "tile", self.coord_to_alg((cx, cy)), extra="mine")
                        reveal_cell(self.state, cx, cy)
            self.consume_item(color, slot)
            self.send_popup_to_client(conn, self.pack_title("chessplus"), item.get("name"), "chessplus")
            self.mark_chaos_item()
            self.apply_chaos_after_action(action_type="item")
            winner, reason = check_royal_elimination(self.state)
            if winner:
                self.broadcast_state()
                self.end_game(reason, winner=winner)
                return
            self.broadcast_state()
            return
        if effect_id == "cp_item_pistol":
            if not isinstance(target, dict):
                send_json(conn, {"type":"error", "msg":"item_requires_target"})
                return
            src = target.get("from")
            dst = target.get("to")
            if not src or not dst or len(src) != 2 or len(dst) != 2:
                send_json(conn, {"type":"error", "msg":"item_requires_target"})
                return
            sx, sy = src
            tx, ty = dst
            if not (0 <= sx < 8 and 0 <= sy < 8 and 0 <= tx < 8 and 0 <= ty < 8):
                send_json(conn, {"type":"error", "msg":"invalid_target"})
                return
            piece = self.state.board.get_piece(sx, sy)
            if not piece or piece.color != color:
                send_json(conn, {"type":"error", "msg":"invalid_target"})
                return
            anchor = self.state.board.find_piece_anchor(piece) if hasattr(self.state.board, "find_piece_anchor") else (sx, sy)
            if anchor is not None:
                sx, sy = anchor
            dx = tx - sx
            dy = ty - sy
            if dx == 0 and dy == 0:
                send_json(conn, {"type":"error", "msg":"invalid_target"})
                return
            if not (dx == 0 or dy == 0 or abs(dx) == abs(dy)):
                send_json(conn, {"type":"error", "msg":"invalid_target"})
                return
            dist = max(abs(dx), abs(dy))
            if dist > 3:
                send_json(conn, {"type":"error", "msg":"invalid_target"})
                return
            step_x = (dx > 0) - (dx < 0)
            step_y = (dy > 0) - (dy < 0)
            hit = False
            shooter_ref = f"{self.piece_short(piece)} {self.coord_to_alg((sx, sy))}->{self.coord_to_alg((tx, ty))}"
            hit_ref = None
            cx, cy = sx, sy
            for _ in range(3):
                nx, ny = cx + step_x, cy + step_y
                if not (0 <= nx < 8 and 0 <= ny < 8):
                    break
                if self.wall_between((cx, cy), (nx, ny)):
                    break
                target_piece = self.state.board.get_piece(nx, ny)
                if target_piece:
                    hit_ref = self.piece_ref((nx, ny), target_piece)
                    self.remove_piece_at(nx, ny)
                    hit = True
                    break
                cx, cy = nx, ny
            self.consume_item(color, slot)
            self.send_popup_to_client(conn, self.pack_title("chessplus"), item.get("name"), "chessplus")
            if hit_ref:
                self.log_event("Pistol", "piece", shooter_ref, extra=f"hit:{hit_ref}")
            else:
                self.log_event("Pistol", "piece", shooter_ref, extra="miss")
            self.mark_chaos_item()
            self.apply_chaos_after_action(action_type="item")
            if hit:
                winner, reason = check_royal_elimination(self.state)
                if winner:
                    self.broadcast_state()
                    self.end_game(reason, winner=winner)
                    return
            self.broadcast_state()
            return
        if effect_id == "cp_item_nuke":
            if not isinstance(target, dict):
                send_json(conn, {"type":"error", "msg":"item_requires_target"})
                return
            src = target.get("from") or target.get("piece")
            if not src or len(src) != 2:
                send_json(conn, {"type":"error", "msg":"item_requires_target"})
                return
            sx, sy = src
            if not (0 <= sx < 8 and 0 <= sy < 8):
                send_json(conn, {"type":"error", "msg":"invalid_target"})
                return
            piece = self.state.board.get_piece(sx, sy)
            if not piece or piece.color != color:
                send_json(conn, {"type":"error", "msg":"invalid_target"})
                return
            anchor = self.state.board.find_piece_anchor(piece) if hasattr(self.state.board, "find_piece_anchor") else (sx, sy)
            if anchor is not None:
                sx, sy = anchor
            nukes = getattr(self.state, "chessplus_nukes", [])
            nukes.append({"center": [sx, sy], "timer": 5})
            self.state.chessplus_nukes = nukes
            self.log_event("Nuke", "board", self.coord_to_alg((sx, sy)), extra="armed")
            self.consume_item(color, slot)
            self.send_popup_to_client(conn, self.pack_title("chessplus"), item.get("name"), "chessplus")
            self.mark_chaos_item()
            self.apply_chaos_after_action(action_type="item")
            self.broadcast_state()
            return
        if effect_id == "cp_item_clone":
            if not isinstance(target, dict):
                send_json(conn, {"type":"error", "msg":"item_requires_target"})
                return
            src = target.get("from")
            dst = target.get("to")
            if not src or not dst or len(src) != 2 or len(dst) != 2:
                send_json(conn, {"type":"error", "msg":"item_requires_target"})
                return
            sx, sy = src
            tx, ty = dst
            if not (0 <= sx < 8 and 0 <= sy < 8 and 0 <= tx < 8 and 0 <= ty < 8):
                send_json(conn, {"type":"error", "msg":"invalid_target"})
                return
            piece = self.state.board.get_piece(sx, sy)
            if not piece or piece.color != color:
                send_json(conn, {"type":"error", "msg":"invalid_target"})
                return
            anchor = self.state.board.find_piece_anchor(piece) if hasattr(self.state.board, "find_piece_anchor") else (sx, sy)
            if anchor is not None:
                sx, sy = anchor
            if max(abs(tx - sx), abs(ty - sy)) != 1:
                send_json(conn, {"type":"error", "msg":"invalid_target"})
                return
            size = max(1, int(getattr(piece, "size", 1)))
            if not (0 <= tx < 8 and 0 <= ty < 8 and 0 <= tx + size - 1 < 8 and 0 <= ty + size - 1 < 8):
                send_json(conn, {"type":"error", "msg":"invalid_target"})
                return
            for yy in range(size):
                for xx in range(size):
                    if self.state.board.get_piece(tx + xx, ty + yy) is not None:
                        send_json(conn, {"type":"error", "msg":"invalid_target"})
                        return
                    if self.get_cell_effect(tx + xx, ty + yy) is not None:
                        send_json(conn, {"type":"error", "msg":"invalid_target"})
                        return
            if not clone_piece(self.state, (sx, sy), (tx, ty)):
                send_json(conn, {"type":"error", "msg":"invalid_target"})
                return
            self.state.chessplus_clones[self.pos_key(tx, ty)] = 3
            clone_ref = f"{self.piece_short(piece)} {self.coord_to_alg((sx, sy))}->{self.coord_to_alg((tx, ty))}"
            self.log_event("Clone", "piece", clone_ref)
            self.consume_item(color, slot)
            self.send_popup_to_client(conn, self.pack_title("chessplus"), item.get("name"), "chessplus")
            self.mark_chaos_item()
            self.apply_chaos_after_action(action_type="item")
            self.broadcast_state()
            return
        send_json(conn, {"type":"error", "msg":"unknown_item"})

def serve():
    print("Starting server on", HOST, PORT)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((HOST, PORT))
    s.listen(2)
    room = Room()
    while True:
        conn, addr = s.accept()
        print("Incoming connection from", addr)
        # handshake: receive join
        msg = recv_json(conn)
        if msg is None or msg.get('type') != 'join':
            conn.close()
            continue
        name = msg.get('name','Player')
        pack_ids = msg.get('packs')
        start_game = False
        clients_snapshot = None
        with room.lock:
            if len(room.clients) >= 2:
                send_json(conn, {"type":"error","msg":"room_full"})
                conn.close()
                continue
            if len(room.clients) == 0 and pack_ids is not None:
                room.set_enabled_packs(pack_ids)
            color = 'white' if len(room.clients) == 0 else 'black'
            client = {'conn': conn, 'addr': addr, 'name': name, 'color': color}
            room.clients.append(client)
            send_json(conn, {"type":"join_ack","color": color})
            print(f"Assigned {name=} as {color}")
            if len(room.clients) == 2:
                # initialize board pieces & game state
                room.reset_game_state()
                for c in room.clients:
                    room.state.players[c['color']] = c.get('name')
                next_id = load_game_id() + 1
                save_game_id(next_id)
                room.state.game_id = next_id
                start_game = True
                clients_snapshot = list(room.clients)
        if start_game:
            room.start_game()
            # spin client threads
            for c in clients_snapshot:
                t = threading.Thread(target=room.handle_client, args=(c,), daemon=True)
                t.start()
        # continue accepting (but only one room in this simple server)

if __name__ == '__main__':
    serve()

