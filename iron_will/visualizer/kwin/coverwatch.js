// Iron Will: tell the visualizer whether other windows completely cover it.
//
// Loaded into KWin over D-Bus by the visualizer (iron_will/visualizer/
// coverwatch.py), which prepends `const VISUALIZER_PID = <pid>;` so we can find
// its surface, and unloads it again when it quits. A Wayland client can't see
// other windows, but the compositor can.
//
// The rule is geometric: the visualizer is "covered" when the windows stacked
// *above* it together hide its whole rectangle. That catches a fullscreen game
// or video, a maximized browser, two windows tiled side by side, or one big
// window parked over it. Stacking order also takes care of the layer setting:
// with layer = top the visualizer sits above normal windows, so they never
// count.
//
// A window only counts while it is really on screen: not minimized or hidden,
// on the current virtual desktop and activity, and not made see-through by
// KWin (opacity < 1). Show Desktop isn't visible to scripts; the visualizer
// follows KWin's own D-Bus signal for that. A window that draws its own
// translucent background (some terminals) can't be told apart from an opaque
// one, so it counts as covering.
//
// Cost: the check runs on window state changes and while a window is dragged
// or resized (a few dozen rectangle subtractions, microseconds). The
// visualizer is only called when the answer flips. The first report goes out
// as soon as the script starts, so the visualizer knows it is alive.

const SERVICE = "org.ironwill.Visualizer";
const PATH = "/Visualizer";
const IFACE = "org.ironwill.Visualizer";

// Gaps up to this share of the visualizer's area still count as covered:
// tiling padding or a rounding pixel leaves a sliver nobody can see bars in.
const UNCOVERED_TOLERANCE = 0.01;
const MAX_PIECES = 64;   // give up (= "not covered") rather than fragment forever

let lastReport = null;   // only call the visualizer when the answer changes

function onCurrentDesktop(w) {
    if (w.onAllDesktops) return true;
    const current = workspace.currentDesktop;
    return w.desktops.some(d => d.id === current.id);
}

function onCurrentActivity(w) {
    // An empty list means "on all activities".
    return w.activities.length === 0 || w.activities.indexOf(workspace.currentActivity) >= 0;
}

function onScreen(w) {
    return !w.minimized && w.hidden !== true && !w.deleted && w.opacity >= 1
        && onCurrentDesktop(w) && onCurrentActivity(w);
}

function rect(g) {
    return { x: g.x, y: g.y, w: g.width, h: g.height };
}

// r minus c, as up to four rectangles (bands above and below, slices beside).
function subtract(r, c) {
    const x1 = Math.max(r.x, c.x), y1 = Math.max(r.y, c.y);
    const x2 = Math.min(r.x + r.w, c.x + c.w), y2 = Math.min(r.y + r.h, c.y + c.h);
    if (x1 >= x2 || y1 >= y2) return [r];            // no overlap
    const out = [];
    if (r.y < y1) out.push({ x: r.x, y: r.y, w: r.w, h: y1 - r.y });
    if (y2 < r.y + r.h) out.push({ x: r.x, y: y2, w: r.w, h: r.y + r.h - y2 });
    if (r.x < x1) out.push({ x: r.x, y: y1, w: x1 - r.x, h: y2 - y1 });
    if (x2 < r.x + r.w) out.push({ x: x2, y: y1, w: r.x + r.w - x2, h: y2 - y1 });
    return out;
}

function isCovered(gone) {
    const stack = workspace.stackingOrder;           // bottom → top
    const index = stack.findIndex(w => w.pid === VISUALIZER_PID && w !== gone && !w.deleted);
    if (index < 0) return false;                     // not mapped (yet)
    const target = rect(stack[index].frameGeometry);
    const area = target.w * target.h;
    if (area <= 0) return false;

    let visible = [target];
    for (let i = index + 1; i < stack.length; i++) {
        const w = stack[i];
        if (w === gone || w.pid === VISUALIZER_PID || !onScreen(w)) continue;
        const cover = rect(w.frameGeometry);
        const next = [];   // (no Array.flatMap: KWin's JS engine predates it)
        for (const piece of visible) next.push(...subtract(piece, cover));
        visible = next;
        if (visible.length === 0) return true;
        if (visible.length > MAX_PIECES) return false;
    }
    const left = visible.reduce((sum, p) => sum + p.w * p.h, 0);
    return left <= area * UNCOVERED_TOLERANCE;
}

function report(gone) {
    const covered = isCovered(gone);
    if (covered !== lastReport) {
        lastReport = covered;
        callDBus(SERVICE, PATH, IFACE, "SetCovered", covered);
    }
}

function refresh() { report(null); }

function watch(w) {
    // Everything that can change what a window hides, or whether it's above
    // the visualizer (stackingOrderChanged also fires when a layer changes).
    for (const name of ["frameGeometryChanged", "fullScreenChanged", "minimizedChanged", "hiddenChanged",
                        "opacityChanged", "desktopsChanged", "activitiesChanged", "outputChanged",
                        "stackingOrderChanged", "keepAboveChanged", "keepBelowChanged"]) {
        if (w[name]) w[name].connect(refresh);
    }
}

workspace.windowList().forEach(watch);
workspace.windowAdded.connect(w => { watch(w); refresh(); });
workspace.windowRemoved.connect(w => report(w));   // it may still be listed while it's being removed
for (const name of ["windowActivated", "currentDesktopChanged", "currentActivityChanged", "screensChanged"]) {
    if (workspace[name]) workspace[name].connect(refresh);
}
refresh();
