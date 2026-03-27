import random
from modules.dlc.minesweeper import spawn_mines, temp_reveal_numbers, trigger_mine
from modules.dlc.chessplus import spawn_cells, spawn_void, spawn_wall, apply_pawn_mutations

RARITY_WEIGHTS = {
    "common": 50,
    "uncommon": 40,
    "rare": 30,
    "epic": 15,
    "legendary": 5,
}

PACK_DEFS = [
    {
        "id": "minesweeper",
        "name": "Minesweeper DLC",
        "size": "medium",
        "theme_color": [20, 120, 20],
        "effects": [
            {
                "id": "ms_spawn_mine",
                "name": "Спавн міни",
                "rarity": "common",
                "spawn_limit": (2, 3),
                "effect_type": "cell",
                "is_item": False,
            },
            {
                "id": "ms_spawn_mines",
                "name": "Спавн мін (2-5)",
                "rarity": "rare",
                "spawn_limit": 2,
                "effect_type": "cell",
                "is_item": False,
            },
            {
                "id": "ms_reveal_numbers",
                "name": "Відкрити числа",
                "rarity": "rare",
                "spawn_limit": 1,
                "effect_type": "field",
                "is_item": False,
            },
            {
                "id": "ms_explode_random",
                "name": "Випадковий вибух",
                "rarity": "epic",
                "spawn_limit": 1,
                "effect_type": "cell",
                "is_item": False,
            },
            {
                "id": "ms_item_place_mine",
                "name": "Поставити міну",
                "rarity": "epic",
                "spawn_limit": 3,
                "effect_type": "item",
                "is_item": True,
                "uses": 1,
                "target": "cell",
            },
            {
                "id": "ms_item_reveal_explode",
                "name": "Показати та підірвати міну",
                "rarity": "legendary",
                "spawn_limit": 1,
                "effect_type": "item",
                "is_item": True,
                "uses": 1,
                "target": "mine",
            },
        ],
    },
    {
        "id": "chessplus",
        "name": "Chess+ DLC",
        "size": "large",
        "theme_color": [242, 224, 178],
        "effects": [
            {
                "id": "cp_dice_tile",
                "name": "Клітинка-кубик",
                "rarity": "rare",
                "spawn_limit": 6,
                "effect_type": "cell",
                "is_item": False,
            },
            {
                "id": "cp_fire_tile",
                "name": "Вогняна клітинка",
                "rarity": "uncommon",
                "spawn_limit": 5,
                "effect_type": "cell",
                "is_item": False,
            },
            {
                "id": "cp_void",
                "name": "Безодня",
                "rarity": "legendary",
                "spawn_limit": 1,
                "effect_type": "field",
                "is_item": False,
            },
            {
                "id": "cp_bomb_tile",
                "name": "Бомба",
                "rarity": "uncommon",
                "spawn_limit": 5,
                "effect_type": "cell",
                "is_item": False,
            },
            {
                "id": "cp_swap_tile",
                "name": "Клітинка-обмін",
                "rarity": "common",
                "spawn_limit": 3,
                "effect_type": "cell",
                "is_item": False,
            },
            {
                "id": "cp_wall",
                "name": "Стіна",
                "rarity": "common",
                "spawn_limit": 4,
                "effect_type": "cell",
                "is_item": False,
            },
            {
                "id": "cp_pawn_mutation",
                "name": "Мутації пішаків",
                "rarity": "uncommon",
                "spawn_limit": 2,
                "effect_type": "mutation",
                "is_item": False,
            },
            {
                "id": "cp_item_teleport",
                "name": "Телепорт",
                "rarity": "rare",
                "spawn_limit": 3,
                "effect_type": "item",
                "is_item": True,
                "uses": 3,
                "target": "piece_cell",
            },
            {
                "id": "cp_item_pistol",
                "name": "Пістолет",
                "rarity": "uncommon",
                "spawn_limit": 3,
                "effect_type": "item",
                "is_item": True,
                "uses": 2,
                "target": "piece_dir",
            },
            {
                "id": "cp_item_nuke",
                "name": "Ядерний удар",
                "rarity": "legendary",
                "spawn_limit": 1,
                "effect_type": "item",
                "is_item": True,
                "uses": 1,
                "target": "piece",
            },
            {
                "id": "cp_item_clone",
                "name": "Клонування",
                "rarity": "epic",
                "spawn_limit": 2,
                "effect_type": "item",
                "is_item": True,
                "uses": 1,
                "target": "piece_cell",
            },
        ],
    },
]


def roll_spawn_limit(limit):
    if isinstance(limit, (list, tuple)) and len(limit) == 2:
        return random.randint(limit[0], limit[1])
    return int(limit)


def build_pack_states(pack_defs=None):
    if pack_defs is None:
        pack_defs = PACK_DEFS
    packs = []
    for pack_def in pack_defs:
        effects = []
        for e in pack_def["effects"]:
            effects.append({
                "id": e["id"],
                "name": e["name"],
                "rarity": e["rarity"],
                "effect_type": e["effect_type"],
                "is_item": bool(e.get("is_item", False)),
                "uses": e.get("uses"),
                "remaining": None,
            })
        packs.append({
            "id": pack_def["id"],
            "name": pack_def["name"],
            "size": pack_def["size"],
            "theme_color": pack_def["theme_color"],
            "active": False,
            "next_effect_in": None,
            "active_moves": 0,
            "effects": effects,
        })
    return packs


def get_pack_def(pack_id):
    for pack_def in PACK_DEFS:
        if pack_def["id"] == pack_id:
            return pack_def
    return None


def get_effect_def(pack_def, effect_id):
    for e in pack_def["effects"]:
        if e["id"] == effect_id:
            return e
    return None


def activate_pack(pack_state, pack_def):
    pack_state["active"] = True
    pack_state["active_moves"] = 0
    pack_state["next_effect_in"] = random.randint(1, 2)
    for eff_state in pack_state["effects"]:
        eff_def = get_effect_def(pack_def, eff_state["id"])
        if eff_def:
            eff_state["remaining"] = roll_spawn_limit(eff_def.get("spawn_limit", 1))


def choose_effect(pack_state, pack_def):
    candidates = []
    for eff_state in pack_state["effects"]:
        if eff_state.get("remaining", 0) <= 0:
            continue
        eff_def = get_effect_def(pack_def, eff_state["id"])
        if not eff_def:
            continue
        weight = RARITY_WEIGHTS.get(eff_def.get("rarity", "common"), 1)
        candidates.append((eff_def, eff_state, weight))
    if not candidates:
        return None, None
    total = sum(w for _, _, w in candidates)
    roll = random.uniform(0, total)
    upto = 0
    for eff_def, eff_state, weight in candidates:
        if upto + weight >= roll:
            return eff_def, eff_state
        upto += weight
    return candidates[-1][0], candidates[-1][1]


def make_item(effect_def):
    return {
        "id": effect_def["id"],
        "name": effect_def["name"],
        "uses": effect_def.get("uses", 1),
        "target": effect_def.get("target"),
        "effect_id": effect_def["id"],
    }


def apply_effect(effect_def, state):
    effect_id = effect_def["id"]
    if effect_id == "ms_spawn_mine":
        coords = spawn_mines(state, count=1)
        return f"Додано міну ({len(coords)})"
    if effect_id == "ms_spawn_mines":
        count = random.randint(2, 5)
        coords = spawn_mines(state, count=count)
        return f"Додано мін: {len(coords)}"
    if effect_id == "ms_reveal_numbers":
        sample = temp_reveal_numbers(state, percent=0.5, duration_moves=2)
        return f"Показано чисел: {len(sample)}"
    if effect_id == "ms_explode_random":
        mines = [(x, y) for y in range(8) for x in range(8) if state.mines[y][x] == 1]
        if not mines:
            return "Мін нема"
        x, y = random.choice(mines)
        trigger_mine(state, x, y)
        return "Випадкова міна підірвана"

    if effect_id == "cp_dice_tile":
        coords = spawn_cells(state, "dice", count=1)
        return f"Додано кубик: {len(coords)}"
    if effect_id == "cp_fire_tile":
        coords = spawn_cells(state, "fire", count=1)
        return f"Додано вогонь: {len(coords)}"
    if effect_id == "cp_void":
        coords = spawn_void(state)
        return "Безодня активована" if coords else "Безодня вже активна"
    if effect_id == "cp_bomb_tile":
        coords = spawn_cells(state, "bomb", count=1)
        return f"Додано бомбу: {len(coords)}"
    if effect_id == "cp_swap_tile":
        coords = spawn_cells(state, "swap", count=1)
        return f"Додано swap: {len(coords)}"
    if effect_id == "cp_wall":
        wall = spawn_wall(state)
        return "Стіна встановлена" if wall else "Стіни недоступні"
    if effect_id == "cp_pawn_mutation":
        muts = apply_pawn_mutations(state, count=2)
        return f"Мутації пішаків: {len(muts)}"

    return None
