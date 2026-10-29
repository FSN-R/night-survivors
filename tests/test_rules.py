"""Tests for the rules in rules.py only (no drawing, no pictures, no sound).

Run them from the project folder with:  python -m unittest
Every number is read from data/game.json, so a test never repeats a number.
"""

import os
import random
import sys
import unittest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

import rules  # noqa: E402

CONFIG = rules.load_config()


def new_game(seed=1):
    return rules.Game(CONFIG, rng=random.Random(seed))


def run_for(game, seconds):
    """Move the game forward with fixed steps, like the real loop does."""
    steps = int(round(seconds / rules.FIXED_DT))
    for _ in range(steps):
        game.update(rules.FIXED_DT)


def drop_gem(game, x, y, xp):
    """Put a gem in the world, like a dead enemy would."""
    gem = rules.Gem(
        x, y, xp, float(CONFIG["gems"]["radius"]), float(CONFIG["gems"]["fly_speed"])
    )
    game.gems.append(gem)
    return gem


def level_up(game):
    """Give the hero enough XP for the next level by letting him pick up a gem."""
    drop_gem(game, game.hero.x, game.hero.y, game.level_xp_needed())
    game.update(rules.FIXED_DT)


def tough_bat(hp=500):
    """A bat that survives long enough to be tested."""
    bat = dict(CONFIG["enemies"]["bat"])
    bat["hp"] = hp
    return bat


class NumbersTest(unittest.TestCase):
    """The numbers really come from data/game.json."""

    def test_hero_numbers(self):
        hero = CONFIG["hero"]
        self.assertEqual(rules.Hero(hero).max_hp, hero["hp"])
        self.assertEqual(rules.Hero(hero).speed, hero["speed"])

    def test_bat_numbers(self):
        bat = CONFIG["enemies"]["bat"]
        enemy = rules.Enemy("bat", bat, 0, 0, 0.5)
        self.assertEqual(enemy.max_hp, bat["hp"])
        self.assertEqual(enemy.damage, bat["damage"])

    def test_spark_wand_levels(self):
        weapon = CONFIG["weapons"]["spark_wand"]
        self.assertEqual(rules.weapon_damage(weapon, 1), weapon["damage"]["base"])
        self.assertEqual(rules.weapon_cooldown(weapon, 1), weapon["cooldown"]["base"])
        self.assertEqual(rules.weapon_shots(weapon, 1), 1)
        # one more spark at each level in extra_at, and only then
        for level in range(1, weapon["max_level"] + 1):
            expected = 1 + sum(1 for at in weapon["sparks"]["extra_at"] if level >= at)
            self.assertEqual(rules.weapon_shots(weapon, level), expected)
        # more damage and a faster shot at every extra level
        self.assertGreater(rules.weapon_damage(weapon, 2), rules.weapon_damage(weapon, 1))
        self.assertLess(rules.weapon_cooldown(weapon, 2), rules.weapon_cooldown(weapon, 1))

    def test_spin_blades_numbers(self):
        weapon = CONFIG["weapons"]["spin_blades"]
        self.assertEqual(rules.weapon_blades(weapon, 1), weapon["blades"]["base"])
        for level in range(1, weapon["max_level"] + 1):
            expected = weapon["blades"]["base"] + sum(
                1 for at in weapon["blades"]["extra_at"] if level >= at
            )
            self.assertEqual(rules.weapon_blades(weapon, level), expected)
        self.assertGreater(rules.weapon_damage(weapon, 2), rules.weapon_damage(weapon, 1))

    def test_holy_ring_numbers(self):
        weapon = CONFIG["weapons"]["holy_ring"]
        level = 1
        self.assertEqual(rules.level_number(weapon["radius"], level), weapon["radius"]["base"])
        self.assertGreater(
            rules.level_number(weapon["radius"], 2), rules.level_number(weapon["radius"], 1)
        )

    def test_xp_needed_goes_up_by_the_step(self):
        game = new_game()
        first = CONFIG["levels"]["first_xp"]
        step = CONFIG["levels"]["step_xp"]
        self.assertEqual(game.level_xp_needed(1), first)
        for level in range(1, 6):
            self.assertEqual(game.level_xp_needed(level + 1) - game.level_xp_needed(level), step)

    def test_min_alive_table(self):
        game = new_game()
        for row in CONFIG["timeline"]:
            self.assertEqual(game.min_alive(row["from"]), row["min_alive"])


class SpawningTest(unittest.TestCase):
    def test_fills_up_to_the_minimum_eight_at_a_time(self):
        game = new_game()
        limit = int(CONFIG["spawning"]["max_per_tick"])
        run_for(game, float(CONFIG["spawning"]["interval_seconds"]) + 0.05)
        self.assertEqual(len(game.enemies), min(limit, game.min_alive()))
        # one more spawn tick is enough to reach the minimum of 12
        run_for(game, float(CONFIG["spawning"]["interval_seconds"]))
        self.assertEqual(len(game.enemies), game.min_alive())

    def test_enemies_appear_just_off_the_screen(self):
        game = new_game()
        self.assertEqual(game.spawn_wave(), min(
            int(CONFIG["spawning"]["max_per_tick"]), game.min_alive()))
        circle = float(CONFIG["spawning"]["circle_radius"])
        for enemy in game.enemies:
            away = rules.distance(game.hero.x, game.hero.y, enemy.x, enemy.y)
            self.assertAlmostEqual(away, circle, delta=0.01)

    def test_never_more_than_max_alive(self):
        game = new_game()
        bat = CONFIG["enemies"]["bat"]
        most = int(CONFIG["spawning"]["max_alive"])
        game.enemies = [
            rules.Enemy("bat", bat, game.hero.x + 400, game.hero.y, 0.5)
            for _ in range(most)
        ]
        self.assertEqual(game.spawn_wave(), 0)
        self.assertEqual(len(game.enemies), most)

    def test_far_enemies_are_removed(self):
        game = new_game()
        bat = CONFIG["enemies"]["bat"]
        far = float(CONFIG["spawning"]["despawn_radius"]) + 10
        game.enemies = [rules.Enemy("bat", bat, far, 0, 0.5)]
        game.update(rules.FIXED_DT)
        self.assertEqual(game.enemies, [])


class DamageTest(unittest.TestCase):
    def test_a_touch_hurts_at_most_every_half_second(self):
        game = new_game()
        bat = CONFIG["enemies"]["bat"]
        # This test is about touching, so make one bat that is too tough
        # for the Spark Wand: otherwise the wand kills it in the first step.
        tough = dict(bat)
        tough["hp"] = 1000
        cooldown = float(CONFIG["contact_damage"]["cooldown_seconds"])
        game.enemies = [rules.Enemy("bat", tough, game.hero.x, game.hero.y, cooldown)]
        full = game.hero.max_hp
        game.update(rules.FIXED_DT)
        self.assertEqual(game.hero.hp, full - bat["damage"])
        steps = 1
        while game.hero.hp == full - bat["damage"] and steps < 200:
            game.update(rules.FIXED_DT)
            steps += 1
        self.assertEqual(game.hero.hp, full - 2 * bat["damage"])
        # the second hurt comes after the half second, never earlier,
        # and never more than one 1/60 s step later
        needed = int(round(cooldown / rules.FIXED_DT))
        self.assertIn(steps, (needed, needed + 1))

    def test_the_spark_wand_kills_a_bat(self):
        game = new_game()
        bat = CONFIG["enemies"]["bat"]
        game.enemies = [rules.Enemy("bat", bat, 120, 0, 0.5)]
        run_for(game, 0.4)
        self.assertEqual(game.enemies, [])
        self.assertEqual(game.kills, 1)
        self.assertEqual(game.hero.hp, game.hero.max_hp)

    def test_hero_walks_and_stops_at_stop_distance(self):
        game = new_game()
        game.target = (200, 0)
        run_for(game, 3.0)
        away = rules.distance(game.hero.x, game.hero.y, 200, 0)
        self.assertAlmostEqual(away, game.hero.stop_distance, delta=0.5)
        self.assertGreater(game.hero.x, 0)   # he really walked

    def test_zero_hp_is_game_over_and_play_again_resets(self):
        game = new_game()
        game.hero.hp = 0
        game.update(rules.FIXED_DT)
        self.assertEqual(game.state, "gameover")
        self.assertEqual(game.hero.hp, 0)
        frozen = game.time
        game.update(rules.FIXED_DT)
        self.assertEqual(game.time, frozen)   # a dead game does not move

        game.restart()
        self.assertEqual(game.state, "playing")
        self.assertEqual(game.hero.hp, game.hero.max_hp)
        self.assertEqual(game.time, 0.0)
        self.assertEqual(game.enemies, [])
        self.assertEqual(game.kills, 0)


class GemTest(unittest.TestCase):
    def test_a_dead_enemy_drops_a_gem_worth_its_xp(self):
        game = new_game()
        bat = CONFIG["enemies"]["bat"]
        game.enemies = [rules.Enemy("bat", bat, 120, 0, 0.5)]
        run_for(game, 0.4)
        self.assertEqual(game.kills, 1)
        self.assertEqual(len(game.gems), 1)
        self.assertEqual(game.gems[0].xp, bat["xp"])

    def test_a_gem_outside_the_magnet_stays_on_the_floor(self):
        game = new_game()
        far = game.hero.magnet_radius + 100
        gem = drop_gem(game, far, 0, 1)
        run_for(game, 0.3)
        self.assertFalse(gem.flying)
        self.assertAlmostEqual(gem.x, far)
        self.assertEqual(game.xp, 0)

    def test_a_gem_inside_the_magnet_flies_in_and_is_counted(self):
        game = new_game()
        drop_gem(game, game.hero.magnet_radius - 5, 0, 1)
        run_for(game, 0.5)
        self.assertEqual(game.gems, [])
        self.assertEqual(game.xp, 1)


class GemTidyTest(unittest.TestCase):
    """Gems merge when they lie on top of each other, and the floor is capped."""

    def test_two_gems_in_the_same_place_become_one(self):
        game = new_game()
        merge = float(CONFIG["gems"]["merge_radius"])
        game.drop_gem(300, 0, 1)
        game.drop_gem(300 + merge / 2.0, 0, 1)
        self.assertEqual(len(game.gems), 1)
        self.assertEqual(game.gems[0].xp, 2)

    def test_gems_that_are_far_apart_stay_separate(self):
        game = new_game()
        merge = float(CONFIG["gems"]["merge_radius"])
        game.drop_gem(300, 0, 1)
        game.drop_gem(300 + merge + 30, 0, 1)
        self.assertEqual(len(game.gems), 2)

    def test_merging_keeps_all_the_xp(self):
        game = new_game()
        for _ in range(5):
            game.drop_gem(300, 0, 1)
        self.assertEqual(len(game.gems), 1)
        self.assertEqual(game.gems[0].xp, 5)
        # and picking it up still gives all 5 XP in one go: that is exactly
        # enough for the first level-up
        game.gems[0].x = game.hero.x
        game.gems[0].y = game.hero.y
        game.update(rules.FIXED_DT)
        self.assertEqual(game.state, "levelup")
        self.assertEqual(game.level, 2)
        self.assertEqual(game.xp, 0)

    def test_the_floor_never_holds_more_than_max_count_gems(self):
        game = new_game()
        most = int(CONFIG["gems"]["max_count"])
        for index in range(most + 40):
            game.drop_gem(index * 100.0, 0, 1)
        self.assertEqual(len(game.gems), most)

    def test_the_gems_kept_are_the_ones_near_the_hero(self):
        game = new_game()
        most = int(CONFIG["gems"]["max_count"])
        game.drop_gem(99999, 0, 1)              # very far away
        for index in range(most):
            game.drop_gem(index * 100.0, 0, 1)
        self.assertNotIn(99999, [gem.x for gem in game.gems])
        self.assertEqual(len(game.gems), most)


class LevelUpTest(unittest.TestCase):
    def test_a_level_up_stops_the_game(self):
        game = new_game()
        level_up(game)
        self.assertEqual(game.state, "levelup")
        self.assertEqual(game.level, 2)
        frozen = game.time
        game.update(rules.FIXED_DT)
        self.assertEqual(game.time, frozen)   # nothing moves until a card is taken

    def test_three_different_cards_are_offered(self):
        game = new_game()
        level_up(game)
        self.assertEqual(len(game.offers), 3)
        ids = [card["id"] for card in game.offers]
        self.assertEqual(len(set(ids)), 3)

    def test_no_card_is_above_level_five(self):
        game = new_game()
        game.weapon_levels = {"spark_wand": 4}
        game.passive_levels = {"swift_boots": 4}
        for card in game.make_offers(20):
            self.assertLessEqual(card["level"], 5)

    def test_when_everything_is_full_the_heal_card_appears(self):
        game = new_game()
        game.weapon_levels = {key: CONFIG["weapons"][key]["max_level"]
                              for key in CONFIG["weapons"]}
        game.passive_levels = {key: CONFIG["passives"][key]["max_level"]
                               for key in CONFIG["passives"]}
        cards = game.make_offers()
        self.assertEqual([card["kind"] for card in cards], ["heal"])

    def test_a_new_weapon_card_adds_the_weapon_and_play_goes_on(self):
        game = new_game()
        game.state = "levelup"
        game.offers = [{"kind": "weapon", "id": "spin_blades", "level": 1,
                        "name": "Spin Blades", "text": ""}]
        card = game.choose(0)
        self.assertEqual(card["id"], "spin_blades")
        self.assertEqual(game.weapon_levels["spin_blades"], 1)
        self.assertEqual(game.state, "playing")

    def test_an_upgrade_card_makes_the_weapon_one_level_better(self):
        game = new_game()
        game.state = "levelup"
        game.offers = [{"kind": "weapon", "id": "spark_wand", "level": 2,
                        "name": "Spark Wand", "text": ""}]
        game.choose(0)
        self.assertEqual(game.weapon_levels["spark_wand"], 2)

    def test_choosing_a_card_that_is_not_there_does_nothing(self):
        game = new_game()
        self.assertIsNone(game.choose(0))
        game.state = "levelup"
        self.assertIsNone(game.choose(9))


class PassiveTest(unittest.TestCase):
    def take(self, game, key, level=1):
        game.state = "levelup"
        game.offers = [{"kind": "passive", "id": key, "level": level,
                        "name": key, "text": ""}]
        game.choose(0)

    def test_big_heart_adds_twenty_max_hp_and_heals_twenty(self):
        game = new_game()
        game.hero.hp = 50
        heart = CONFIG["passives"]["big_heart"]
        before = game.hero.max_hp
        self.take(game, "big_heart")
        self.assertEqual(game.hero.max_hp, before + heart["max_hp"])
        self.assertEqual(game.hero.hp, 50 + heart["heal"])

    def test_swift_boots_make_the_hero_ten_percent_faster(self):
        game = new_game()
        before = game.hero.speed
        self.take(game, "swift_boots")
        percent = CONFIG["passives"]["swift_boots"]["speed_percent"] / 100.0
        self.assertAlmostEqual(game.hero.speed, before * (1.0 + percent), places=3)

    def test_magnet_makes_the_magnet_radius_bigger(self):
        game = new_game()
        before = game.hero.magnet_radius
        self.take(game, "magnet")
        self.assertEqual(
            game.hero.magnet_radius,
            before + CONFIG["passives"]["magnet"]["magnet_radius"],
        )

    def test_the_heal_card_gives_hp_back(self):
        game = new_game()
        game.hero.hp = 10
        heal = CONFIG["heal"]["hp"]
        game.state = "levelup"
        game.offers = [{"kind": "heal", "id": "heal", "level": 0,
                        "name": "Heal", "text": ""}]
        game.choose(0)
        self.assertEqual(game.hero.hp, 10 + heal)

    def test_the_summary_lists_what_the_hero_has(self):
        game = new_game()
        game.weapon_levels = {"spark_wand": 2, "spin_blades": 1}
        game.passive_levels = {"swift_boots": 1}
        self.assertEqual(game.summary(), ["Spark 2", "Blades 1", "Boots 1"])


class WeaponTest(unittest.TestCase):
    def test_spin_blades_hurt_an_enemy_that_touches_them(self):
        game = new_game()
        game.weapon_levels = {"spin_blades": 1}
        weapon = CONFIG["weapons"]["spin_blades"]
        enemy = rules.Enemy("bat", tough_bat(), weapon["orbit_radius"], 0, 0.5)
        game.enemies = [enemy]
        game.update(rules.FIXED_DT)
        self.assertEqual(enemy.hp, enemy.max_hp - rules.weapon_damage(weapon, 1))

    def test_holy_ring_hurts_everyone_inside_its_circle(self):
        game = new_game()
        game.weapon_levels = {"holy_ring": 1}
        weapon = CONFIG["weapons"]["holy_ring"]
        radius = rules.level_number(weapon["radius"], 1)
        inside_one = rules.Enemy("bat", tough_bat(), radius - 10, 0, 0.5)
        inside_two = rules.Enemy("bat", tough_bat(), 0, -(radius - 10), 0.5)
        outside = rules.Enemy("bat", tough_bat(), radius + 200, 0, 0.5)
        game.enemies = [inside_one, inside_two, outside]
        game.update(rules.FIXED_DT)
        damage = rules.weapon_damage(weapon, 1)
        self.assertEqual(inside_one.hp, inside_one.max_hp - damage)
        self.assertEqual(inside_two.hp, inside_two.max_hp - damage)
        self.assertEqual(outside.hp, outside.max_hp)

    def test_blades_only_hurt_the_same_enemy_again_after_half_a_second(self):
        game = new_game()
        game.weapon_levels = {"spin_blades": 1}
        weapon = CONFIG["weapons"]["spin_blades"]
        enemy = rules.Enemy("bat", tough_bat(), weapon["orbit_radius"], 0, 0.5)
        game.enemies = [enemy]
        game.update(rules.FIXED_DT)
        after_first = enemy.hp
        game.update(rules.FIXED_DT)
        self.assertEqual(enemy.hp, after_first)   # too soon for a second hit


class EventTest(unittest.TestCase):
    """The game tells the screen and the speakers what just happened."""

    def test_a_spark_hit_is_reported(self):
        game = new_game()
        bat = CONFIG["enemies"]["bat"]
        game.enemies = [rules.Enemy("bat", bat, 120, 0, 0.5)]
        run_for(game, 0.4)
        events = game.take_events()
        kinds = [event["kind"] for event in events]
        self.assertIn("hit", kinds)
        self.assertIn("kill", kinds)
        hit = [event for event in events if event["kind"] == "hit"][0]
        self.assertEqual(hit["amount"], CONFIG["weapons"]["spark_wand"]["damage"]["base"])

    def test_picking_up_a_gem_is_reported(self):
        game = new_game()
        drop_gem(game, game.hero.x, game.hero.y, 1)
        game.update(rules.FIXED_DT)
        kinds = [event["kind"] for event in game.take_events()]
        self.assertIn("gem", kinds)

    def test_a_level_up_is_reported(self):
        game = new_game()
        level_up(game)
        kinds = [event["kind"] for event in game.take_events()]
        self.assertIn("levelup", kinds)

    def test_getting_hurt_is_reported(self):
        game = new_game()
        bat = CONFIG["enemies"]["bat"]
        tough = dict(bat, hp=1000)
        game.enemies = [rules.Enemy("bat", tough, game.hero.x, game.hero.y, 0.5)]
        game.update(rules.FIXED_DT)
        hurts = [e for e in game.take_events() if e["kind"] == "hurt"]
        self.assertEqual(hurts[0]["amount"], bat["damage"])

    def test_the_end_is_reported(self):
        game = new_game()
        game.hero.hp = 0
        game.update(rules.FIXED_DT)
        ends = [e for e in game.take_events() if e["kind"] == "end"]
        self.assertEqual(ends[0]["result"], "gameover")

        game.restart()
        game.time = game.duration() - 0.01
        game.update(rules.FIXED_DT)
        ends = [e for e in game.take_events() if e["kind"] == "end"]
        self.assertEqual(ends[0]["result"], "victory")

    def test_take_events_empties_the_list(self):
        game = new_game()
        drop_gem(game, game.hero.x, game.hero.y, 1)
        game.update(rules.FIXED_DT)
        self.assertTrue(game.take_events())
        self.assertEqual(game.take_events(), [])


class WaveTest(unittest.TestCase):
    """The whole table, the boss, the timer and the victory."""

    def test_the_table_decides_which_enemies_come(self):
        game = new_game()
        self.assertEqual(game.spawn_types(0), ["bat"])
        self.assertIn("slime", game.spawn_types(30))
        self.assertIn("ghost", game.spawn_types(45))
        self.assertNotIn("ghost", game.spawn_types(30))
        # the boss is never part of the random waves
        self.assertNotIn("boss", game.spawn_types(200))

    def test_the_boss_comes_once_at_its_time(self):
        game = new_game()
        moment = game.boss_time()
        self.assertEqual(moment, 90.0)
        game.time = moment - 0.02
        run_for(game, 0.2)
        bosses = [enemy for enemy in game.enemies if enemy.kind == "boss"]
        self.assertEqual(len(bosses), 1)
        self.assertTrue(game.boss_spawned)
        # and it does not come back a second time
        game.time = moment + 5.0
        run_for(game, 1.1)
        bosses = [enemy for enemy in game.enemies if enemy.kind == "boss"]
        self.assertEqual(len(bosses), 1)

    def test_the_boss_is_never_removed_but_comes_back_close(self):
        game = new_game()
        boss = rules.Enemy("boss", CONFIG["enemies"]["boss"], 5000, 5000, 0.5)
        game.enemies = [boss]
        game.update(rules.FIXED_DT)
        self.assertEqual(game.enemies, [boss])
        away = rules.distance(game.hero.x, game.hero.y, boss.x, boss.y)
        reset = float(CONFIG["spawning"]["boss_reset_radius"])
        self.assertLessEqual(away, reset)

    def test_the_boss_gives_no_gem(self):
        game = new_game()
        boss = rules.Enemy("boss", CONFIG["enemies"]["boss"], 300, 0, 0.5)
        boss.hp = 0
        game.enemies = [boss]
        game.update(rules.FIXED_DT)
        self.assertEqual(game.gems, [])
        self.assertEqual(game.kills, 1)

    def test_a_normal_enemy_still_gets_removed_when_far(self):
        game = new_game()
        bat = CONFIG["enemies"]["bat"]
        far = float(CONFIG["spawning"]["despawn_radius"]) + 10
        game.enemies = [rules.Enemy("bat", bat, far, 0, 0.5)]
        game.update(rules.FIXED_DT)
        self.assertEqual(game.enemies, [])

    def test_two_minutes_is_victory(self):
        game = new_game()
        self.assertEqual(game.state, "playing")
        game.time = game.duration() - 0.02
        run_for(game, 0.1)
        self.assertEqual(game.state, "victory")
        frozen = game.time
        game.update(rules.FIXED_DT)
        self.assertEqual(game.time, frozen)     # a won game does not move
        game.restart()
        self.assertEqual(game.state, "playing")
        self.assertFalse(game.boss_spawned)

    def test_the_timer_text(self):
        game = new_game()
        game.time = 45.0
        self.assertEqual(game.run_time_text(), "0:45 / 2:00")
        game.time = 5.0
        self.assertEqual(game.run_time_text(), "0:05 / 2:00")


if __name__ == "__main__":
    unittest.main()
