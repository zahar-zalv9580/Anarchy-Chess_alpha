WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 720

BOARD_SIZE = 8
TILE_SIZE = 64
BOARD_MARGIN = 104

SERVER_HOST = "0.0.0.0"
SERVER_PORT = 9999

MATCH_TIME_SECONDS = 600

INTRO_DURATION = 8.0
INTRO_VIDEO_FPS_FALLBACK = 60.0

MOVE_COOLDOWN = 0.5
EXPLOSION_FRAME_TIME = 0.06
EXPLOSION_DELAY = 0.2
CHAIN_REACTION_DELAY = 0.3

FONT_MAIN_NAME = "IosevkaCharon"
FONT_MAIN_FILE = "IosevkaCharon-BoldItalic.ttf"
FONT_ACCENT_NAME = "Handjet-Medium"
FONT_ACCENT_FILE = "Handjet-Medium.ttf"
FONT_USES_NAME = "Minecraft_1.1"
FONT_USES_FILE = "Minecraft_1.1.ttf"

PIECE_VALUES = {
    "pawn": 1,
    "knight": 3,
    "bishop": 3,
    "rook": 5,
    "queen": 9,
    "king": 2,
    "amazon": 12,
    "archbishop": 6,
    "camel": 3,
    "giant_pawn": 3,
}
ROYAL_TYPES = {"king", "queen", "amazon"}

# Currency (ШахоГривні) & Shop
COIN_CAPTURE_PAWN = 2
COIN_CAPTURE_MINOR = 4
COIN_CAPTURE_ROOK = 6
COIN_CAPTURE_ROYAL = 15
COIN_SURVIVAL = 1
COIN_EXPLOSION = 2
COIN_CHAIN = 4
COIN_WIN = 10

SHOP_REFRESH_MOVES = 5
SHOP_ITEM_OFFERS = 5
SHOP_EFFECT_OFFERS = 3
SHOP_PACK_OFFERS = 2
SHOP_MAX_DISCOUNT = 0.35

SHOP_EFFECT_PRICE = {
    "common": (5, 7),
    "uncommon": (7, 10),
    "rare": (10, 15),
    "epic": (20, 25),
    "legendary": (30, 36),
}
SHOP_ITEM_PRICE = {
    "common": (6, 9),
    "uncommon": (8, 12),
    "rare": (12, 16),
    "epic": (20, 26),
    "legendary": (30, 38),
}
SHOP_PACK_PRICE = {
    "small": (15, 20),
    "medium": (25, 35),
    "large": (40, 60),
}
SHOP_PIECE_BASE = 6
SHOP_PIECE_MULT = 2
