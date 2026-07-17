"""基本図形を組み合わせる最小 example。"""

from grafix import G, run

CANVAS_SIZE = (300, 300)


def draw(t: float):
    """時刻 ``t`` の scene を返す。"""

    _ = t
    circle = G.circle(radius=72.0, center=(95.0, 150.0, 0.0))
    rectangle = G.rect(width=110.0, height=110.0, center=(205.0, 150.0, 0.0))
    return circle + rectangle


if __name__ == "__main__":
    run(draw, canvas_size=CANVAS_SIZE)
