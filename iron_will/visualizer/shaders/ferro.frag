#version 440
// Iron Will · ferrofluid mode.
//
// A pool of glossy black magnetic liquid along the edge of the screen; the
// music (via ferro.py) pulls it up into spikes. Runs once per pixel, inside-out:
//
//  1. Surface height S(x): a pool level plus a row of spikes on a jittered
//     lattice. A spike is a cone with concave sides, H·(1 − |d|/w)^k (k from
//     Sharpness), so tips are needle-sharp and bases flare like real
//     ferrofluid. Spikes and pool are joined with a smooth max, so the liquid
//     forms valleys between neighbours instead of hard corners. Small
//     secondary spikes grow between big ones when the field is strong.
//  2. Fake 3D: each spike is shaded as a cone you could walk around. A
//     pixel's position across the cone gives the roundness (normal x/z), the
//     cone's slope at that height gives how much it faces up (normal y). The
//     pool is shaded as a rounded lip that faces up at its edge.
//  3. Studio lighting: what makes black liquid read as *wet* is reflections.
//     The reflected view ray samples two softboxes and a ceiling strip
//     (sharp white highlights), and a fresnel rim light in your colors
//     outlines the silhouette where the surface turns away from you.
//  4. Backlight: a colored glow behind the spikes that flashes on kicks, so
//     black liquid stays readable on a dark wallpaper.
//
// Edges are antialiased from a distance estimate (height difference divided
// by the surface slope), measured in pixels via `res`. Float-only math (the
// GLSL ES 1.00 / 1.20 variants have no integer clamp/min/max; see fire.frag).

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

// Generic GPU-mode uniforms (see qml/Visualizer.qml); what they mean here:
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec4 colsA;        // spike heights 0..3 (bass in the middle)
    vec4 colsB;        // 4..7
    vec4 colsC;        // 8..11
    vec4 colsD;        // 12..15
    vec4 motion;       // x = phase, y = pulse (backlight flash), z = shimmer (cymbals), w = bed (guitar field)
    vec4 look;         // x = spike reach (share of window), y = density, z = up (1) / down (0), w = aspect (w/h)
    vec4 colorA;       // rim light
    vec4 colorB;       // backlight (also the rim on the right-facing side)
    vec4 colorC;       // highlight tint (near white)
    vec4 extra;        // x = surge (kick pull), y = rim + backlight amount, z = gloss
    vec4 res;          // x, y = item size in pixels
    float param;       // sharpness: 0 = soft cones … 1 = needles
};

// ── helpers ────────────────────────────────────────────────────────────────
float hash11(float p) {
    p = fract(p * 0.1031);
    p *= p + 33.33;
    p *= p + p;
    return fract(p);
}

// Smooth maximum: like max(), but blends within k so joins become fillets.
float smax(float a, float b, float k) {
    float h = max(k - abs(a - b), 0.0) / k;
    return max(a, b) + h * h * k * 0.25;
}

// Same hue at full brightness: dimmed color is what turns orange into brown.
vec3 vivid(vec3 c) {
    return c / max(max(c.r, c.g), max(c.b, 1e-3));
}

// ── the music's height profile (same packing as fire.frag) ─────────────────
float column(float i) {
    i = clamp(i, 0.0, 15.0);
    vec4 v = colsD;
    if (i < 3.5) v = colsA;
    else if (i < 7.5) v = colsB;
    else if (i < 11.5) v = colsC;
    float k = i - 4.0 * floor(i / 4.0 + 0.01);
    if (k < 0.5) return v.x;
    if (k < 1.5) return v.y;
    if (k < 2.5) return v.z;
    return v.w;
}

float profile(float u) {                    // smooth interpolation over 16 columns
    float x = clamp(u, 0.0, 1.0) * 15.0;
    float i = floor(x);
    float t = x - i;
    t = t * t * (3.0 - 2.0 * t);
    return mix(column(i), column(i + 1.0), t);
}

// ── geometry (all lengths in window heights; x runs 0 … aspect) ────────────
float gPitch, gReach, gSharp, gAspect, gPhase, gShimmer, gBed, gSurge;

float taper(float x) {                      // the pool thins out at the window's sides (a meniscus)
    float u = x / gAspect;
    return smoothstep(0.0, 0.05, u) * smoothstep(1.0, 0.95, u);
}

float poolLevel(float x) {
    float ripple = (0.004 + 0.006 * gShimmer) * sin(x * 38.0 - gPhase * 5.0)
                 + 0.003 * sin(x * 17.0 + gPhase * 3.1);
    return (gReach * (0.05 + 0.08 * gBed + 0.04 * gSurge) + ripple * gReach) * taper(x);
}

// Spike i of the lattice: returns its height, writes its centre.
float spike(float i, out float c) {
    float r = hash11(i * 7.13 + 1.7);
    c = (i + 0.5) * gPitch
      + gPitch * 0.14 * (r - 0.5)                                         // not a perfect grid
      + gPitch * 0.05 * gShimmer * sin(gPhase * 11.0 + i * 1.7);          // cymbals sway the tips
    float h = gReach * profile(c / gAspect) * (0.82 + 0.36 * hash11(i * 3.31 + 9.2));
    h *= 1.0 + 0.05 * gShimmer * sin(gPhase * 29.0 + i * 2.3);            // and make them quiver
    return h * taper(c);
}

float cone(float d, float w) {              // 1 at the centre → 0 at |d| = w, concave sides
    return pow(max(0.0, 1.0 - abs(d) / w), gSharp);
}

// Surface height at x. `info` = (offset from the dominant spike's centre,
// its height, its half-width, 1 if a spike dominates / 0 for open pool).
float surface(float x, out vec4 info) {
    float base = poolLevel(x);
    float w = 0.60 * gPitch;
    float i0 = floor(x / gPitch);
    float s = base;
    float best = base;
    info = vec4(0.0, 0.0, w, 0.0);
    float kJoin = 0.03 * gReach + 0.002;
    for (int j = -1; j <= 1; j++) {
        float i = i0 + float(j);
        float c, c2;
        float h = spike(i, c);
        float h2 = spike(i + 1.0, c2);
        float d = x - c;
        float val = base + h * cone(d, w);
        if (val > best) { best = val; info = vec4(d, h, w, 1.0); }
        s = smax(s, val, kJoin);
        // A small secondary spike between two big ones once the field is strong.
        float hm = 0.42 * min(h, h2) * smoothstep(0.15, 0.6, gBed + gSurge);
        float dm = x - 0.5 * (c + c2);
        float wm = 0.42 * gPitch;
        float valm = base + hm * cone(dm, wm);
        if (valm > best) { best = valm; info = vec4(dm, hm, wm, 1.0); }
        s = smax(s, valm, kJoin);
    }
    return s;
}

float surfaceOnly(float x) {
    vec4 unused;
    return surface(x, unused);
}

void main() {
    gPhase = motion.x;
    float pulse = motion.y;
    gShimmer = motion.z;
    gBed = motion.w;
    gSurge = extra.x;
    float rimAmt = extra.y, gloss = extra.z;
    gAspect = max(look.w, 0.01);
    gReach = look.x;
    gPitch = mix(0.34, 0.14, look.y);
    gSharp = mix(1.25, 3.2, param);

    vec2 uv = qt_TexCoord0;
    float v = look.z > 0.5 ? 1.0 - uv.y : uv.y;     // 0 at the base, 1 at the far edge
    float x = uv.x * gAspect;
    float px = 1.0 / max(res.y, 1.0);               // one pixel, in window heights

    // Nothing reaches this high: the sky above the liquid only gets backlight.
    float glowReach = gReach * (0.05 + 0.10 * pulse) + 0.006;
    float ceilingTop = gReach * 1.25 + 0.03;
    if (v > ceilingTop + glowReach * 6.0) {
        fragColor = vec4(0.0);
        return;
    }

    // 1 · surface and a distance estimate for antialiasing.
    vec4 info;
    float S = surface(x, info);
    float g = (surfaceOnly(x + px) - surfaceOnly(x - px)) / (2.0 * px);   // slope dS/dx
    float sd = (S - v) / sqrt(1.0 + g * g);         // ≈ distance to the edge (inside > 0)
    float cover = clamp(sd / px + 0.5, 0.0, 1.0);
    float base = poolLevel(x);

    // 2 · normal: a walk-around cone for spikes, a rounded lip for the pool.
    vec3 nPool;
    {
        float q = clamp((S - v) / (0.06 * gReach + 3.0 * px), 0.0, 1.0);   // 0 at the edge → 1 deeper
        nPool = normalize(vec3(-g * (1.0 - q), 1.0 - q, 0.25 + q));
    }
    vec3 n = nPool;
    if (info.w > 0.5 && info.y > 1e-4) {
        float t = clamp((v - base) / info.y, 0.0, 1.0);                 // how far up the spike
        float r = info.z * (1.0 - pow(max(t, 1e-4), 1.0 / gSharp));    // cone radius at this height
        float a = clamp(info.x / max(r, px), -1.0, 1.0);                // across the cone: -1 … 1
        float up = info.z / (gSharp * info.y) * pow(max(t, 1e-3), 1.0 / gSharp - 1.0);
        vec3 nSpike = normalize(vec3(a, min(up, 3.0), sqrt(max(0.0, 1.0 - a * a))));
        n = normalize(mix(nPool, nSpike, smoothstep(0.0, 0.03 * gReach + px, v - base)));
    }

    // 3 · studio lighting on black liquid.
    vec3 R = reflect(vec3(0.0, 0.0, -1.0), n);      // the view ray, bounced off the surface
    // Small, far-away lights give thin, razor-sharp highlights: broad ones
    // turn the liquid into polished chrome instead of wet black ink.
    float key = smoothstep(0.955, 0.993, dot(R, normalize(vec3(-0.45, 0.70, 0.55))));
    float key2 = 0.5 * smoothstep(0.970, 0.996, dot(R, normalize(vec3(0.55, 0.55, 0.62))));
    float strip = 0.06 * smoothstep(0.88, 0.99, R.y);                   // faint ceiling light
    float fres = pow(1.0 - clamp(n.z, 0.0, 1.0), 3.0);                  // grazing edges
    vec3 rimCol = mix(colorA.rgb, colorB.rgb, 0.5 + 0.5 * n.x);
    vec3 liquid = vec3(0.010, 0.011, 0.016)                              // ferrofluid: nearly pure black
                + gloss * (colorC.rgb * (1.1 * key + key2) + vec3(strip))
                + rimCol * fres * rimAmt * (0.55 + 0.45 * pulse) * 1.2;

    // 4 · backlight glow above the surface (pure added light). Measured from
    // a smooth envelope over the spike crowns, not the jagged surface itself,
    // which would throw a vertical beam above every spike.
    // Kept tight and saturated: a wide, dim orange wash over a dark wallpaper
    // reads as brown. It blooms out on kicks instead.
    float crown = base + 0.75 * gReach * profile(uv.x) * taper(x);
    float above = max(v - crown, 0.0);
    float glow = exp(-above / glowReach) * rimAmt * (0.06 + 0.70 * pulse * pulse);
    glow *= smoothstep(1.0, 0.80, v) * smoothstep(0.0, 0.05, uv.x) * smoothstep(1.0, 0.95, uv.x);
    vec3 glowCol = vivid(colorB.rgb) * glow;

    // Premultiplied: the liquid is opaque; the glow only adds light.
    vec3 rgb = liquid * cover + glowCol * (1.0 - cover);
    // Valid premultiplied output (rgb <= alpha). Added light used to be written
    // with zero alpha, which blends fine inside Qt, but KWin's color pipeline
    // un-premultiplies every window pixel (rgb / max(a, 0.001)), converts it and
    // multiplies by alpha again, so zero-alpha light comes out as nothing on the
    // real screen (screenshots skip that step and still show it). Raising alpha
    // to the brightest channel is the most additive blend that survives it: on
    // a dark wallpaper it looks the same; on a bright one the light covers a
    // little instead of adding on top.
    rgb = min(rgb, vec3(1.0));
    fragColor = vec4(rgb, max(cover, max(rgb.r, max(rgb.g, rgb.b)))) * qt_Opacity;
}
