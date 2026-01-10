from grafix import E, G, L, cc, preset, run

meta = {
    "center": {"kind": "vec3", "ui_min": 0.0, "ui_max": 100.0},
    "scale": {"kind": "vec3", "ui_min": 0.0, "ui_max": 5.0},
    "fill_density_coef": {"kind": "float", "ui_min": 0.0, "ui_max": 1.0},
    "fill_angle": {"kind": "float", "ui_min": 0.0, "ui_max": 360.0},
    "subdivide_levels": {"kind": "int", "ui_min": 0, "ui_max": 10},
    "displace_amplitude": {"kind": "vec3", "ui_min": 0.0, "ui_max": 5.0},
    "displace_frequency": {"kind": "vec3", "ui_min": 0.0, "ui_max": 0.5},
}


@preset(meta=meta)
def flow(
    center=(0, 0, 0),
    scale=(1.0, 1.0, 1.0),
    fill_density_coef=0.5,
    fill_angle=45.0,
    subdivide_levels=6,
    displace_amplitude=(5.0, 5.0, 0.0),
    displace_frequency=(0.025, 0.025, 0.0),
):
    flow = G(name="flow").polygon(
        n_sides=4,
        phase=45.0,
        center=(50.0, 50.0, 0.0),
        scale=100.0,
    )

    flow_e = (
        E(name="flow_eff")
        .fill(
            bypass=False,
            angle_sets=1,
            angle=fill_angle,
            density=300 * fill_density_coef,
            spacing_gradient=0.0,
            remove_boundary=False,
        )
        .subdivide(
            bypass=False,
            subdivisions=subdivide_levels,
        )
        .displace(
            bypass=False,
            amplitude=displace_amplitude,
            spatial_freq=displace_frequency,
            amplitude_gradient=(0.0, 0.0, 0.0),
            frequency_gradient=(0.0, 0.0, 0.0),
            min_gradient_factor=0.1,
            max_gradient_factor=2.0,
            t=0.0,
        )
    )

    flow = flow_e(flow)

    square = G(name="square").polygon(
        n_sides=4,
        phase=45.0,
        center=(50.0, 50.0, 0.0),
        scale=50.0,
    )

    clip = E(name="clip").clip(
        bypass=False,
        mode="inside",
        draw_outline=True,
    )

    ret = clip(flow, square)

    total_e = E(name="affine").affine(
        bypass=False,
        auto_center=True,
        pivot=(0.0, 0.0, 0.0),
        rotation=(0.0, 0.0, 0.0),
        scale=scale,
        delta=center,
    )

    return total_e(ret)


def draw(t):
    return flow()


if __name__ == "__main__":
    run(
        draw,
        canvas_size=(100, 100),
        render_scale=8,
        midi_port_name="Grid",
        midi_mode="14bit",
    )
