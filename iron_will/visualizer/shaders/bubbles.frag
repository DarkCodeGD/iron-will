#version 440
// Iron Will · bubbles mode.
//
// Soap bubbles drifting up from the base. The bubbles themselves (where they
// are, how big, when they pop) are simulated in bubbles.py and arrive as up
// to 24 particle slots p0…p23; this shader only draws them. Per pixel:
//
//  1. Each bubble is a fake 3D sphere: a pixel's offset from the centre gives
//     the surface normal, so the film is seen face-on in the middle (clear)
//     and edge-on at the rim (bright). That fresnel falloff is what makes a
//     bubble read as a bubble instead of a disc.
//  2. Soap-film iridescence: the swirling rainbow on a real bubble is
//     thin-film interference, and its color depends on the film's thickness.
//     Thickness here = slow swirling noise + drainage (soap runs down, so the
//     bottom is thicker) + a longer light path toward the rim. Thickness →
//     color through a cosine rainbow (or pastels, or your two colors).
//  3. The cute part: a cartoon "window" shine and a little dot up top-left,
//     a crescent reflection lower right.
//  4. Pops: the film tears into arcs and retracts, droplets spray outward,
//     and a sparkle (or a heart) twinkles where the bubble was.
//  5. Fizz: tiny procedural background bubbles, no simulation needed.
//
// Premultiplied output: bubbles are mostly see-through (low alpha, light
// added), only the shine and the pop shapes are near-solid. Float-only math
// (the GLSL ES 1.00 / 1.20 variants have no integer clamp/min/max; see
// fire.frag).

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

// Generic GPU-mode uniforms (see qml/Visualizer.qml); what they mean here:
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec4 motion;       // x = phase (speeds up with the music), y = jiggle (signed squish), z = fizz, w = energy
    vec4 look;         // z = up (1) / down (0), w = aspect (w/h)
    vec4 colorA;       // "colors" palette: first gradient color
    vec4 colorB;       //                   last gradient color
    vec4 colorC;       // hearts
    vec4 extra;        // x = sheen, y = pop shape (0 sparkles, 1 hearts), z = fizz setting, w = live slots
    vec4 res;          // x, y = item size in pixels
    float param;       // palette: 0 iridescent, 1 pastel, 2 your colors
    // Particle slots: (x / width, distance from base / height, radius / height, state).
    // state < 1: alive (value = seed); 1 + t: popping, t = 0 … 1. Radius 0 = empty slot.
    vec4 p0;  vec4 p1;  vec4 p2;  vec4 p3;  vec4 p4;  vec4 p5;
    vec4 p6;  vec4 p7;  vec4 p8;  vec4 p9;  vec4 p10; vec4 p11;
    vec4 p12; vec4 p13; vec4 p14; vec4 p15; vec4 p16; vec4 p17;
    vec4 p18; vec4 p19; vec4 p20; vec4 p21; vec4 p22; vec4 p23;
};

// ── helpers ────────────────────────────────────────────────────────────────
float hash11(float p) {
    p = fract(p * 0.1031);
    p *= p + 33.33;
    p *= p + p;
    return fract(p);
}

float hash21(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

float noise(vec2 p) {                       // value noise, smooth
    vec2 i = floor(p);
    vec2 f = p - i;
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash21(i), hash21(i + vec2(1.0, 0.0)), f.x),
               mix(hash21(i + vec2(0.0, 1.0)), hash21(i + vec2(1.0, 1.0)), f.x), f.y);
}

float fbm(vec2 p) {                         // three octaves: enough for a film swirl
    float s = 0.5 * noise(p);
    p = mat2(1.6, 1.2, -1.2, 1.6) * p;
    s += 0.25 * noise(p);
    p = mat2(1.6, 1.2, -1.2, 1.6) * p;
    s += 0.125 * noise(p);
    return s / 0.875;
}

vec2 rot(vec2 p, float a) {
    float c = cos(a), s = sin(a);
    return vec2(c * p.x - s * p.y, s * p.x + c * p.y);
}

// Same hue at full brightness: dimmed orange is what reads as brown.
vec3 vivid(vec3 c) {
    return c / max(max(c.r, c.g), max(c.b, 1e-3));
}

// 0 inside → 1 outside over a soft edge of width w (always edge0 < edge1).
float outside(float d, float w) {
    return smoothstep(-w, w, d);
}

// Signed distance to a heart (Inigo Quilez): y from 0 (tip) to ~1, x ±0.5.
float sdHeart(vec2 p) {
    p.x = abs(p.x);
    if (p.y + p.x > 1.0) {
        vec2 a = p - vec2(0.25, 0.75);
        return sqrt(dot(a, a)) - 0.35355339;
    }
    vec2 a = p - vec2(0.0, 1.0);
    vec2 b = p - 0.5 * max(p.x + p.y, 0.0);
    return sqrt(min(dot(a, a), dot(b, b))) * sign(p.x - p.y);
}

// ── shared state ───────────────────────────────────────────────────────────
float gAspect, gUp, gPhase, gJiggle, gSheen, gPx, gPalette;

// Film thickness → color. Iridescent: the soap-film rainbow (magenta, gold,
// green, blue bands). Pastel: the same bands, washed soft. Colors: between
// your two gradient colors, kept vivid.
vec3 filmColor(float t) {
    if (gPalette > 1.5) {
        return mix(vivid(colorA.rgb), vivid(colorB.rgb), 0.5 + 0.5 * sin(t * 6.2831853));
    }
    vec3 rainbow = 0.5 + 0.5 * cos(6.2831853 * (t + vec3(0.0, 0.33, 0.67)));
    if (gPalette > 0.5) {
        return 0.74 + 0.26 * cos(6.2831853 * (0.8 * t + vec3(0.0, 0.30, 0.62)));
    }
    return rainbow;
}

// Premultiplied "over": a on top of acc.
void over(inout vec4 acc, vec3 rgb, float a) {
    acc.rgb = rgb + acc.rgb * (1.0 - a);
    acc.a = a + acc.a * (1.0 - a);
}

// A bubble popping: t = 0 … 1. d = pixel offset from its centre (window heights).
void popping(vec2 d, float r, float seed, float t, inout vec4 acc) {
    float fade = 1.0 - t;
    float dist = length(d);
    vec3 film = mix(filmColor(seed * 3.0 + 0.2), vec3(1.0), 0.45);

    // The film tears into arcs and snaps outward.
    float R = r * (1.0 + 0.30 * t);
    float w = max(gPx * 1.2, r * 0.05 * fade);
    float ring = 1.0 - smoothstep(0.0, w + gPx, abs(dist - R));
    float arcs = 0.5 + 0.5 * sin(atan(d.y, d.x) * 7.0 + seed * 40.0);
    ring *= smoothstep(0.9 * t, 0.9 * t + 0.25, arcs) * fade * fade;

    // Droplets spray out and fall a little.
    float drops = 0.0;
    for (int k = 0; k < 8; k++) {
        float fk = float(k);
        float ang = fk * 0.7853982 + seed * 6.2831853 + 0.3 * sin(fk * 3.7 + seed * 9.0);
        float reach = r * (0.9 + 1.1 * t * (0.8 + 0.4 * hash11(fk * 7.7 + seed * 31.0)));
        vec2 pos = vec2(cos(ang), sin(ang)) * reach - vec2(0.0, 0.35 * r * t * t);
        float rk = max(gPx * 1.1, r * 0.07 * fade);
        drops += 1.0 - smoothstep(rk * 0.5, rk + gPx, length(d - pos));
    }
    drops = min(drops, 1.0) * fade;
    over(acc, film * (ring + drops), 0.5 * (ring + drops));

    // A twinkle where the bubble was: a sparkle or a heart.
    float b = sin(3.14159 * min(1.0, t * 1.25));          // in and out
    float scale = r * (0.45 + 0.65 * t);
    vec2 lp = d / scale;
    if (extra.y > 0.5) {
        float sd = sdHeart(lp * 1.15 + vec2(0.0, 0.55));
        float aa = gPx / scale;
        float fill = 1.0 - outside(sd, aa);
        float glow = exp(-max(sd, 0.0) * 9.0) * 0.35;
        vec3 pink = vivid(colorC.rgb);
        over(acc, pink * (fill + glow) * b, fill * 0.92 * b);
        // a tiny shine on the heart's left lobe
        float shine = 1.0 - smoothstep(0.05, 0.12, length(lp - vec2(-0.22, 0.20)));
        over(acc, vec3(1.0) * shine * fill * b, shine * fill * b * 0.9);
    } else {
        vec2 s2 = rot(lp, 0.785398);
        float star = exp(-abs(lp.x) * 16.0) * max(0.0, 1.0 - abs(lp.y))
                   + exp(-abs(lp.y) * 16.0) * max(0.0, 1.0 - abs(lp.x))
                   + 0.5 * (exp(-abs(s2.x) * 22.0) * max(0.0, 1.0 - 1.8 * abs(s2.y))
                          + exp(-abs(s2.y) * 22.0) * max(0.0, 1.0 - 1.8 * abs(s2.x)))
                   + exp(-dot(lp, lp) * 40.0);
        star = min(star, 1.4) * b;
        vec3 col = mix(vec3(1.0), film, 0.35);
        over(acc, col * star, min(1.0, star) * 0.6);
    }
}

// One particle slot. s = pixel in window heights (x 0 … aspect, y up the screen).
void bubble(vec4 P, vec2 s, inout vec4 acc) {
    float r = P.z;
    if (r <= 0.0) return;
    vec2 c = vec2(P.x * gAspect, gUp > 0.5 ? P.y : 1.0 - P.y);
    vec2 d = s - c;
    float reach = 2.5 * r + 3.0 * gPx;                     // pops: droplets fly ~2.3 r, plus their own size
    if (dot(d, d) > reach * reach) return;
    if (P.w >= 1.0) {
        popping(d, r, fract(P.x * 13.7 + P.z * 71.0), P.w - 1.0, acc);
        return;
    }
    float seed = P.w;

    // Jelly squish: kicks stretch every bubble wide and short, then it wobbles
    // back; each bubble also ripples on its own a little.
    float j = clamp(gJiggle * (0.7 + 0.6 * seed), -1.0, 1.0) * 0.16;
    vec2 q = d / r;
    q = vec2(q.x / (1.0 + j), q.y * (1.0 + j));
    float ang = atan(q.y, q.x);
    float wob = 1.0 + 0.035 * sin(3.0 * ang + gPhase * 4.0 + seed * 30.0)
                    + 0.025 * sin(2.0 * ang - gPhase * 3.1 + seed * 11.0);
    float rr = length(q) / wob;
    float aa = gPx / r;
    float cover = 1.0 - outside(rr - 1.0, aa);
    if (cover <= 0.0) return;

    // 1 · fake sphere: face-on in the middle, edge-on at the rim.
    float z = sqrt(max(0.0, 1.0 - rr * rr));
    float fres = pow(1.0 - z, 2.5);
    float rimLine = smoothstep(1.0 - 3.0 * aa - 0.05, 1.0 - aa, rr);   // crisp outline

    // 2 · soap film: swirl + drainage + longer path at the rim.
    vec2 fq = rot(q, gPhase * 0.25 + seed * 6.0) * 1.8 + seed * 13.0;
    float thick = 0.30 + 0.55 * fbm(fq + vec2(0.0, gPhase * 0.18)) + 0.30 * (-q.y);
    vec3 film = filmColor(thick * (1.0 + 0.8 * (1.0 - z)) + seed);
    float sheen = gSheen;
    // Your-colors film keeps its color at the rim only: a dim orange wash
    // across the middle reads as brown on a dark wallpaper.
    float body = gPalette > 1.5 ? 0.02 : 0.16;
    vec3 rgb = film * sheen * (body + 1.15 * fres)
             + vec3(0.55, 0.60, 0.70) * (1.0 - 0.6 * sheen) * fres        // clear glass when sheen is low
             + mix(vec3(1.0), film, 0.75 * sheen) * rimLine * 0.50;
    float a = 0.03 + 0.30 * fres + 0.30 * rimLine;

    // 3 · the cute shine: a soft window up top-left, a dot beside it, a
    // crescent lower right.
    vec2 hq = rot(q - vec2(-0.36, 0.40), 0.70);
    // Edge softness never narrower than ~1.5 px (aa is one pixel in bubble
    // units): on a tiny bubble a sharp sub-pixel shine shimmers and crawls.
    float winSoft = min(1.0, max(0.45, 1.5 * aa / 0.13));
    float win = 1.0 - smoothstep(1.0 - winSoft, 1.0, length(hq / vec2(0.27, 0.13)));
    win *= mix(0.6, 1.0, smoothstep(0.5, 1.5, 0.13 / aa));            // dimmer once it's a blur
    float dotSoft = min(1.0, max(0.45, 1.5 * aa / 0.075));
    float dotHl = 1.0 - smoothstep(1.0 - dotSoft, 1.0, length(q - vec2(-0.02, 0.64)) / 0.075);
    dotHl *= smoothstep(0.6, 1.4, 0.075 / aa);                         // gone below ~1 px
    float side = dot(q / max(rr, 1e-3), vec2(0.7071, -0.7071));
    float cres = smoothstep(0.68, 0.82, rr) * (1.0 - smoothstep(0.86, 0.94, rr)) * smoothstep(0.35, 0.95, side) * 0.45;
    float hl = 0.92 * win + 0.95 * dotHl + cres;
    rgb += vec3(hl);
    a += 0.80 * hl;

    over(acc, rgb * cover, min(a, 1.0) * cover);
}

// Tiny background bubbles, in pixels (so they look the same on a 150 px strip
// and a full screen): a grid of cells that scrolls up the screen, one fizz
// bubble per cell at a hashed spot. Each column scrolls at its own speed. A
// bubble sways and its ring can poke into the cells around it, so every pixel
// checks its own cell and all eight neighbours; otherwise the ring gets sliced
// flat at the cell borders. x, v = pixel position in px (v from the base).
void fizzCell(vec2 cell, float layer, float x, float vs, vec2 size, float amount,
              inout float fill, inout float ring) {
    float h1 = hash21(cell + layer * 37.0);
    if (h1 > amount) return;
    float h2 = hash21(cell * 1.7 + layer * 11.0 + 3.1);
    float h3 = hash21(cell * 2.3 + layer * 5.0 + 7.7);
    float cx = (cell.x + 0.25 + 0.5 * h2) * size.x
             + 0.22 * size.x * sin(gPhase * (1.0 + h3) + h1 * 30.0);
    float cy = (cell.y + 0.2 + 0.6 * h3) * size.y;
    float rr = mix(1.2, 3.2, hash21(cell * 3.9 + layer)) * (layer > 0.5 ? 0.75 : 1.0);
    float dist = length(vec2(x - cx, vs - cy));
    ring = max(ring, 1.0 - smoothstep(0.0, 1.3, abs(dist - rr)));
    fill = max(fill, 1.0 - smoothstep(rr - 1.0, rr, dist));
}

float fizzLayer(float x, float v, vec2 size, float layer, float amount, out float ringOut) {
    float col = floor(x / size.x);
    float fill = 0.0;
    ringOut = 0.0;
    for (int i = -1; i <= 1; i++) {
        float c = col + float(i);
        // Each column rises at its own speed (px/s at phase rate): the scroll
        // is per column, so the grid never tears vertically.
        float speed = mix(28.0, 75.0, hash11(c * 5.11 + layer * 17.3));
        float vs = v - gPhase * speed;                  // scrolled: the bubbles rise
        float row = floor(vs / size.y);
        for (int j = -1; j <= 1; j++) {
            fizzCell(vec2(c, row + float(j)), layer, x, vs, size, amount, fill, ringOut);
        }
    }
    return fill;
}

void main() {
    gAspect = max(look.w, 0.01);
    gUp = look.z;
    gPhase = motion.x;
    gJiggle = motion.y;
    gSheen = extra.x;
    gPalette = param;
    gPx = 1.0 / max(res.y, 1.0);

    vec2 uv = qt_TexCoord0;
    vec2 s = vec2(uv.x * gAspect, 1.0 - uv.y);          // y up the screen
    float v = gUp > 0.5 ? 1.0 - uv.y : uv.y;            // distance from the base

    vec4 acc = vec4(0.0);

    // 5 · fizz first, so the real bubbles drift in front of it. It thins out
    // over the last quarter of the window (float-only px math via gPx).
    float fizzAmt = extra.z * (0.25 + 0.75 * motion.z);
    if (fizzAmt > 0.01) {
        float xp = s.x / gPx, vp = v / gPx;             // pixel position
        float ring1, ring2;
        float f1 = fizzLayer(xp, vp, vec2(34.0, 70.0), 0.0, fizzAmt * 0.7, ring1);
        float f2 = fizzLayer(xp + 9.0, vp, vec2(22.0, 48.0), 1.0, fizzAmt * 0.5, ring2);
        float fade = 1.0 - smoothstep(0.75, 1.0, v);
        float ring = max(ring1, ring2 * 0.8) * fade;
        float fill = max(f1, f2) * fade;
        vec3 tint = filmColor(0.3 + uv.x * 2.0 + gPhase * 0.05);
        over(acc, mix(vec3(1.0), tint, 0.4) * (0.75 * ring + 0.10 * fill), 0.30 * ring + 0.05 * fill);
    }

    bubble(p0, s, acc);  bubble(p1, s, acc);  bubble(p2, s, acc);  bubble(p3, s, acc);
    bubble(p4, s, acc);  bubble(p5, s, acc);  bubble(p6, s, acc);  bubble(p7, s, acc);
    bubble(p8, s, acc);  bubble(p9, s, acc);  bubble(p10, s, acc); bubble(p11, s, acc);
    bubble(p12, s, acc); bubble(p13, s, acc); bubble(p14, s, acc); bubble(p15, s, acc);
    bubble(p16, s, acc); bubble(p17, s, acc); bubble(p18, s, acc); bubble(p19, s, acc);
    bubble(p20, s, acc); bubble(p21, s, acc); bubble(p22, s, acc); bubble(p23, s, acc);

    fragColor = acc * qt_Opacity;
}
