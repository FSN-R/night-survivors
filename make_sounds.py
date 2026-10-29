"""Make the game sounds with the Python standard library only.

Run this on your own computer:  python make_sounds.py

No pygame, no Pillow, no internet: just `wave`, `math` and `struct`.
It writes five short .wav files into sounds/:

    hit.wav      a spark or a blade touches an enemy
    gem.wav      a gem is picked up
    levelup.wav  the level-up cards appear
    hurt.wav     the hero is hurt
    end.wav      VICTORY or GAME OVER
"""

import math
import os
import random
import struct
import wave

RATE = 22050                # samples per second
VOLUME = 0.45               # keep it quiet, the sounds are short and sharp
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOUNDS_DIR = os.path.join(BASE_DIR, "sounds")


def render(seconds, shape, volume=VOLUME):
    """Turn a function of time into a list of samples between -1 and 1."""
    count = max(1, int(RATE * seconds))
    samples = []
    for index in range(count):
        t = index / RATE
        progress = index / (count - 1)
        samples.append(max(-1.0, min(1.0, shape(t, progress) * volume)))
    return samples


def square(frequency, t):
    return 1.0 if math.sin(2.0 * math.pi * frequency * t) >= 0.0 else -1.0


def sine(frequency, t):
    return math.sin(2.0 * math.pi * frequency * t)


def write_wav(name, samples):
    """Write mono 16-bit samples to sounds/<name>."""
    data = bytearray()
    for value in samples:
        data += struct.pack("<h", int(value * 32767))
    path = os.path.join(SOUNDS_DIR, name)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(bytes(data))
    print("%-12s %5.2f s  %5.1f KB" % (
        name, len(samples) / RATE, os.path.getsize(path) / 1024.0))


def make_hit():
    """A short, bright click: a spark touching an enemy."""
    def shape(t, p):
        fade = (1.0 - p) ** 3
        return (0.65 * square(430.0, t) + 0.35 * random.uniform(-1.0, 1.0)) * fade
    return render(0.07, shape)


def make_gem():
    """Two quick notes going up: a gem was picked up."""
    def shape(t, p):
        frequency = 880.0 + 520.0 * p
        return sine(frequency, t) * (1.0 - p) ** 2
    return render(0.11, shape)


def make_levelup():
    """Four notes going up: the level-up cards appear."""
    samples = []
    for frequency in (523.25, 659.25, 783.99, 1046.5):
        samples += render(
            0.11,
            lambda t, p, f=frequency: sine(f, t) * (1.0 - p) ** 1.5,
            volume=VOLUME * 0.9,
        )
    return samples


def make_hurt():
    """A low buzz going down: the hero got hurt."""
    def shape(t, p):
        frequency = 170.0 - 80.0 * p
        buzz = 0.7 * square(frequency, t) + 0.3 * random.uniform(-1.0, 1.0)
        return buzz * (1.0 - p) ** 2
    return render(0.18, shape, volume=VOLUME * 0.8)


def make_end():
    """A soft chord that fades away: the run is over."""
    def shape(t, p):
        chord = (sine(392.0, t) + sine(329.63, t) + sine(261.63, t)) / 3.0
        attack = min(1.0, p * 12.0)
        return chord * attack * (1.0 - p) ** 1.5
    return render(0.9, shape, volume=VOLUME * 0.85)


def main():
    random.seed(7)                      # the same sounds every time you run it
    os.makedirs(SOUNDS_DIR, exist_ok=True)
    for old in os.listdir(SOUNDS_DIR):
        if old.lower().endswith((".wav", ".ogg")):
            os.remove(os.path.join(SOUNDS_DIR, old))

    write_wav("hit.wav", make_hit())
    write_wav("gem.wav", make_gem())
    write_wav("levelup.wav", make_levelup())
    write_wav("hurt.wav", make_hurt())
    write_wav("end.wav", make_end())
    print("done: %d sounds in %s" % (len(os.listdir(SOUNDS_DIR)), SOUNDS_DIR))


if __name__ == "__main__":
    main()
