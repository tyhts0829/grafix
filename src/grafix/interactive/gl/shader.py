"""
どこで: `src/grafix/interactive/gl/shader.py`。
何を: 線の太さをジオメトリシェーダで表現する最小頂点/ジオメトリ/フラグメントのセットを提供。
なぜ: 単純なラインを太さ付き四角形に展開し、視認性を高めるため。
"""


class Shader:
    VERTEX_SHADER = """
    #version 410
    uniform mat4 projection;
    in vec3 in_vert;
    void main() {
        gl_Position = projection * vec4(in_vert.xy, 0.0, 1.0);
    }
    """
    GEOMETRY_SHADER = """
        #version 410
        layout(lines) in; // 入力は線
        layout(triangle_strip, max_vertices = 4) out; // 出力は四角形（2つの三角形）
        uniform vec2 viewport_size;
        uniform float line_width_px;
        void main() {
            vec4 p0 = gl_in[0].gl_Position;
            vec4 p1 = gl_in[1].gl_Position;
            vec2 delta_px = (p1.xy - p0.xy) * viewport_size * 0.5;
            float segment_length_px = length(delta_px);
            if (segment_length_px <= 1e-6) {
                return;
            }
            vec2 normal_px = vec2(-delta_px.y, delta_px.x) / segment_length_px;
            vec2 offset = normal_px * line_width_px / viewport_size;
            // 四角形の頂点を出力
            gl_Position = p0 + vec4(offset, 0.0, 0.0);
            EmitVertex();
            gl_Position = p0 - vec4(offset, 0.0, 0.0);
            EmitVertex();
            gl_Position = p1 + vec4(offset, 0.0, 0.0);
            EmitVertex();
            gl_Position = p1 - vec4(offset, 0.0, 0.0);
            EmitVertex();
            EndPrimitive();
        }
    """
    FRAGMENT_SHADER = """
        #version 410
        uniform vec4 color = vec4(0.0, 0.0, 0.0, 1.0);
        out vec4 fragColor;
        void main() {
            fragColor = color;
        }
    """

    @classmethod
    def create_shader(cls, mgl_context):
        line_program = mgl_context.program(
            vertex_shader=Shader.VERTEX_SHADER,
            geometry_shader=Shader.GEOMETRY_SHADER,
            fragment_shader=Shader.FRAGMENT_SHADER,
        )
        return line_program
