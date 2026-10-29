"""Night Survivors -- the game rules.

There is no pygame in this file on purpose: the rules are easy to test
with `python -m unittest`, and a web build stays small.
Every number comes from data/game.json (they are the numbers of GAME.md).
"""

import json
import math
import os
import random

#: The game always moves in steps of 1/60 of a second (a fixed time step),
#: so it plays the same on every computer and in a web browser.
FIXED_DT = 1.0 / 60.0

#: Timers go down by 1/60 s each step, and 0.5 - 30 * (1/60) is not exactly
#: 0.0 in Python, so "this timer is finished" means "it is smaller than this".
EPSILON = 1e-9

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(BASE_DIR, "data", "game.json")


def load_config(path=None):
    """Read data/game.json and return it as a dict of numbers."""
    with open(path or DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def distance(ax, ay, bx, by):
    """How far apart two points are, in pixels."""
    return math.hypot(bx - ax, by - ay)


def level_number(spec, level):
    """Turn {"base": 10, "per_level": 3} into the value for this level.

    Level 1 is the base, every extra level adds per_level.
    """
    if isinstance(spec, dict):
        return spec["base"] + spec["per_level"] * (level - 1)
    return spec


def level_count(spec, level):
    """Turn {"base": 2, "extra_at": [2, 4]} into how many things there are."""
    return int(spec["base"]) + sum(1 for needed in spec["extra_at"] if level >= needed)


def weapon_damage(weapon, level=1):
    return level_number(weapon["damage"], level)


def weapon_cooldown(weapon, level=1):
    return level_number(weapon["cooldown"], level)


def weapon_shots(weapon, level=1):
    """How many sparks one shot fires. Extra sparks come at some levels."""
    return level_count(weapon["sparks"], level)


def weapon_blades(weapon, level=1):
    """How many blades spin around the hero."""
    return level_count(weapon["blades"], level)


class Hero:
    """The player. He only walks; the weapons work by themselves."""

    def __init__(self, config):
        self.base_speed = float(config["speed"])
        self.speed = self.base_speed
        self.base_max_hp = int(config["hp"])
        self.max_hp = self.base_max_hp
        self.hp = self.max_hp
        self.hit_radius = float(config["hit_radius"])
        self.base_magnet_radius = float(config["magnet_radius"])
        self.magnet_radius = self.base_magnet_radius
        self.stop_distance = float(config["stop_distance"])
        self.x = 0.0
        self.y = 0.0

    def walk_toward(self, point, dt):
        """Walk to `point` (world pixels), but stop `stop_distance` short."""
        if point is None:
            return
        dx = point[0] - self.x
        dy = point[1] - self.y
        away = math.hypot(dx, dy)
        if away <= self.stop_distance:
            return
        step = min(self.speed * dt, away - self.stop_distance)
        self.x += dx / away * step
        self.y += dy / away * step


class Enemy:
    """One enemy (for now that is only a Bat)."""

    def __init__(self, kind, config, x, y, contact_cooldown):
        self.kind = kind
        self.name = config["name"]
        self.max_hp = int(config["hp"])
        self.hp = self.max_hp
        self.speed = float(config["speed"])
        self.damage = int(config["damage"])
        self.xp = int(config["xp"])
        self.radius = float(config["hit_radius"])
        self.x = float(x)
        self.y = float(y)
        self.touch_cooldown = float(contact_cooldown)
        self.touch_timer = 0.0
        #: when each blade (by number) may hit this enemy again
        self.blade_timers = {}

    @property
    def alive(self):
        return self.hp > 0

    def take_damage(self, amount):
        self.hp -= amount

    def move_toward(self, x, y, dt):
        dx = x - self.x
        dy = y - self.y
        away = math.hypot(dx, dy)
        if away == 0:
            return
        self.x += dx / away * self.speed * dt
        self.y += dy / away * self.speed * dt


class Spark:
    """A small shot from the Spark Wand."""

    def __init__(self, x, y, vx, vy, damage, radius, life):
        self.x = float(x)
        self.y = float(y)
        self.vx = float(vx)
        self.vy = float(vy)
        self.damage = damage
        self.radius = float(radius)
        self.life = float(life)

    @property
    def dead(self):
        return self.life <= 0.0

    def update(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.life -= dt


class Gem:
    """A gem an enemy dropped. It is worth that enemy's XP."""

    def __init__(self, x, y, xp, radius, fly_speed):
        self.x = float(x)
        self.y = float(y)
        self.xp = int(xp)
        self.radius = float(radius)
        self.fly_speed = float(fly_speed)
        self.flying = False

    def fly_to(self, hero, dt):
        """Fly to the hero at the gem speed."""
        dx = hero.x - self.x
        dy = hero.y - self.y
        away = math.hypot(dx, dy)
        if away == 0.0:
            return
        step = self.fly_speed * dt
        if step >= away:
            self.x = hero.x
            self.y = hero.y
        else:
            self.x += dx / away * step
            self.y += dy / away * step


class Game:
    """The whole game: hero, enemies, shots, gems, XP and the time.

    Call `game.update()` with a step of FIXED_DT seconds, never with the
    real time of the frame. That keeps the game the same at any speed.
    """

    def __init__(self, config, rng=None):
        self.config = config
        self.rng = rng or random.Random()
        self.contact_cooldown = float(config["contact_damage"]["cooldown_seconds"])
        self.spawn_config = config["spawning"]
        self.timeline = config["timeline"]
        self.weapons = config["weapons"]
        self.passives = config["passives"]
        self.gem_config = config["gems"]
        self.max_weapons = int(config["max_weapons"])
        self.restart()

    def restart(self):
        """Start a new game, keeping the same settings."""
        self.hero = Hero(self.config["hero"])
        self.enemies = []
        self.sparks = []
        self.gems = []
        self.time = 0.0
        self.kills = 0
        self.state = "playing"          # "playing", "levelup", "victory", "gameover"
        self.target = None              # world point the hero walks to
        self.spawn_timer = 0.0
        self.spark_timer = 0.0
        self.ring_timer = 0.0
        self.blade_angle = 0.0
        self.blade_positions = []       # where the blades are, for drawing
        self.ring_radius = 0.0          # size of the Holy Ring, for drawing
        self.boss_spawned = False       # the boss appears only once
        self.level = 1
        self.xp = 0
        self.weapon_levels = {"spark_wand": 1}
        self.passive_levels = {}
        self.offers = []                # the three level-up cards
        self.events = []                # what happened, for sound and effects

    # -------------------------------------------------------------- events
    def take_events(self):
        """Everything that happened since the last call (for sound and effects)."""
        events = self.events
        self.events = []
        return events

    def _event(self, kind, **data):
        event = {"kind": kind}
        event.update(data)
        self.events.append(event)

    # ---------------------------------------------------------------- time
    def update(self, dt=FIXED_DT):
        """Move the game forward by `dt` seconds."""
        if self.state != "playing":
            return
        self.time += dt
        self.hero.walk_toward(self.target, dt)
        for enemy in self.enemies:
            enemy.move_toward(self.hero.x, self.hero.y, dt)
        self._update_spawning(dt)
        self._update_contact_damage(dt)
        self._update_weapons(dt)
        self._update_sparks(dt)
        self._collect_dead()
        self._update_gems(dt)
        self._remove_far_enemies()
        if self.hero.hp <= 0:
            self.hero.hp = 0
            self.state = "gameover"
            self._event("end", result="gameover")
        elif self.time >= float(self.config["run"]["duration_seconds"]):
            self.state = "victory"
            self._event("end", result="victory")

    def run_time_text(self):
        """The timer, like "0:45 / 2:00"."""
        def short(seconds):
            minutes, rest = divmod(int(seconds), 60)
            return "%d:%02d" % (minutes, rest)

        return "%s / %s" % (short(min(self.time, self.duration())), short(self.duration()))

    def duration(self):
        return float(self.config["run"]["duration_seconds"])

    # ----------------------------------------------------------- the table
    def timeline_row(self, time=None):
        """The row of the table in GAME.md that is true at `time`."""
        time = self.time if time is None else time
        row = self.timeline[0]
        for candidate in self.timeline:
            if time >= candidate["from"]:
                row = candidate
        return row

    def min_alive(self, time=None):
        """How many enemies should be alive at this time."""
        return int(self.timeline_row(time)["min_alive"])

    def spawn_types(self, time=None):
        """Which enemy types may come in the waves (the boss comes alone)."""
        known = self.config["enemies"]
        return [
            kind for kind in self.timeline_row(time)["types"]
            if kind in known and kind != "boss"
        ]

    def boss_time(self):
        """The moment in the table when the boss appears (None if never)."""
        for row in self.timeline:
            if "boss" in row["types"]:
                return float(row["from"])
        return None

    # ------------------------------------------------------------ spawning
    def spawn_point(self):
        """A random point on a circle around the hero, just off the screen."""
        angle = self.rng.uniform(0.0, math.tau)
        radius = float(self.spawn_config["circle_radius"])
        return (
            self.hero.x + math.cos(angle) * radius,
            self.hero.y + math.sin(angle) * radius,
        )

    def spawn_wave(self):
        """Spawn enemies until the table's minimum is reached. Returns how many."""
        room = int(self.spawn_config["max_alive"]) - len(self.enemies)
        wanted = self.min_alive() - len(self.enemies)
        count = min(wanted, int(self.spawn_config["max_per_tick"]), room)
        if count <= 0:
            return 0
        kinds = self.spawn_types()
        if not kinds:
            return 0
        for _ in range(count):
            kind = self.rng.choice(kinds)
            x, y = self.spawn_point()
            self.enemies.append(
                Enemy(kind, self.config["enemies"][kind], x, y, self.contact_cooldown)
            )
        return count

    def _update_spawning(self, dt):
        self.spawn_timer += dt
        interval = float(self.spawn_config["interval_seconds"])
        while self.spawn_timer >= interval:
            self.spawn_timer -= interval
            self.spawn_wave()
        self._maybe_spawn_boss()

    def _maybe_spawn_boss(self):
        """The boss appears once, when the table says so."""
        if self.boss_spawned:
            return
        moment = self.boss_time()
        if moment is None or self.time < moment:
            return
        if "boss" not in self.config["enemies"]:
            return
        x, y = self.spawn_point()
        self.enemies.append(
            Enemy("boss", self.config["enemies"]["boss"], x, y, self.contact_cooldown)
        )
        self.boss_spawned = True

    def _remove_far_enemies(self):
        """Normal enemies far off the screen are dropped; the boss is not."""
        limit = float(self.spawn_config["despawn_radius"])
        boss_reset = float(self.spawn_config["boss_reset_radius"])
        kept = []
        for enemy in self.enemies:
            away = distance(self.hero.x, self.hero.y, enemy.x, enemy.y)
            if enemy.kind == "boss":
                if away > boss_reset:
                    # Too far away to matter: put it back on the circle.
                    enemy.x, enemy.y = self.spawn_point()
                kept.append(enemy)
            elif away <= limit:
                kept.append(enemy)
        self.enemies = kept

    # ------------------------------------------------------- contact damage
    def _update_contact_damage(self, dt):
        hero = self.hero
        for enemy in self.enemies:
            if enemy.touch_timer > 0.0:
                enemy.touch_timer = max(0.0, enemy.touch_timer - dt)
            touching = distance(hero.x, hero.y, enemy.x, enemy.y) <= (
                hero.hit_radius + enemy.radius
            )
            if touching and enemy.touch_timer <= EPSILON:
                hero.hp -= enemy.damage
                enemy.touch_timer = enemy.touch_cooldown
                self._event("hurt", amount=enemy.damage,
                            x=enemy.x, y=enemy.y)

    # ------------------------------------------------------------- the end
    def _collect_dead(self):
        """Enemies with no HP left: count the kill and drop a gem."""
        still_alive = []
        for enemy in self.enemies:
            if enemy.alive:
                still_alive.append(enemy)
            else:
                self.kills += 1
                self._event("kill", x=enemy.x, y=enemy.y, enemy=enemy.kind)
                if enemy.xp > 0:        # the boss is worth 0 XP: no gem
                    self.drop_gem(enemy.x, enemy.y, enemy.xp)
        self.enemies = still_alive

    # --------------------------------------------------------------- gems
    def drop_gem(self, x, y, xp):
        """Drop a gem, or add its XP to a gem that already lies there.

        Two gems closer together than `merge_radius` become one gem, so the
        floor stays easy to read and the XP is not lost.
        """
        merge_radius = float(self.gem_config.get("merge_radius", 0.0))
        if merge_radius > 0.0:
            for gem in self.gems:
                if gem.flying:
                    continue
                if distance(x, y, gem.x, gem.y) <= merge_radius:
                    gem.xp += xp
                    return
        self.gems.append(Gem(
            x, y, xp,
            float(self.gem_config["radius"]),
            float(self.gem_config["fly_speed"]),
        ))
        self._trim_gems()

    def _trim_gems(self):
        """Keep the floor tidy: never more than `max_count` gems."""
        max_count = int(self.gem_config.get("max_count", 0))
        if max_count <= 0 or len(self.gems) <= max_count:
            return
        # keep the gems closest to the hero, drop the ones far away
        self.gems.sort(
            key=lambda gem: distance(self.hero.x, self.hero.y, gem.x, gem.y)
        )
        self.gems = self.gems[:max_count]

    # --------------------------------------------------------------- gems
    def _update_gems(self, dt):
        hero = self.hero
        kept = []
        picked_up = False
        for gem in self.gems:
            if not gem.flying:
                inside = distance(hero.x, hero.y, gem.x, gem.y) <= hero.magnet_radius
                if not inside:
                    kept.append(gem)
                    continue
                gem.flying = True
            gem.fly_to(hero, dt)
            if distance(hero.x, hero.y, gem.x, gem.y) > hero.hit_radius:
                kept.append(gem)
            else:
                self.xp += gem.xp
                self._event("gem", x=gem.x, y=gem.y, xp=gem.xp)
                picked_up = True
        self.gems = kept
        if picked_up:
            self._check_level_up()

    # ----------------------------------------------------------- XP levels
    def level_xp_needed(self, level=None):
        """XP for the next level: 5 at level 1, then 3 more each level."""
        level = self.level if level is None else level
        levels = self.config["levels"]
        return int(levels["first_xp"]) + int(levels["step_xp"]) * (level - 1)

    def _check_level_up(self):
        """When enough XP is in: stop the game and show cards."""
        if self.state != "playing":
            return
        needed = self.level_xp_needed()
        if self.xp < needed:
            return
        self.xp -= needed
        self.level += 1
        self.offers = self.make_offers()
        self.state = "levelup"
        self._event("levelup", level=self.level)

    def make_offers(self, amount=3):
        """Cards: a new weapon, a better weapon, or a passive item."""
        cards = []
        room_for_weapons = len(self.weapon_levels) < self.max_weapons
        for key, weapon in self.weapons.items():
            level = int(self.weapon_levels.get(key, 0))
            top = int(weapon["max_level"])
            if level == 0 and room_for_weapons:
                cards.append({
                    "kind": "weapon", "id": key, "level": 1,
                    "name": weapon["name"], "text": weapon["text"],
                })
            elif 0 < level < top:
                cards.append({
                    "kind": "weapon", "id": key, "level": level + 1,
                    "name": weapon["name"], "text": weapon["text"],
                })
        for key, item in self.passives.items():
            level = int(self.passive_levels.get(key, 0))
            top = int(item["max_level"])
            if level < top:
                cards.append({
                    "kind": "passive", "id": key, "level": level + 1,
                    "name": item["name"], "text": item["text"],
                })
        self.rng.shuffle(cards)
        chosen = cards[:amount]
        if not chosen:
            chosen = [{
                "kind": "heal", "id": "heal", "level": 0,
                "name": "Heal", "text": "Heal %d HP" % self.config["heal"]["hp"],
            }]
        return chosen

    def choose(self, index):
        """Take the card at `index`. Returns it (or None if not allowed)."""
        if self.state != "levelup":
            return None
        if index < 0 or index >= len(self.offers):
            return None
        card = self.offers[index]
        if card["kind"] == "weapon":
            self.weapon_levels[card["id"]] = int(card["level"])
        elif card["kind"] == "passive":
            self.passive_levels[card["id"]] = int(card["level"])
            self._apply_passives()
        else:
            heal = int(self.config["heal"]["hp"])
            self.hero.hp = min(self.hero.max_hp, self.hero.hp + heal)
        self.offers = []
        self.state = "playing"
        self._check_level_up()          # maybe one more level is waiting
        return card

    def _apply_passives(self):
        """Recompute the hero's numbers from the passive items he has."""
        boots = int(self.passive_levels.get("swift_boots", 0))
        heart = int(self.passive_levels.get("big_heart", 0))
        magnet = int(self.passive_levels.get("magnet", 0))

        boots_item = self.passives["swift_boots"]
        percent = float(boots_item["speed_percent"]) / 100.0
        self.hero.speed = self.hero.base_speed * (1.0 + percent) ** boots

        heart_item = self.passives["big_heart"]
        self.hero.max_hp = self.hero.base_max_hp + int(heart_item["max_hp"]) * heart
        if heart > 0:
            self.hero.hp = min(
                self.hero.max_hp, self.hero.hp + int(heart_item["heal"])
            )

        magnet_item = self.passives["magnet"]
        self.hero.magnet_radius = (
            self.hero.base_magnet_radius
            + float(magnet_item["magnet_radius"]) * magnet
        )

    def summary(self):
        """What the hero has, like ["Spark 2", "Blades 1", "Boots 1"]."""
        parts = []
        for key, weapon in self.weapons.items():
            level = int(self.weapon_levels.get(key, 0))
            if level > 0:
                parts.append("%s %d" % (weapon["short"], level))
        for key, item in self.passives.items():
            level = int(self.passive_levels.get(key, 0))
            if level > 0:
                parts.append("%s %d" % (item["short"], level))
        return parts

    # ------------------------------------------------------------- weapons
    def nearest_enemy(self):
        best = None
        best_away = None
        for enemy in self.enemies:
            away = distance(self.hero.x, self.hero.y, enemy.x, enemy.y)
            if best_away is None or away < best_away:
                best = enemy
                best_away = away
        return best

    def _update_weapons(self, dt):
        self._update_spark_wand(dt)
        self._update_spin_blades(dt)
        self._update_holy_ring(dt)

    def _update_spark_wand(self, dt):
        level = int(self.weapon_levels.get("spark_wand", 0))
        if level <= 0:
            return
        self.spark_timer -= dt
        if self.spark_timer > EPSILON:
            return
        target = self.nearest_enemy()
        if target is None:
            return
        weapon = self.weapons["spark_wand"]
        damage = weapon_damage(weapon, level)
        shots = weapon_shots(weapon, level)
        angle = math.atan2(target.y - self.hero.y, target.x - self.hero.x)
        speed = float(weapon["projectile_speed"])
        for index in range(shots):
            # With more than one spark, spread them a little.
            spread = (index - (shots - 1) / 2.0) * 0.12
            a = angle + spread
            self.sparks.append(
                Spark(
                    self.hero.x,
                    self.hero.y,
                    math.cos(a) * speed,
                    math.sin(a) * speed,
                    damage,
                    float(weapon["projectile_radius"]),
                    float(weapon["projectile_life_seconds"]),
                )
            )
        self.spark_timer = max(0.05, weapon_cooldown(weapon, level))

    def _update_spin_blades(self, dt):
        """Blades go round the hero; a blade may hurt an enemy again after 0.5 s."""
        level = int(self.weapon_levels.get("spin_blades", 0))
        if level <= 0:
            self.blade_positions = []
            return
        weapon = self.weapons["spin_blades"]
        count = weapon_blades(weapon, level)
        damage = weapon_damage(weapon, level)
        orbit = float(weapon["orbit_radius"])
        hit_radius = float(weapon["blade_hit_radius"])
        cooldown = float(weapon["hit_cooldown_seconds"])
        self.blade_angle += math.tau / float(weapon["turn_seconds"]) * dt

        for enemy in self.enemies:
            for index in list(enemy.blade_timers):
                enemy.blade_timers[index] = max(0.0, enemy.blade_timers[index] - dt)

        self.blade_positions = []
        for index in range(count):
            angle = self.blade_angle + index * math.tau / count
            blade_x = self.hero.x + math.cos(angle) * orbit
            blade_y = self.hero.y + math.sin(angle) * orbit
            self.blade_positions.append((blade_x, blade_y))
            for enemy in self.enemies:
                if enemy.blade_timers.get(index, 0.0) > EPSILON:
                    continue
                if distance(blade_x, blade_y, enemy.x, enemy.y) <= (
                    enemy.radius + hit_radius
                ):
                    enemy.take_damage(damage)
                    enemy.blade_timers[index] = cooldown
                    self._event("hit", x=enemy.x, y=enemy.y, amount=damage)

    def _update_holy_ring(self, dt):
        """A circle around the hero that hurts everything inside it."""
        level = int(self.weapon_levels.get("holy_ring", 0))
        if level <= 0:
            self.ring_radius = 0.0
            return
        weapon = self.weapons["holy_ring"]
        self.ring_radius = float(level_number(weapon["radius"], level))
        self.ring_timer -= dt
        if self.ring_timer > EPSILON:
            return
        damage = weapon_damage(weapon, level)
        for enemy in self.enemies:
            if distance(self.hero.x, self.hero.y, enemy.x, enemy.y) <= (
                self.ring_radius + enemy.radius
            ):
                enemy.take_damage(damage)
                self._event("hit", x=enemy.x, y=enemy.y, amount=damage)
        self.ring_timer = max(0.05, float(weapon["cooldown_seconds"]))

    def _update_sparks(self, dt):
        for spark in self.sparks:
            spark.update(dt)
        for spark in self.sparks[:]:
            for enemy in self.enemies:
                if not enemy.alive:
                    continue
                if distance(spark.x, spark.y, enemy.x, enemy.y) <= (
                    enemy.radius + spark.radius
                ):
                    enemy.take_damage(spark.damage)
                    self._event("hit", x=spark.x, y=spark.y, amount=spark.damage)
                    self.sparks.remove(spark)
                    break
        self.sparks = [spark for spark in self.sparks if not spark.dead]
