"""
Haiku / short-poem rotation pool for the blocking overlay.

All strictly 5-7-5 adjacent or short form. Public-domain classical poets
and original short verses. Used alongside Spanish vocabulary and "Did you
know?" facts as rotation content during ad blocks.

Format: (lines, attribution) where lines is a list of 3 strings.
Render path: src/ad_blocker.py::_get_blocking_text.
"""

HAIKUS = [
    (["An old silent pond",
      "A frog jumps into the pond —",
      "Splash! Silence again."],
     "Matsuo Basho"),

    (["Over the wintry",
      "forest, winds howl in rage",
      "with no leaves to blow."],
     "Natsume Soseki"),

    (["The light of a candle",
      "is transferred to another candle —",
      "spring twilight."],
     "Yosa Buson"),

    (["In the twilight rain",
      "these brilliant-hued hibiscus —",
      "A lovely sunset."],
     "Matsuo Basho"),

    (["A world of dew,",
      "And within every dewdrop",
      "A world of struggle."],
     "Kobayashi Issa"),

    (["The lamp once out",
      "Cool stars enter",
      "The window frame."],
     "Natsume Soseki"),

    (["First autumn morning",
      "the mirror I stare into",
      "shows my father's face."],
     "Murakami Kijo"),

    (["The wren earns his living",
      "noiselessly.",
      "New year's day."],
     "Kobayashi Issa"),

    (["After killing",
      "a spider, how lonely I feel",
      "in the cold of night!"],
     "Masaoka Shiki"),

    (["Temple bells die out.",
      "The fragrant blossoms remain.",
      "A perfect evening!"],
     "Matsuo Basho"),

    (["The taste",
      "of rain",
      "why kneel?"],
     "Jack Kerouac"),

    (["No sky",
      "no earth — but still",
      "snowflakes fall."],
     "Hashin"),

    (["Everything I touch",
      "with tenderness, alas,",
      "pricks like a bramble."],
     "Kobayashi Issa"),

    (["Don't weep, insects —",
      "Lovers, stars themselves,",
      "Must part."],
     "Kobayashi Issa"),

    (["Autumn moonlight —",
      "a worm digs silently",
      "into the chestnut."],
     "Matsuo Basho"),

    (["In the coolness",
      "of the empty sixth-month sky...",
      "the cuckoo's cry."],
     "Matsuo Basho"),

    # Original short modern pieces for contrast
    (["Server fans hum on",
      "somewhere in a dim closet —",
      "someone's packets fly."],
     "anon."),
    (["Soft blue screen at dawn",
      "last notification unread —",
      "the cat stretches out."],
     "anon."),
    (["Gray coffee cooling",
      "cursor blinks at empty line —",
      "a bird calls outside."],
     "anon."),
    (["Crumbs on the keyboard",
      "warm laptop on sleeping knees —",
      "one more chapter left."],
     "anon."),
    (["Rain along the roof,",
      "candle flickering — the draft",
      "of an old window."],
     "anon."),
    (["Autumn leaf on screen —",
      "dust under the kitchen fridge —",
      "the day lets go."],
     "anon."),
    (["Empty avenue,",
      "streetlamps stretching on and on —",
      "late bus brakes sigh."],
     "anon."),
    (["Train passes the bridge,",
      "gulls rise above the water —",
      "someone waves goodbye."],
     "anon."),
    (["Tea leaves in a jar",
      "hold a memory of rain —",
      "open the window."],
     "anon."),
    (["Paper crane unfolds,",
      "creases tell of other hands —",
      "afternoon light fades."],
     "anon."),
]


__all__ = ["HAIKUS"]
