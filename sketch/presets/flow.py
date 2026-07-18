from collections.abc import Mapping

from grafix import E, G, preset, run

meta: dict[str, Mapping[str, object]] = {
    "center": {
        "kind": "vec3",
        "ui_min": 0.0,
        "ui_max": 100.0,
        "description": "完成した流線パターン全体を移動する量を指定する。",
    },
    "scale": {
        "kind": "vec3",
        "ui_min": 0.0,
        "ui_max": 5.0,
        "description": "完成した流線パターン全体を軸ごとに拡大縮小する。",
    },
    "fill_density_coef": {
        "kind": "float",
        "ui_min": 0.0,
        "ui_max": 1.0,
        "description": "変形前に生成する平行線の密度を基準値に対する比率で指定する。",
    },
    "fill_angle": {
        "kind": "float",
        "ui_min": 0.0,
        "ui_max": 360.0,
        "description": "流線の元になる平行線の角度を度で指定する。",
    },
    "subdivide_levels": {
        "kind": "int",
        "ui_min": 0,
        "ui_max": 10,
        "description": "変位前に各線分を細分化する反復回数を指定する。",
    },
    "displace_amplitude": {
        "kind": "vec3",
        "ui_min": 0.0,
        "ui_max": 5.0,
        "description": "ノイズ変位の最大振幅を軸ごとに指定する。",
    },
    "displace_frequency": {
        "kind": "vec3",
        "ui_min": 0.0,
        "ui_max": 0.5,
        "description": "ノイズ場の空間周波数を軸ごとに指定する。",
    },
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
            activate=True,
            angle_sets=1,
            angle=fill_angle,
            density=300 * fill_density_coef,
            spacing_gradient=0.0,
            remove_boundary=False,
        )
        .subdivide(
            activate=True,
            subdivisions=subdivide_levels,
        )
        .displace(
            activate=True,
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
        activate=True,
        mode="inside",
        draw_outline=True,
    )

    ret = clip(flow, square)

    total_e = E(name="affine").affine(
        activate=True,
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
