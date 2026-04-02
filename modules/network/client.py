import socket, threading, json, argparse, pygame, sys, time, subprocess
from pathlib import Path
import random
import math
import re
import copy
try:
    import cv2
    CV2_AVAILABLE = True
except Exception:
    cv2 = None
    CV2_AVAILABLE = False

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from modules.game.state import GameState
from modules.game.rules import validate_move, apply_move
from modules.game.board import coord_for_pixel, coord_in_bounds
from modules.game.pieces import Piece, apply_piece_type, piece_size
from modules.dlc.minesweeper import compute_adj_counts, trigger_mine, clear_reveal_on_mine, reveal_numbers_under_pieces
from modules.dlc.packs import PACK_DEFS
import settings as cfg


def send_json(conn, obj):
    data = json.dumps(obj).encode('utf-8')
    conn.sendall(len(data).to_bytes(4,'big') + data)

def recv_json(conn):
    length_bytes = conn.recv(4)
    if not length_bytes:
        return None
    length = int.from_bytes(length_bytes,'big')
    data = b''
    while len(data) < length:
        chunk = conn.recv(length - len(data))
        if not chunk:
            return None
        data += chunk
    return json.loads(data.decode('utf-8'))

class Client:
    def __init__(self, host, name="Player"):
        self.host = host
        self.name = name
        self.ui_state = "menu"
        self.mode = None
        self.name_input = name or ""
        self.last_name = name or ""
        self.ip_input = host or "127.0.0.1"
        self.last_ip = self.ip_input
        self.input_focus = "name"
        self.available_packs = [{"id": p.get("id"), "name": p.get("name")} for p in PACK_DEFS]
        self.enabled_packs = {p.get("id"): True for p in PACK_DEFS}
        self.popups_enabled = True
        self.replay_games = []
        self.replay_selected = 0
        self.replay_states = []
        self.replay_state = None
        self.replay_move_index = 0
        self.replay_playing = False
        self.replay_speed_index = 0
        self.replay_next_time = 0.0
        self.replay_game_rects = {}
        self.replay_list_offset = 0
        self.replay_scroll_rects = {}
        self.item_target_phase = None
        self.item_selected_piece = None
        self.last_nuke_event_id = 0
        self.shake_offset = (0, 0)
        self.shake_time_left = 0.0
        self.shake_duration = 0.0
        self.shake_intensity = 0.0
        self.server_process = None
        self.game_id = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.state = None
        self.my_color = None
        self.running = True
        self.net_running = True
        self.connected = False
        self.has_state = False
        self.last_error = None
        self.game_over = False
        self.game_over_reason = None
        self.game_over_winner = None
        self.seen_craters = set()
        self.explosions = []
        self.explosion_frames = []
        self.explosion_frame_time = cfg.EXPLOSION_FRAME_TIME
        self.explosion_delay = cfg.EXPLOSION_DELAY
        self.last_move_count = 0
        self.move_cooldown = cfg.MOVE_COOLDOWN
        self.move_block_until = 0.0
        self.sfx_explosion = None
        self.sfx_move = []
        self.sfx_capture = []
        self.sfx_click = []
        self.sfx_hover = []
        self.sfx_mine_plant = []
        self.sfx_dice = None
        self.sfx_fire = None
        self.sfx_void = None
        self.sfx_teleport = None
        self.sfx_pistol = None
        self.sfx_nuke_charge = None
        self.sfx_nuke_explosion = None
        self.sfx_clone = None
        self.sfx_chaos_tick = None
        self.sfx_giant_spawn = None
        self.chaos_bucket = 0
        self.game_over_buttons = {}
        self.texture_cache = {}
        self.number_cache = {}
        self.timer_sync_ms = None
        self.timer_sync_time = None
        self.timer_running = False
        self.assets_root = PROJECT_ROOT / "assets"
        self.inventory_slot_image = None
        self.inventory_slot_size = None
        self.intro_played = False
        self.intro_start_time = None
        self.intro_duration = cfg.INTRO_DURATION
        self.intro_frame_paths = []
        self.intro_frame_index = -1
        self.intro_frame_surface = None
        self.intro_frame_time = 1 / 24.0
        self.intro_static_path = self.assets_root / "video" / "intro.png"
        self.intro_frames_dir = self.assets_root / "video" / "intro_frames"
        self.intro_video_path = self.assets_root / "video" / "intro.mp4"
        self.intro_video_cap = None
        self.intro_video_fps = cfg.INTRO_VIDEO_FPS_FALLBACK
        self.intro_video_last_time = 0.0
        self.intro_video_frame_surface = None
        self.intro_video_frame_index = -1
        self.intro_use_video = False
        self.menu_logo_cache = {}
        self.font_cache = {}
        self.local_ip_cache = None
        self.mine_image = None
        self.inventory_bar_image = None
        self.inventory_bar_size = None
        self.inventory_slot_rects = {}
        self.mine_reveals = []
        self.hint_move_surface = None
        self.hint_capture_surface = None
        self.hint_item_surface = None
        self.selected_item_slot = None
        self.item_target_cells = set()
        self.item_target_mode = False
        self.item_target_slot = None
        self.item_texture_cache = {}
        self.effect_texture_cache = {}
        self.button_anim = {}
        self.button_hover_state = {}
        self.prev_state = None
        self.piece_animations = []
        self.hover_cell = None
        self.popup_pattern = None
        self.dt = 0.0
        self.colors = {
            "vanilla_primary": (146, 96, 214),
            "vanilla_secondary": (246, 178, 96),
            "vanilla_bg": (24, 18, 32),
            "vanilla_panel": (36, 28, 50),
            "vanilla_panel_border": (246, 178, 96),
            "vanilla_button_base": (78, 62, 102),
            "vanilla_button_hover": (110, 86, 140),
            "vanilla_button_border": (246, 178, 96),
            "board_light": (236, 224, 242),
            "board_dark": (92, 72, 112),
            "hint_move": (146, 96, 214),
            "hint_capture": (246, 178, 96),
            "hint_item": (110, 150, 90),
            "mine_primary": (90, 130, 80),
            "mine_secondary": (150, 106, 70),
            "mine_bg": (28, 34, 26),
            "chessplus_primary": (242, 224, 178),
            "chessplus_secondary": (210, 186, 120),
            "chessplus_wall": (160, 140, 96),
            "chessplus_bg": (38, 34, 28),
        }
        # Audio settings
        self.audio_ready = False
        self.current_music = None
        self.music_master = 0.6
        self.music_volumes = {
            "menu": 0.7,
            "game": 0.6,
            "win": 0.8,
            "lose": 0.8,
            "chaos": 0.7,
        }
        self.sfx_master = 0.7
        self.sfx_base = {
            "explosion": 0.7,
            "move": 0.5,
            "capture": 0.6,
            "click": 0.5,
            "hover": 0.3,
            "mine_plant": 0.5,
            "dice": 0.55,
            "fire": 0.45,
            "void": 0.6,
            "teleport": 0.6,
            "pistol": 0.6,
            "nuke_charge": 0.75,
            "nuke_explosion": 0.9,
            "clone": 0.6,
            "chaos_tick": 0.6,
            "giant_spawn": 0.7,
        }
        self.music_tracks = {
            "menu": self.assets_root / "sound" / "ost" / "Anarchy-Chess-OST-0-Menu.ogg",
            "game": self.assets_root / "sound" / "ost" / "Anarchy-Chess-OST-1-The-Bad-Calm.ogg",
            "win": self.assets_root / "sound" / "ost" / "Anarchy-Chess-OST-2-Victory.ogg",
            "lose": self.assets_root / "sound" / "ost" / "Anarchy-Chess-OST-3-Defeat.ogg",
            "chaos": self.assets_root / "sound" / "ost" / "Anarchy-Chess-OST-4-Bad-Nine.ogg",
        }
        self.settings_rows = [
            ("music_master", "Гучність музики"),
            ("music_menu", "Музика головного меню"),
            ("music_game", "Музика гри"),
            ("music_result", "Перемога/програш"),
            ("sfx_master", "Гучність ефектів"),
        ]
        # UI params
        self.cell = cfg.TILE_SIZE
        self.margin = cfg.BOARD_MARGIN
        self.board_origin = (self.margin, self.margin)
        self.explosion_size = self.cell * 3
        self.chain_reaction_delay = cfg.CHAIN_REACTION_DELAY
        self.winw = cfg.WINDOW_WIDTH
        self.winh = cfg.WINDOW_HEIGHT
        self.replay_speeds = [("1x", 2.0), ("1.5x", 1.5), ("2x", 1.0), ("0.5x", 4.0)]

    def connect(self):
        self.last_error = None
        connected = False
        for _ in range(20):
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.connect((self.host, cfg.SERVER_PORT))
                connected = True
                break
            except Exception:
                time.sleep(0.2)
        if not connected:
            self.last_error = "Не вдалося під'єднатись до сервера."
            return False

        payload = {"type": "join", "name": self.name}
        if self.mode == "host":
            payload["packs"] = self.get_enabled_pack_ids()
        send_json(self.sock, payload)
        ack = recv_json(self.sock)
        if ack and ack.get('type') == 'join_ack':
            self.my_color = ack.get('color')
            self.connected = True
            print("Ти зайшов за:", self.my_color)
            return True

        self.last_error = "Помилка входу."
        try:
            self.sock.close()
        except Exception:
            pass
        return False

    def start_server_process(self):
        if self.server_process and self.server_process.poll() is None:
            return
        try:
            self.server_process = subprocess.Popen(
                [sys.executable, "-m", "modules.network.server"],
                cwd=str(PROJECT_ROOT)
            )
        except Exception as e:
            self.last_error = "Не вдалося запустити сервер."
            print("Помилка запуску сервера:", e)

    def stop_server_process(self):
        if self.server_process and self.server_process.poll() is None:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=2)
            except Exception:
                self.server_process.kill()
        self.server_process = None

    def disconnect(self):
        self.net_running = False
        try:
            if self.connected:
                send_json(self.sock, {"type":"left"})
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass
        self.connected = False

    def reset_round_state(self):
        self.state = None
        self.my_color = None
        self.connected = False
        self.has_state = False
        self.last_error = None
        self.game_over = False
        self.game_over_reason = None
        self.game_over_winner = None
        self.seen_craters = set()
        self.explosions = []
        self.last_move_count = 0
        self.game_over_buttons = {}
        self.timer_sync_ms = None
        self.timer_sync_time = None
        self.timer_running = False
        self.prev_state = None
        self.piece_animations = []
        self.last_nuke_event_id = 0
        self.clear_item_targeting()
        if hasattr(self, "popup"):
            del self.popup

    def get_enabled_pack_ids(self):
        return [pid for pid, enabled in self.enabled_packs.items() if enabled]

    def try_start_game(self):
        name = self.name_input.strip()
        if not name:
            name = "Player"
        self.name = name
        self.last_name = name

        if self.mode == "host":
            self.host = "127.0.0.1"
            self.start_server_process()
        elif self.mode == "join":
            ip = self.ip_input.strip() or "127.0.0.1"
            self.host = ip
            self.last_ip = ip

        self.disconnect()
        self.reset_round_state()
        self.net_running = True
        if not self.connect():
            self.net_running = False
            return

        t = threading.Thread(target=self.listen_loop, daemon=True)
        t.start()
        self.ui_state = "game"

    def to_menu(self):
        self.disconnect()
        self.reset_round_state()
        self.mode = None
        self.name_input = self.last_name
        self.ip_input = self.last_ip
        self.input_focus = "name"
        self.ui_state = "menu"

    def restart_game(self):
        if self.mode == "host":
            self.start_server_process()
        self.disconnect()
        self.reset_round_state()
        self.name_input = self.last_name
        self.ip_input = self.last_ip
        self.input_focus = "name"
        self.ui_state = "name"

    def shutdown(self):
        self.disconnect()
        self.stop_server_process()
        self.running = False

    def listen_loop(self):
        try:
            while self.net_running:
                msg = recv_json(self.sock)
                if msg is None:
                    print("Сервер від'єднався.")
                    self.net_running = False
                    break
                mtype = msg.get('type')
                if mtype == 'state_update':
                    self.state = GameState.from_dict(msg.get('state'))
                    self.has_state = True
                    self.update_effects_from_state()
                elif mtype == 'popup':
                    # store popup temporarily
                    if self.popups_enabled:
                        self.popup = {"title":msg.get('title'), "message":msg.get('message'), "time": time.time(), "theme": msg.get('theme')}
                elif mtype == 'game_over':
                    print("Кінець гри:", msg.get('reason'))
                    self.game_over = True
                    self.game_over_reason = msg.get('reason')
                    self.game_over_winner = msg.get('winner')
                    self.net_running = False
                elif mtype == 'item_target':
                    slot = msg.get('slot')
                    targets = msg.get('targets', [])
                    self.item_target_cells = set(tuple(t) for t in targets)
                    self.item_target_mode = True
                    self.item_target_slot = slot
                    self.item_target_phase = "cell"
                elif mtype == 'error':
                    self.last_error = msg.get('msg')
                    print("Помилка сервера:", msg.get('msg'))
        except Exception as e:
            print("Помилка прийому:", e)
            self.net_running = False

    def start_ui(self):
        pygame.init()
        self.init_audio()
        screen = pygame.display.set_mode((self.winw, self.winh))
        self.set_window_icon()
        pygame.display.set_caption("Anarchy Chess a-b 0.1")
        self.load_explosion_frames()
        self.load_mine_image()
        self.prepare_intro()
        clock = pygame.time.Clock()
        font = self.get_font("main", 26)
        big_font = self.get_font("main", 32)
        title_font = self.get_font("accent", 48)
        selected = None

        while self.running:
            self.dt = clock.tick(60) / 1000.0
            self.update_shake()
            if self.ui_state == "replay":
                self.update_replay_autoplay()
            mouse_pos = pygame.mouse.get_pos()
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self.shutdown()
                    continue

                if self.ui_state == "intro" and ev.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                    self.finish_intro()
                    continue

                if ev.type == pygame.KEYDOWN and self.ui_state == "name":
                    if ev.key == pygame.K_RETURN:
                        self.try_start_game()
                    elif ev.key == pygame.K_BACKSPACE:
                        if self.input_focus == "ip" and self.mode == "join":
                            self.ip_input = self.ip_input[:-1]
                        else:
                            self.name_input = self.name_input[:-1]
                    elif ev.key == pygame.K_TAB and self.mode == "join":
                        self.input_focus = "ip" if self.input_focus == "name" else "name"
                    else:
                        if ev.unicode and ev.unicode.isprintable():
                            if self.input_focus == "ip" and self.mode == "join":
                                if len(self.ip_input) < 32:
                                    self.ip_input += ev.unicode
                            else:
                                if len(self.name_input) < 16:
                                    self.name_input += ev.unicode

                if ev.type == pygame.KEYDOWN and self.ui_state == "game" and not self.game_over:
                    if pygame.K_1 <= ev.key <= pygame.K_9:
                        slot = ev.key - pygame.K_1
                        self.handle_inventory_key(slot)
                    elif ev.key == pygame.K_ESCAPE:
                        self.clear_item_targeting()

                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    if self.ui_state == "menu":
                        rects = self.menu_buttons()
                        if rects["join"].collidepoint(ev.pos):
                            self.play_sfx_list(self.sfx_click)
                            self.ui_state = "mode"
                        elif rects.get("replay") and rects["replay"].collidepoint(ev.pos):
                            self.play_sfx_list(self.sfx_click)
                            self.enter_replay_mode()
                        elif rects["settings"].collidepoint(ev.pos):
                            self.play_sfx_list(self.sfx_click)
                            self.ui_state = "settings"
                    elif self.ui_state == "mode":
                        rects = self.mode_buttons()
                        if rects["host"].collidepoint(ev.pos):
                            self.play_sfx_list(self.sfx_click)
                            self.mode = "host"
                            self.start_server_process()
                            self.last_error = None
                            self.ui_state = "host_menu"
                        elif rects["join"].collidepoint(ev.pos):
                            self.play_sfx_list(self.sfx_click)
                            self.mode = "join"
                            self.last_error = None
                            self.ui_state = "name"
                        elif rects["back"].collidepoint(ev.pos):
                            self.play_sfx_list(self.sfx_click)
                            self.ui_state = "menu"
                    elif self.ui_state == "host_menu":
                        rects = self.host_menu_buttons()
                        if rects["back"].collidepoint(ev.pos):
                            self.play_sfx_list(self.sfx_click)
                            self.ui_state = "mode"
                        elif rects["continue"].collidepoint(ev.pos):
                            self.play_sfx_list(self.sfx_click)
                            self.ui_state = "name"
                        else:
                            for pack in self.available_packs:
                                pid = pack.get("id")
                                key = f"pack_{pid}"
                                if pid and key in rects and rects[key].collidepoint(ev.pos):
                                    self.play_sfx_list(self.sfx_click)
                                    self.enabled_packs[pid] = not self.enabled_packs.get(pid, True)
                                    break
                    elif self.ui_state == "name":
                        rects = self.name_buttons()
                        if rects["start"].collidepoint(ev.pos):
                            self.play_sfx_list(self.sfx_click)
                            self.try_start_game()
                        elif rects["back"].collidepoint(ev.pos):
                            self.play_sfx_list(self.sfx_click)
                            self.ui_state = "mode"
                        else:
                            if rects["name_input"].collidepoint(ev.pos):
                                self.input_focus = "name"
                            elif self.mode == "join" and rects["ip_input"].collidepoint(ev.pos):
                                self.input_focus = "ip"
                    elif self.ui_state == "settings":
                        rects = self.settings_buttons()
                        if rects["back"].collidepoint(ev.pos):
                            self.play_sfx_list(self.sfx_click)
                            self.ui_state = "menu"
                        else:
                            for key in rects:
                                if key.endswith("_minus") and rects[key].collidepoint(ev.pos):
                                    setting = key[:-6]
                                    self.play_sfx_list(self.sfx_click)
                                    step = self.get_setting_step()
                                    self.adjust_setting(setting, -step)
                                    break
                                if key.endswith("_plus") and rects[key].collidepoint(ev.pos):
                                    setting = key[:-5]
                                    self.play_sfx_list(self.sfx_click)
                                    step = self.get_setting_step()
                                    self.adjust_setting(setting, step)
                                    break
                            if rects.get("popups_toggle") and rects["popups_toggle"].collidepoint(ev.pos):
                                self.play_sfx_list(self.sfx_click)
                                self.popups_enabled = not self.popups_enabled
                    elif self.ui_state == "replay":
                        rects = self.replay_controls()
                        list_rects = self.replay_game_rects or {}
                        scroll_rects = self.replay_scroll_rects or {}
                        if rects.get("back") and rects["back"].collidepoint(ev.pos):
                            self.play_sfx_list(self.sfx_click)
                            self.ui_state = "menu"
                            self.replay_playing = False
                        else:
                            if scroll_rects.get("up") and scroll_rects["up"].collidepoint(ev.pos):
                                self.play_sfx_list(self.sfx_click)
                                self.adjust_replay_scroll(-1)
                                continue
                            if scroll_rects.get("down") and scroll_rects["down"].collidepoint(ev.pos):
                                self.play_sfx_list(self.sfx_click)
                                self.adjust_replay_scroll(1)
                                continue
                            clicked_game = False
                            for idx, r in list_rects.items():
                                if r.collidepoint(ev.pos):
                                    self.play_sfx_list(self.sfx_click)
                                    self.select_replay_game(idx)
                                    clicked_game = True
                                    break
                            if clicked_game:
                                continue
                            if rects.get("first") and rects["first"].collidepoint(ev.pos):
                                self.play_sfx_list(self.sfx_click)
                                self.replay_playing = False
                                first_idx = 1 if self.get_replay_total_moves() > 0 else 0
                                self.set_replay_index(first_idx)
                            elif rects.get("prev") and rects["prev"].collidepoint(ev.pos):
                                self.play_sfx_list(self.sfx_click)
                                self.replay_playing = False
                                self.set_replay_index(self.replay_move_index - 1)
                            elif rects.get("play") and rects["play"].collidepoint(ev.pos):
                                self.play_sfx_list(self.sfx_click)
                                self.toggle_replay_play()
                            elif rects.get("speed") and rects["speed"].collidepoint(ev.pos):
                                self.play_sfx_list(self.sfx_click)
                                self.cycle_replay_speed()
                            elif rects.get("next") and rects["next"].collidepoint(ev.pos):
                                self.play_sfx_list(self.sfx_click)
                                self.replay_playing = False
                                self.set_replay_index(self.replay_move_index + 1)
                            elif rects.get("last") and rects["last"].collidepoint(ev.pos):
                                self.play_sfx_list(self.sfx_click)
                                self.replay_playing = False
                                self.set_replay_index(self.get_replay_total_moves())
                    elif self.ui_state == "game":
                        if time.time() < self.move_block_until:
                            continue
                        if self.game_over:
                            rects = self.game_over_buttons or self.get_game_over_buttons()
                            if rects["exit"].collidepoint(ev.pos):
                                self.play_sfx_list(self.sfx_click)
                                self.shutdown()
                            elif rects["menu"].collidepoint(ev.pos):
                                self.play_sfx_list(self.sfx_click)
                                selected = None
                                self.to_menu()
                            elif rects["restart"].collidepoint(ev.pos):
                                    self.play_sfx_list(self.sfx_click)
                                    selected = None
                                    self.restart_game()
                        elif self.state:
                            if self.handle_inventory_click(ev.pos):
                                continue
                            if self.handle_item_click(ev.pos):
                                continue
                            if self.item_target_mode:
                                continue
                            mx, my = ev.pos
                            display_coord = coord_for_pixel(mx, my, self.get_board_origin(), self.cell)
                            if display_coord:
                                coord = self.display_to_board(display_coord)
                            else:
                                coord = None
                            if coord and coord_in_bounds(*coord):
                                if selected is None:
                                    p = self.state.board.get_piece(*coord)
                                    if p and p.color == self.my_color:
                                        selected = self.get_piece_anchor(coord)
                                else:
                                    send_json(self.sock, {"type":"move","from":[selected[0],selected[1]], "to":[coord[0],coord[1]], "color": self.my_color})
                                    self.move_block_until = time.time() + self.move_cooldown
                                    selected = None

                if ev.type == pygame.MOUSEWHEEL and self.ui_state == "replay":
                    if ev.y != 0:
                        self.adjust_replay_scroll(-ev.y)

                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button in (4, 5) and self.ui_state == "replay":
                    delta = -1 if ev.button == 4 else 1
                    self.adjust_replay_scroll(delta)

            self.sync_music()
            screen.fill(self.colors["vanilla_bg"])

            if self.ui_state == "intro":
                self.draw_intro(screen, font)
            elif self.ui_state == "menu":
                self.draw_menu(screen, title_font, big_font, mouse_pos)
            elif self.ui_state == "mode":
                self.draw_mode_select(screen, big_font, mouse_pos)
            elif self.ui_state == "host_menu":
                self.draw_host_menu(screen, big_font, font, mouse_pos)
            elif self.ui_state == "name":
                self.draw_name_screen(screen, big_font, font, mouse_pos)
            elif self.ui_state == "settings":
                self.draw_settings(screen, big_font, font, mouse_pos)
            elif self.ui_state == "replay":
                self.draw_replay(screen, big_font, font, mouse_pos)
            elif self.ui_state == "game":
                self.game_over_buttons = {}
                self.hover_cell = None
                if not self.game_over:
                    display_coord = coord_for_pixel(mouse_pos[0], mouse_pos[1], self.get_board_origin(), self.cell)
                    if display_coord:
                        coord = self.display_to_board(display_coord)
                        if coord and coord_in_bounds(*coord):
                            self.hover_cell = coord
                hint_moves = set()
                hint_captures = set()
                if self.state and selected is not None:
                    hint_moves, hint_captures = self.get_move_hints(selected)
                if self.item_target_mode:
                    hint_moves = set()
                    hint_captures = set()
                if self.item_target_mode and self.item_target_phase == "piece":
                    item_targets = self.get_my_piece_coords()
                else:
                    item_targets = self.item_target_cells if self.item_target_mode else set()
                self.draw_board_background(screen, selected, hint_moves, hint_captures, item_targets, self.hover_cell)
                if self.state:
                    self.draw_board_pieces(screen)
                    self.draw_mine_reveals(screen)
                    self.draw_piece_animations(screen)
                    self.draw_explosions(screen)
                self.draw_top_bar(screen, font)
                self.draw_right_panel(screen, font, big_font)
                self.draw_inventory_bar(screen)
                if self.game_over:
                    self.draw_game_over(screen, big_font, font, mouse_pos)
                if hasattr(self,'popup'):
                    self.draw_popup(screen, font)

            self.apply_chaos_visuals(screen)
            pygame.display.flip()

        pygame.quit()
        try:
            self.sock.close()
        except:
            pass

    def set_window_icon(self):
        candidates = [
            self.assets_root / "textures" / "ui" / "logo_2.png",
            self.assets_root / "textures" / "logo_2.png",
            self.assets_root / "logo_2.png",
        ]
        for path in candidates:
            if not path.exists():
                continue
            try:
                icon = pygame.image.load(str(path)).convert_alpha()
                pygame.display.set_icon(icon)
                return True
            except Exception:
                continue
        return False

    def menu_buttons(self):
        join_rect = pygame.Rect(self.winw//2 - 120, self.winh//2 - 60, 240, 56)
        replay_rect = pygame.Rect(self.winw//2 - 120, self.winh//2 + 4, 240, 56)
        settings_rect = pygame.Rect(self.winw//2 - 120, self.winh//2 + 68, 240, 56)
        return {"join": join_rect, "replay": replay_rect, "settings": settings_rect}

    def mode_buttons(self):
        w = 200
        h = 56
        gap = 24
        total = w * 2 + gap
        start_x = self.winw//2 - total//2
        y = self.winh//2
        return {
            "host": pygame.Rect(start_x, y, w, h),
            "join": pygame.Rect(start_x + w + gap, y, w, h),
            "back": pygame.Rect(20, 20, 120, 40),
        }

    def host_menu_buttons(self):
        rects = {"back": pygame.Rect(20, 20, 120, 40)}
        layout = self.layout()
        start_y = layout["board_y"] + 80
        row_h = 56
        left_x = layout["board_x"]
        row_w = layout["board_size"]
        for i, pack in enumerate(self.available_packs):
            pid = pack.get("id")
            y = start_y + i * row_h
            rects[f"pack_{pid}"] = pygame.Rect(left_x, y, row_w, 40)
            rects[f"pack_box_{pid}"] = pygame.Rect(left_x + 12, y + 7, 26, 26)
        rects["continue"] = pygame.Rect(self.winw//2 - 120, self.winh - 110, 240, 56)
        return rects

    def name_buttons(self):
        w = 200
        h = 50
        x = self.winw//2 - w//2
        y = self.winh//2 + 60
        name_rect = pygame.Rect(self.winw//2 - 160, self.winh//2 - 20, 320, 44)
        ip_rect = pygame.Rect(self.winw//2 - 160, self.winh//2 + 34, 320, 44)
        return {
            "start": pygame.Rect(x, y + 50, w, h),
            "back": pygame.Rect(20, 20, 120, 40),
            "name_input": name_rect,
            "ip_input": ip_rect,
        }

    def get_game_over_buttons(self):
        w = 180
        h = 46
        gap = 16
        total = w * 3 + gap * 2
        start_x = self.winw//2 - total//2
        y = self.winh//2 + 80
        return {
            "exit": pygame.Rect(start_x, y, w, h),
            "menu": pygame.Rect(start_x + w + gap, y, w, h),
            "restart": pygame.Rect(start_x + (w + gap) * 2, y, w, h),
        }

    def draw_button(self, screen, rect, text, font, key, hover=False):
        if key not in self.button_anim:
            self.button_anim[key] = 0.0
        anim = self.button_anim[key]
        target = 1.0 if hover else 0.0
        prev_hover = self.button_hover_state.get(key, False)
        if hover and not prev_hover:
            self.play_sfx_list(self.sfx_hover)
        self.button_hover_state[key] = hover
        speed = 8.0
        step = speed * self.dt
        if anim < target:
            anim = min(target, anim + step)
        else:
            anim = max(target, anim - step)
        self.button_anim[key] = anim

        pressed = hover and pygame.mouse.get_pressed(num_buttons=3)[0]
        press = 1.0 if pressed else 0.0

        base = self.colors["vanilla_button_base"]
        hover_col = self.colors["vanilla_button_hover"]
        col = (
            int(base[0] + (hover_col[0] - base[0]) * anim),
            int(base[1] + (hover_col[1] - base[1]) * anim),
            int(base[2] + (hover_col[2] - base[2]) * anim),
        )
        if press:
            col = (max(0, col[0] - 20), max(0, col[1] - 20), max(0, col[2] - 20))

        scale = 1.0 + 0.03 * anim - 0.05 * press
        draw_rect = rect.copy()
        draw_rect.width = int(rect.width * scale)
        draw_rect.height = int(rect.height * scale)
        draw_rect.center = rect.center

        pygame.draw.rect(screen, col, draw_rect, border_radius=8)
        pygame.draw.rect(screen, self.colors["vanilla_button_border"], draw_rect, 2, border_radius=8)
        txt = self.fit_text_surface(font, text, draw_rect.width - 16, (255, 255, 255), max_height=draw_rect.height - 8)
        screen.blit(txt, txt.get_rect(center=draw_rect.center))

    def fit_text_surface(self, font, text, max_width, color, max_height=None):
        surf = font.render(text, True, color)
        if max_width <= 0:
            return surf
        scale_w = max_width / max(1, surf.get_width())
        scale_h = None
        if max_height is not None and max_height > 0:
            scale_h = max_height / max(1, surf.get_height())
        scale = scale_w if scale_h is None else min(scale_w, scale_h)
        if scale >= 1.0:
            return surf
        new_w = max(1, int(surf.get_width() * scale))
        new_h = max(1, int(surf.get_height() * scale))
        return pygame.transform.smoothscale(surf, (new_w, new_h))

    def get_font(self, kind, size):
        key = (kind, size)
        if key in self.font_cache:
            return self.font_cache[key]
        if kind == "accent":
            font_name = cfg.FONT_ACCENT_NAME
            font_file = cfg.FONT_ACCENT_FILE
        elif kind == "uses":
            font_name = getattr(cfg, "FONT_USES_NAME", cfg.FONT_MAIN_NAME)
            font_file = getattr(cfg, "FONT_USES_FILE", cfg.FONT_MAIN_FILE)
        else:
            font_name = cfg.FONT_MAIN_NAME
            font_file = cfg.FONT_MAIN_FILE
        path = self.assets_root / "fonts" / font_file
        font = None
        if path.exists():
            try:
                font = pygame.font.Font(str(path), size)
            except Exception:
                font = None
        if font is None:
            font = pygame.font.SysFont(font_name, size)
        self.font_cache[key] = font
        return font

    def fit_surface(self, surf, max_w, max_h):
        if surf is None:
            return surf
        if surf.get_width() <= max_w and surf.get_height() <= max_h:
            return surf
        scale = min(max_w / max(1, surf.get_width()), max_h / max(1, surf.get_height()))
        new_w = max(1, int(surf.get_width() * scale))
        new_h = max(1, int(surf.get_height() * scale))
        try:
            return pygame.transform.smoothscale(surf, (new_w, new_h))
        except Exception:
            return surf

    def get_local_ip(self):
        if self.local_ip_cache:
            return self.local_ip_cache
        ip = "127.0.0.1"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
        except Exception:
            try:
                ip = socket.gethostbyname(socket.gethostname())
            except Exception:
                ip = "127.0.0.1"
        self.local_ip_cache = ip
        return ip

    def draw_menu(self, screen, title_font, font, mouse_pos):
        title = title_font.render("Anarchy Chess", True, self.colors["vanilla_secondary"])
        screen.blit(title, title.get_rect(center=(self.winw//2, self.winh//2 - 120)))
        rects = self.menu_buttons()
        self.draw_button(screen, rects["join"], "Join", font, "menu_join", rects["join"].collidepoint(mouse_pos))
        self.draw_button(screen, rects["replay"], "Replay", font, "menu_replay", rects["replay"].collidepoint(mouse_pos))
        self.draw_button(screen, rects["settings"], "Налаштування", font, "menu_settings", rects["settings"].collidepoint(mouse_pos))
        self.draw_menu_footer(screen, font)

    def get_menu_logo_images(self, size):
        key = ("menu_logos", size)
        if key in self.menu_logo_cache:
            return self.menu_logo_cache[key]
        names = ["logo_1.png", "logo_2.png", "logo_3.png"]
        imgs = []
        for name in names:
            path = self.assets_root / "textures" / "ui" / name
            if not path.exists():
                continue
            try:
                img = pygame.image.load(str(path)).convert_alpha()
                img = pygame.transform.smoothscale(img, (size, size))
                imgs.append(img)
            except Exception:
                continue
        self.menu_logo_cache[key] = imgs
        return imgs

    def draw_menu_footer(self, screen, font):
        text = font.render('Made by Zahar "kitplay"', True, (200, 200, 200))
        logo_size = 28
        gap = 8
        padding = 12
        logos = self.get_menu_logo_images(logo_size)
        logos_w = sum(img.get_width() for img in logos) + gap * max(0, len(logos) - 1)
        base_y = self.winh - padding
        if logos:
            x = self.winw - padding - logos_w
            y = base_y - logo_size
            for img in logos:
                screen.blit(img, (x, y))
                x += img.get_width() + gap
            text_y = y - 6 - text.get_height()
        else:
            text_y = base_y - text.get_height()
        text_x = self.winw - padding - text.get_width()
        screen.blit(text, (text_x, text_y))

    def enter_replay_mode(self):
        self.load_replay_games()
        if self.replay_games:
            self.select_replay_game(0)
        else:
            self.replay_states = []
            self.replay_state = None
            self.replay_move_index = 0
        self.replay_playing = False
        self.replay_speed_index = 0
        self.replay_next_time = 0.0
        self.replay_list_offset = 0
        self.piece_animations = []
        self.ui_state = "replay"

    def load_replay_games(self):
        self.replay_games = []
        logs_dir = PROJECT_ROOT / "data" / "match_logs"
        if not logs_dir.exists():
            return
        files = list(logs_dir.glob("game_*.json"))
        def game_num(p):
            m = re.search(r"game_(\\d+)", p.stem)
            return int(m.group(1)) if m else 0
        files.sort(key=game_num, reverse=True)
        for path in files:
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            events = data.get("events", [])
            moves = [e for e in events if e.get("type") == "move"]
            game_over = None
            for e in events:
                if e.get("type") == "game_over":
                    game_over = e
            self.replay_games.append({
                "path": path,
                "game_id": data.get("game_id"),
                "started_at": data.get("started_at", ""),
                "players": data.get("players", {}),
                "events": events,
                "move_total": len(moves),
                "game_over": game_over,
            })

    def select_replay_game(self, index):
        if not self.replay_games:
            return
        index = max(0, min(index, len(self.replay_games) - 1))
        self.replay_selected = index
        game = self.replay_games[index]
        self.replay_states = self.build_replay_states(game.get("events", []))
        self.replay_move_index = 0
        self.replay_state = self.snapshot_state(self.replay_states[0]) if self.replay_states else None
        self.replay_playing = False
        self.replay_next_time = time.time()
        self.replay_list_offset = 0
        self.piece_animations = []
        self.explosions = []
        self.mine_reveals = []

    def build_replay_states(self, events):
        state = GameState()
        state.setup_starting_position()
        states = [self.snapshot_state(state)]
        last_move_no = None
        for i, entry in enumerate(events):
            move_no = entry.get("move")
            if move_no is not None and last_move_no is not None and move_no != last_move_no:
                self.advance_replay_temporary_effects(state)
            etype = entry.get("type")
            if etype == "move":
                frm = entry.get("from")
                to = entry.get("to")
                if isinstance(frm, list) and isinstance(to, list) and len(frm) == 2 and len(to) == 2:
                    try:
                        apply_move(state, (int(frm[0]), int(frm[1])), (int(to[0]), int(to[1])))
                    except Exception:
                        pass
                if move_no is not None:
                    state.move_count = int(move_no)
            elif etype == "event":
                self.apply_replay_event(state, entry)
            if move_no is not None:
                last_move_no = move_no
            next_move = events[i + 1].get("move") if i + 1 < len(events) else None
            if move_no is not None and move_no != next_move:
                states.append(self.snapshot_state(state))
        game_over = None
        for entry in events:
            if entry.get("type") == "game_over":
                game_over = entry
        if game_over:
            final_position = game_over.get("final_position")
            final_move = game_over.get("final_move")
            if isinstance(final_position, dict):
                final_state = self.state_from_position(final_position)
                if final_move is not None:
                    final_state.move_count = int(final_move)
                if states and final_move is not None and states[-1].move_count == int(final_move):
                    states[-1] = self.snapshot_state(final_state)
                else:
                    states.append(self.snapshot_state(final_state))
        return states

    def state_from_position(self, position):
        state = GameState()
        if not isinstance(position, dict):
            return state
        board = position.get("board", [])
        pieces_by_gid = {}
        for y in range(8):
            for x in range(8):
                cell = None
                if y < len(board) and x < len(board[y]):
                    cell = board[y][x]
                if cell:
                    gid = cell.get("gid") if isinstance(cell, dict) else None
                    if gid is not None and gid in pieces_by_gid:
                        p = pieces_by_gid[gid]
                    else:
                        p = Piece(cell.get("ptype"), cell.get("color"), pid=gid, size=cell.get("size"), anchor=cell.get("anchor"))
                        if gid is not None:
                            pieces_by_gid[gid] = p
                    state.board.set_piece(x, y, p)
        if "mines" in position:
            state.mines = position.get("mines")
        if "revealed" in position:
            state.revealed = position.get("revealed")
        if "adj_counts" in position:
            state.adj_counts = position.get("adj_counts")
        craters = position.get("craters")
        if craters:
            state.craters = set(tuple(c) for c in craters)
        if "chessplus_cells" in position:
            state.chessplus_cells = position.get("chessplus_cells")
        if "chessplus_walls" in position:
            state.chessplus_walls = position.get("chessplus_walls")
        if "chessplus_bombs" in position:
            state.chessplus_bombs = position.get("chessplus_bombs")
        if "chessplus_void" in position:
            state.chessplus_void = position.get("chessplus_void")
        if "chessplus_mutations" in position:
            state.chessplus_mutations = position.get("chessplus_mutations")
        if "chessplus_clones" in position:
            state.chessplus_clones = position.get("chessplus_clones")
        if "chessplus_nukes" in position:
            state.chessplus_nukes = position.get("chessplus_nukes")
        return state

    def snapshot_state(self, state):
        try:
            return GameState.from_dict(copy.deepcopy(state.to_dict()))
        except Exception:
            return GameState.from_dict(state.to_dict())

    def advance_replay_temporary_effects(self, state):
        temp = getattr(state, "temp_reveal", None)
        if temp and temp.get("remaining_moves", 0) > 0:
            temp["remaining_moves"] = max(0, int(temp.get("remaining_moves", 0)) - 1)
            if temp["remaining_moves"] == 0:
                temp["cells"] = []
        vision = getattr(state, "mine_vision", None)
        if vision:
            for color in ("white", "black"):
                if vision.get(color, 0) > 0:
                    vision[color] = max(0, int(vision.get(color, 0)) - 1)

    def trigger_replay_explosions(self, prev_state, new_state):
        prev_craters = set(getattr(prev_state, "craters", set()) or set())
        new_craters = set(getattr(new_state, "craters", set()) or set())
        added = new_craters - prev_craters
        if not added:
            return
        prev = self.state
        self.state = new_state
        for coord in added:
            self.handle_crater(coord)
        self.state = prev

    def set_replay_index(self, index):
        total = self.get_replay_total_moves()
        index = max(0, min(index, total))
        prev_index = self.replay_move_index
        prev_state = self.replay_state
        self.replay_move_index = index
        if self.replay_states and index < len(self.replay_states):
            new_state = self.snapshot_state(self.replay_states[index])
            if prev_state and new_state and abs(index - prev_index) == 1:
                move_info = self.detect_moved_piece(prev_state, new_state)
                if move_info:
                    fx, fy, tx, ty, piece, _ = move_info
                    prev_color = self.my_color
                    self.my_color = "white"
                    self.start_piece_animation(fx, fy, tx, ty, piece)
                    self.my_color = prev_color
                self.trigger_replay_explosions(prev_state, new_state)
            else:
                self.piece_animations = []
                self.explosions = []
                self.mine_reveals = []
            self.replay_state = new_state

    def get_replay_total_moves(self):
        if not self.replay_states:
            return 0
        return max(0, len(self.replay_states) - 1)

    def toggle_replay_play(self):
        if self.get_replay_total_moves() == 0:
            return
        if self.replay_move_index >= self.get_replay_total_moves():
            self.set_replay_index(0)
        self.replay_playing = not self.replay_playing
        if self.replay_playing:
            _, interval = self.replay_speeds[self.replay_speed_index]
            self.replay_next_time = time.time() + interval

    def cycle_replay_speed(self):
        self.replay_speed_index = (self.replay_speed_index + 1) % len(self.replay_speeds)
        if self.replay_playing:
            _, interval = self.replay_speeds[self.replay_speed_index]
            self.replay_next_time = time.time() + interval

    def update_replay_autoplay(self):
        if not self.replay_playing:
            return
        if self.replay_move_index >= self.get_replay_total_moves():
            self.replay_playing = False
            return
        label, interval = self.replay_speeds[self.replay_speed_index]
        now = time.time()
        if now >= self.replay_next_time:
            self.set_replay_index(self.replay_move_index + 1)
            self.replay_next_time = now + interval

    def replay_controls(self):
        layout = self.replay_layout()
        board_x = layout["board_x"]
        board_y = layout["board_y"]
        board_size = layout["board_size"]
        gap = 10
        btn_h = 44
        widths = [64, 64, 110, 64, 64, 64]
        total = sum(widths) + gap * (len(widths) - 1)
        x = board_x + (board_size - total) // 2
        y = board_y + board_size + 24
        rects = {}
        rects["first"] = pygame.Rect(x, y, widths[0], btn_h)
        rects["prev"] = pygame.Rect(x + (widths[0] + gap), y, widths[1], btn_h)
        rects["play"] = pygame.Rect(x + (widths[0] + gap) + (widths[1] + gap), y, widths[2], btn_h)
        rects["speed"] = pygame.Rect(x + (widths[0] + gap) + (widths[1] + gap) + (widths[2] + gap), y, widths[3], btn_h)
        rects["next"] = pygame.Rect(x + (widths[0] + gap) + (widths[1] + gap) + (widths[2] + gap) + (widths[3] + gap), y, widths[4], btn_h)
        rects["last"] = pygame.Rect(x + (widths[0] + gap) + (widths[1] + gap) + (widths[2] + gap) + (widths[3] + gap) + (widths[4] + gap), y, widths[5], btn_h)
        rects["back"] = pygame.Rect(20, 20, 120, 40)
        return rects

    def replay_list_layout(self):
        layout = self.replay_layout()
        panel = layout["panel_rect"]
        list_x = panel.x + 12
        list_y = panel.y + 70
        list_w = panel.width - 24
        row_h = 56
        result_h = 170
        list_bottom = panel.bottom - result_h - 12
        visible = max(1, int((list_bottom - list_y) // row_h)) if list_bottom > list_y else 1
        max_offset = max(0, len(self.replay_games) - visible)
        return {
            "panel": panel,
            "list_x": list_x,
            "list_y": list_y,
            "list_w": list_w,
            "row_h": row_h,
            "list_bottom": list_bottom,
            "result_h": result_h,
            "visible": visible,
            "max_offset": max_offset,
        }

    def adjust_replay_scroll(self, delta):
        layout = self.replay_list_layout()
        max_offset = layout["max_offset"]
        self.replay_list_offset = max(0, min(self.replay_list_offset + delta, max_offset))

    def draw_replay(self, screen, big_font, font, mouse_pos):
        screen.fill(self.colors["vanilla_bg"])
        title = big_font.render("Replay", True, self.colors["vanilla_secondary"])
        screen.blit(title, (20, 20))

        rects = self.replay_controls()
        self.draw_button(screen, rects["back"], "Назад", font, "replay_back", rects["back"].collidepoint(mouse_pos))

        # draw board
        prev_state = self.state
        prev_color = self.my_color
        self.state = self.replay_state
        self.my_color = "white"
        self.hover_cell = None
        self.draw_board_background(screen, None, set(), set(), set(), None)
        if self.state:
            self.draw_board_pieces(screen)
            self.draw_mine_reveals(screen)
            self.draw_piece_animations(screen)
            self.draw_explosions(screen)
        self.state = prev_state
        self.my_color = prev_color

        # controls
        play_label = "PLAY" if not self.replay_playing else "PAUSE"
        speed_label = self.replay_speeds[self.replay_speed_index][0]
        self.draw_button(screen, rects["first"], "<<", font, "replay_first", rects["first"].collidepoint(mouse_pos))
        self.draw_button(screen, rects["prev"], "<", font, "replay_prev", rects["prev"].collidepoint(mouse_pos))
        self.draw_button(screen, rects["play"], play_label, font, "replay_play", rects["play"].collidepoint(mouse_pos))
        self.draw_button(screen, rects["speed"], speed_label, font, "replay_speed", rects["speed"].collidepoint(mouse_pos))
        self.draw_button(screen, rects["next"], ">", font, "replay_next", rects["next"].collidepoint(mouse_pos))
        self.draw_button(screen, rects["last"], ">>", font, "replay_last", rects["last"].collidepoint(mouse_pos))

        # move counter
        total = self.get_replay_total_moves()
        move_txt = font.render(f"Хід: {self.replay_move_index}/{total}", True, (220, 220, 220))
        screen.blit(move_txt, move_txt.get_rect(center=(self.winw // 2, rects["first"].bottom + 24)))

        # game list
        layout = self.replay_list_layout()
        panel = layout["panel"]
        list_x = layout["list_x"]
        list_y = layout["list_y"]
        list_w = layout["list_w"]
        row_h = layout["row_h"]
        list_bottom = layout["list_bottom"]
        visible = layout["visible"]
        max_offset = layout["max_offset"]
        self.replay_list_offset = max(0, min(self.replay_list_offset, max_offset))
        result_rect = pygame.Rect(panel.x + 12, panel.bottom - layout["result_h"] - 12, panel.width - 24, layout["result_h"])
        self.replay_game_rects = {}
        list_title = font.render("Партії", True, self.colors["vanilla_secondary"])
        screen.blit(list_title, (panel.x + 12, panel.y + 18))

        self.replay_scroll_rects = {}
        if max_offset > 0:
            up_rect = pygame.Rect(panel.right - 44, panel.y + 16, 18, 18)
            down_rect = pygame.Rect(panel.right - 22, panel.y + 16, 18, 18)
            self.replay_scroll_rects = {"up": up_rect, "down": down_rect}
            up_enabled = self.replay_list_offset > 0
            down_enabled = self.replay_list_offset < max_offset
            up_col = self.colors["vanilla_button_hover"] if up_enabled else (60, 60, 60)
            down_col = self.colors["vanilla_button_hover"] if down_enabled else (60, 60, 60)
            pygame.draw.rect(screen, up_col, up_rect, border_radius=4)
            pygame.draw.rect(screen, down_col, down_rect, border_radius=4)
            pygame.draw.rect(screen, self.colors["vanilla_button_border"], up_rect, 1, border_radius=4)
            pygame.draw.rect(screen, self.colors["vanilla_button_border"], down_rect, 1, border_radius=4)
            up_txt = font.render("▲", True, (220, 220, 220))
            down_txt = font.render("▼", True, (220, 220, 220))
            screen.blit(up_txt, up_txt.get_rect(center=up_rect.center))
            screen.blit(down_txt, down_txt.get_rect(center=down_rect.center))

        if not self.replay_games:
            msg = font.render("Немає збережених ігор", True, (180, 180, 180))
            screen.blit(msg, (list_x, list_y + 8))
            return

        start_idx = self.replay_list_offset
        for i in range(visible):
            idx = start_idx + i
            if idx >= len(self.replay_games):
                break
            game = self.replay_games[idx]
            y = list_y + i * row_h
            row_rect = pygame.Rect(list_x, y, list_w, row_h - 8)
            self.replay_game_rects[idx] = row_rect
            hovered = row_rect.collidepoint(mouse_pos)
            selected = (idx == self.replay_selected)
            bg = (60, 50, 80) if hovered else (52, 42, 70)
            if selected:
                bg = (76, 60, 100)
            pygame.draw.rect(screen, bg, row_rect, border_radius=8)
            pygame.draw.rect(screen, self.colors["vanilla_button_border"], row_rect, 2, border_radius=8)

            gid = game.get("game_id")
            players = game.get("players", {})
            white = players.get("white") or "White"
            black = players.get("black") or "Black"
            title_text = f"#{gid} {white} vs {black}" if gid is not None else f"{white} vs {black}"
            title_surf = self.fit_text_surface(font, title_text, row_rect.width - 16, (230, 230, 230), max_height=22)
            screen.blit(title_surf, (row_rect.x + 8, row_rect.y + 6))

            sub = game.get("started_at") or ""
            if sub:
                sub_surf = self.fit_text_surface(font, sub, row_rect.width - 16, (180, 180, 180), max_height=20)
                screen.blit(sub_surf, (row_rect.x + 8, row_rect.y + 28))

        self.draw_replay_result_panel(screen, font, result_rect)

    def draw_replay_result_panel(self, screen, font, rect):
        pygame.draw.rect(screen, (48, 40, 66), rect, border_radius=8)
        pygame.draw.rect(screen, self.colors["vanilla_button_border"], rect, 2, border_radius=8)
        title = font.render("Результат", True, self.colors["vanilla_secondary"])
        screen.blit(title, (rect.x + 10, rect.y + 8))
        body_font = self.get_font("main", 18)

        game_over = None
        if self.replay_games and 0 <= self.replay_selected < len(self.replay_games):
            game_over = self.replay_games[self.replay_selected].get("game_over")

        y = rect.y + 32
        if not game_over:
            msg = body_font.render("Немає даних про кінець гри", True, (180, 180, 180))
            screen.blit(msg, (rect.x + 10, y))
            return

        final_move = game_over.get("final_move")
        if final_move is not None:
            line = body_font.render(f"Фінальний хід: {final_move}", True, (210, 210, 210))
            screen.blit(line, (rect.x + 10, y))
            y += 20
        final_move_text = game_over.get("final_move_text")
        if final_move_text:
            lines = self.clamp_wrapped_lines(final_move_text, body_font, rect.width - 20, 2)
            for line in lines:
                surf = body_font.render(line, True, (180, 180, 180))
                screen.blit(surf, (rect.x + 10, y))
                y += 18

        comment = game_over.get("comment") or ""
        if comment:
            score_h = body_font.get_height() + 6
            available = max(0, rect.bottom - score_h - y - 6)
            max_lines = max(1, available // max(1, body_font.get_height()))
            lines = self.clamp_wrapped_lines(comment, body_font, rect.width - 20, max_lines)
            for line in lines:
                surf = body_font.render(line, True, (190, 190, 190))
                screen.blit(surf, (rect.x + 10, y))
                y += 18

        final_score = game_over.get("final_score")
        if isinstance(final_score, dict):
            royals = final_score.get("royals", {})
            material = final_score.get("material", {})
            score_text = (
                f"Рахунок: королівські {royals.get('white', 0)}-{royals.get('black', 0)}, "
                f"матеріал {material.get('white', 0)}-{material.get('black', 0)}"
            )
            sc = self.fit_text_surface(body_font, score_text, rect.width - 20, (200, 200, 200), max_height=18)
            screen.blit(sc, (rect.x + 10, rect.bottom - 24))

    def apply_replay_event(self, state, entry):
        name = entry.get("name") or ""
        target = entry.get("target")
        extra = entry.get("extra") or ""
        coords = self.extract_coords(target)
        def clear_at(x, y):
            if hasattr(state.board, "clear_piece"):
                state.board.clear_piece(x, y)
            else:
                state.board.set_piece(x, y, None)

        if name in ("SpawnMine", "SpawnMines", "PlaceMine"):
            for (x, y) in coords:
                if 0 <= x < 8 and 0 <= y < 8:
                    state.mines[y][x] = 1
                    clear_reveal_on_mine(state, x, y)
            compute_adj_counts(state)
            reveal_numbers_under_pieces(state, duration_moves=2)
            return

        if name == "RevealNumbers":
            cells = []
            for (x, y) in coords:
                if 0 <= x < 8 and 0 <= y < 8:
                    cells.append([x, y])
            state.temp_reveal = {"cells": cells, "remaining_moves": 2 if cells else 0}
            return

        if name == "Explosion":
            for (x, y) in coords:
                self.apply_replay_explosion(state, (x, y), radius=1)
            return

        if name == "Nuke":
            if "detonate" in str(extra):
                for (x, y) in coords:
                    self.apply_replay_explosion(state, (x, y), radius=2)
                nukes = getattr(state, "chessplus_nukes", None)
                if nukes is not None and coords:
                    remaining = []
                    for nuke in nukes:
                        center = nuke.get("center") if isinstance(nuke, dict) else None
                        if center and tuple(center) in coords:
                            continue
                        remaining.append(nuke)
                    state.chessplus_nukes = remaining
                return
            if "armed" in str(extra):
                for (x, y) in coords:
                    state.chessplus_nukes.append({"center": [x, y], "timer": 5})
                return

        if name == "DiceTile":
            for (x, y) in coords:
                state.chessplus_cells[y][x] = "dice"
            return
        if name in ("FireTile", "Fire"):
            for (x, y) in coords:
                state.chessplus_cells[y][x] = "fire"
                if name == "Fire":
                    state.chessplus_burning[self.pos_key(x, y)] = 2
            return
        if name in ("BombTile", "Bomb"):
            for (x, y) in coords:
                state.chessplus_cells[y][x] = "bomb"
                if name == "Bomb" and "armed" in str(extra):
                    state.chessplus_bombs[self.pos_key(x, y)] = 1
            return
        if name == "SwapTile":
            for (x, y) in coords:
                state.chessplus_cells[y][x] = "swap"
            return
        if name == "Wall":
            if len(coords) >= 2:
                x1, y1 = coords[0]
                x2, y2 = coords[1]
                state.chessplus_walls.append([x1, y1, x2, y2])
            return
        if name == "Void":
            for (x, y) in coords:
                if 0 <= x < 8 and 0 <= y < 8:
                    state.chessplus_cells[y][x] = "void"
                    clear_at(x, y)
            return
        if name == "Swap" and len(coords) >= 2:
            (ax, ay), (bx, by) = coords[0], coords[1]
            pa = state.board.get_piece(ax, ay)
            pb = state.board.get_piece(bx, by)
            state.board.set_piece(ax, ay, pb)
            state.board.set_piece(bx, by, pa)
            return
        if name == "Teleport" and len(coords) >= 2:
            (sx, sy), (tx, ty) = coords[0], coords[1]
            p = state.board.get_piece(sx, sy)
            if p:
                state.board.move_piece((sx, sy), (tx, ty))
            return
        if name == "Pistol":
            hit_coords = self.extract_coords(extra)
            if hit_coords:
                x, y = hit_coords[0]
                clear_at(x, y)
            return
        if name == "Burn":
            if coords:
                x, y = coords[0]
                clear_at(x, y)
                state.chessplus_burning.pop(self.pos_key(x, y), None)
            return
        if name == "Clone":
            if "expired" in str(extra):
                if coords:
                    x, y = coords[0]
                    clear_at(x, y)
                    state.chessplus_clones.pop(self.pos_key(x, y), None)
            elif len(coords) >= 2:
                (sx, sy), (tx, ty) = coords[0], coords[1]
                p = state.board.get_piece(sx, sy)
                if p:
                    size = max(1, int(getattr(p, "size", 1)))
                    new_piece = Piece(p.ptype, p.color, size=size, anchor=(tx, ty))
                    if hasattr(state.board, "place_piece"):
                        state.board.place_piece(new_piece, (tx, ty))
                    else:
                        state.board.set_piece(tx, ty, new_piece)
                    state.chessplus_clones[self.pos_key(tx, ty)] = 3
            return
        if name == "SpawnPiece":
            if coords:
                x, y = coords[0]
                extra_text = str(extra)
                color = None
                ptype = None
                if ":" in extra_text:
                    color, ptype = extra_text.split(":", 1)
                if ptype and color:
                    size = piece_size(ptype)
                    new_piece = Piece(ptype, color, size=size, anchor=(x, y))
                    if hasattr(state.board, "place_piece"):
                        state.board.place_piece(new_piece, (x, y))
                    else:
                        state.board.set_piece(x, y, new_piece)
            return
        if name == "ChangePiece":
            if coords:
                x, y = coords[0]
                p = state.board.get_piece(x, y)
                if p:
                    change_text = str(extra)
                    if ":" in change_text:
                        _, change_text = change_text.split(":", 1)
                    if "->" in change_text:
                        new_type = change_text.split("->")[-1].strip()
                        anchor = getattr(p, "anchor", None)
                        if anchor is None and hasattr(state.board, "find_piece_anchor"):
                            anchor = state.board.find_piece_anchor(p)
                        if anchor is None:
                            anchor = (x, y)
                        state.board.clear_piece(anchor[0], anchor[1])
                        apply_piece_type(p, new_type, anchor=anchor)
                        state.board.place_piece(p, anchor)
            return
        if name == "PawnMutation":
            if coords:
                muts = getattr(state, "chessplus_mutations", None)
                if muts is None:
                    state.chessplus_mutations = {}
                    muts = state.chessplus_mutations
                for (x, y) in coords:
                    muts[self.pos_key(x, y)] = "backstep"
            return
        if name == "Promotion":
            if coords:
                x, y = coords[0]
                p = state.board.get_piece(x, y)
                if p:
                    apply_piece_type(p, "queen", anchor=(x, y))
            return
        if name == "Dice":
            if coords:
                x, y = coords[0]
                p = state.board.get_piece(x, y)
                if "removed" in str(extra):
                    clear_at(x, y)
                elif "->" in str(extra) and p:
                    new_type = str(extra).split("->")[-1].strip()
                    anchor = getattr(p, "anchor", None)
                    if anchor is None and hasattr(state.board, "find_piece_anchor"):
                        anchor = state.board.find_piece_anchor(p)
                    if anchor is None:
                        anchor = (x, y)
                    state.board.clear_piece(anchor[0], anchor[1])
                    apply_piece_type(p, new_type, anchor=anchor)
                    state.board.place_piece(p, anchor)
            return
        if name == "Toxic":
            if coords and "removed" in str(extra):
                x, y = coords[0]
                clear_at(x, y)
            return

    def apply_replay_explosion(self, state, center, radius=1):
        cx, cy = center
        if radius <= 1:
            try:
                trigger_mine(state, cx, cy)
            except Exception:
                pass
            return
        for x in range(cx - radius, cx + radius + 1):
            for y in range(cy - radius, cy + radius + 1):
                if 0 <= x < 8 and 0 <= y < 8:
                    if hasattr(state.board, "clear_piece"):
                        state.board.clear_piece(x, y)
                    else:
                        state.board.set_piece(x, y, None)
                    state.mines[y][x] = 0
                    state.revealed[y][x] = 0
        state.craters.add((cx, cy))
        compute_adj_counts(state)

    def extract_coords(self, value):
        coords = []
        if value is None:
            return coords
        if isinstance(value, (list, tuple)):
            if len(value) == 2 and all(isinstance(v, int) for v in value):
                return [tuple(value)]
            for item in value:
                coords.extend(self.extract_coords(item))
            return coords
        if isinstance(value, str):
            matches = re.findall(r"[a-h][1-8]", value)
            for m in matches:
                coord = self.coord_from_alg(m)
                if coord is not None:
                    coords.append(coord)
        return coords

    def coord_from_alg(self, alg):
        try:
            file = alg[0].lower()
            rank = int(alg[1:])
            x = ord(file) - ord('a')
            y = rank - 1
            if 0 <= x < 8 and 0 <= y < 8:
                return (x, y)
        except Exception:
            return None
        return None

    def draw_mode_select(self, screen, font, mouse_pos):
        title = font.render("Оберіть режим", True, self.colors["vanilla_secondary"])
        screen.blit(title, title.get_rect(center=(self.winw//2, self.winh//2 - 60)))
        rects = self.mode_buttons()
        self.draw_button(screen, rects["host"], "Host", font, "mode_host", rects["host"].collidepoint(mouse_pos))
        self.draw_button(screen, rects["join"], "Join", font, "mode_join", rects["join"].collidepoint(mouse_pos))
        self.draw_button(screen, rects["back"], "Назад", font, "mode_back", rects["back"].collidepoint(mouse_pos))

    def draw_host_menu(self, screen, big_font, font, mouse_pos):
        title = big_font.render("Меню хоста", True, self.colors["vanilla_secondary"])
        screen.blit(title, title.get_rect(center=(self.winw//2, 90)))
        subtitle = font.render("Оберіть активні DLC-паки", True, (200, 200, 200))
        screen.blit(subtitle, subtitle.get_rect(center=(self.winw//2, 130)))
        ip_text = font.render(f"IP хоста: {self.get_local_ip()}", True, (200, 200, 200))
        screen.blit(ip_text, ip_text.get_rect(center=(self.winw//2, 155)))

        rects = self.host_menu_buttons()
        layout = self.layout()
        start_y = layout["board_y"] + 80
        row_h = 56
        left_x = layout["board_x"]
        box_size = 26

        for i, pack in enumerate(self.available_packs):
            pid = pack.get("id")
            name = pack.get("name", pid or "DLC")
            y = start_y + i * row_h
            row_rect = rects.get(f"pack_{pid}")
            box_rect = rects.get(f"pack_box_{pid}")
            if not row_rect or not box_rect:
                continue
            hovered = row_rect.collidepoint(mouse_pos)
            bg_col = (58, 48, 74) if hovered else (50, 40, 64)
            pygame.draw.rect(screen, bg_col, row_rect, border_radius=8)
            pygame.draw.rect(screen, self.colors["vanilla_button_border"], row_rect, 2, border_radius=8)

            enabled = self.enabled_packs.get(pid, True)
            pygame.draw.rect(screen, (30, 30, 30), box_rect, border_radius=4)
            pygame.draw.rect(screen, self.colors["vanilla_button_border"], box_rect, 2, border_radius=4)
            if enabled:
                pygame.draw.line(screen, self.colors["vanilla_secondary"], (box_rect.x + 5, box_rect.centery), (box_rect.x + 11, box_rect.bottom - 6), 3)
                pygame.draw.line(screen, self.colors["vanilla_secondary"], (box_rect.x + 11, box_rect.bottom - 6), (box_rect.right - 4, box_rect.y + 6), 3)

            label_col = self.colors["vanilla_secondary"]
            if pid == "minesweeper":
                label_col = self.colors["mine_secondary"]
            elif pid == "chessplus":
                label_col = self.colors["chessplus_secondary"]
            name_max = row_rect.width - (box_rect.width + 110)
            name_surf = self.fit_text_surface(font, name, name_max, label_col, max_height=row_rect.height - 12)
            screen.blit(name_surf, (box_rect.right + 12, y + (row_rect.height - name_surf.get_height()) // 2))

            status = "увімкнено" if enabled else "вимкнено"
            status_col = (190, 190, 190) if enabled else (160, 120, 120)
            status_txt = self.fit_text_surface(font, status, 90, status_col, max_height=row_rect.height - 12)
            screen.blit(status_txt, (row_rect.right - status_txt.get_width() - 14, y + (row_rect.height - status_txt.get_height()) // 2))

        self.draw_button(screen, rects["back"], "Назад", font, "host_back", rects["back"].collidepoint(mouse_pos))
        self.draw_button(screen, rects["continue"], "Далі", font, "host_continue", rects["continue"].collidepoint(mouse_pos))

    def draw_name_screen(self, screen, big_font, font, mouse_pos):
        title = big_font.render("Введіть ім'я", True, self.colors["vanilla_secondary"])
        screen.blit(title, title.get_rect(center=(self.winw//2, self.winh//2 - 90)))
        if self.mode:
            mode_label = font.render(f"Режим: {self.mode.title()}", True, (200,200,200))
            screen.blit(mode_label, mode_label.get_rect(center=(self.winw//2, self.winh//2 - 55)))
        if self.last_error:
            err = font.render(self.last_error, True, (220, 80, 80))
            screen.blit(err, err.get_rect(center=(self.winw//2, self.winh//2 - 25)))

        rects = self.name_buttons()
        base = self.colors["vanilla_button_base"]
        name_color = base if self.input_focus == "name" else (max(0, base[0]-12), max(0, base[1]-12), max(0, base[2]-12))
        pygame.draw.rect(screen, name_color, rects["name_input"], border_radius=6)
        pygame.draw.rect(screen, self.colors["vanilla_button_border"], rects["name_input"], 2, border_radius=6)
        name_text = font.render(self.name_input or " ", True, (255,255,255))
        screen.blit(name_text, name_text.get_rect(midleft=(rects["name_input"].x + 10, rects["name_input"].centery)))

        if self.mode == "join":
            ip_label = font.render("IP сервера", True, (200,200,200))
            screen.blit(ip_label, ip_label.get_rect(midbottom=(rects["ip_input"].centerx, rects["ip_input"].y - 6)))
            ip_color = base if self.input_focus == "ip" else (max(0, base[0]-12), max(0, base[1]-12), max(0, base[2]-12))
            pygame.draw.rect(screen, ip_color, rects["ip_input"], border_radius=6)
            pygame.draw.rect(screen, self.colors["vanilla_button_border"], rects["ip_input"], 2, border_radius=6)
            ip_text = font.render(self.ip_input or " ", True, (255,255,255))
            screen.blit(ip_text, ip_text.get_rect(midleft=(rects["ip_input"].x + 10, rects["ip_input"].centery)))

        self.draw_button(screen, rects["start"], "Почати", font, "name_start", rects["start"].collidepoint(mouse_pos))
        self.draw_button(screen, rects["back"], "Назад", font, "name_back", rects["back"].collidepoint(mouse_pos))

    def start_shake(self, intensity=6.0, duration=0.25):
        if intensity > self.shake_intensity or self.shake_time_left <= 0:
            self.shake_intensity = intensity
            self.shake_duration = duration
            self.shake_time_left = duration
        else:
            self.shake_time_left = max(self.shake_time_left, duration)

    def update_shake(self):
        if self.shake_time_left <= 0:
            self.shake_offset = (0, 0)
            return
        self.shake_time_left = max(0.0, self.shake_time_left - self.dt)
        factor = self.shake_time_left / self.shake_duration if self.shake_duration > 0 else 0
        amp = self.shake_intensity * factor
        ox = int(random.uniform(-amp, amp))
        oy = int(random.uniform(-amp, amp))
        self.shake_offset = (ox, oy)

    def get_board_origin(self):
        if self.ui_state == "replay":
            bx, by = self.get_replay_board_origin()
        else:
            bx, by = self.board_origin
        ox, oy = self.shake_offset
        return (bx + ox, by + oy)

    def get_replay_board_origin(self):
        board_size = self.cell * 8
        bx = (self.winw - board_size) // 2
        by = self.margin
        return (bx, by)

    def layout(self):
        board_x, board_y = self.board_origin
        board_size = self.cell * 8
        gap = self.margin
        panel_x = board_x + board_size + gap
        panel_w = max(0, self.winw - panel_x - gap)
        panel_rect = pygame.Rect(panel_x, board_y, panel_w, board_size)
        return {
            "board_x": board_x,
            "board_y": board_y,
            "board_size": board_size,
            "gap": gap,
            "panel_rect": panel_rect,
        }

    def replay_layout(self):
        board_x, board_y = self.get_replay_board_origin()
        board_size = self.cell * 8
        gap = 20
        panel_x = board_x + board_size + gap
        panel_w = max(0, self.winw - panel_x - gap)
        if panel_w < 200:
            panel_x = gap
            panel_w = max(0, board_x - gap * 2)
        panel_rect = pygame.Rect(panel_x, board_y, panel_w, board_size)
        return {
            "board_x": board_x,
            "board_y": board_y,
            "board_size": board_size,
            "gap": gap,
            "panel_rect": panel_rect,
        }

    def clamp(self, value, lo=0.0, hi=1.0):
        return max(lo, min(hi, value))

    def get_desired_music_track(self):
        if self.game_over and self.game_over_winner and self.my_color:
            return "win" if self.game_over_winner == self.my_color else "lose"
        if self.ui_state == "intro":
            return None
        if self.ui_state in ("menu", "mode", "host_menu", "name", "settings", "replay"):
            return "menu"
        if self.ui_state == "game" and self.state is not None:
            chaos = int(getattr(self.state, "chaos", 0))
            if chaos >= 67:
                return "chaos"
        if self.ui_state == "game" and not self.has_state:
            return "menu"
        return "game"

    def effective_music_volume(self, track):
        return self.clamp(self.music_master * self.music_volumes.get(track, 1.0))

    def update_music_volume(self):
        if not self.audio_ready or not self.current_music:
            return
        try:
            pygame.mixer.music.set_volume(self.effective_music_volume(self.current_music))
        except Exception:
            pass

    def set_music_track(self, track):
        if not self.audio_ready:
            return
        if track is None:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
            self.current_music = None
            return
        if track == self.current_music:
            self.update_music_volume()
            return
        path = self.music_tracks.get(track)
        if not path or not path.exists():
            return
        try:
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.set_volume(self.effective_music_volume(track))
            pygame.mixer.music.play(-1)
            self.current_music = track
        except Exception as e:
            print("Помилка відтворення музики:", e)

    def sync_music(self):
        self.set_music_track(self.get_desired_music_track())

    def update_sfx_volume(self):
        if not self.audio_ready:
            return
        if self.sfx_explosion:
            self.sfx_explosion.set_volume(self.sfx_base["explosion"] * self.sfx_master)
        if self.sfx_dice:
            self.sfx_dice.set_volume(self.sfx_base["dice"] * self.sfx_master)
        if self.sfx_fire:
            self.sfx_fire.set_volume(self.sfx_base["fire"] * self.sfx_master)
        if self.sfx_void:
            self.sfx_void.set_volume(self.sfx_base["void"] * self.sfx_master)
        if self.sfx_teleport:
            self.sfx_teleport.set_volume(self.sfx_base["teleport"] * self.sfx_master)
        if self.sfx_pistol:
            self.sfx_pistol.set_volume(self.sfx_base["pistol"] * self.sfx_master)
        if self.sfx_nuke_charge:
            self.sfx_nuke_charge.set_volume(self.sfx_base["nuke_charge"] * self.sfx_master)
        if self.sfx_nuke_explosion:
            self.sfx_nuke_explosion.set_volume(self.sfx_base["nuke_explosion"] * self.sfx_master)
        if self.sfx_clone:
            self.sfx_clone.set_volume(self.sfx_base["clone"] * self.sfx_master)
        if self.sfx_chaos_tick:
            self.sfx_chaos_tick.set_volume(self.sfx_base["chaos_tick"] * self.sfx_master)
        if self.sfx_giant_spawn:
            self.sfx_giant_spawn.set_volume(self.sfx_base["giant_spawn"] * self.sfx_master)
        for snd in self.sfx_move:
            snd.set_volume(self.sfx_base["move"] * self.sfx_master)
        for snd in self.sfx_capture:
            snd.set_volume(self.sfx_base["capture"] * self.sfx_master)
        for snd in self.sfx_click:
            snd.set_volume(self.sfx_base["click"] * self.sfx_master)
        for snd in self.sfx_hover:
            snd.set_volume(self.sfx_base["hover"] * self.sfx_master)
        for snd in self.sfx_mine_plant:
            snd.set_volume(self.sfx_base["mine_plant"] * self.sfx_master)

    def init_audio(self):
        try:
            pygame.mixer.init()
        except Exception as e:
            print("Помилка ініціалізації аудіо:", e)
            return
        self.audio_ready = True

        self.sfx_explosion = self.load_sound(self.assets_root / "sound" / "sfx" / "explosion.wav", self.sfx_base["explosion"])
        self.sfx_move = self.load_sound_variants([
            self.assets_root / "sound" / "sfx" / "move_1.wav",
            self.assets_root / "sound" / "sfx" / "move_2.wav",
            self.assets_root / "sound" / "sfx" / "move_3.wav",
        ], self.sfx_base["move"])
        self.sfx_capture = self.load_sound_variants([
            self.assets_root / "sound" / "sfx" / "capture_1.wav",
            self.assets_root / "sound" / "sfx" / "capture_2.wav",
        ], self.sfx_base["capture"])
        self.sfx_click = self.load_sound_variants([
            self.assets_root / "sound" / "sfx" / "click_1.wav",
            self.assets_root / "sound" / "sfx" / "click_2.wav",
            self.assets_root / "sound" / "sfx" / "click_3.wav",
        ], self.sfx_base["click"])
        self.sfx_hover = self.load_sound_variants([
            self.assets_root / "sound" / "sfx" / "hover_wind.wav",
        ], self.sfx_base["hover"])
        self.sfx_mine_plant = self.load_sound_variants([
            self.assets_root / "sound" / "sfx" / "mine_plant.wav",
        ], self.sfx_base["mine_plant"])
        self.sfx_dice = self.load_sound(self.assets_root / "sound" / "sfx" / "dice_roll.wav", self.sfx_base["dice"])
        self.sfx_fire = self.load_sound(self.assets_root / "sound" / "sfx" / "fire_crackle.wav", self.sfx_base["fire"])
        self.sfx_void = self.load_sound(self.assets_root / "sound" / "sfx" / "void_absorb.wav", self.sfx_base["void"])
        self.sfx_teleport = self.load_sound(self.assets_root / "sound" / "sfx" / "teleport.wav", self.sfx_base["teleport"])
        self.sfx_pistol = self.load_sound(self.assets_root / "sound" / "sfx" / "pistol.wav", self.sfx_base["pistol"])
        self.sfx_nuke_charge = self.load_sound(self.assets_root / "sound" / "sfx" / "nuke_charge.wav", self.sfx_base["nuke_charge"])
        self.sfx_nuke_explosion = self.load_sound(self.assets_root / "sound" / "sfx" / "nuke_explosion.wav", self.sfx_base["nuke_explosion"])
        self.sfx_clone = self.load_sound(self.assets_root / "sound" / "sfx" / "clone.wav", self.sfx_base["clone"])
        self.sfx_chaos_tick = self.load_sound(self.assets_root / "sound" / "sfx" / "chaos_tick.wav", self.sfx_base["chaos_tick"])
        self.sfx_giant_spawn = self.load_sound(self.assets_root / "sound" / "sfx" / "giant_spawn.wav", self.sfx_base["giant_spawn"])
        self.update_sfx_volume()
        # Defer music start to the main loop (prevents a blip before intro).

    def load_sound(self, path, volume=0.7):
        if not path.exists():
            return None
        try:
            snd = pygame.mixer.Sound(str(path))
            snd.set_volume(volume * self.sfx_master)
            return snd
        except Exception:
            return None

    def load_sound_variants(self, paths, volume):
        sounds = []
        for path in paths:
            snd = self.load_sound(path, volume)
            if snd:
                sounds.append(snd)
        return sounds

    def play_sfx_list(self, sounds):
        if not sounds:
            return
        random.choice(sounds).play()

    def play_sfx(self, sound):
        if sound:
            sound.play()

    def load_explosion_frames(self):
        frames = []
        base_dir = self.assets_root / "textures" / "effects"
        for base in (base_dir / "explosion", base_dir):
            if not base.exists():
                continue
            i = 0
            while True:
                path = base / f"explosion_{i}.png"
                if not path.exists():
                    break
                try:
                    img = pygame.image.load(str(path)).convert_alpha()
                    img = pygame.transform.smoothscale(img, (self.explosion_size, self.explosion_size))
                    frames.append(img)
                except Exception:
                    break
                i += 1
            if frames:
                break
        self.explosion_frames = frames

    def load_mine_image(self):
        path = self.assets_root / "textures" / "mines" / "mine.png"
        if not path.exists():
            self.mine_image = None
            return
        try:
            img = pygame.image.load(str(path)).convert_alpha()
            img = pygame.transform.smoothscale(img, (self.cell, self.cell))
            self.mine_image = img
        except Exception:
            self.mine_image = None

    def get_inventory_bar_image(self, size):
        if self.inventory_bar_image is not None and self.inventory_bar_size == size:
            return self.inventory_bar_image
        path = self.assets_root / "textures" / "ui" / "inventory_bar.png"
        if not path.exists():
            self.inventory_bar_image = None
            self.inventory_bar_size = None
            return None
        try:
            img = pygame.image.load(str(path)).convert_alpha()
            img = pygame.transform.smoothscale(img, size)
            self.inventory_bar_image = img
            self.inventory_bar_size = size
            return img
        except Exception:
            self.inventory_bar_image = None
            self.inventory_bar_size = None
            return None

    def get_inventory_slot_image(self, size):
        if self.inventory_slot_image is not None and self.inventory_slot_size == size:
            return self.inventory_slot_image
        path = self.assets_root / "textures" / "ui" / "inventory_slot.png"
        if not path.exists():
            self.inventory_slot_image = None
            self.inventory_slot_size = None
            return None
        try:
            img = pygame.image.load(str(path)).convert_alpha()
            img = pygame.transform.smoothscale(img, (size, size))
            self.inventory_slot_image = img
            self.inventory_slot_size = size
            return img
        except Exception:
            self.inventory_slot_image = None
            self.inventory_slot_size = None
            return None

    def load_intro_frames(self):
        frames = []
        if self.intro_frames_dir.exists():
            for pattern in ("*.png", "*.jpg", "*.jpeg"):
                frames.extend(self.intro_frames_dir.glob(pattern))
        frames = sorted(frames, key=lambda p: p.name)
        self.intro_frame_paths = frames
        if frames:
            self.intro_frame_time = self.intro_duration / max(1, len(frames))
        else:
            self.intro_frame_time = 1 / 24.0

    def prepare_intro(self):
        if self.intro_played:
            return
        self.load_intro_frames()
        self.intro_use_video = False
        self.intro_video_cap = None
        if CV2_AVAILABLE and self.intro_video_path.exists():
            try:
                cap = cv2.VideoCapture(str(self.intro_video_path))
                if cap.isOpened():
                    # Smart FPS: use source FPS when available, fallback to 60
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    if fps and fps > 1:
                        self.intro_video_fps = float(fps)
                    else:
                        self.intro_video_fps = 60.0
                    self.intro_video_cap = cap
                    self.intro_use_video = True
                    self.intro_video_last_time = 0.0
                    self.intro_video_frame_surface = None
                    self.intro_video_frame_index = -1
                else:
                    cap.release()
            except Exception as e:
                print("Помилка відкриття intro відео:", e)
                self.intro_video_cap = None
                self.intro_use_video = False
        has_intro = self.intro_use_video or bool(self.intro_frame_paths) or self.intro_static_path.exists()
        if not has_intro:
            self.intro_played = True
            return
        if self.audio_ready:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
            self.current_music = None
        self.ui_state = "intro"
        self.intro_start_time = time.time()
        self.intro_frame_index = -1
        self.intro_frame_surface = None

    def finish_intro(self):
        self.intro_played = True
        self.ui_state = "menu"
        self.intro_start_time = None
        self.intro_frame_index = -1
        self.intro_frame_surface = None
        self.intro_video_last_time = 0.0
        self.intro_video_frame_surface = None
        self.intro_video_frame_index = -1
        if self.intro_video_cap is not None:
            try:
                self.intro_video_cap.release()
            except Exception:
                pass
        self.intro_video_cap = None
        self.intro_use_video = False

    def draw_intro(self, screen, font):
        if self.intro_start_time is None:
            self.intro_start_time = time.time()
        elapsed = time.time() - self.intro_start_time
        if elapsed >= self.intro_duration:
            self.finish_intro()
            return
        screen.fill((0, 0, 0))
        frame = None
        if self.intro_use_video and self.intro_video_cap is not None:
            target_index = int(elapsed * max(1.0, self.intro_video_fps))
            if target_index > self.intro_video_frame_index or self.intro_video_frame_surface is None:
                steps = max(1, target_index - self.intro_video_frame_index)
                # skip frames quickly if needed
                for _ in range(max(0, steps - 1)):
                    if not self.intro_video_cap.grab():
                        steps = 0
                        break
                ok, frame_bgr = (self.intro_video_cap.read() if steps > 0 else (False, None))
                if not ok or frame_bgr is None:
                    # video ended early -> freeze last frame until intro_duration
                    try:
                        self.intro_video_cap.release()
                    except Exception:
                        pass
                    self.intro_video_cap = None
                    self.intro_use_video = False
                    if self.intro_video_frame_surface is None:
                        self.finish_intro()
                        return
                else:
                    try:
                        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                        h, w = frame_rgb.shape[:2]
                        surf = pygame.image.frombuffer(frame_rgb.tobytes(), (w, h), "RGB")
                        frame = pygame.transform.smoothscale(surf, (self.winw, self.winh))
                        self.intro_video_frame_surface = frame
                        self.intro_video_frame_index += steps
                    except Exception:
                        self.intro_video_frame_surface = None
            frame = self.intro_video_frame_surface
        elif self.intro_frame_paths:
            idx = min(int(elapsed / self.intro_frame_time), len(self.intro_frame_paths) - 1)
            if idx != self.intro_frame_index:
                self.intro_frame_index = idx
                try:
                    img = pygame.image.load(str(self.intro_frame_paths[idx])).convert_alpha()
                    img = pygame.transform.smoothscale(img, (self.winw, self.winh))
                    self.intro_frame_surface = img
                except Exception:
                    self.intro_frame_surface = None
            frame = self.intro_frame_surface
        elif self.intro_static_path.exists():
            if self.intro_frame_surface is None:
                try:
                    img = pygame.image.load(str(self.intro_static_path)).convert_alpha()
                    img = pygame.transform.smoothscale(img, (self.winw, self.winh))
                    self.intro_frame_surface = img
                except Exception:
                    self.intro_frame_surface = None
            frame = self.intro_frame_surface
        if frame:
            screen.blit(frame, (0, 0))
        else:
            txt = font.render("Anarchy Chess", True, (220, 220, 220))
            screen.blit(txt, txt.get_rect(center=(self.winw // 2, self.winh // 2)))

        # fade-in / fade-out
        fade_in_time = 0.7
        fade_out_time = 0.7
        fade_alpha = 0.0
        if elapsed < fade_in_time:
            fade_alpha = 1.0 - (elapsed / max(0.001, fade_in_time))
        elif elapsed > (self.intro_duration - fade_out_time):
            fade_alpha = 1.0 - ((self.intro_duration - elapsed) / max(0.001, fade_out_time))
        if fade_alpha > 0:
            overlay = pygame.Surface((self.winw, self.winh), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, int(255 * min(1.0, fade_alpha))))
            screen.blit(overlay, (0, 0))

    def update_effects_from_state(self):
        if not self.state:
            return

        if hasattr(self.state, "game_id"):
            self.game_id = self.state.game_id

        match_ms = getattr(self.state, "timer", {}).get("match_ms")
        match_running = getattr(self.state, "timer", {}).get("match_running")
        if match_ms is not None:
            self.timer_sync_ms = match_ms
            self.timer_sync_time = time.time()
        if match_running is not None:
            self.timer_running = bool(match_running)

        chaos = int(getattr(self.state, "chaos", 0))
        new_bucket = min(9, chaos // 10)
        if new_bucket > self.chaos_bucket:
            if self.ui_state == "game":
                self.play_sfx(self.sfx_chaos_tick)
            self.chaos_bucket = new_bucket
        elif new_bucket < self.chaos_bucket:
            self.chaos_bucket = new_bucket

        if self.state.move_count != self.last_move_count:
            move_info = None
            if self.prev_state:
                move_info = self.detect_moved_piece(self.prev_state, self.state)
            if move_info:
                fx, fy, tx, ty, piece, captured = move_info
                self.start_piece_animation(fx, fy, tx, ty, piece)
                if captured:
                    self.play_sfx_list(self.sfx_capture)
                else:
                    self.play_sfx_list(self.sfx_move)
                effect = self.get_cell_effect_at(tx, ty)
                if effect == "dice":
                    self.play_sfx(self.sfx_dice)
                elif effect == "fire":
                    self.play_sfx(self.sfx_fire)
                elif effect == "void":
                    self.play_sfx(self.sfx_void)
                elif effect == "bomb":
                    self.play_sfx_list(self.sfx_mine_plant)
            else:
                self.play_sfx_list(self.sfx_move)
            self.last_move_count = self.state.move_count
            self.move_block_until = time.time() + self.move_cooldown

        new_craters = set(tuple(c) for c in getattr(self.state, "craters", []))
        fresh = sorted(new_craters - self.seen_craters)
        for idx, crater in enumerate(fresh):
            extra_delay = self.chain_reaction_delay * idx
            self.handle_crater(crater, extra_delay=extra_delay)
        if fresh:
            self.start_shake(6.0, 0.22)
        self.seen_craters = new_craters

        nuke_id = getattr(self.state, "nuke_event_id", 0)
        if nuke_id and nuke_id != self.last_nuke_event_id:
            self.start_shake(16.0, 0.45)
            self.play_sfx(self.sfx_nuke_explosion)
            self.last_nuke_event_id = nuke_id

        if self.prev_state:
            planted = 0
            for y in range(8):
                for x in range(8):
                    if self.prev_state.mines[y][x] == 0 and self.state.mines[y][x] == 1:
                        planted += 1
            if planted > 0:
                self.play_sfx_list(self.sfx_mine_plant)
            prev_giants = set()
            curr_giants = set()
            for y in range(8):
                for x in range(8):
                    pp = self.prev_state.board.get_piece(x, y)
                    if pp and pp.ptype == "giant_pawn":
                        key = getattr(pp, "gid", None)
                        if key is None:
                            key = id(pp)
                        prev_giants.add(key)
                    pc = self.state.board.get_piece(x, y)
                    if pc and pc.ptype == "giant_pawn":
                        key = getattr(pc, "gid", None)
                        if key is None:
                            key = id(pc)
                        curr_giants.add(key)
            if curr_giants - prev_giants:
                self.play_sfx(self.sfx_giant_spawn)

        if self.selected_item_slot is not None:
            if not self.get_inventory_item(self.selected_item_slot):
                self.clear_item_targeting()

        self.prev_state = self.state

    def detect_moved_piece(self, prev_state, curr_state):
        def build_map(state):
            mapping = {}
            seen = set()
            for y in range(8):
                for x in range(8):
                    p = state.board.get_piece(x, y)
                    if not p:
                        continue
                    key = getattr(p, "gid", None)
                    if key is None:
                        key = id(p)
                    if key in seen:
                        continue
                    seen.add(key)
                    anchor = getattr(p, "anchor", None)
                    if anchor is None and hasattr(state.board, "find_piece_anchor"):
                        anchor = state.board.find_piece_anchor(p)
                    if anchor is None:
                        anchor = (x, y)
                    mapping[key] = (p, anchor)
            return mapping

        prev_map = build_map(prev_state)
        curr_map = build_map(curr_state)
        for key, (p, cur_anchor) in curr_map.items():
            if key not in prev_map:
                continue
            prev_anchor = prev_map[key][1]
            if prev_anchor != cur_anchor:
                captured = False
                size = max(1, int(getattr(p, "size", 1)))
                if size > 1:
                    for dy in range(size):
                        for dx in range(size):
                            nx = cur_anchor[0] + dx
                            ny = cur_anchor[1] + dy
                            prev_dest = prev_state.board.get_piece(nx, ny)
                            if prev_dest and prev_dest.color != p.color:
                                captured = True
                                break
                        if captured:
                            break
                else:
                    prev_dest = prev_state.board.get_piece(cur_anchor[0], cur_anchor[1])
                    captured = prev_dest is not None and prev_dest.color != p.color
                return (prev_anchor[0], prev_anchor[1], cur_anchor[0], cur_anchor[1], p, captured)

        from_squares = []
        to_squares = []
        for y in range(8):
            for x in range(8):
                p_prev = prev_state.board.get_piece(x, y)
                p_curr = curr_state.board.get_piece(x, y)
                if p_prev and (p_curr is None or p_curr.color != p_prev.color or p_curr.ptype != p_prev.ptype):
                    from_squares.append((x, y, p_prev))
                if p_curr and (p_prev is None or p_prev.color != p_curr.color or p_prev.ptype != p_prev.ptype):
                    to_squares.append((x, y, p_curr))
        if not to_squares:
            return None
        # exact match by color + type
        for tx, ty, p in to_squares:
            for fx, fy, pp in from_squares:
                if pp.color == p.color and pp.ptype == p.ptype:
                    prev_dest = prev_state.board.get_piece(tx, ty)
                    captured = prev_dest is not None and prev_dest.color != p.color
                    return (fx, fy, tx, ty, p, captured)
        # promotion or type change: match by color if unique
        for tx, ty, p in to_squares:
            same_color = [fs for fs in from_squares if fs[2].color == p.color]
            if len(same_color) == 1:
                fx, fy, _ = same_color[0]
                prev_dest = prev_state.board.get_piece(tx, ty)
                captured = prev_dest is not None and prev_dest.color != p.color
                return (fx, fy, tx, ty, p, captured)
        if len(from_squares) == 1 and len(to_squares) == 1:
            fx, fy, _ = from_squares[0]
            tx, ty, p = to_squares[0]
            prev_dest = prev_state.board.get_piece(tx, ty)
            captured = prev_dest is not None and prev_dest.color != p.color
            return (fx, fy, tx, ty, p, captured)
        return None

    def start_piece_animation(self, fx, fy, tx, ty, piece):
        img = self.get_piece_image(piece)
        if not img:
            return
        size = max(1, int(getattr(piece, "size", 1)))
        start_disp = self.board_to_display((fx, fy))
        end_disp = self.board_to_display((tx, ty))
        bx, by = self.get_board_origin()
        half = int(self.cell * size / 2)
        start_px = (bx + start_disp[0] * self.cell + half, by + start_disp[1] * self.cell + half)
        end_px = (bx + end_disp[0] * self.cell + half, by + end_disp[1] * self.cell + half)
        self.piece_animations.append({
            "img": img,
            "start": start_px,
            "end": end_px,
            "start_time": time.time(),
            "duration": 0.3,
            "to": (tx, ty),
        })

    def draw_piece_animations(self, screen):
        if not self.piece_animations:
            return
        now = time.time()
        remaining = []
        for anim in self.piece_animations:
            t = (now - anim["start_time"]) / anim["duration"]
            if t >= 1.0:
                continue
            t = max(0.0, min(1.0, t))
            t = t * t * (3 - 2 * t)
            sx, sy = anim["start"]
            ex, ey = anim["end"]
            px = sx + (ex - sx) * t
            py = sy + (ey - sy) * t
            rect = anim["img"].get_rect(center=(int(px), int(py)))
            screen.blit(anim["img"], rect)
            remaining.append(anim)
        self.piece_animations = remaining

    def handle_crater(self, coord, extra_delay=0.0):
        if self.sfx_explosion:
            self.sfx_explosion.play()
        if not self.explosion_frames:
            return
        delay = extra_delay
        if self.state:
            x, y = coord
            if 0 <= x < 8 and 0 <= y < 8:
                try:
                    if self.state.mines[y][x] == 1:
                        delay += self.explosion_delay
                        self.mine_reveals.append({
                            "coord": coord,
                            "start": time.time(),
                            "duration": self.explosion_delay,
                        })
                except Exception:
                    pass
        self.explosions.append({"coord": coord, "start": time.time() + delay})

    def draw_explosions(self, screen):
        if not self.explosion_frames:
            return
        now = time.time()
        remaining = []
        bx, by = self.get_board_origin()
        for exp in self.explosions:
            if now < exp["start"]:
                remaining.append(exp)
                continue
            age = now - exp["start"]
            frame_idx = int(age / self.explosion_frame_time)
            if frame_idx >= len(self.explosion_frames):
                continue
            board_coord = exp["coord"]
            dx, dy = self.board_to_display(board_coord)
            rect = pygame.Rect(
                bx + (dx - 1) * self.cell,
                by + (dy - 1) * self.cell,
                self.explosion_size,
                self.explosion_size,
            )
            screen.blit(self.explosion_frames[frame_idx], rect)
            remaining.append(exp)
        self.explosions = remaining

    def draw_mine_reveals(self, screen):
        if not self.mine_image or not self.mine_reveals:
            return
        now = time.time()
        remaining = []
        bx, by = self.get_board_origin()
        for item in self.mine_reveals:
            age = now - item["start"]
            duration = item.get("duration", self.explosion_delay)
            if age >= duration:
                continue
            alpha = int(255 * min(1.0, max(0.0, age / duration)))
            img = self.mine_image.copy()
            img.set_alpha(alpha)
            dx, dy = self.board_to_display(item["coord"])
            rect = pygame.Rect(bx + dx*self.cell, by + dy*self.cell, self.cell, self.cell)
            screen.blit(img, rect)
            remaining.append(item)
        self.mine_reveals = remaining

    def is_flipped(self):
        return self.my_color == "white"

    def is_pack_active(self, pack_id):
        if not self.state:
            return False
        for pack in getattr(self.state, "dlc_packs", []):
            if pack.get("id") == pack_id:
                return bool(pack.get("active"))
        return False

    def display_to_board(self, coord):
        dx, dy = coord
        if self.is_flipped():
            return (7 - dx, 7 - dy)
        return (dx, dy)

    def board_to_display(self, coord):
        x, y = coord
        if self.is_flipped():
            return (7 - x, 7 - y)
        return (x, y)

    def get_my_inventory(self):
        if not self.state or not self.my_color:
            return [None]*9
        inv = self.state.inventory.get(self.my_color)
        if inv is None:
            return [None]*9
        return inv

    def pos_key(self, x, y):
        return f"{x},{y}"

    def get_cell_effect_at(self, x, y):
        if not self.state:
            return None
        try:
            return self.state.chessplus_cells[y][x]
        except Exception:
            return None

    def get_bomb_timer_at(self, x, y):
        if not self.state:
            return None
        bombs = getattr(self.state, "chessplus_bombs", None)
        if not bombs:
            return None
        return bombs.get(self.pos_key(x, y))

    def get_mutation_at(self, x, y):
        if not self.state:
            return None
        muts = getattr(self.state, "chessplus_mutations", None)
        if not muts:
            return None
        return muts.get(self.pos_key(x, y))

    def get_burning_at(self, x, y):
        if not self.state:
            return None
        burn = getattr(self.state, "chessplus_burning", None)
        if not burn:
            return None
        return burn.get(self.pos_key(x, y))

    def get_clone_at(self, x, y):
        if not self.state:
            return None
        clones = getattr(self.state, "chessplus_clones", None)
        if not clones:
            return None
        return clones.get(self.pos_key(x, y))

    def get_my_piece_coords(self):
        coords = set()
        if not self.state or not self.my_color:
            return coords
        seen = set()
        for y in range(8):
            for x in range(8):
                p = self.state.board.get_piece(x, y)
                if p and p.color == self.my_color:
                    key = getattr(p, "gid", None)
                    if key is None:
                        key = id(p)
                    if key in seen:
                        continue
                    seen.add(key)
                    anchor = getattr(p, "anchor", None)
                    if anchor is None and hasattr(self.state.board, "find_piece_anchor"):
                        anchor = self.state.board.find_piece_anchor(p)
                    coords.add(tuple(anchor) if anchor is not None else (x, y))
        return coords

    def get_piece_anchor(self, coord):
        if not self.state:
            return coord
        piece = self.state.board.get_piece(*coord)
        if not piece:
            return coord
        anchor = getattr(piece, "anchor", None)
        if anchor is None and hasattr(self.state.board, "find_piece_anchor"):
            anchor = self.state.board.find_piece_anchor(piece)
        return tuple(anchor) if anchor is not None else coord

    def get_inventory_item(self, slot):
        inv = self.get_my_inventory()
        if slot is None or slot < 0 or slot >= len(inv):
            return None
        return inv[slot]

    def get_temp_reveal_cells(self):
        if not self.state:
            return set()
        temp = getattr(self.state, "temp_reveal", None)
        if not temp:
            return set()
        return set(tuple(c) for c in temp.get("cells", []))

    def has_mine_vision(self):
        if not self.state or not self.my_color:
            return False
        vision = getattr(self.state, "mine_vision", None)
        if not vision:
            return False
        return vision.get(self.my_color, 0) > 0

    def replay_has_mines(self):
        if not self.state:
            return False
        for row in self.state.mines:
            if 1 in row:
                return True
        for row in self.state.revealed:
            if 1 in row:
                return True
        temp = getattr(self.state, "temp_reveal", None)
        if temp and temp.get("cells"):
            return True
        return False

    def clear_item_targeting(self):
        self.selected_item_slot = None
        self.item_target_cells = set()
        self.item_target_mode = False
        self.item_target_slot = None
        self.item_target_phase = None
        self.item_selected_piece = None

    def handle_inventory_key(self, slot):
        if not self.state or self.game_over:
            return
        if self.state.turn != self.my_color:
            return
        if self.selected_item_slot == slot:
            self.clear_item_targeting()
            return
        item = self.get_inventory_item(slot)
        if not item:
            self.clear_item_targeting()
            return
        self.selected_item_slot = slot
        self.item_target_cells = set()
        self.item_target_mode = False
        self.item_target_slot = slot
        self.item_target_phase = None
        self.item_selected_piece = None
        target_type = item.get("target")
        if target_type == "mine":
            send_json(self.sock, {"type":"use_item_request", "slot": slot})
            self.item_target_mode = True
            self.item_target_phase = "cell"
        elif target_type == "cell":
            self.item_target_mode = True
            self.item_target_phase = "cell"
        elif target_type in ("piece", "piece_cell", "piece_dir"):
            self.item_target_mode = True
            self.item_target_phase = "piece"
        else:
            send_json(self.sock, {"type":"use_item", "slot": slot})
            self.play_item_sfx(item.get("effect_id"))
            self.clear_item_targeting()

    def handle_inventory_click(self, pos):
        if not self.inventory_slot_rects:
            return False
        for slot, rect in self.inventory_slot_rects.items():
            if rect.collidepoint(pos):
                self.play_sfx_list(self.sfx_click)
                self.handle_inventory_key(slot)
                return True
        return False

    def play_item_sfx(self, effect_id):
        if effect_id == "cp_item_teleport":
            self.play_sfx(self.sfx_teleport)
        elif effect_id == "cp_item_pistol":
            self.play_sfx(self.sfx_pistol)
        elif effect_id == "cp_item_nuke":
            self.play_sfx(self.sfx_nuke_charge)
        elif effect_id == "cp_item_clone":
            self.play_sfx(self.sfx_clone)

    def handle_item_click(self, pos):
        if not self.item_target_mode or self.selected_item_slot is None:
            return False
        item = self.get_inventory_item(self.selected_item_slot)
        if not item:
            self.clear_item_targeting()
            return False
        display_coord = coord_for_pixel(pos[0], pos[1], self.get_board_origin(), self.cell)
        if not display_coord:
            return False
        coord = self.display_to_board(display_coord)
        if coord is None or not coord_in_bounds(*coord):
            return False
        target_type = item.get("target")
        if target_type in ("piece", "piece_cell", "piece_dir"):
            if self.item_target_phase == "piece":
                p = self.state.board.get_piece(*coord) if self.state else None
                if not p or p.color != self.my_color:
                    return False
                anchor = self.get_piece_anchor(coord)
                self.item_selected_piece = anchor
                if target_type == "piece":
                    send_json(self.sock, {"type":"use_item", "slot": self.selected_item_slot, "target": {"from":[anchor[0], anchor[1]]}})
                    self.play_item_sfx(item.get("effect_id"))
                    self.clear_item_targeting()
                    return True
                self.item_target_phase = "cell"
                self.item_target_cells = self.get_item_target_cells(item, anchor)
                return True
            else:
                if self.item_target_cells and coord not in self.item_target_cells:
                    return False
                src = self.item_selected_piece
                if not src:
                    return False
                send_json(self.sock, {"type":"use_item", "slot": self.selected_item_slot, "target": {"from":[src[0], src[1]], "to":[coord[0], coord[1]]}})
                self.play_item_sfx(item.get("effect_id"))
                self.clear_item_targeting()
                return True
        if self.item_target_cells and coord not in self.item_target_cells:
            return False
        if target_type == "mine":
            send_json(self.sock, {"type":"use_item_target", "slot": self.selected_item_slot, "target":[coord[0], coord[1]]})
        else:
            send_json(self.sock, {"type":"use_item", "slot": self.selected_item_slot, "target":[coord[0], coord[1]]})
        self.play_item_sfx(item.get("effect_id"))
        self.clear_item_targeting()
        return True

    def get_item_target_cells(self, item, src):
        cells = set()
        if not self.state:
            return cells
        sx, sy = src
        effect_id = item.get("effect_id")
        piece = self.state.board.get_piece(sx, sy)
        size = max(1, int(getattr(piece, "size", 1))) if piece else 1
        if effect_id == "cp_item_teleport":
            for y in range(8):
                for x in range(8):
                    if x + size - 1 >= 8 or y + size - 1 >= 8:
                        continue
                    ok = True
                    for dy in range(size):
                        for dx in range(size):
                            if self.state.board.get_piece(x + dx, y + dy) is not None:
                                ok = False
                                break
                        if not ok:
                            break
                    if ok:
                        cells.add((x, y))
        elif effect_id == "cp_item_clone":
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = sx + dx, sy + dy
                    if 0 <= nx < 8 and 0 <= ny < 8 and nx + size - 1 < 8 and ny + size - 1 < 8:
                        ok = True
                        for yy in range(size):
                            for xx in range(size):
                                if self.state.board.get_piece(nx + xx, ny + yy) is not None:
                                    ok = False
                                    break
                            if not ok:
                                break
                        if ok:
                            effect = None
                            for yy in range(size):
                                for xx in range(size):
                                    try:
                                        effect = self.state.chessplus_cells[ny + yy][nx + xx]
                                    except Exception:
                                        effect = None
                                    if effect is not None:
                                        ok = False
                                        break
                                if not ok:
                                    break
                            if ok:
                                cells.add((nx, ny))
        elif effect_id == "cp_item_pistol":
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
                for step in range(1, 4):
                    nx, ny = sx + dx * step, sy + dy * step
                    if 0 <= nx < 8 and 0 <= ny < 8:
                        cells.add((nx, ny))
        else:
            for y in range(8):
                for x in range(8):
                    cells.add((x, y))
        return cells

    def get_move_hints(self, coord):
        moves = set()
        captures = set()
        if not self.state or not self.my_color:
            return moves, captures
        if self.state.turn != self.my_color:
            return moves, captures
        coord = self.get_piece_anchor(coord)
        piece = self.state.board.get_piece(*coord)
        if not piece or piece.color != self.my_color:
            return moves, captures
        for y in range(8):
            for x in range(8):
                ok, _ = validate_move(self.state, coord, (x, y), piece.color)
                if not ok:
                    continue
                if piece.ptype == "giant_pawn":
                    enemy = False
                    for dy in range(2):
                        for dx in range(2):
                            nx, ny = x + dx, y + dy
                            if 0 <= nx < 8 and 0 <= ny < 8:
                                dest = self.state.board.get_piece(nx, ny)
                                if dest and dest.color != piece.color:
                                    enemy = True
                                    break
                        if enemy:
                            break
                    if enemy:
                        captures.add((x, y))
                    else:
                        moves.add((x, y))
                else:
                    dest = self.state.board.get_piece(x, y)
                    if dest and dest.color != piece.color:
                        captures.add((x, y))
                    else:
                        moves.add((x, y))
        return moves, captures

    def draw_board_background(self, screen, selected, hint_moves=None, hint_captures=None, hint_items=None, hover_cell=None):
        bx, by = self.get_board_origin()
        if hint_moves is None:
            hint_moves = set()
        if hint_captures is None:
            hint_captures = set()
        if hint_items is None:
            hint_items = set()
        if self.hint_move_surface is None:
            surf = pygame.Surface((self.cell, self.cell), pygame.SRCALPHA)
            r, g, b = self.colors["hint_move"]
            surf.fill((r, g, b, 120))
            self.hint_move_surface = surf
        if self.hint_capture_surface is None:
            surf = pygame.Surface((self.cell, self.cell), pygame.SRCALPHA)
            r, g, b = self.colors["hint_capture"]
            surf.fill((r, g, b, 140))
            self.hint_capture_surface = surf
        if self.hint_item_surface is None:
            surf = pygame.Surface((self.cell, self.cell), pygame.SRCALPHA)
            r, g, b = self.colors["hint_item"]
            surf.fill((r, g, b, 140))
            self.hint_item_surface = surf
        temp_reveal = self.get_temp_reveal_cells()
        show_mines = self.has_mine_vision()
        mines_active = self.state is not None and self.is_pack_active("minesweeper")
        if self.ui_state == "replay" and self.state is not None:
            mines_active = mines_active or self.replay_has_mines()
            if not show_mines:
                vision = getattr(self.state, "mine_vision", None)
                if vision and any(vision.get(c, 0) > 0 for c in ("white", "black")):
                    show_mines = True
        for y in range(8):
            for x in range(8):
                rect = pygame.Rect(bx + x*self.cell, by + y*self.cell, self.cell, self.cell)
                color = self.colors["board_light"] if (x+y)%2==0 else self.colors["board_dark"]
                pygame.draw.rect(screen, color, rect)
                board_xy = self.display_to_board((x, y))
                if mines_active and board_xy:
                    board_x, board_y = board_xy
                    try:
                        cell_is_mine = self.state.mines[board_y][board_x] == 1
                        is_revealed = self.state.revealed[board_y][board_x] or (board_x, board_y) in temp_reveal
                        if is_revealed:
                            if cell_is_mine:
                                if self.mine_image:
                                    screen.blit(self.mine_image, rect)
                                else:
                                    pygame.draw.circle(screen, self.colors["mine_secondary"], rect.center, self.cell//3)
                            else:
                                n = self.state.adj_counts[board_y][board_x]
                                if n > 0:
                                    img = self.get_number_image(n)
                                    if img:
                                        screen.blit(img, img.get_rect(center=rect.center))
                                    else:
                                        font = self.get_font("main", 24)
                                        txt = font.render(str(n), True, (255,255,255))
                                        screen.blit(txt, txt.get_rect(center=rect.center))
                        elif show_mines and cell_is_mine:
                            if self.mine_image:
                                screen.blit(self.mine_image, rect)
                            else:
                                pygame.draw.circle(screen, self.colors["mine_primary"], rect.center, self.cell//3)
                    except Exception:
                        pass
                effect = self.get_cell_effect_at(board_xy[0], board_xy[1]) if board_xy else None
                if effect:
                    self.draw_chessplus_cell_effect(screen, rect, effect)
                if board_xy in hint_moves:
                    screen.blit(self.hint_move_surface, rect.topleft)
                elif board_xy in hint_captures:
                    screen.blit(self.hint_capture_surface, rect.topleft)
                elif board_xy in hint_items:
                    screen.blit(self.hint_item_surface, rect.topleft)
                if hover_cell == board_xy:
                    pygame.draw.rect(screen, self.colors["vanilla_secondary"], rect, 2)
                if selected == board_xy:
                    pygame.draw.rect(screen, self.colors["vanilla_primary"], rect, 3)
        self.draw_chessplus_overlays(screen, bx, by)
        self.draw_chessplus_walls(screen, bx, by)
        # border
        pygame.draw.rect(screen, self.colors["vanilla_secondary"], (bx-2, by-2, self.cell*8+4, self.cell*8+4), 2)

    def draw_chessplus_cell_effect(self, screen, rect, effect_id):
        img = self.get_effect_image(effect_id, self.cell)
        if img:
            screen.blit(img, rect.topleft)
            return
        if effect_id == "dice":
            pygame.draw.rect(screen, (240, 240, 240), rect.inflate(-28, -28), border_radius=4)
            dot_col = (60, 60, 60)
            cx, cy = rect.center
            pygame.draw.circle(screen, dot_col, (cx - 6, cy - 6), 3)
            pygame.draw.circle(screen, dot_col, (cx + 6, cy + 6), 3)
        elif effect_id == "fire":
            t = time.time()
            pulse = (math.sin(t * 6) + 1) / 2
            radius = int(self.cell * (0.18 + 0.06 * pulse))
            col = (220, 120, 40) if pulse < 0.5 else (190, 80, 160)
            pygame.draw.circle(screen, col, rect.center, radius)
        elif effect_id == "void":
            pygame.draw.circle(screen, (10, 10, 10), rect.center, self.cell // 3)
            pygame.draw.circle(screen, (60, 60, 80), rect.center, self.cell // 3, 2)
        elif effect_id == "bomb":
            pygame.draw.circle(screen, (150, 40, 40), rect.center, self.cell // 4)
            pygame.draw.line(screen, (220, 200, 160), (rect.centerx, rect.centery - 10), (rect.centerx + 6, rect.centery - 16), 3)
        elif effect_id == "swap":
            pygame.draw.circle(screen, (120, 200, 200), rect.center, self.cell // 5, 2)
            pygame.draw.line(screen, (120, 200, 200), (rect.centerx - 10, rect.centery), (rect.centerx + 10, rect.centery), 2)
        elif effect_id == "toxic":
            overlay = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
            overlay.fill((80, 160, 80, 90))
            screen.blit(overlay, rect.topleft)

    def draw_chessplus_overlays(self, screen, bx, by):
        if not self.state:
            return
        # bomb warning (3x3) when timer <=1
        bombs = getattr(self.state, "chessplus_bombs", None)
        if bombs:
            for key, timer in bombs.items():
                try:
                    sx, sy = key.split(",")
                    x, y = int(sx), int(sy)
                except Exception:
                    continue
                if int(timer) > 1:
                    continue
                for nx in range(x - 1, x + 2):
                    for ny in range(y - 1, y + 2):
                        if 0 <= nx < 8 and 0 <= ny < 8:
                            dx, dy = self.board_to_display((nx, ny))
                            rect = pygame.Rect(bx + dx*self.cell, by + dy*self.cell, self.cell, self.cell)
                            overlay = pygame.Surface((self.cell, self.cell), pygame.SRCALPHA)
                            overlay.fill((200, 60, 60, 80))
                            screen.blit(overlay, rect.topleft)
        # nuke warning (5x5)
        nukes = getattr(self.state, "chessplus_nukes", [])
        for nuke in nukes:
            center = nuke.get("center")
            if not center or len(center) != 2:
                continue
            cx, cy = center
            for nx in range(cx - 2, cx + 3):
                for ny in range(cy - 2, cy + 3):
                    if 0 <= nx < 8 and 0 <= ny < 8:
                        dx, dy = self.board_to_display((nx, ny))
                        rect = pygame.Rect(bx + dx*self.cell, by + dy*self.cell, self.cell, self.cell)
                        overlay = pygame.Surface((self.cell, self.cell), pygame.SRCALPHA)
                        overlay.fill((220, 120, 60, 60))
                        screen.blit(overlay, rect.topleft)

    def draw_chessplus_walls(self, screen, bx, by):
        if not self.state:
            return
        walls = getattr(self.state, "chessplus_walls", None)
        if not walls:
            return
        col = self.colors["chessplus_wall"]
        for w in walls:
            if len(w) == 4:
                x1, y1, x2, y2 = w
            elif len(w) == 2:
                (x1, y1), (x2, y2) = w
            else:
                continue
            d1 = self.board_to_display((x1, y1))
            d2 = self.board_to_display((x2, y2))
            sx = bx + d1[0] * self.cell
            sy = by + d1[1] * self.cell
            ex = bx + d2[0] * self.cell
            ey = by + d2[1] * self.cell
            if d1[0] == d2[0]:
                # vertical neighbors -> draw horizontal wall
                y = max(sy, ey)
                pygame.draw.line(screen, col, (sx, y), (sx + self.cell, y), 4)
            else:
                # horizontal neighbors -> draw vertical wall
                x = max(sx, ex)
                pygame.draw.line(screen, col, (x, sy), (x, sy + self.cell), 4)

    def get_piece_image(self, piece):
        size = max(1, int(getattr(piece, "size", 1)))
        key = (piece.color, piece.ptype, size)
        if key in self.texture_cache:
            return self.texture_cache[key]
        candidates = [
            self.assets_root / "textures" / "pieces" / f"{piece.color}_{piece.ptype}.png",
            self.assets_root / "textures" / "pieces" / f"{piece.ptype}{'1' if piece.color == 'black' else ''}.png",
            self.assets_root / "textures" / "pieces" / f"{piece.ptype}.png",
        ]
        img = None
        for path in candidates:
            if path.exists():
                try:
                    img = pygame.image.load(str(path)).convert_alpha()
                    target = 42 if size <= 1 else int(self.cell * size)
                    img = pygame.transform.smoothscale(img, (target, target))
                    break
                except Exception:
                    img = None
        self.texture_cache[key] = img
        return img

    def get_number_image(self, n):
        key = (n, self.cell)
        if key in self.number_cache:
            return self.number_cache[key]
        path = self.assets_root / "textures" / "numbers" / f"{n}.png"
        img = None
        if path.exists():
            try:
                img = pygame.image.load(str(path)).convert_alpha()
                img = pygame.transform.smoothscale(img, (self.cell, self.cell))
            except Exception:
                img = None
        self.number_cache[key] = img
        return img

    def get_item_image(self, effect_id, size):
        key = (effect_id, size)
        if key in self.item_texture_cache:
            return self.item_texture_cache[key]
        mapping = {
            "ms_item_place_mine": [
                self.assets_root / "textures" / "items" / "place_mine.png",
            ],
            "ms_item_reveal_explode": [
                self.assets_root / "textures" / "items" / "reveal_explode.png",
                self.assets_root / "textures" / "mines" / "reveal_explode.png",
            ],
            "cp_item_teleport": [
                self.assets_root / "textures" / "items" / "teleport_gun.png",
            ],
            "cp_item_pistol": [
                self.assets_root / "textures" / "items" / "pistol.png",
            ],
            "cp_item_nuke": [
                self.assets_root / "textures" / "items" / "nuke.png",
            ],
            "cp_item_clone": [
                self.assets_root / "textures" / "items" / "clone.png",
            ],
        }
        paths = mapping.get(effect_id, [])
        img = None
        for path in paths:
            if path and path.exists():
                try:
                    img = pygame.image.load(str(path)).convert_alpha()
                    img = pygame.transform.smoothscale(img, (size, size))
                    break
                except Exception:
                    img = None
        self.item_texture_cache[key] = img
        return img

    def get_effect_image(self, effect_id, size):
        key = (effect_id, size)
        if key in self.effect_texture_cache:
            return self.effect_texture_cache[key]
        effect_files = {
            "dice": ["dice.png"],
            "fire": ["fire.png"],
            "void": ["void.png"],
            "bomb": ["bomb.png"],
            "swap": ["swap.png"],
            "toxic": ["toxic.png"],
            "pawn_mutation": ["pawn_mutation.png", "mutation.png"],
        }
        names = effect_files.get(effect_id)
        if not names:
            self.effect_texture_cache[key] = None
            return None
        base_dirs = [
            self.assets_root / "textures" / "effects" / "chessplus",
            self.assets_root / "textures" / "effects" / "explosion" / "chessplus",
            self.assets_root / "textures" / "effects",
        ]
        path = None
        for base in base_dirs:
            for name in names:
                cand = base / name
                if cand.exists():
                    path = cand
                    break
            if path:
                break
        img = None
        if path and path.exists():
            try:
                img = pygame.image.load(str(path)).convert_alpha()
                if size:
                    img = pygame.transform.smoothscale(img, (size, size))
            except Exception:
                img = None
        self.effect_texture_cache[key] = img
        return img

    def draw_board_pieces(self, screen):
        bx, by = self.get_board_origin()
        anim_dests = set()
        for anim in self.piece_animations:
            anim_dests.add(anim.get("to"))
        for y in range(8):
            for x in range(8):
                rect = pygame.Rect(bx + x*self.cell, by + y*self.cell, self.cell, self.cell)
                board_x, board_y = self.display_to_board((x, y))
                # draw piece if present
                piece = self.state.board.get_piece(board_x, board_y)
                if piece and (board_x, board_y) not in anim_dests:
                    size = max(1, int(getattr(piece, "size", 1)))
                    anchor = getattr(piece, "anchor", None)
                    if anchor is None and hasattr(self.state.board, "find_piece_anchor"):
                        anchor = self.state.board.find_piece_anchor(piece)
                    if size > 1:
                        if anchor is None:
                            anchor = (board_x, board_y)
                        if (board_x, board_y) != tuple(anchor):
                            continue
                        disp = self.board_to_display(anchor)
                        rect = pygame.Rect(bx + disp[0]*self.cell, by + disp[1]*self.cell, self.cell * size, self.cell * size)
                    img = self.get_piece_image(piece)
                    if img:
                        screen.blit(img, img.get_rect(center=rect.center))
                    else:
                        # fallback: draw circle
                        col = (255,255,255) if piece.color=='white' else (0,0,0)
                        pygame.draw.circle(screen, col, rect.center, 18)
                    # mutation marker (pawn)
                    if piece.ptype == "pawn" and self.get_mutation_at(board_x, board_y):
                        mut_img = self.get_effect_image("pawn_mutation", int(self.cell * 0.42))
                        if mut_img:
                            mut_rect = mut_img.get_rect(center=(rect.centerx, rect.y + int(self.cell * 0.25)))
                            screen.blit(mut_img, mut_rect)
                        else:
                            crown = [
                                (rect.centerx - 8, rect.y + 8),
                                (rect.centerx - 2, rect.y + 2),
                                (rect.centerx + 2, rect.y + 8),
                                (rect.centerx + 8, rect.y + 2),
                                (rect.centerx + 12, rect.y + 10),
                                (rect.centerx - 12, rect.y + 10),
                            ]
                            pygame.draw.polygon(screen, self.colors["chessplus_secondary"], crown)
                    # burning marker
                    if self.get_burning_at(board_x, board_y):
                        pygame.draw.circle(screen, (220, 120, 40), (rect.right - 10, rect.y + 10), 5)
                    # clone marker
                    if self.get_clone_at(board_x, board_y):
                        pygame.draw.circle(screen, (120, 200, 240), (rect.x + 10, rect.bottom - 10), 5, 2)

    def draw_status(self, screen, font, big_font):
        layout = self.layout()
        x = layout["board_x"]
        y = layout["board_y"] + layout["board_size"] + 12
        color_map = {"white": "білий", "black": "чорний"}
        ox, oy = self.get_chaos_text_offset()

        lines = []
        if self.state:
            turn_color = color_map.get(self.state.turn, self.state.turn)
            turn_number = self.state.move_count + 1
            lines.append(f"Хід: {turn_color}, № {turn_number}")
        else:
            lines.append("Очікуємо гравців...")

        lines.append(f"Таймер: {self.get_timer_display()}")
        lines.append(f"Партія № {self.game_id if self.game_id is not None else '--'}")
        if self.item_target_mode:
            if self.item_target_phase == "piece":
                lines.append("Вибрати фігуру для ефекту")
            else:
                lines.append("Вибрати ціль ефекту")

        for i, line in enumerate(lines):
            color = (230,230,230)
            if line.startswith("Таймер"):
                remaining = self.get_timer_remaining_ms()
                if remaining is not None:
                    if remaining <= 30_000:
                        color = (230, 60, 60)
                    elif remaining <= 60_000:
                        color = (220, 140, 40)
            txt = font.render(line, True, color)
            screen.blit(txt, (x + ox, y + oy))
            y += 24

        self.draw_chaos_bar(screen, font, x + ox, y + oy + 4, width=280, height=20)

    def get_timer_display(self):
        if self.timer_sync_ms is None or self.timer_sync_time is None:
            return "--:--"
        if self.timer_running:
            elapsed = int((time.time() - self.timer_sync_time) * 1000)
            remaining = max(0, self.timer_sync_ms - elapsed)
        else:
            remaining = max(0, self.timer_sync_ms)
        total_seconds = remaining // 1000
        mm = total_seconds // 60
        ss = total_seconds % 60
        return f"{mm:02d}:{ss:02d}"

    def get_timer_remaining_ms(self):
        if self.timer_sync_ms is None or self.timer_sync_time is None:
            return None
        if self.timer_running:
            elapsed = int((time.time() - self.timer_sync_time) * 1000)
            return max(0, self.timer_sync_ms - elapsed)
        return max(0, self.timer_sync_ms)

    def error_text(self, code):
        mapping = {
            "not_your_turn": "Не ваш хід",
            "not_your_piece": "Не ваша фігура",
            "illegal_move": "Нелегальний хід",
            "no_piece": "Нема фігури",
            "dest_occupied": "Клітинка зайнята",
            "out_of_bounds": "Позa межами дошки",
            "illegal_pawn_move": "Нелегальний хід пішака",
            "illegal_knight_move": "Нелегальний хід коня",
            "illegal_bishop_move": "Нелегальний хід слона",
            "illegal_rook_move": "Нелегальний хід тури",
            "illegal_queen_move": "Нелегальний хід ферзя",
            "illegal_king_move": "Нелегальний хід короля",
            "illegal_amazon_move": "Нелегальний хід амазона",
            "illegal_archbishop_move": "Нелегальний хід архієпископа",
            "illegal_camel_move": "Нелегальний хід верблюда",
            "illegal_giant_move": "Нелегальний хід гігантської пішаки",
            "illegal_giant_capture": "Нелегальне взяття гігантською пішаки",
            "same_square": "Хід у ту саму клітинку",
            "blocked": "Шлях заблоковано",
            "item_missing": "Предмет відсутній",
            "item_requires_target": "Потрібна ціль",
            "invalid_target": "Невірна ціль",
            "unknown_item": "Невідомий предмет",
        }
        return mapping.get(code, code)

    def get_chaos_value(self):
        if not self.state:
            return 0
        return int(getattr(self.state, "chaos", 0))

    def chaos_bar_color(self, chaos):
        chaos = max(0, min(100, chaos))
        if chaos < 67:
            t = chaos / 67.0
            r = int(40 + (220 - 40) * t)
            g = int(200 + (200 - 200) * t)
            b = int(60 + (40 - 60) * t)
            return (r, g, b)
        t = (chaos - 67) / 33.0 if chaos > 67 else 0
        r = 220
        g = int(200 - 160 * t)
        b = 40
        return (r, g, b)

    def get_chaos_text_offset(self):
        if self.ui_state not in ("game", "replay"):
            return (0, 0)
        chaos = self.get_chaos_value()
        if chaos < 80:
            return (0, 0)
        if chaos >= 90:
            intensity = 4
        else:
            intensity = 2
        t = time.time()
        ox = int(math.sin(t * 6.5) * intensity)
        oy = int(math.cos(t * 5.2) * intensity)
        return (ox, oy)

    def draw_chaos_bar(self, screen, font, x, y, width=240, height=14):
        chaos = self.get_chaos_value()
        back_rect = pygame.Rect(x, y, width, height)
        pygame.draw.rect(screen, (40, 40, 40), back_rect, border_radius=6)
        fill_w = int(width * (chaos / 100.0))
        if fill_w > 0:
            fill_rect = pygame.Rect(x, y, fill_w, height)
            pygame.draw.rect(screen, self.chaos_bar_color(chaos), fill_rect, border_radius=6)
        pygame.draw.rect(screen, (120, 120, 120), back_rect, 1, border_radius=6)

    def apply_chaos_visuals(self, screen):
        if self.ui_state not in ("game", "replay"):
            return
        chaos = self.get_chaos_value()
        if chaos <= 80:
            return
        tint_strength = min(1.0, (chaos - 80) / 20.0)
        alpha = int((200 if chaos >= 90 else 120) * tint_strength)
        if alpha > 0:
            overlay = pygame.Surface((self.winw, self.winh), pygame.SRCALPHA)
            overlay.fill((160, 30, 30, alpha))
            screen.blit(overlay, (0, 0))
        if chaos >= 90:
            w, h = screen.get_size()
            scale = 0.985
            sw, sh = max(1, int(w * scale)), max(1, int(h * scale))
            small = pygame.transform.smoothscale(screen, (sw, sh))
            temp = pygame.Surface((w, h), pygame.SRCALPHA)
            temp.blit(small, ((w - sw) // 2, (h - sh) // 2))
            temp.set_alpha(120)
            screen.blit(temp, (0, 0))

    def compute_final_score(self):
        if not self.state:
            return None
        royals = {"white": 0, "black": 0}
        material = {"white": 0, "black": 0}
        for y in range(8):
            for x in range(8):
                p = self.state.board.get_piece(x, y)
                if not p:
                    continue
                material[p.color] = material.get(p.color, 0) + cfg.PIECE_VALUES.get(p.ptype, 0)
                if p.ptype in cfg.ROYAL_TYPES:
                    royals[p.color] = royals.get(p.color, 0) + 1
        return {"royals": royals, "material": material}

    def draw_top_bar(self, screen, font):
        layout = self.layout()
        board_x = layout["board_x"]
        board_y = layout["board_y"]
        board_size = layout["board_size"]
        top_y = board_y - 64
        ox, oy = self.get_chaos_text_offset()

        if self.state and hasattr(self.state, "players"):
            white_name = self.state.players.get("white") or "—"
            black_name = self.state.players.get("black") or "—"
        else:
            white_name = "—"
            black_name = "—"

        text_color = self.colors["vanilla_secondary"]
        white_text = font.render(f"Білий: {white_name}", True, text_color)
        black_text = font.render(f"Чорний: {black_name}", True, text_color)
        screen.blit(white_text, (board_x + ox, top_y + oy))
        screen.blit(black_text, (board_x + board_size - black_text.get_width() + ox, top_y + oy))

    def wrap_text(self, text, font, max_width):
        if not text:
            return []
        words = text.split()
        lines = []
        current = ""
        for w in words:
            test = w if not current else current + " " + w
            if font.size(test)[0] <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = w
        if current:
            lines.append(current)
        return lines

    def clamp_wrapped_lines(self, text, font, max_width, max_lines):
        lines = self.wrap_text(text, font, max_width)
        if max_lines is None or max_lines <= 0:
            return []
        if len(lines) <= max_lines:
            return lines
        lines = lines[:max_lines]
        last = lines[-1]
        ell = "..."
        if font.size(last + ell)[0] <= max_width:
            lines[-1] = last + ell
            return lines
        trimmed = last
        while trimmed and font.size(trimmed + ell)[0] > max_width:
            trimmed = trimmed[:-1].rstrip()
        lines[-1] = (trimmed + ell) if trimmed else ell
        return lines

    def get_popup_pattern(self):
        if self.popup_pattern is not None:
            return self.popup_pattern
        pattern = pygame.Surface((64, 64), pygame.SRCALPHA)
        pattern.fill((0, 0, 0, 0))
        for i in range(-64, 64, 10):
            pygame.draw.line(pattern, (255, 255, 255, 18), (i, 0), (i + 64, 64), 2)
        self.popup_pattern = pattern
        return pattern

    def draw_popup(self, screen, font):
        if not self.popups_enabled:
            return
        life_duration = 2.2
        fade_in_time = 0.25
        fade_out_time = 0.3
        age = time.time() - self.popup['time']
        if age > life_duration:
            del self.popup
            return
        fade_in = min(1.0, max(0.0, age / fade_in_time))
        fade_out = 1.0
        if age > (life_duration - fade_out_time):
            fade_out = max(0.0, 1.0 - (age - (life_duration - fade_out_time)) / fade_out_time)
        fade = min(fade_in, fade_out)

        layout = self.layout()
        popup_font = self.get_font("accent", 28)
        title = self.popup.get('title', '')
        message = self.popup.get('message', '')
        theme = self.popup.get('theme')

        max_w = min(520, layout["board_size"])
        title_color = self.colors["vanilla_secondary"]
        if theme == "minesweeper":
            title_color = self.colors["mine_secondary"]
        elif theme == "chessplus":
            title_color = self.colors["chessplus_secondary"]
        title_surf = popup_font.render(title, True, title_color)
        lines = self.wrap_text(message, font, max_w - 40)
        line_surfs = [font.render(line, True, (230, 230, 230)) for line in lines]
        content_h = title_surf.get_height() + (len(line_surfs) * (font.get_height() + 2))
        box_w = max(title_surf.get_width(), max((s.get_width() for s in line_surfs), default=0)) + 40
        box_w = min(max_w, max(220, box_w))
        box_h = max(46, content_h + 28)

        popup_x = layout["board_x"] + layout["board_size"] // 2
        popup_y = layout["board_y"] - 52
        rect = pygame.Rect(0, 0, box_w, box_h)
        slide = int((1.0 - fade_in) * 10)
        rect.center = (popup_x, popup_y - slide)

        # shadow
        shadow = rect.move(3, 3)
        shadow_surf = pygame.Surface((shadow.w, shadow.h), pygame.SRCALPHA)
        shadow_surf.fill((0, 0, 0, int(120 * fade)))
        screen.blit(shadow_surf, shadow)

        # background with subtle texture
        bg = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        if theme == "minesweeper":
            base = self.colors["mine_bg"]
        elif theme == "chessplus":
            base = self.colors["chessplus_bg"]
        else:
            base = self.colors["vanilla_panel"]
        bg.fill((base[0], base[1], base[2], int(210 * fade)))
        pattern = self.get_popup_pattern()
        for px in range(0, rect.w, pattern.get_width()):
            for py in range(0, rect.h, pattern.get_height()):
                bg.blit(pattern, (px, py))
        screen.blit(bg, rect)

        if theme == "minesweeper":
            border_col = self.colors["mine_secondary"]
        elif theme == "chessplus":
            border_col = self.colors["chessplus_secondary"]
        else:
            border_col = self.colors["vanilla_secondary"]
        pygame.draw.rect(screen, (*border_col, int(220 * fade)), rect, 2, border_radius=10)

        # text
        title_rect = title_surf.get_rect(center=(rect.centerx, rect.y + 18))
        screen.blit(title_surf, title_rect)
        ty = rect.y + 18 + title_surf.get_height() + 6
        for s in line_surfs:
            s_rect = s.get_rect(center=(rect.centerx, ty + s.get_height() // 2))
            screen.blit(s, s_rect)
            ty += s.get_height() + 2

        # life line under popup
        life_ratio = max(0.0, 1.0 - (age / life_duration))
        if life_ratio > 0:
            bar_w = max(2, int((rect.w - 16) * life_ratio))
            bar_h = 4
            bar_x = rect.x + 8
            bar_y = rect.bottom + 6
            bar_bg = pygame.Surface((rect.w - 16, bar_h), pygame.SRCALPHA)
            bar_bg.fill((20, 20, 20, int(120 * fade)))
            bar_fg = pygame.Surface((bar_w, bar_h), pygame.SRCALPHA)
            bar_fg.fill((*border_col, int(200 * fade)))
            screen.blit(bar_bg, (bar_x, bar_y))
            screen.blit(bar_fg, (bar_x, bar_y))

    def settings_buttons(self):
        buttons = {"back": pygame.Rect(20, 20, 120, 40)}
        start_y = 170
        row_h = 54
        for i, (key, _) in enumerate(self.settings_rows):
            y = start_y + i * row_h
            minus_rect = pygame.Rect(self.winw//2 + 140, y - 6, 36, 32)
            plus_rect = pygame.Rect(self.winw//2 + 182, y - 6, 36, 32)
            buttons[f"{key}_minus"] = minus_rect
            buttons[f"{key}_plus"] = plus_rect
        pop_y = start_y + len(self.settings_rows) * row_h
        buttons["popups_toggle"] = pygame.Rect(self.winw//2 + 140, pop_y - 6, 80, 32)
        return buttons

    def get_setting_value(self, key):
        if key == "music_master":
            return self.music_master
        if key == "sfx_master":
            return self.sfx_master
        if key == "music_result":
            return self.music_volumes.get("win", 1.0)
        if key.startswith("music_"):
            track = key.split("_", 1)[1]
            return self.music_volumes.get(track, 1.0)
        return 0.0

    def adjust_setting(self, key, delta):
        if key == "music_master":
            self.music_master = self.clamp(self.music_master + delta)
            self.update_music_volume()
        elif key == "sfx_master":
            self.sfx_master = self.clamp(self.sfx_master + delta)
            self.update_sfx_volume()
        elif key == "music_result":
            current = self.music_volumes.get("win", 1.0)
            new_val = self.clamp(current + delta)
            self.music_volumes["win"] = new_val
            self.music_volumes["lose"] = new_val
            self.update_music_volume()
        elif key.startswith("music_"):
            track = key.split("_", 1)[1]
            current = self.music_volumes.get(track, 1.0)
            self.music_volumes[track] = self.clamp(current + delta)
            self.update_music_volume()

    def get_setting_step(self):
        mods = pygame.key.get_mods()
        return 0.25 if (mods & pygame.KMOD_SHIFT) else 0.05

    def draw_settings(self, screen, big_font, font, mouse_pos):
        title = big_font.render("Налаштування", True, (230,230,230))
        screen.blit(title, title.get_rect(center=(self.winw//2, 90)))
        hint = font.render("Підказка: утримуйте Shift для кроку 25%", True, (180, 180, 180))
        screen.blit(hint, hint.get_rect(center=(self.winw//2, 120)))

        rects = self.settings_buttons()
        start_y = 170
        row_h = 54
        label_x = self.winw//2 - 260

        for i, (key, label) in enumerate(self.settings_rows):
            y = start_y + i * row_h
            value = int(self.get_setting_value(key) * 100)
            txt = font.render(f"{label}: {value}%", True, (230,230,230))
            screen.blit(txt, (label_x, y))

            minus_rect = rects[f"{key}_minus"]
            plus_rect = rects[f"{key}_plus"]
            self.draw_button(screen, minus_rect, "-", font, f"settings_{key}_minus", minus_rect.collidepoint(mouse_pos))
            self.draw_button(screen, plus_rect, "+", font, f"settings_{key}_plus", plus_rect.collidepoint(mouse_pos))

        pop_y = start_y + len(self.settings_rows) * row_h
        pop_label = font.render("Спливаючі вікна", True, (230,230,230))
        screen.blit(pop_label, (label_x, pop_y))
        toggle_rect = rects["popups_toggle"]
        base_col = (80, 80, 80) if not self.popups_enabled else self.colors["vanilla_secondary"]
        pygame.draw.rect(screen, base_col, toggle_rect, border_radius=6)
        pygame.draw.rect(screen, self.colors["vanilla_button_border"], toggle_rect, 2, border_radius=6)
        mark = "ON" if self.popups_enabled else "OFF"
        mark_surf = font.render(mark, True, (20, 20, 20) if self.popups_enabled else (220, 220, 220))
        screen.blit(mark_surf, mark_surf.get_rect(center=toggle_rect.center))

        self.draw_button(screen, rects["back"], "Назад", font, "settings_back", rects["back"].collidepoint(mouse_pos))

    def draw_right_panel(self, screen, font, big_font):
        layout = self.layout()
        rect = layout["panel_rect"]
        pygame.draw.rect(screen, self.colors["vanilla_panel"], rect, border_radius=8)
        pygame.draw.rect(screen, self.colors["vanilla_panel_border"], rect, 2, border_radius=8)
        ox, oy = self.get_chaos_text_offset()

        title = big_font.render("DLC", True, self.colors["vanilla_secondary"])
        screen.blit(title, (rect.x + 16 + ox, rect.y + 12 + oy))

        y = rect.y + 54
        if self.state and getattr(self.state, "dlc_packs", None):
            for pack in self.state.dlc_packs:
                active = pack.get("active", False)
                name = pack.get("name", "DLC")
                size = pack.get("size", "")
                header_color = self.colors["vanilla_secondary"]
                if pack.get("id") == "minesweeper":
                    header_color = self.colors["mine_primary"]
                elif pack.get("id") == "chessplus":
                    header_color = self.colors["chessplus_primary"]
                header_text = f"{name} ({size})"
                header = self.fit_text_surface(font, header_text, rect.width - 32, header_color, max_height=20)
                screen.blit(header, (rect.x + 16 + ox, y + oy))
                y += 22
                status_text = f"Статус: {'активний' if active else 'неактивний'}"
                status = self.fit_text_surface(font, status_text, rect.width - 40, (200,200,200), max_height=18)
                screen.blit(status, (rect.x + 24 + ox, y + oy))
                y += 20
                if active and pack.get("next_effect_in") is not None:
                    nxt = pack.get("next_effect_in")
                    if pack.get("id") == "minesweeper":
                        info_color = self.colors["mine_secondary"]
                    elif pack.get("id") == "chessplus":
                        info_color = self.colors["chessplus_secondary"]
                    else:
                        info_color = (200,200,200)
                    info_text = f"Наст. ефект: {nxt} ход(и)"
                    info = self.fit_text_surface(font, info_text, rect.width - 40, info_color, max_height=18)
                    screen.blit(info, (rect.x + 24 + ox, y + oy))
                    y += 20
                y += 8
        else:
            empty = font.render("Нема DLC паків", True, (190,190,190))
            screen.blit(empty, (rect.x + 16 + ox, y + oy))

        status_rect = pygame.Rect(rect.x + 12, rect.bottom - 130, rect.width - 24, 120)

        # error text under DLC list
        if self.last_error:
            err_text = self.error_text(self.last_error)
            err_line = f"Помилка: {err_text}"
            line_h = font.get_height() + 2
            status_top = status_rect.top
            available = max(0, status_top - y - 8)
            max_lines = max(1, available // max(1, line_h)) if available > 0 else 1
            lines = self.clamp_wrapped_lines(err_line, font, rect.width - 32, max_lines)
            box_h = len(lines) * line_h + 8
            box_y = y + 4
            if box_y + box_h > status_top - 4:
                box_y = status_top - box_h - 4
            box_rect = pygame.Rect(rect.x + 12, box_y, rect.width - 24, box_h)
            pygame.draw.rect(screen, (80, 40, 40), box_rect, border_radius=6)
            pygame.draw.rect(screen, (180, 80, 80), box_rect, 1, border_radius=6)
            ty = box_rect.y + 4
            for line in lines:
                surf = font.render(line, True, (240, 200, 200))
                screen.blit(surf, (box_rect.x + 8, ty))
                ty += line_h

        self.draw_status_panel(screen, font, status_rect)

    def draw_status_panel(self, screen, font, rect):
        pygame.draw.rect(screen, (44, 36, 58), rect, border_radius=8)
        pygame.draw.rect(screen, self.colors["vanilla_button_border"], rect, 2, border_radius=8)
        ox, oy = self.get_chaos_text_offset()
        x = rect.x + 12 + ox
        y = rect.y + 10 + oy
        color_map = {"white": "білий", "black": "чорний"}
        lines = []
        if self.state:
            turn_color = color_map.get(self.state.turn, self.state.turn)
            turn_number = self.state.move_count + 1
            lines.append(f"Хід: {turn_color}, № {turn_number}")
        else:
            lines.append("Очікуємо гравців...")
        lines.append(f"Таймер: {self.get_timer_display()}")
        lines.append(f"Партія № {self.game_id if self.game_id is not None else '--'}")
        if self.item_target_mode:
            if self.item_target_phase == "piece":
                lines.append("Вибрати фігуру для ефекту")
            else:
                lines.append("Вибрати ціль ефекту")
        line_h = font.get_height() + 2
        max_lines = max(1, (rect.height - 34) // line_h)
        lines = lines[:max_lines]
        for line in lines:
            txt = self.fit_text_surface(font, line, rect.width - 24, (230, 230, 230), max_height=18)
            screen.blit(txt, (x, y))
            y += line_h
        bar_w = rect.width - 24
        self.draw_chaos_bar(screen, font, rect.x + 12 + ox, rect.bottom - 26 + oy, width=bar_w, height=18)

    def draw_inventory_bar(self, screen):
        inv = self.get_my_inventory()
        gap = 8
        slot_size = min(70, max(48, int((self.winw - 2 * self.margin - gap * 8) / 9)))
        total_slots_w = slot_size * 9 + gap * 8
        bar_w = total_slots_w + 24
        bar_h = slot_size + 12
        x = (self.winw - bar_w) // 2
        y = self.winh - bar_h - 10
        bar_rect = pygame.Rect(x, y, bar_w, bar_h)
        pygame.draw.rect(screen, (50, 44, 66), bar_rect, border_radius=10)
        pygame.draw.rect(screen, self.colors["vanilla_button_border"], bar_rect, 2, border_radius=10)

        start_x = bar_rect.x + (bar_rect.width - total_slots_w) // 2
        slot_y = bar_rect.y + (bar_rect.height - slot_size) // 2
        item_font = self.get_font("main", 18)
        uses_font = self.get_font("uses", max(12, int(slot_size * 0.28)))
        self.inventory_slot_rects = {}
        slot_img = self.get_inventory_slot_image(slot_size)

        for i in range(9):
            sx = start_x + i * (slot_size + gap)
            rect = pygame.Rect(sx, slot_y, slot_size, slot_size)
            self.inventory_slot_rects[i] = rect
            if slot_img:
                screen.blit(slot_img, rect.topleft)
                if self.selected_item_slot == i:
                    pygame.draw.rect(screen, self.colors["vanilla_primary"], rect, 2, border_radius=6)
            else:
                base_color = (70, 70, 70)
                if self.selected_item_slot == i:
                    base_color = self.colors["vanilla_primary"]
                pygame.draw.rect(screen, base_color, rect, border_radius=6)
                pygame.draw.rect(screen, self.colors["vanilla_button_border"], rect, 2, border_radius=6)

            item = inv[i] if i < len(inv) else None
            if item:
                effect_id = item.get("effect_id")
                icon = self.get_item_image(effect_id, int(slot_size * 0.6))
                if icon:
                    screen.blit(icon, icon.get_rect(center=rect.center))
                else:
                    name = item.get("name", "")
                    short = name if len(name) <= 6 else name[:6] + "."
                    txt = item_font.render(short, True, (230, 230, 230))
                    screen.blit(txt, (rect.x + 4, rect.y + int(slot_size * 0.45)))
                uses = item.get("uses")
                if uses is not None:
                    uses_txt = uses_font.render(str(uses), True, (0, 0, 0))
                    screen.blit(uses_txt, (rect.right - uses_txt.get_width() - 4, rect.bottom - uses_txt.get_height() - 3))

    def draw_game_over(self, screen, big_font, font, mouse_pos):
        overlay = pygame.Surface((self.winw, self.winh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        screen.blit(overlay, (0, 0))

        title = "Кінець гри"
        subtitle = None
        if self.game_over_winner and self.my_color:
            title = "Перемога!" if self.game_over_winner == self.my_color else "Поразка"
        if self.game_over_reason:
            reason_map = {
                "royal_captured": "Усі королівські фігури захоплено",
                "royal_both": "Всі королівські фігури знищено",
                "timer_royal": "Перемога за королівськими фігурами",
                "timer_material": "Перемога за матеріалом",
                "timer_random": "Перемога визначена випадково",
                "opponent_left": "Суперник вийшов",
                "room_full": "Кімната заповнена",
            }
            subtitle = reason_map.get(self.game_over_reason, self.game_over_reason)

        t_surf = big_font.render(title, True, (255, 255, 255))
        t_rect = t_surf.get_rect(center=(self.winw // 2, self.winh // 2 - 20))
        screen.blit(t_surf, t_rect)

        if subtitle:
            s_surf = font.render(subtitle, True, (220, 220, 220))
            s_rect = s_surf.get_rect(center=(self.winw // 2, self.winh // 2 + 20))
            screen.blit(s_surf, s_rect)

        score = self.compute_final_score()
        if score:
            royals = score.get("royals", {})
            material = score.get("material", {})
            score_text = (
                f"Рахунок: королівські {royals.get('white', 0)}-{royals.get('black', 0)}, "
                f"матеріал {material.get('white', 0)}-{material.get('black', 0)}"
            )
            sc_surf = font.render(score_text, True, (200, 200, 200))
            sc_rect = sc_surf.get_rect(center=(self.winw // 2, self.winh // 2 + 44))
            screen.blit(sc_surf, sc_rect)

        hint = font.render("Оберіть дію:", True, (200, 200, 200))
        h_rect = hint.get_rect(center=(self.winw // 2, self.winh // 2 + 78))
        screen.blit(hint, h_rect)

        rects = self.get_game_over_buttons()
        self.game_over_buttons = rects
        self.draw_button(screen, rects["exit"], "Вийти", font, "over_exit", rects["exit"].collidepoint(mouse_pos))
        self.draw_button(screen, rects["menu"], "Головне меню", font, "over_menu", rects["menu"].collidepoint(mouse_pos))
        self.draw_button(screen, rects["restart"], "Рестарт", font, "over_restart", rects["restart"].collidepoint(mouse_pos))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--name', default='Player')
    args = parser.parse_args()
    client = Client(args.host, args.name)
    client.start_ui()

if __name__ == '__main__':
    main()
