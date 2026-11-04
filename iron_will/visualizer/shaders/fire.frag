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
//  6. Embers: two layers of drifting grid cells (near = big and fast,
//     far = small and slow, for depth). Cymbal hits and ignitions light up
//     more cells; each ember is a streak that sways, twinkles and cools from
//     white-gold to the tip color as it climbs well above the flames.
//  7. Blending like real fire: emission + absorption (see the end).
//
// Fire space: everything is measured in units of the flame's reach, not the
// window, so a tall (even full-screen) window gives the fire headroom instead
// of zooming it. `look.x` is the reach as a share of the window; at the
// default 0.9 fire space equals window space.
//
// Motion comes from a combustion model on the CPU (fire.py): hits add fuel,
// heat flashes first, the flare (height) follows on a spring, and a heat
// front rises through the flames. The shader just renders that state.

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

// Generic GPU-mode uniforms (see qml/Visualizer.qml); what they mean for fire:
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec4 colsA;        // column heights 0..3
    vec4 colsB;        // 4..7
    vec4 colsC;        // 8..11
    vec4 colsD;        // 12..15
    vec4 motion;       // x = phase, y = heat (brightness flash), z = sparks, w = bed (guitars)
    vec4 look;         // x = flame reach (share of window), y = spark amount, z = up (1) / down (0), w = aspect (w/h)
    vec4 colorA;       // body: hottest user color, near the base
    vec4 colorB;       // mid
    vec4 colorC;       // tip: coolest visible flame (tongue tips)
    vec4 extra;        // x = flare (extra height), y = heat-front height, z = front strength, w = glow amount
    float param;       // translucency: 0 = solid stylized flames … 1 = ghostly, see-through
};
// Readable names for the generic slots.
#define bodyColor colorA
#define midColor colorB
#define tipColor colorC
#define ignite extra
#define translucency param

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

// ── embers ─────────────────────────────────────────────────────────────────
// One layer of rising embers. The plane is cut into cells scrolling upward;
// each grid column rises at its own speed, and a cell holds an ember when its
// random roll is under `density`. Embers fade in over a small band of rolls
// instead of popping when the density changes.
// Returns (core, bloom, center): the solid speck, its soft glow and its
// white-hot center, kept apart so the core can also cover the wallpaper
// (see the composite).
// The ember sits in the middle 40 % of its cell and its bloom stops short of
// the cell's edge, so no ember is ever clipped into a square.
//   p      fire-space position      scale  cells per fire unit
//   rise   upward speed             size   ember core radius (cell units)
vec3 emberLayer(vec2 p, float phase, float density, float scale, float rise, float size, float seed) {
    vec2 g = p * vec2(scale, scale * 0.6);
    float colId = floor(g.x);
    g.y -= phase * rise * scale * (0.65 + 0.7 * hash12(vec2(colId, seed)));
    vec2 cell = floor(g);
    vec2 rnd = hash22(cell + seed);
    float on = clamp((density - rnd.x) / 0.04, 0.0, 1.0);
    if (on <= 0.0) return vec3(0.0);
    vec2 pos = vec2(0.32, 0.35) + vec2(0.36, 0.30) * hash22(cell + seed + 7.7);
    pos.x += 0.08 * sin(phase * 4.0 + rnd.y * 40.0);         // sway in the updraft
    vec2 d = fract(g) - pos;
    d.y *= 0.75;                                               // a little stretched: a motion streak
    float r = length(d);
    float twinkle = (0.75 + 0.25 * sin(phase * 23.0 + rnd.y * 70.0)) * on;
    return vec3(smoothstep(size, size * 0.35, r), smoothstep(size * 1.9, 0.0, r),
                smoothstep(size * 0.55, 0.0, r)) * twinkle;
}

void main() {
    float phase = motion.x, heat = motion.y, burst = motion.z, bed = motion.w;
    float flare = ignite.x, front = ignite.y, frontHeat = ignite.z, glowAmt = ignite.w;
    float aspect = max(look.w, 0.01);

    vec2 uv = qt_TexCoord0;
    float vw = look.z > 0.5 ? 1.0 - uv.y : uv.y;    // window space: 0 at the base, 1 at the far edge
    float fs = 0.9 / max(look.x, 0.05);              // window → fire space
    float v = vw * fs;
    float x = uv.x * aspect * fs;                    // square noise cells whatever the size

    // 1 · height: pilot flame + guitar bed + this column's music + the ignition flare.
    float music = profile(uv.x);
    float h = 0.9 * clamp(0.07 + 0.45 * bed * (0.5 + 0.5 * music) + 0.33 * music + 0.40 * flare, 0.0, 1.0);
    h = max(h, 0.02);
    float rel = v / h;                               // 0 base → 1 nominal flame top

    // 2 · rising, self-warping turbulence. Skipped far above the flames (no
    // tongue reaches past rel 2.2), which keeps a full-screen window cheap:
    // the sky above the fire only pays for glow and embers.
    // Stretched tall (x squeezed, y relaxed) so the noise forms tongues, not clouds.
    float n = 0.47;
    if (rel < 2.3) {
        vec2 q = vec2(x * 3.4, v * 1.35 - phase * 1.5);
        vec2 warp = vec2(fbm(q * 0.7 + vec2(0.0, phase * 0.3)), fbm(q * 0.7 + vec2(5.2, 1.3)));
        n = fbm(q + (warp - 0.5) * vec2(1.1, 0.6));
    }

    // 3 · fuel: solid near the base, torn into tongues near the top.
    float fuel = 1.0 - rel;
    fuel += (n - 0.47) * (0.25 + 1.55 * rel);
    fuel -= smoothstep(1.4, 2.2, rel) * 0.8;                            // cap the wildest licks
    fuel -= smoothstep(0.0, 1.0, abs(uv.x - 0.5) * 2.0 - 0.96) * 0.6;   // soft side edges
    // The heat front: a band of extra heat rising through the flames after an
    // ignition. Tongues stretch as it passes, then it fades near the top.
    float wave = frontHeat * exp(-pow((rel - front) / 0.22, 2.0));
    fuel += 0.30 * wave * (0.6 + 0.8 * n);
    // Soft ceiling: a tongue that reaches the window's far edge dissolves
    // over the last stretch instead of being sliced off by the border.
    float ceiling = smoothstep(1.0, 0.86, vw);
    // Feathered edge: wider when translucent, so tongues dissolve into the wallpaper.
    float flame = smoothstep(0.0, mix(0.18, 0.34, translucency), fuel) * ceiling;

    // 4 · temperature: hotter near the base, flashes on every ignition.
    // The turbulence feeds the temperature too, so color follows the tongues
    // instead of lying in flat horizontal stripes.
    // The heat flash is added *through the turbulence* (patchy, licking),
    // not as a flat multiplier, which blew the whole base out to white.
    float temp = clamp(fuel * (0.72 + 0.10 * bed) + (n - 0.47) * 0.45 + 0.25 * wave
                       + heat * 0.30 * (n - 0.25) * smoothstep(0.0, 0.4, fuel), 0.0, 1.0);
    vec3 col = ramp(temp, heat);

    // A tight halo just past the flame edge.
    float halo = exp(-max(-fuel, 0.0) * 9.0) * (1.0 - flame) * (0.16 + 0.40 * heat)
               * smoothstep(1.6, 0.4, rel) * ceiling;

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
    aura *= smoothstep(1.0, 0.70, vw) * smoothstep(0.0, 0.06, uv.x) * smoothstep(1.0, 0.94, uv.x);
    vec3 auraCol = mix(mix(bodyColor.rgb, midColor.rgb, 0.5), tipColor.rgb, smoothstep(0.0, 0.6, above / reach));

    // 6 · embers, thrown up by cymbals and ignitions, cooling as they climb.
    // A burning fire always sheds some; hits throw showers.
    float emberCore = 0.0, emberBloom = 0.0, emberCenter = 0.0, cool = 0.0;
    if (look.y > 0.001) {
        float climb = 0.55 + 0.60 * burst + 0.30 * heat;        // how far above the flames they live
        float top = h + climb;
        if (v < top) {
            float density = look.y * (0.30 + 0.30 * bed + 0.80 * burst + 0.30 * heat);
            vec2 p = vec2(x, v);
            vec3 near = emberLayer(p, phase, density * 0.45, 5.0, 0.95, 0.14, 3.1);
            vec3 far = emberLayer(p, phase, density * 0.35, 9.0, 0.60, 0.10, 11.7) * 0.7;
            // Born in the upper flames, fading out as they cool.
            float life = smoothstep(h * 0.45, h * 0.85, v) * (1.0 - smoothstep(h + climb * 0.45, top, v));
            life *= ceiling * smoothstep(0.0, 0.03, uv.x) * smoothstep(1.0, 0.97, uv.x);
            emberCore = max(near.x, far.x) * life;
            emberBloom = max(near.y, far.y) * life;
            emberCenter = max(near.z, far.z) * life;
            cool = smoothstep(h, top, v);
        }
    }
    // An orange-gold speck with a white-hot center, cooling as it climbs.
    // Two tones read on any background: the white center on dark wallpaper,
    // the saturated orange body on bright wallpaper (white alone vanishes
    // there, a dim red speck vanishes on the fire's own glow).
    vec3 emberBody = mix(vec3(1.0, 0.62, 0.16), vec3(1.0, 0.44, 0.10), cool);
    vec3 emberHot = mix(emberBody, vec3(1.0, 0.97, 0.86), emberCenter * (1.0 - 0.6 * cool));
    vec3 emberWarm = mix(vec3(1.0, 0.58, 0.20), mix(bodyColor.rgb, tipColor.rgb, 0.3), cool * 0.6);

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

    // Halo and aura are added light (no coverage here; the last step gives
    // them just the alpha KWin needs): they only brighten the wallpaper.
    // Blending faint orange the normal way mixes it into muddy brown around
    // every tongue. The halo uses the tip color
    // (crimson in the Ascend palette): faded crimson reads as wine.
    rgb += tipColor.rgb * halo;
    rgb += auraCol * aura;
    // Embers: the core is a solid speck that also covers what's behind it,
    // so it reads on a bright wallpaper and on top of the fire's own glow
    // instead of melting into them. The bloom covers a little too: pure
    // added light would wash a bright wallpaper to white around each ember
    // (a donut), while a slight cover tints it warm instead.
    float hide = 1.0 - flame * 0.35;                    // a little dimmer inside the flames
    float speck = emberCore * hide;
    float haze = emberBloom * hide * (1.0 - speck);
    rgb = rgb * (1.0 - speck * 0.9) + emberHot * speck * 1.25 + emberWarm * haze * 0.35;
    a = a + (1.0 - a) * (speck * 0.9 + haze * 0.30);

    // Valid premultiplied output (rgb <= alpha). Added light used to be written
    // with zero alpha, which blends fine inside Qt, but KWin's color pipeline
    // un-premultiplies every window pixel (rgb / max(a, 0.001)), converts it and
    // multiplies by alpha again, so zero-alpha light comes out as nothing on the
    // real screen (screenshots skip that step and still show it). Raising alpha
    // to the brightest channel is the most additive blend that survives it: on
    // a dark wallpaper it looks the same; on a bright one the light covers a
    // little instead of adding on top.
    rgb = min(rgb, vec3(1.0));
    a = max(min(a, 1.0), max(rgb.r, max(rgb.g, rgb.b)));
    fragColor = vec4(rgb, a) * qt_Opacity;
}
