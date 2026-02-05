from pathlib import Path

from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210

from grafix import E, G, run


def draw(t: float):
    poly = G.polyhedron()
    effect = E.fill().subdivide().displace().rotate(rotation=(t * 6, t * 5, t * 4))
    return effect(poly)


if __name__ == "__main__":
    run(draw, canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT), render_scale=5)
