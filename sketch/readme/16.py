from grafix import E, G, P, run

# A5
CANVAS_WIDTH = 148
CANVAS_HEIGHT = 210


def draw(t):
    # --- primitives（変更対象）---
    sphere = G(name="sphere").sphere()
    asemic = G(name="asemic").asemic()

    # --- effects（変更対象）---
    base_ring = G(name="base_ring").polygon(
        center=(CANVAS_WIDTH * 0.25, CANVAS_HEIGHT * 0.25, 0.0),
        scale=40.0,
    )

    changed_fx = (
        E(name="changed_fx")
        .rotate()
        .twist()
        .scale()
        .repeat()
        .mirror()
        .collapse()
        .affine()
        .displace()
    )
    fx_out = changed_fx(base_ring)

    partition_out = E(name="partition").partition()(base_ring)
    mirror3d_out = E(name="mirror3d").mirror3d()(sphere)

    # --- presets（変更対象）---
    layout_grid_system = P.layout_grid_system()
    layout_bounds = P.layout_bounds()
    grn_a5_frame = P.grn_a5_frame()

    return [
        grn_a5_frame,
        layout_grid_system,
        layout_bounds,
        sphere,
        asemic,
        fx_out,
        partition_out,
        mirror3d_out,
    ]


if __name__ == "__main__":
    run(
        draw,
        background_color=(1.0, 1.0, 1.0),
        line_thickness=0.001,
        line_color=(0.0, 0.0, 0.0),
        render_scale=5,
        canvas_size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        parameter_gui=True,
        midi_port_name="auto",
        midi_mode="14bit",
    )
