#include <metal_stdlib>
using namespace metal;

struct RadarVertexOut {
    float4 position [[position]];
    float2 uv;
};

struct RadarUniforms {
    float opacity;
    float plotRadius;
};

vertex RadarVertexOut radar_vertex(uint vertexID [[vertex_id]]) {
    const float2 positions[6] = {
        float2(-1.0, -1.0), float2( 1.0, -1.0), float2(-1.0,  1.0),
        float2(-1.0,  1.0), float2( 1.0, -1.0), float2( 1.0,  1.0)
    };
    const float2 uvs[6] = {
        float2(0.0, 1.0), float2(1.0, 1.0), float2(0.0, 0.0),
        float2(0.0, 0.0), float2(1.0, 1.0), float2(1.0, 0.0)
    };
    RadarVertexOut output;
    output.position = float4(positions[vertexID], 0.0, 1.0);
    output.uv = uvs[vertexID];
    return output;
}

fragment float4 radar_fragment(
    RadarVertexOut input [[stage_in]],
    texture2d<float> dataTexture [[texture(0)]],
    texture2d<float> paletteTexture [[texture(1)]],
    constant RadarUniforms& uniforms [[buffer(0)]]
) {
    constexpr sampler nearestSampler(coord::normalized, address::clamp_to_edge, filter::nearest);
    float2 point = float2(
        (input.uv.x - 0.5) * 2.0,
        (0.5 - input.uv.y) * 2.0
    );
    float radius = length(point) / uniforms.plotRadius;
    if (radius > 1.0) {
        return float4(0.0);
    }
    float azimuth = atan2(point.x, point.y);
    if (azimuth < 0.0) {
        azimuth += 2.0 * M_PI_F;
    }
    float2 polarUV = float2(
        clamp(radius, 0.0, 0.999999),
        clamp(azimuth / (2.0 * M_PI_F), 0.0, 0.999999)
    );
    float2 gate = dataTexture.sample(nearestSampler, polarUV).rg;
    if (gate.g < 0.5) {
        return float4(0.0);
    }
    float4 color = paletteTexture.sample(
        nearestSampler,
        float2(clamp(gate.r, 0.0, 0.999999), 0.5)
    );
    color.a *= uniforms.opacity;
    return color;
}
