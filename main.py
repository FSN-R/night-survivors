"""Night Survivors -- the window, the drawing, the sound and the input.

Only pygame-ce is used here (no Pillow, no wave): so pygbag can run this
file in a web browser later. The main loop is `async def main()` and it
waits with `await asyncio.sleep(0)` once per frame.
"""

import asyncio
import math
import os
import random

import pygame

import rules

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
SOUNDS_DIR = os.path.join(BASE_DIR, "sounds")

#: How loud each sound is, and how often it may start again (in seconds).
SOUND_VOLUME = {
    "hit": 0.35,
    "gem": 0.45,
    "levelup": 0.7,
    "hurt": 0.6,
    "end": 0.7,
}
SOUND_GAP = {"hit": 0.06, "gem": 0.05, "hurt": 0.15}


def load_sounds():
    """Load sounds/hit.wav and friends. A sound may be .ogg or .wav."""
    sounds = {}
    if not pygame.mixer.get_init():
        return sounds
    for name, volume in SOUND_VOLUME.items():
        for extension in (".ogg", ".wav"):
            path = os.path.join(SOUNDS_DIR, name + extension)
            if not os.path.exists(path):
                continue
            try:
                sound = pygame.mixer.Sound(path)
            except pygame.error:
                break
            sound.set_volume(volume)
            sounds[name] = sound
            break
    return sounds


def load_picture(name):
    """Load one finished picture from assets/. None means "not there"."""
    try:
        return pygame.image.load(os.path.join(ASSETS_DIR, name)).convert_alpha()
    except (pygame.error, OSError):
        return None


def load_pictures(config):
    """Load every picture the game may draw. Missing files are simply skipped."""
    names = ["hero.png", "floor.png", "gem.png", "sword.png"]
    names += [enemy["image"] for enemy in config["enemies"].values()]
    names += list(config["gems"]["images"].values())
    pictures = {}
    for name in dict.fromkeys(names):
        image = load_picture(name)
        if image is not None:
            pictures[name] = image
    return pictures


# ---- Colours: only used when a picture is missing (so nothing breaks). ---
FLOOR_DARK = (24, 24, 34)
FLOOR_LIGHT = (31, 31, 44)
HERO_FILL = (120, 220, 255)
HERO_EDGE = (235, 250, 255)
SPARK_FILL = (255, 226, 120)
HP_BACK = (40, 18, 22)
HP_FILL = (225, 60, 70)
TEXT = (235, 240, 250)
OVERLAY = (8, 8, 14)
SPARK_EDGE = (92, 40, 18)
HUD_PANEL = (10, 8, 12, 150)
XP_BACK = (18, 24, 46)
XP_FILL = (80, 150, 250)
GEM_FILL = (120, 190, 255)
RING_EDGE = (255, 220, 140)
CARD_BG = (22, 22, 34)
CARD_EDGE = (96, 116, 168)
CARD_MUTED = (156, 166, 190)
VICTORY_TEXT = (255, 232, 128)


def short_time(seconds):
    """Turn 83.4 into "1:23"."""
    minutes, rest = divmod(int(seconds), 60)
    return "%d:%02d" % (minutes, rest)


ENEMY_COLOURS = {
    "bat": (190, 90, 220),
    "slime": (110, 200, 120),
    "ghost": (200, 205, 225),
    "boss": (230, 70, 60),
}

#: At most this many damage numbers are on the screen at the same time.
MAX_DAMAGE_NUMBERS = 40

#: The last App that was created. The fake-input test uses it to look at
#: the game while it runs.
CURRENT_APP = None


class App:
    """Everything pygame lives here."""

    def __init__(self, config, screen=None):
        self.config = config
        self.width = int(config["screen"]["width"])
        self.height = int(config["screen"]["height"])
        self.fps = int(config["screen"]["fps"])

        pygame.init()
        if screen is None:
            self.screen = pygame.display.set_mode((self.width, self.height))
        else:
            self.screen = screen
        pygame.display.set_caption("Night Survivors")
        self.clock = pygame.time.Clock()
        self.font_huge = pygame.font.Font(None, 76)
        self.font_big = pygame.font.Font(None, 40)
        self.font_small = pygame.font.Font(None, 22)

        self.pictures = load_pictures(config)
        self.bigger_pictures = {}
        self.floor_tile = self.make_floor_tile()

        # Sound is nice but never required: in a browser it may not work.
        try:
            pygame.mixer.init()
        except pygame.error:
            pass
        self.sounds = load_sounds()
        self.sound_started = {}
        self.numbers = []           # floating damage numbers
        self.flashes = []           # a flash where an enemy died
        self.shake_timer = 0.0      # small camera shake when the hero is hurt
        self.camera_shake = (0.0, 0.0)

        self.game = rules.Game(config)
        self.paused = False
        self.running = True
        self.pointer = None         # last mouse position on the screen
        self.finger = None          # last finger position on the screen
        self.using_touch = False
        self.accumulator = 0.0      # real time not used up by fixed steps

    # ---------------------------------------------------------- coordinates
    def world_to_screen(self, world_x, world_y):
        """The camera always keeps the hero in the middle of the window."""
        return (
            world_x - self.game.hero.x + self.width / 2.0 + self.camera_shake[0],
            world_y - self.game.hero.y + self.height / 2.0 + self.camera_shake[1],
        )

    def screen_to_world(self, screen_pos):
        return (
            screen_pos[0] + self.game.hero.x - self.width / 2.0,
            screen_pos[1] + self.game.hero.y - self.height / 2.0,
        )

    # ------------------------------------------------------------ pictures
    def make_floor_tile(self):
        """The floor picture, cut to exactly one tile of the map."""
        floor = self.pictures.get("floor.png")
        if floor is None:
            return None
        tile = int(self.config["floor"]["tile"])
        return pygame.transform.scale(floor, (tile, tile))

    def picture(self, name, bigger=1):
        """A picture, made `bigger` times bigger when asked (the boss uses 2)."""
        image = self.pictures.get(name)
        if image is None or bigger == 1:
            return image
        key = (name, bigger)
        if key not in self.bigger_pictures:
            self.bigger_pictures[key] = pygame.transform.scale(
                image, (image.get_width() * bigger, image.get_height() * bigger)
            )
        return self.bigger_pictures[key]

    def draw_picture(self, name, world_x, world_y, bigger=1):
        """Draw a picture centred on a world point. False when it is missing."""
        image = self.picture(name, bigger)
        if image is None:
            return False
        x, y = self.world_to_screen(world_x, world_y)
        self.screen.blit(image, image.get_rect(center=(int(x), int(y))))
        return True

    # --------------------------------------------------------------- input
    def handle_event(self, event):
        if event.type == pygame.QUIT:
            self.running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_p:
                if self.game.state == "playing":
                    self.paused = not self.paused
        elif event.type == pygame.MOUSEMOTION:
            # A real mouse takes control back (a touch screen also sends
            # mouse events, but then the finger wins, see current_target()).
            self.using_touch = False
            self.pointer = event.pos
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if self.game.state == "levelup":
                self.choose_card(event.pos)
            elif self.game.state != "playing":
                # A click or a tap on the end screen always plays again.
                self.play_again()
            else:
                self.using_touch = False
                self.pointer = event.pos
        elif event.type == pygame.FINGERDOWN:
            self.using_touch = True
            spot = (event.x * self.width, event.y * self.height)
            if self.game.state == "levelup":
                self.choose_card(spot)
            elif self.game.state != "playing":
                self.play_again()
            else:
                self.finger = spot
        elif event.type == pygame.FINGERMOTION:
            self.using_touch = True
            self.finger = (event.x * self.width, event.y * self.height)
        elif event.type == pygame.FINGERUP:
            self.using_touch = True
            self.finger = None
            self.pointer = None

    def current_target(self):
        """Where the hero should walk to, in world pixels (or None)."""
        if self.finger is not None:
            return self.screen_to_world(self.finger)
        if self.pointer is not None:
            return self.screen_to_world(self.pointer)
        return None

    def play_again(self):
        self.game.restart()
        self.paused = False
        self.accumulator = 0.0
        self.numbers = []
        self.flashes = []
        self.shake_timer = 0.0
        self.camera_shake = (0.0, 0.0)

    # ----------------------------------------------------- the level-up cards
    def card_rects(self):
        """Where the level-up cards are on the screen."""
        count = max(1, len(self.game.offers))
        card_width = self.width - 48
        card_height = 112
        gap = 14
        total = count * card_height + (count - 1) * gap
        top = (self.height - total) // 2 + 24
        return [
            pygame.Rect(24, top + index * (card_height + gap), card_width, card_height)
            for index in range(count)
        ]

    def choose_card(self, screen_pos):
        """Click or tap a card. Returns True when a card was taken."""
        for index, rect in enumerate(self.card_rects()):
            if rect.collidepoint(screen_pos):
                self.game.choose(index)
                return True
        return False

    def wrap_text(self, text, font, max_width):
        """Split a sentence into lines that fit in `max_width` pixels."""
        words = text.split()
        lines = []
        line = ""
        for word in words:
            try_line = (line + " " + word).strip()
            if font.size(try_line)[0] <= max_width or not line:
                line = try_line
            else:
                lines.append(line)
                line = word
        if line:
            lines.append(line)
        return lines

    # -------------------------------------------------------------- update
    def update(self):
        """One frame: real time goes in, fixed steps of 1/60 s come out."""
        real_dt = self.clock.tick(self.fps) / 1000.0
        self.update_effects(real_dt)
        if self.paused:
            return
        if self.game.state != "playing":
            self.handle_game_events()
            return
        self.game.target = self.current_target()
        self.accumulator += min(real_dt, 0.25)
        while self.accumulator >= rules.FIXED_DT:
            self.game.update(rules.FIXED_DT)
            self.accumulator -= rules.FIXED_DT
        self.handle_game_events()

    # ------------------------------------------------------- sound and feel
    def play_sound(self, name):
        """Play a sound now, unless it just played (many hits in one frame)."""
        sound = self.sounds.get(name)
        if sound is None:
            return
        now = pygame.time.get_ticks() / 1000.0
        gap = SOUND_GAP.get(name, 0.0)
        if now - self.sound_started.get(name, -99.0) < gap:
            return
        self.sound_started[name] = now
        sound.play()

    def add_damage_number(self, x, y, amount):
        """One number per spot: a repeated hit just refreshes it."""
        for number in self.numbers:
            if abs(number["x"] - x) < 18 and abs(number["y"] - y) < 18:
                number["life"] = number["total"]
                number["text"] = "-%d" % amount
                return
        self.numbers.append({
            "text": "-%d" % amount, "x": x, "y": y,
            "life": 0.5, "total": 0.5,
        })
        if len(self.numbers) > MAX_DAMAGE_NUMBERS:
            self.numbers.pop(0)

    def handle_game_events(self):
        """Turn the game events into sounds, numbers and flashes."""
        for event in self.game.take_events():
            kind = event["kind"]
            if kind == "hit":
                self.add_damage_number(event["x"], event["y"], int(event["amount"]))
                self.play_sound("hit")
            elif kind == "kill":
                self.flashes.append({
                    "x": event["x"], "y": event["y"],
                    "life": 0.2, "total": 0.2,
                })
            elif kind == "gem":
                self.play_sound("gem")
            elif kind == "hurt":
                self.shake_timer = 0.22
                self.play_sound("hurt")
            elif kind == "levelup":
                self.play_sound("levelup")
            elif kind == "end":
                self.play_sound("end")

    def update_effects(self, real_dt):
        """Move the damage numbers and flashes, and let the shake die down."""
        for number in self.numbers:
            number["life"] -= real_dt
        self.numbers = [number for number in self.numbers if number["life"] > 0]

        for flash in self.flashes:
            flash["life"] -= real_dt
        self.flashes = [flash for flash in self.flashes if flash["life"] > 0]

        if self.shake_timer > 0.0:
            self.shake_timer = max(0.0, self.shake_timer - real_dt)
            amount = 3.0 * (self.shake_timer / 0.22)
            self.camera_shake = (
                random.uniform(-amount, amount),
                random.uniform(-amount, amount),
            )
        else:
            self.camera_shake = (0.0, 0.0)

    # ---------------------------------------------------------------- draw
    def draw(self):
        self.screen.fill(FLOOR_DARK)
        self.draw_floor()
        self.draw_gems()
        self.draw_ring()
        self.draw_sparks()
        self.draw_enemies()
        self.draw_flashes()
        self.draw_hero()
        self.draw_blades()
        self.draw_numbers()
        self.draw_hud()
        if self.paused:
            self.draw_overlay("PAUSED", "Press P to keep playing")
        elif self.game.state == "levelup":
            self.draw_levelup()
        elif self.game.state == "victory":
            self.draw_end("VICTORY")
        elif self.game.state == "gameover":
            self.draw_end("GAME OVER")

    def draw_gems(self):
        """Gems on the floor: blue is 1 XP, pink is 2 XP."""
        names = self.config["gems"]["images"]
        for gem in self.game.gems:
            # blue is 1 XP; 2 XP and any merged gem above that look pink
            colour_key = "2" if gem.xp >= 2 else "1"
            if not self.draw_picture(names.get(colour_key, "gem.png"), gem.x, gem.y):
                x, y = self.world_to_screen(gem.x, gem.y)
                pygame.draw.circle(
                    self.screen, GEM_FILL, (int(x), int(y)), int(gem.radius)
                )

    def draw_ring(self):
        """The Holy Ring: a circle around the hero."""
        if self.game.ring_radius <= 0.0:
            return
        x, y = self.world_to_screen(self.game.hero.x, self.game.hero.y)
        pygame.draw.circle(
            self.screen, RING_EDGE, (int(x), int(y)), int(self.game.ring_radius), 2
        )

    def draw_blades(self):
        """The Spin Blades: swords that go round the hero."""
        sword = self.picture("sword.png")
        for blade_x, blade_y in self.game.blade_positions:
            x, y = self.world_to_screen(blade_x, blade_y)
            if sword is None:
                pygame.draw.circle(self.screen, HERO_FILL, (int(x), int(y)), 8)
                continue
            # Point the sword away from the hero.
            angle = math.atan2(blade_y - self.game.hero.y, blade_x - self.game.hero.x)
            step = int(round((90 - math.degrees(angle)) / 15.0)) * 15
            key = ("sword", step)
            if key not in self.bigger_pictures:
                self.bigger_pictures[key] = pygame.transform.rotate(sword, step)
            image = self.bigger_pictures[key]
            self.screen.blit(image, image.get_rect(center=(int(x), int(y))))

    def draw_flashes(self):
        """A quick white ring where an enemy died."""
        for flash in self.flashes:
            x, y = self.world_to_screen(flash["x"], flash["y"])
            progress = 1.0 - flash["life"] / flash["total"]
            radius = int(10 + 22 * progress)
            alpha = int(200 * (1.0 - progress))
            layer = pygame.Surface((radius * 2 + 4, radius * 2 + 4), pygame.SRCALPHA)
            pygame.draw.circle(
                layer, (255, 255, 255, alpha),
                (radius + 2, radius + 2), radius, 2,
            )
            self.screen.blit(layer, (int(x) - radius - 2, int(y) - radius - 2))

    def draw_numbers(self):
        """Damage numbers floating up and fading out."""
        for number in self.numbers:
            progress = 1.0 - number["life"] / number["total"]
            x, y = self.world_to_screen(number["x"], number["y"] - 10 - 26 * progress)
            shade = int(255 * (1.0 - progress * 0.7))
            text = self.font_small.render(
                number["text"], True, (255, shade, int(shade * 0.6))
            )
            shadow = self.font_small.render(number["text"], True, (40, 20, 10))
            self.screen.blit(shadow, (int(x) + 1, int(y) + 1))
            self.screen.blit(text, (int(x), int(y)))

    def draw_levelup(self):
        """Three big cards: click or tap one."""
        layer = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        layer.fill((OVERLAY[0], OVERLAY[1], OVERLAY[2], 190))
        self.screen.blit(layer, (0, 0))
        title = self.font_big.render("Level %d" % self.game.level, True, TEXT)
        self.screen.blit(title, title.get_rect(center=(self.width // 2, 64)))
        hint = self.font_small.render("Click or tap a card", True, CARD_MUTED)
        self.screen.blit(hint, hint.get_rect(center=(self.width // 2, 94)))
        for card, rect in zip(self.game.offers, self.card_rects()):
            pygame.draw.rect(self.screen, CARD_BG, rect, border_radius=10)
            pygame.draw.rect(self.screen, CARD_EDGE, rect, 2, border_radius=10)
            name = self.font_big.render(card["name"], True, TEXT)
            self.screen.blit(name, (rect.x + 16, rect.y + 12))
            if card["kind"] != "heal":
                subtitle = "Level %d" % card["level"]
                level_text = self.font_small.render(subtitle, True, CARD_EDGE)
                self.screen.blit(level_text, (rect.x + 16, rect.y + 48))
            lines = self.wrap_text(card["text"], self.font_small, rect.width - 32)
            for number, line in enumerate(lines[:2]):
                text = self.font_small.render(line, True, CARD_MUTED)
                self.screen.blit(text, (rect.x + 16, rect.y + 74 + number * 20))

    def draw_floor(self):
        """One tile, repeated forever: the map has no edges."""
        tile = float(self.config["floor"]["tile"])
        camera_x = self.game.hero.x - self.width / 2.0 - self.camera_shake[0]
        camera_y = self.game.hero.y - self.height / 2.0 - self.camera_shake[1]
        first_col = int(camera_x // tile)
        first_row = int(camera_y // tile)
        cols = int(self.width // tile) + 2
        rows = int(self.height // tile) + 2
        for row in range(first_row, first_row + rows):
            for col in range(first_col, first_col + cols):
                x = col * tile - camera_x
                y = row * tile - camera_y
                if self.floor_tile is not None:
                    self.screen.blit(self.floor_tile, (int(x), int(y)))
                else:
                    colour = FLOOR_LIGHT if (row + col) % 2 == 0 else FLOOR_DARK
                    pygame.draw.rect(self.screen, colour, (x, y, tile + 1, tile + 1))

    def draw_hero(self):
        if self.draw_picture("hero.png", self.game.hero.x, self.game.hero.y):
            return
        x, y = self.world_to_screen(self.game.hero.x, self.game.hero.y)
        radius = self.game.hero.hit_radius
        pygame.draw.circle(self.screen, HERO_FILL, (int(x), int(y)), int(radius))
        pygame.draw.circle(self.screen, HERO_EDGE, (int(x), int(y)), int(radius), 2)

    def draw_enemies(self):
        for enemy in self.game.enemies:
            kind = self.config["enemies"][enemy.kind]
            bigger = int(kind.get("scale", 1))
            if self.draw_picture(kind["image"], enemy.x, enemy.y, bigger):
                continue
            colour = ENEMY_COLOURS.get(enemy.kind, (190, 190, 190))
            x, y = self.world_to_screen(enemy.x, enemy.y)
            pygame.draw.circle(self.screen, colour, (int(x), int(y)), int(enemy.radius))
            pygame.draw.circle(
                self.screen, (20, 20, 28), (int(x), int(y)), int(enemy.radius), 1
            )

    def draw_sparks(self):
        for spark in self.game.sparks:
            x, y = self.world_to_screen(spark.x, spark.y)
            radius = int(spark.radius)
            pygame.draw.circle(self.screen, SPARK_EDGE, (int(x), int(y)), radius + 1)
            pygame.draw.circle(self.screen, SPARK_FILL, (int(x), int(y)), radius)

    def draw_hud(self):
        bar_width = int(self.width * 0.55)
        hp_height = 16
        xp_height = 8
        left = 12
        top = 12
        xp_top = top + hp_height + 8
        label_top = xp_top + xp_height + 5
        # A dark see-through panel: the floor picture is bright, so the
        # white numbers need something dark behind them.
        panel = pygame.Surface((bar_width + 12, hp_height + 8 + xp_height + 32), pygame.SRCALPHA)
        panel.fill(HUD_PANEL)
        self.screen.blit(panel, (left - 6, top - 6))
        pygame.draw.rect(self.screen, HP_BACK, (left, top, bar_width, hp_height))
        fraction = max(0.0, min(1.0, self.game.hero.hp / self.game.hero.max_hp))
        if fraction > 0.0:
            pygame.draw.rect(
                self.screen,
                HP_FILL,
                (left, top, int(bar_width * fraction), hp_height),
            )
        pygame.draw.rect(
            self.screen, TEXT, (left, top, bar_width, hp_height), 1
        )

        # The XP bar (blue) and the level, under the HP bar.
        pygame.draw.rect(self.screen, XP_BACK, (left, xp_top, bar_width, xp_height))
        needed = max(1, self.game.level_xp_needed())
        xp_fraction = max(0.0, min(1.0, self.game.xp / needed))
        if xp_fraction > 0.0:
            pygame.draw.rect(
                self.screen,
                XP_FILL,
                (left, xp_top, int(bar_width * xp_fraction), xp_height),
            )
        pygame.draw.rect(
            self.screen, TEXT, (left, xp_top, bar_width, xp_height), 1
        )

        label = self.font_small.render(
            "HP %d / %d" % (self.game.hero.hp, self.game.hero.max_hp), True, TEXT
        )
        self.screen.blit(label, (left, label_top))
        level_label = self.font_small.render("Lv %d" % self.game.level, True, TEXT)
        self.screen.blit(level_label, (left + bar_width - level_label.get_width(), label_top))

        # Top right: the timer, like "0:45 / 2:00".
        timer = self.font_small.render(self.game.run_time_text(), True, TEXT)
        timer_box = pygame.Surface(
            (timer.get_width() + 14, timer.get_height() + 8), pygame.SRCALPHA
        )
        timer_box.fill(HUD_PANEL)
        timer_x = self.width - timer_box.get_width() - 12
        self.screen.blit(timer_box, (timer_x, 10))
        self.screen.blit(timer, (timer_x + 7, 14))

        # Bottom left: what the hero has, like "Spark 2  Blades 1  Boots 1".
        line = "  ".join(self.game.summary())
        if line:
            text = self.font_small.render(line, True, TEXT)
            box = pygame.Surface(
                (text.get_width() + 16, text.get_height() + 8), pygame.SRCALPHA
            )
            box.fill(HUD_PANEL)
            bottom = self.height - box.get_height() - 10
            self.screen.blit(box, (10, bottom))
            self.screen.blit(text, (18, bottom + 4))

    def draw_overlay(self, title, subtitle):
        layer = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        layer.fill((OVERLAY[0], OVERLAY[1], OVERLAY[2], 170))
        self.screen.blit(layer, (0, 0))
        middle = self.height // 2
        text = self.font_huge.render(title, True, TEXT)
        self.screen.blit(text, text.get_rect(center=(self.width // 2, middle - 10)))
        hint = self.font_small.render(subtitle, True, TEXT)
        self.screen.blit(hint, hint.get_rect(center=(self.width // 2, middle + 34)))

    def draw_end(self, title):
        """VICTORY or GAME OVER, with the time, the kills and the level."""
        layer = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        layer.fill((OVERLAY[0], OVERLAY[1], OVERLAY[2], 185))
        self.screen.blit(layer, (0, 0))
        middle = self.height // 2
        colour = VICTORY_TEXT if title == "VICTORY" else TEXT
        text = self.font_huge.render(title, True, colour)
        self.screen.blit(text, text.get_rect(center=(self.width // 2, middle - 60)))
        summary = "Time %s   Kills %d   Lv %d" % (
            short_time(self.game.time), self.game.kills, self.game.level)
        line = self.font_big.render(summary, True, TEXT)
        self.screen.blit(line, line.get_rect(center=(self.width // 2, middle + 14)))
        hint = self.font_small.render("Click or tap to play again", True, CARD_MUTED)
        self.screen.blit(hint, hint.get_rect(center=(self.width // 2, middle + 60)))


async def main(max_frames=None):
    """The main loop. `max_frames` is only used by the fake-input test."""
    global CURRENT_APP
    config = rules.load_config()
    app = App(config)
    CURRENT_APP = app
    frames = 0
    while app.running:
        for event in pygame.event.get():
            app.handle_event(event)
        app.update()
        app.draw()
        pygame.display.flip()
        await asyncio.sleep(0)
        frames += 1
        if max_frames is not None and frames >= max_frames:
            app.running = False
    pygame.quit()
    return app


if __name__ == "__main__":
    asyncio.run(main())
