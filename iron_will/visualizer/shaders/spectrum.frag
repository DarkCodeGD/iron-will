#version 440
// Iron Will: bars, mirror and wave on the GPU.
//
// The CPU painter (VisualizerItem.paint in renderer.py) rasterised every bar
// with QPainter and uploaded a window-sized image each frame: up to a whole
// CPU core at full screen height. This shader draws the same picture from a
// tiny data texture instead (visualizer/spectrum.py):
//
//   spectrum   n × 2 texels: row 0 = bar heights, row 1 = peak caps, each a
//              16-bit value in R (high byte) and G (low byte), 0..1
//
// Mirror is just bars: the CPU side mirrors the values before uploading.
//
// Geometry matches the CPU painter so the two look the same (the software
// fallback still uses it): the same bar width / spacing rule, rounded
// rectangles with the same radius, peak caps that skip when they sit on
// their bar, and for wave the same Catmull-Rom curve through the band
// centres, filled at 35 % under a 2 px line. Edges are antialiased with a
// signed distance, one device pixel wide (fwidth), so they stay crisp at any
// display scale.
//
// "u" below is the distance from the base edge (the anchored edge the bars
// grow from), so one code path serves both directions.

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;  // visualizer.opacity × idle fade
    vec4 res;          // x, y = item size in logical px; z = bar count; w = 0 bars, 1 wave
    vec4 bars;         // x = spacing px; y = roundness 0..1; z = min height px; w = peaks on (1) / off (0)
    vec4 grad;         // x = number of colors (1..6); y = 1 horizontal / 0 vertical; z = 1 grow up / 0 down
    vec4 c0;           // gradient stops, evenly spaced, first at the base (or the left)
    vec4 c1;
    vec4 c2;
    vec4 c3;
    vec4 c4;
    vec4 c5;
};
layout(binding = 1) uniform sampler2D spectrum;

const float PEAK_GAP = 0.015;    // cap sitting on its bar: not drawn (as on the CPU)
const float CAP_ALPHA = 0.85;
const float FILL_ALPHA = 0.35;   // wave: area under the line
const float LINE_HALF = 1.0;     // wave: 2 px line

// Bar i's height (row 0) or peak (row 1), 0..1.
float level(float i, float row) {
    vec4 t = texture(spectrum, vec2((i + 0.5) / res.z, (row + 0.5) * 0.5));
    return (t.r * 65280.0 + t.g * 255.0) / 65535.0;
}

vec3 stopColor(float k) {
    if (k < 0.5) return c0.rgb;
    if (k < 1.5) return c1.rgb;
    if (k < 2.5) return c2.rgb;
    if (k < 3.5) return c3.rgb;
    if (k < 4.5) return c4.rgb;
    return c5.rgb;
}

// Evenly spaced stops, clamped at both ends (QLinearGradient's pad spread).
vec3 gradient(float t) {
    float n = grad.x;
    if (n < 1.5) return c0.rgb;
    float x = clamp(t, 0.0, 1.0) * (n - 1.0);
    float k = min(floor(x), n - 2.0);
    return mix(stopColor(k), stopColor(k + 1.0), x - k);
}

// Signed distance to a rounded rectangle (centre-relative point, half size, radius).
float roundBox(vec2 p, vec2 half_size, float r) {
    vec2 q = abs(p) - half_size + r;
    return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - r;
}

float coverage(float d, float aa) {
    return clamp(0.5 - d / aa, 0.0, 1.0);
}

float drawBars(vec2 p, float h, float aa) {
    float n = res.z, w = res.x;
    // Same metrics as VisualizerItem._bar_metrics.
    float spacing = bars.x;
    if (n > 1.0 && (w - spacing * (n - 1.0)) / n < 1.0)
        spacing = max(0.0, (w - n) / (n - 1.0));            // too dense: shrink gaps first
    float bw = max(1.0, (w - spacing * (n - 1.0)) / n);
    float pitch = bw + spacing;
    float radius = bars.y * bw * 0.5;
    float minH = bars.z, span = h - minH;
    float cap = clamp(bw * 0.35, 2.0, 4.0);
    float capR = min(radius, cap * 0.5);

    float body = 0.0, caps = 0.0;
    float home = floor(p.x / pitch);
    // This pixel's bar and its neighbours: with little spacing, an edge pixel
    // is partly covered by the next bar.
    for (int k = -1; k <= 1; k++) {
        float i = home + float(k);
        if (i < 0.0 || i >= n) continue;
        float cx = i * pitch + bw * 0.5;
        float v = level(i, 0.0);
        float bh = minH + v * span;
        if (bh >= 0.5) {
            float r = min(radius, bh * 0.5);
            body = max(body, coverage(roundBox(vec2(p.x - cx, p.y - bh * 0.5), vec2(bw * 0.5, bh * 0.5), r), aa));
        }
        if (bars.w > 0.5) {
            float pk = level(i, 1.0);
            if (pk - v >= PEAK_GAP) {
                float off = min(h - cap, minH + pk * span + cap);
                caps = max(caps, coverage(roundBox(vec2(p.x - cx, p.y - off - cap * 0.5),
                                                   vec2(bw * 0.5, cap * 0.5), capR), aa));
            }
        }
    }
    return body + caps * CAP_ALPHA * (1.0 - body);
}

// Wave: the curve's height (from the base) at point index i, clamped to the ends.
float waveHeight(float i, float minH, float span) {
    return minH + level(clamp(i, 0.0, res.z - 1.0), 0.0) * span + 1.0;
}

// Wave: x of point index i. Points sit at band centres, plus one point on each
// edge (x = 0 and x = w, at the height of the band next to it).
float waveX(float i, float step) {
    return i <= -1.0 ? 0.0 : i >= res.z ? res.x : (i + 0.5) * step;
}

float bezier(float b0, float b1, float b2, float b3, float t) {
    float s = 1.0 - t;
    return s * s * s * b0 + 3.0 * s * s * t * b1 + 3.0 * s * t * t * b2 + t * t * t * b3;
}

float bezierSlope(float b0, float b1, float b2, float b3, float t) {   // d/dt
    float s = 1.0 - t;
    return 3.0 * (s * s * (b1 - b0) + 2.0 * s * t * (b2 - b1) + t * t * (b3 - b2));
}

float drawWave(vec2 p, float h, float aa) {
    float n = res.z;
    float minH = bars.z;
    float span = h - minH - 2.0;          // keep the 2 px line inside the item
    float step = res.x / n;
    // Segment a runs from band a to band a + 1 (a = -1 and a = n - 1 are the
    // half-width end pieces from and to the edge points).
    float j = p.x / step - 0.5;
    float a = j < 0.0 ? -1.0 : min(floor(j), n - 1.0);
    // Catmull-Rom → cubic Bézier, exactly as the CPU painter builds it, for
    // both coordinates (the ends duplicate their last point).
    float x0 = waveX(a - 1.0, step), x1 = waveX(a, step), x2 = waveX(a + 1.0, step), x3 = waveX(a + 2.0, step);
    float y0 = waveHeight(a - 1.0, minH, span), y1 = waveHeight(a, minH, span);
    float y2 = waveHeight(a + 1.0, minH, span), y3 = waveHeight(a + 2.0, minH, span);
    float xb1 = x1 + (x2 - x0) / 6.0, xb2 = x2 - (x3 - x1) / 6.0;
    float b1 = y1 + (y2 - y0) / 6.0, b2 = y2 - (y3 - y1) / 6.0;
    // Which t lands on this pixel's x? Linear in the middle of the wave; near
    // the edges the half-width end piece bends it, so refine with Newton
    // (x(t) only ever increases, so it converges in a few steps).
    float t = clamp((p.x - x1) / max(x2 - x1, 1e-4), 0.0, 1.0);
    for (int k = 0; k < 4; k++) {
        float dx = bezierSlope(x1, xb1, xb2, x2, t);
        t = clamp(t - (bezier(x1, xb1, xb2, x2, t) - p.x) / max(dx, 1e-4), 0.0, 1.0);
    }
    float dxdt = max(bezierSlope(x1, xb1, xb2, x2, t), 1e-4);
    float yc = bezier(y1, b1, b2, y2, t);
    float dydt = bezierSlope(y1, b1, b2, y2, t);
    // Distance to the curve, to first order: the vertical gap divided by the
    // slope's stretch, so steep flanks get as thick a line as flat ones.
    float dist = (p.y - yc) / sqrt(1.0 + (dydt / dxdt) * (dydt / dxdt));
    float line = coverage(abs(dist) - LINE_HALF, aa);
    float fill = coverage(dist, aa);
    return line + fill * FILL_ALPHA * (1.0 - line);
}

void main() {
    float h = res.y;
    vec2 p = qt_TexCoord0 * res.xy;
    if (grad.z > 0.5) p.y = h - p.y;      // grow up: measure from the bottom
    float aa = max(fwidth(qt_TexCoord0.x * res.x), 1e-4);   // one device pixel, in logical px

    float alpha = res.w > 0.5 ? drawWave(p, h, aa) : drawBars(p, h, aa);
    vec3 color = gradient(grad.y > 0.5 ? p.x / res.x : p.y / h);
    fragColor = vec4(color * alpha, alpha) * qt_Opacity;    // premultiplied
}
