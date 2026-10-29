"""Run main.py for a few seconds WITHOUT a window and post fake input.

This is not a unittest (unittests test rules.py only): it starts the real
game loop with the SDL dummy video driver, posts mouse moves, clicks, finger
touches and key presses with pygame.event.post, clicks the level-up cards
when they appear, and then reports what happened.

    python tools/fake_input_test.py
"""

import asyncio
import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

import pygame  # noqa: E402

import main  # noqa: E402
import rules  # noqa: E402

FRAMES = 600
seen = {}
frame = 0
original_get = pygame.event.get


def post(event):
    pygame.event.post(event)


def click(pos):
    post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))


def fake_get(*args, **kwargs):
    """Post the fake input just before the game reads its events."""
    global frame
    frame += 1
    app = main.CURRENT_APP
    game = app.game

    # ---- sound and feel: what did the last frames produce? ------------
    if app.numbers:
        seen["had_numbers"] = True
    if app.flashes:
        seen["had_flashes"] = True
    if app.shake_timer > 0.0:
        seen["shook"] = True

    # ---- the scripted part: mouse, finger, keys -----------------------
    if frame == 4:                       # the mouse moves to the right
        post(pygame.event.Event(
            pygame.MOUSEMOTION, pos=(300, 120), rel=(0, 0), buttons=(0, 0, 0)))
    elif frame == 6:
        seen["hero_x_before"] = round(game.hero.x, 1)
    elif frame == 40:
        seen["hero_x_after"] = round(game.hero.x, 1)
        seen["pointer"] = app.pointer
    elif frame == 45:                    # a plain click while playing
        click((300, 120))
    elif frame == 60:                    # a finger touches the screen
        post(pygame.event.Event(
            pygame.FINGERDOWN, touch_id=0, finger_id=0,
            x=0.25, y=0.75, dx=0.0, dy=0.0, pressure=1.0))
    elif frame == 80:                    # the finger slides
        post(pygame.event.Event(
            pygame.FINGERMOTION, touch_id=0, finger_id=0,
            x=0.75, y=0.30, dx=0.5, dy=-0.45, pressure=1.0))
    elif frame == 100:                   # the finger is lifted
        post(pygame.event.Event(
            pygame.FINGERUP, touch_id=0, finger_id=0,
            x=0.75, y=0.30, dx=0.0, dy=0.0, pressure=0.0))
    elif frame == 105:
        seen["finger_lifted_target"] = app.current_target()
    elif frame == 120:                   # P pauses
        post(pygame.event.Event(
            pygame.KEYDOWN, key=pygame.K_p, mod=0, unicode="p", scancode=0))
    elif frame == 122:
        seen["paused"] = app.paused
        seen["time_while_paused"] = round(game.time, 2)
    elif frame == 150:                   # P again, playing continues
        post(pygame.event.Event(
            pygame.KEYDOWN, key=pygame.K_p, mod=0, unicode="p", scancode=0))
    elif frame == 152:
        seen["resumed"] = not app.paused

    # ---- the level-up cards: the game waits until one is taken ---------
    if game.state == "levelup":
        seen.setdefault("first_offers", [card["name"] for card in game.offers])
        card_set = tuple(card["id"] for card in game.offers)
        sets = seen.setdefault("card_sets", [])
        if card_set not in sets:
            sets.append(card_set)
            seen["cards_shown"] = seen.get("cards_shown", 0) + len(game.offers)
        seen["levelup_waits"] = seen.get("levelup_waits", 0) + 1
        if seen["levelup_waits"] % 3 == 1:      # pick a card after a short pause
            click(app.card_rects()[0].center)
            seen["cards_taken"] = seen.get("cards_taken", 0) + 1
    elif game.state == "gameover":
        seen.setdefault("gameover", "gameover")
        waits = seen.get("gameover_waits", 0) + 1
        seen["gameover_waits"] = waits
        if waits == 4:
            click((195, 350))                   # play again
    elif game.state == "playing":
        if "gameover" in seen and "state_after_restart" not in seen:
            seen["state_after_restart"] = game.state
            seen["hp_after_restart"] = game.hero.hp
            seen["time_after_restart"] = round(game.time, 2)
        # Play like a real player: keep moving in a circle, so the hero
        # walks over the gems and does not stand still in the enemies.
        if frame > 160 and frame % 20 == 0:
            angle = frame / 20.0
            post(pygame.event.Event(
                pygame.MOUSEMOTION,
                pos=(app.width / 2 + math.cos(angle) * 150,
                     app.height / 2 + math.sin(angle) * 120),
                rel=(0, 0), buttons=(0, 0, 0)))
        # A gem on the hero now and then, so the level-up path is always
        # tried (real kills also drop gems, but their timing is random).
        if frame in (200, 260):
            gems = app.config["gems"]
            game.gems.append(rules.Gem(
                game.hero.x, game.hero.y, game.level_xp_needed(),
                float(gems["radius"]), float(gems["fly_speed"])))
        if frame > 300 and game.level >= 2 and "killed" not in seen:
            game.hero.hp = 0                    # let the hero die
            seen["level_at_death"] = game.level
            seen["killed"] = True

    return original_get(*args, **kwargs)


async def run():
    pygame.event.get = fake_get
    app = await main.main(max_frames=FRAMES)
    return app


if __name__ == "__main__":
    app = asyncio.run(run())
    game = app.game
    print("--- fake input test: %d frames, %.2f s of game time ---"
          % (frame, game.time))
    print("hero x before / after the mouse move:", seen.get("hero_x_before"),
          "/", seen.get("hero_x_after"))
    print("last mouse position (screen px):", seen.get("pointer"))
    print("target after the finger was lifted:", seen.get("finger_lifted_target"))
    print("paused after P:", seen.get("paused"),
          " game time then:", seen.get("time_while_paused"))
    print("playing again after the 2nd P:", seen.get("resumed"))
    print("first level-up cards:", seen.get("first_offers"))
    print("cards shown / taken:", seen.get("cards_shown"), "/", seen.get("cards_taken"))
    print("state after HP reached 0:", seen.get("gameover"))
    print("state after the click:", seen.get("state_after_restart"),
          " hp:", seen.get("hp_after_restart"),
          " time:", seen.get("time_after_restart"))
    print("final: level", game.level, "xp", game.xp, "hp", game.hero.hp,
          "kills", game.kills, "has", game.summary(), "state", game.state)
    print("sounds loaded:", sorted(app.sounds))
    print("damage numbers seen:", seen.get("had_numbers"),
          " death flashes:", seen.get("had_flashes"),
          " shake:", seen.get("shook"))

    ok = True
    checks = [
        ("the hero walked toward the mouse",
         seen.get("hero_x_after", 0) > seen.get("hero_x_before", 0)),
        ("the mouse position was stored", seen.get("pointer") == (300, 120)),
        ("lifting the finger stops the hero",
         seen.get("finger_lifted_target") is None),
        ("P pauses", seen.get("paused") is True),
        ("P plays again", seen.get("resumed") is True),
        ("three cards were offered first",
         len(seen.get("first_offers", [])) == 3),
        ("cards could be clicked", seen.get("cards_taken", 0) > 0),
        ("the hero really got stronger", seen.get("level_at_death", 0) >= 2),
        ("0 HP is game over", seen.get("gameover") == "gameover"),
        ("a click starts a new game", seen.get("state_after_restart") == "playing"),
        ("the new game has full HP", seen.get("hp_after_restart", 0) > 0),
        ("the new game starts at 0:00",
         seen.get("time_after_restart", 1.0) < 0.1),
        ("all five sounds were loaded", len(app.sounds) == 5),
        ("damage numbers appeared", seen.get("had_numbers") is True),
        ("death flashes appeared", seen.get("had_flashes") is True),
        ("the screen shook when the hero was hurt",
         seen.get("shook") is True),
    ]
    for label, passed in checks:
        print(("  OK   " if passed else "  FAIL ") + label)
        ok = ok and passed
    print("RESULT:", "all checks passed" if ok else "SOMETHING FAILED")
    sys.exit(0 if ok else 1)

