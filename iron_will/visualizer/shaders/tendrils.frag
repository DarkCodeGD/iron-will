#version 440
// Iron Will: Void Tendrils.
//
// Black, tapered tendrils rooted along the base edge, edged with a thin
// bright rim on their lit side and a glow that hugs them, over a dark mass of
// roots, bleeding motes of void essence. Not a fire: no noise anywhere, every
// shape is a distance field around a skeleton computed on the CPU
// (visualizer/tendrils.py, which documents the data texture layout).
//
// Per pixel, back to front:
//   1. a haze of void light rising off the roots (analytic, follows the music)
//   2. every tendril whose bounding box is near: distance to its spine, a
//      chain of tapered capsules → body, rim, aura. The back rank are dim
//      violet silhouettes, the front rank black with a bright edge.
//   3. the root mass along the base, so the tendrils grow out of something
//   4. essence motes: a bright core, a short streak along their heading, a halo
//
// Light (haze, aura, rim, motes) is added as premultiplied colour with zero
// alpha: on a transparent window it brightens the wallpaper like real glow,
// and fades out through transparency rather than through dark (brown-ish)
// shades of the glow colour.

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec4 colsA;        // spectrum levels across the width (bass in the middle)
    vec4 colsB;
    vec4 colsC;
    vec4 colsD;
    vec4 motion;       // x = writhe phase, y = energy, z = kick flash, w = snare/cymbal flash
    vec4 extra;        // x = tendrils, y = mote rows, z = glow setting, w = essence setting
    vec4 look;         // z = 1 grow up / 0 down
    vec4 res;          // xy = item size in px, zw = data texture size in texels
    vec4 colorA;       // rim light
    vec4 colorB;       // glow near the tendrils, essence
    vec4 colorC;       // glow further out, haze
    float param;       // palette: 0 void, 1 ember, 2 your colors
};
layout(binding = 1) uniform sampler2D dataTex;

const int MAX_TENDRILS = 40;
const int POINTS = 17;          // SEGMENTS + 1
const int MOTE_ROWS = 8;
const int MOTES_PER_ROW = 8;
const float MOTE_INDEX = 80.0;   // 2 × MAX_TENDRILS
const float RADIUS_UNIT = 6.0;

vec4 texel(float i, float row) {
    return texture(dataTex, vec2((i + 0.5) / res.z, (row + 0.5) / res.w));
}
float dec16(vec4 t) { return (t.r * 65280.0 + t.g * 255.0) / 65535.0; }
float winPos(vec4 t) { return dec16(t) * 1.5 - 0.25; }          // window fraction with headroom

float column(float i) {
    if (i < 4.0) return i < 1.0 ? colsA.x : i < 2.0 ? colsA.y : i < 3.0 ? colsA.z : colsA.w;
    if (i < 8.0) return i < 5.0 ? colsB.x : i < 6.0 ? colsB.y : i < 7.0 ? colsB.z : colsB.w;
    if (i < 12.0) return i < 9.0 ? colsC.x : i < 10.0 ? colsC.y : i < 11.0 ? colsC.z : colsC.w;
    return i < 13.0 ? colsD.x : i < 14.0 ? colsD.y : i < 15.0 ? colsD.z : colsD.w;
}
float levelAt(float u) {
    float f = clamp(u, 0.0, 0.999) * 15.0;
    float i = floor(f);
    return mix(column(i), column(min(i + 1.0, 15.0)), f - i);
}

void main() {
    float w = res.x, h = res.y;
    vec2 p = vec2(qt_TexCoord0.x * w, (look.z > 0.5 ? 1.0 - qt_TexCoord0.y : qt_TexCoord0.y) * h);
    float aa = max(fwidth(qt_TexCoord0.x * w), 1e-4);      // one device pixel, in logical px
    float glowSet = extra.z;
    float energy = motion.y, flash = motion.z;
    float pulse = 1.0 + 0.9 * flash;                        // kicks flare the light
    vec4 acc = vec4(0.0);                                   // premultiplied

    // ── 1. void light rising off the roots ────────────────────────────────
    float lvl = levelAt(p.x / w);
    // Brightest just above the root mass, fading up through the lower half.
    float haze = (0.62 * exp(-pow((p.y - 0.16 * h) / (0.20 * h + 8.0), 2.0)) + 0.20 * exp(-p.y / (0.45 * h)))
               * (0.35 + 0.65 * lvl) * (0.55 + 0.45 * energy) * pulse;
    acc.rgb += colorC.rgb * haze * glowSet;

    // ── 2. tendrils, back to front ────────────────────────────────────────
    int count = int(extra.x + 0.5);
    for (int j = 0; j < MAX_TENDRILS; j++) {
        if (j >= count) break;
        vec4 i0 = texel(2.0 * float(j), 0.0);
        vec4 i1 = texel(2.0 * float(j) + 1.0, 0.0);
        float layer = i0.b;                                 // 0 far back … 1 front
        float glowR = (3.0 + 9.0 * glowSet) * (layer < 0.5 ? 1.6 : 1.0);
        float margin = 5.0 * glowR + 2.0;
        if (p.x < winPos(i0) * w - margin || p.x > winPos(i1) * w + margin || p.y > i1.b * 1.25 * h + margin)
            continue;

        float row = float(j) + 1.0;
        vec4 ta = texel(0.0, row), tb = texel(1.0, row);
        vec2 a = vec2(winPos(ta) * w, winPos(tb) * h);
        float ra = ta.b * 255.0 / RADIUS_UNIT;
        float best = 1e6, across = 0.0, along = 0.0, bestR = 1.0;
        for (int k = 1; k < POINTS; k++) {
            vec4 ua = texel(2.0 * float(k), row), ub = texel(2.0 * float(k) + 1.0, row);
            vec2 b = vec2(winPos(ua) * w, winPos(ub) * h);
            float rb = ua.b * 255.0 / RADIUS_UNIT;
            vec2 ab = b - a, ap = p - a;
            float len2 = max(dot(ab, ab), 1e-4);
            float t = clamp(dot(ap, ab) / len2, 0.0, 1.0);
            float r = mix(ra, rb, t);
            float d = length(ap - ab * t) - r;
            if (d < best) {
                best = d;
                bestR = r;
                // which side of the spine (−1 … 1 across the body), and how far up it
                across = clamp((ab.x * ap.y - ab.y * ap.x) / sqrt(len2) / max(r, 0.5), -1.0, 1.0);
                along = (float(k) - 1.0 + t) / float(POINTS - 1);
            }
            a = b; ra = rb;
        }
        if (best > margin) continue;

        vec4 shade = texel(2.0 * float(POINTS), row);
        float litSide = shade.r * 2.0 - 1.0;               // which edge catches the light
        float tGlow = shade.g;                              // this tendril's share of the music
        float body = clamp(0.5 - best / aa, 0.0, 1.0);
        float front = smoothstep(0.4, 0.8, layer);

        // Body: front rank near-black with a faint sheen down the lit side;
        // back rank a dim violet silhouette.
        vec3 dark = vec3(0.010, 0.004, 0.018);
        vec3 sheen = colorB.rgb * 0.10 * exp(-pow((across - 0.55 * litSide) * 2.6, 2.0));
        float bodyA = body * mix(0.55, 0.97, front);
        acc = vec4((dark + sheen) * bodyA, bodyA) + acc * (1.0 - bodyA);
        // The back rank stands further into the haze: a dark core whose edges
        // light up violet, so it reads as a tendril, just with less contrast.
        float edgeGlow = smoothstep(0.15, 1.0, abs(across));
        acc.rgb += mix(colorC.rgb * 0.35, colorB.rgb, edgeGlow) * body * (1.0 - front)
                 * (0.30 + 0.55 * edgeGlow) * (0.6 + 0.4 * tGlow) * (1.0 - 0.45 * along)
                 * (0.5 + 0.5 * glowSet) * pulse;

        // Sheath: the violet shape each front tendril stands in, as in the
        // reference art. It tapers with the tendril (its width follows the
        // local radius) and bulges out on the lit side.
        float out_ = max(best, 0.0);
        float side = across * litSide > 0.0 ? 1.0 : 0.0;
        float sheathW = (2.0 + 1.6 * bestR) * (0.7 + 0.8 * side) * (0.5 + 0.7 * glowSet);
        float sheath = pow(1.0 - smoothstep(0.0, sheathW, out_), 1.6) * (1.0 - body) * front;
        acc.rgb += mix(colorB.rgb, colorC.rgb, out_ / max(sheathW, 1e-3)) * sheath
                 * (0.45 + 0.35 * tGlow) * (1.0 - 0.5 * smoothstep(0.6, 1.0, along)) * pulse;

        // Aura: a soft halo beyond it, hot near the skin, cooling to the far
        // colour further out; dies away towards the very tip.
        float aura = exp(-out_ / glowR) * (1.0 - body) * (1.0 - 0.6 * smoothstep(0.75, 1.0, along));
        vec3 auraCol = mix(colorB.rgb, colorC.rgb, smoothstep(0.0, 2.5 * glowR, out_));
        acc.rgb += auraCol * aura * glowSet * (0.30 + 0.55 * tGlow) * mix(0.55, 0.85, front) * pulse;

        // Rim: a thin bright line on the silhouette, strongest on the lit side.
        float rimW = 0.7 + 0.5 * aa;
        float rim = exp(-(best * best) / (rimW * rimW));
        float lit = 0.25 + 0.75 * smoothstep(-0.3, 0.8, across * litSide);
        acc.rgb += colorA.rgb * rim * lit * (0.35 + 0.85 * glowSet) * mix(0.45, 1.0, front) * (0.75 + 0.4 * tGlow);
    }

    // ── 3. the root mass along the base ───────────────────────────────────
    float T = motion.x;
    // Rounded lumps (no sharp peaks), a soft top, faintly lit from above.
    float lump = 0.4 + 0.010 * h;                          // lumps grow with the window
    float ground = 0.065 * h + 3.0
                 + lump * (2.2 * sin(p.x * 0.011 + T * 0.30) + 1.5 * sin(p.x * 0.029 - T * 0.45 + 1.3)
                           + 0.8 * sin(p.x * 0.057 + 2.1));
    float g = clamp(0.5 - (p.y - ground) / (2.5 + aa), 0.0, 1.0);
    vec3 mass = vec3(0.008, 0.003, 0.014) + colorC.rgb * 0.10 * smoothstep(ground - 0.05 * h - 6.0, ground, p.y);
    acc = vec4(mass * g, g) + acc * (1.0 - g);
    acc.rgb += colorA.rgb * exp(-pow((p.y - ground) / 1.3, 2.0)) * 0.22 * glowSet
             * (0.4 + 0.6 * lvl) * (0.6 + 0.4 * sin(p.x * 0.11 + T * 0.4));

    // ── 4. void essence ───────────────────────────────────────────────────
    int moteRows = int(extra.y + 0.5);
    float moteRow0 = float(count) + 1.0;
    for (int r = 0; r < MOTE_ROWS; r++) {
        if (r >= moteRows) break;
        vec4 b0 = texel(MOTE_INDEX + 2.0 * float(r), 0.0);
        vec4 b1 = texel(MOTE_INDEX + 2.0 * float(r) + 1.0, 0.0);
        if (p.x < winPos(b0) * w || p.x > winPos(b1) * w || p.y < b0.b * 1.25 * h || p.y > b1.b * 1.25 * h)
            continue;
        float row = moteRow0 + float(r);
        for (int m = 0; m < MOTES_PER_ROW; m++) {
            vec4 m0 = texel(3.0 * float(m), row);
            if (m0.b <= 0.0) break;                         // empty slot: the row is done
            vec4 m1 = texel(3.0 * float(m) + 1.0, row), m2 = texel(3.0 * float(m) + 2.0, row);
            vec2 c = vec2(winPos(m0) * w, winPos(m1) * h);
            vec2 q = p - c;
            if (dot(q, q) > 2500.0) continue;               // 50 px: nothing to draw here
            float size = m0.b * 255.0 / RADIUS_UNIT;
            vec2 heading = m2.rg * 2.0 - 1.0;               // (vx, vy) × streak
            vec2 tail = -heading * (5.0 + 7.0 * size);
            float t = clamp(dot(q, tail) / max(dot(tail, tail), 1e-4), 0.0, 1.0);
            float d = length(q - tail * t);
            float taper = 1.0 - 0.7 * t;                    // the streak thins behind the mote
            float core = exp(-pow(d / (size * taper), 2.0));
            float halo = exp(-d / (2.5 * size + 2.0)) * 0.35;
            vec3 col = mix(colorB.rgb, mix(colorA.rgb, vec3(1.0), 0.4), core * (1.0 - t));
            acc.rgb += col * (core + halo) * m1.b * (0.8 + 0.5 * motion.w) * (0.5 + 0.5 * extra.w);
        }
    }

    // Valid premultiplied output (rgb <= alpha). Added light used to be written
    // with zero alpha, which blends fine inside Qt, but KWin's color pipeline
    // un-premultiplies every window pixel (rgb / max(a, 0.001)), converts it and
    // multiplies by alpha again, so zero-alpha light comes out as nothing on the
    // real screen (screenshots skip that step and still show it). Raising alpha
    // to the brightest channel is the most additive blend that survives it: on
    // a dark wallpaper it looks the same; on a bright one the light covers a
    // little instead of adding on top.
    acc = min(acc, vec4(1.0));
    acc.a = max(acc.a, max(acc.r, max(acc.g, acc.b)));
    fragColor = acc * qt_Opacity;
}
