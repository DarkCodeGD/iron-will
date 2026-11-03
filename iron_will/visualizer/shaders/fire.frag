#version 440
// Iron Will · fire mode.
//
// Runs once per pixel on the GPU. The idea, inside-out:
//
//  1. A height profile H(x): 16 column heights from the music, interpolated
//     smoothly across the width, scaled by the flame bed + ignition flare.
//  2. Rising turbulence: fractal noise scrolled upward by `phase` and warped
//     by a second noise layer, so flames twist instead of sliding.
//  3. A "fuel" field: 1 at the base, 0 at the flame top, eaten away by the
//     turbulence — stronger the higher you go, which splits the top into
//     flickering tongues while the base stays solid.
//  4. Temperature: fuel → tip color → body color → hot → white-hot core.
//     Each ignition's heat flash pushes the whole ramp hotter.
//  5. Glow: an aura of light thrown onto the wallpaper, plus core bloom.
//  6. Sparks: a grid of cells drifting upward; a few cells (more on cymbal
//     hits and flare-ups) hold a tiny glowing ember that cools as it rises.
//  7. Blending like real fire: emission + absorption (see the end).
//
// Motion comes from a combustion model on the CPU (fire.py): hits add fuel,
// heat flashes first, the flare (height) follows on a spring, and a heat
// front rises through the flames. The shader just renders that state.

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec4 colsA;        // column heights 0..3
    vec4 colsB;        // 4..7
    vec4 colsC;        // 8..11
    vec4 colsD;        // 12..15
    vec4 motion;       // x = phase, y = heat (brightness flash), z = sparks, w = bed (guitars)
    vec4 look;         // x = max height share, y = spark amount, z = up (1) / down (0), w = aspect (w/h)
    vec4 tipColor;     // coolest visible flame (tongue tips)
    vec4 midColor;
    vec4 bodyColor;    // hottest user color, near the base
    vec4 ignite;       // x = flare (extra height), y = heat-front height, z = front strength, w = glow amount
    float translucency; // 0 = solid stylized flames … 1 = ghostly, see-through
};

// ── noise ──────────────────────────────────────────────────────────────────
float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

vec2 hash22(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973));
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.xx + p3.yz) * p3.zy);
}

float vnoise(vec2 p) {                      // smooth value noise, 0..1
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    float a = hash12(i), b = hash12(i + vec2(1, 0));
    float c = hash12(i + vec2(0, 1)), d = hash12(i + vec2(1, 1));
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

float fbm(vec2 p) {                         // 4 octaves of turbulence
    float s = 0.0, amp = 0.5;
    for (int i = 0; i < 4; i++) {
        s += amp * vnoise(p);
        p = p * 2.03 + vec2(17.1, 9.2);
        amp *= 0.5;
    }
    return s;                               // ~0..0.94
}

// ── the music's height profile ─────────────────────────────────────────────
// Float-only on purpose: qsb also emits GLSL ES 1.00 and GLSL 1.20 variants,
// and neither has integer clamp()/min()/max(). An int version worked in one
// GL context and drew *nothing* in another (Qt only logs that under a
// filtered category), so keep the shader in plain float math.
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

// ── temperature → color ────────────────────────────────────────────────────
vec3 ramp(float t, float heat) {
    // Hot stays saturated gold: mixing orange toward cream/grey is exactly
    // what turns fire beige or brown, so we only push it toward yellow.
    // Lighten toward gold, scaled by the headroom each channel has left:
    // orange → amber, blue → ice blue (a custom gradient keeps its hue family).
    vec3 hot = bodyColor.rgb + (1.0 - bodyColor.rgb) * vec3(0.45, 0.42, 0.12);
    vec3 core = vec3(1.0, 0.96, 0.82);
    vec3 c = mix(tipColor.rgb, midColor.rgb, smoothstep(0.0, 0.30, t));
    c = mix(c, bodyColor.rgb, smoothstep(0.25, 0.55, t));
    c = mix(c, hot, smoothstep(0.62, 0.88, t));
    c = mix(c, core, smoothstep(0.90, 1.0, t) * heat);   // white-hot only in the flash
    return c;
}

void main() {
    float phase = motion.x, heat = motion.y, burst = motion.z, bed = motion.w;
    float flare = ignite.x, front = ignite.y, frontHeat = ignite.z, glowAmt = ignite.w;
    float aspect = max(look.w, 0.01);

    vec2 uv = qt_TexCoord0;
    float v = look.z > 0.5 ? 1.0 - uv.y : uv.y;     // 0 at the base, 1 at the far edge
    float x = uv.x * aspect;                         // square noise cells whatever the size

    // 1 · height: pilot flame + guitar bed + this column's music + the ignition flare.
    float music = profile(uv.x);
    float h = look.x * clamp(0.07 + 0.45 * bed * (0.5 + 0.5 * music) + 0.33 * music + 0.40 * flare, 0.0, 1.0);
    h = max(h, 0.02);

    // 2 · rising, self-warping turbulence.
    // Stretched tall (x squeezed, y relaxed) so the noise forms tongues, not clouds.
    vec2 q = vec2(x * 3.4, v * 1.35 - phase * 1.5);
    vec2 warp = vec2(fbm(q * 0.7 + vec2(0.0, phase * 0.3)), fbm(q * 0.7 + vec2(5.2, 1.3)));
    float n = fbm(q + (warp - 0.5) * vec2(1.1, 0.6));

    // 3 · fuel: solid near the base, torn into tongues near the top.
    float rel = v / h;                               // 0 base → 1 nominal flame top
    float fuel = 1.0 - rel;
    fuel += (n - 0.47) * (0.25 + 1.55 * rel);
    fuel -= smoothstep(0.0, 1.0, abs(uv.x - 0.5) * 2.0 - 0.96) * 0.6;   // soft side edges
    // The heat front: a band of extra heat rising through the flames after an
    // ignition. Tongues stretch as it passes, then it fades near the top.
    float wave = frontHeat * exp(-pow((rel - front) / 0.22, 2.0));
    fuel += 0.30 * wave * (0.6 + 0.8 * n);
    // Feathered edge: wider when translucent, so tongues dissolve into the wallpaper.
    float flame = smoothstep(0.0, mix(0.18, 0.34, translucency), fuel);

    // 4 · temperature: hotter near the base, flashes on every ignition.
    // The turbulence feeds the temperature too, so color follows the tongues
    // instead of lying in flat horizontal stripes.
    // The heat flash is added *through the turbulence* (patchy, licking),
    // not as a flat multiplier, which blew the whole base out to white.
    float temp = clamp(fuel * (0.72 + 0.10 * bed) + (n - 0.47) * 0.45 + 0.25 * wave
                       + heat * 0.30 * (n - 0.25) * smoothstep(0.0, 0.4, fuel), 0.0, 1.0);
    vec3 col = ramp(temp, heat);

    // A tight halo just past the flame edge.
    float halo = exp(-max(-fuel, 0.0) * 9.0) * (1.0 - flame) * (0.16 + 0.40 * heat) * smoothstep(1.6, 0.4, rel);

    // 5 · glow. The aura is the light the fire throws onto the wallpaper:
    // full strength in the gaps between tongues, falling off with distance
    // above the flame line, reaching higher and brighter as the fire heats
    // up. It slowly flickers, like firelight on a wall. Near the flames it is
    // the flame's own color; far out it shifts to the tip color, so a faint
    // glow reads as wine-red instead of murky brown.
    float above = max(v - h, 0.0);
    float reach = 0.10 + 0.28 * glowAmt + 0.12 * heat;
    float flick = 0.82 + 0.18 * vnoise(vec2(x * 0.9, phase * 2.2));
    float aura = exp(-above / reach) * (0.30 + 0.70 * heat) * (0.4 + 0.6 * smoothstep(0.0, 0.5, music + bed * 0.5)) * flick;
    aura *= glowAmt * 0.55 * (1.0 - flame * 0.6);
    // Fade out before the window's far edge and sides: light that reaches the
    // border would show the window as a hard rectangle on the desktop.
    aura *= smoothstep(1.0, 0.70, v) * smoothstep(0.0, 0.06, uv.x) * smoothstep(1.0, 0.94, uv.x);
    vec3 auraCol = mix(mix(bodyColor.rgb, midColor.rgb, 0.5), tipColor.rgb, smoothstep(0.0, 0.6, above / reach));

    // 6 · sparks drifting up, cooling as they rise.
    float sparkA = 0.0;
    if (look.y > 0.001) {
        vec2 grid = vec2(x * 7.0, v * 5.0 - phase * 2.6);
        vec2 cell = floor(grid);
        vec2 rnd = hash22(cell);
        float chance = look.y * (0.04 + 0.10 * bed + 0.50 * burst);
        if (rnd.x < chance) {
            vec2 pos = 0.3 + 0.4 * hash22(cell + 7.7);
            pos.x += 0.12 * sin(phase * 5.0 + rnd.y * 40.0);             // a little sway
            vec2 dv = (fract(grid) - pos) * vec2(1.0, 0.75);
            float d = length(dv);
            // Born inside the flames, cooling out over a short climb above them.
            float life = 1.0 - smoothstep(h * 0.6, h + 0.25 + 0.2 * burst, v);
            float flicker = 0.7 + 0.3 * sin(phase * 25.0 + rnd.y * 60.0);
            sparkA = (smoothstep(0.07, 0.0, d) + 0.35 * smoothstep(0.2, 0.0, d)) * life * flicker;
            sparkA = min(sparkA, 1.0);
        }
    }
    vec3 sparkCol = mix(bodyColor.rgb, vec3(1.0, 0.93, 0.75), 0.6);

    // 7 · Blending like real fire.
    //
    // Fire is a light source, not paint: it *emits* light and only partly
    // *absorbs* what's behind it. With premultiplied alpha the compositor does
    //     result = rgb + wallpaper * (1 - a)
    // so we can set the two independently:
    //   emission (rgb) — the flame's own light. Added, never averaged with the
    //                    wallpaper, so colors stay luminous over anything.
    //                    Cooler tips glow a little dimmer than the core.
    //   absorption (a) — how much of the wallpaper the flame hides. Tied to
    //                    temperature: thin cool tips are see-through wisps,
    //                    the white-hot core is nearly solid.
    // translucency = 0 gives back solid, sticker-like stylized flames.
    float hotness = smoothstep(0.10, 0.90, temp);
    // Cool parts break into fast, fine streaks (wisps) instead of an even
    // tint: an even translucent red reads as tinted glass, not fire.
    float wisp = smoothstep(0.30, 0.80, vnoise(vec2(x * 11.0, v * 3.0 - phase * 3.2)));
    float wispy = (1.0 - hotness) * translucency;
    float cover = mix(mix(1.0, 0.06, translucency), mix(1.0, 0.78, translucency), hotness);
    cover *= mix(1.0, 0.35 + 0.65 * wisp, wispy);
    float glow = mix(mix(1.0, 0.70, translucency), 1.0, hotness) * mix(1.0, 0.45 + 0.55 * wisp, wispy);
    vec3 rgb = col * flame * glow;
    float a = flame * cover;

    // Core bloom: overdrive the hottest flame so it burns toward white.
    float peak = hotness * hotness * hotness * hotness;   // only the very hottest spots
    rgb += col * flame * peak * glowAmt * (0.10 + 0.18 * heat);

    // Halo and sparks are pure additive light (zero alpha): they can only
    // brighten the wallpaper. Blending faint orange the normal way mixes it
    // into muddy brown around every tongue. The halo uses the tip color
    // (crimson in the Ascend palette): faded crimson reads as wine.
    rgb += tipColor.rgb * halo;
    rgb += auraCol * aura;
    rgb += sparkCol * sparkA * (1.0 - flame * 0.7);

    fragColor = vec4(rgb, a) * qt_Opacity;
}
