# J.A.R.V.I.S. Dashboard V2 — Implementation Spec

Read this entire document before writing any code. It describes the CURRENT state of the dashboard, what WORKS, what's BROKEN, and exactly what needs to be FIXED or BUILT.

---

## Project Context

This is a voice-controlled AI assistant (Iron Man's Jarvis). The dashboard is served by FastAPI on `http://localhost:9000`. It uses vanilla JS (no framework), CSS, and SVG for all visuals.

## File Structure

```
ui/static/index.html           — Main SPA (no sidebar, neural-hub navigation)
ui/static/css/style.css         — All styles (~1200 lines)
ui/static/js/main.js            — Clock, routing, toast helper, apiFetch
ui/static/js/pages/home.js      — Home: arc reactor, satellites, particles, data loading
ui/static/js/pages/brain.js     — Brain analytics page
ui/static/js/pages/briefing.js  — Daily briefing page
ui/static/js/pages/projects.js  — Project tracker
ui/static/js/pages/ide.js       — Claude Code terminal (3-panel IDE)
ui/static/js/pages/settings.js  — Settings page
ui/dashboard.py                 — FastAPI backend (routes, WebSocket, data endpoints)
ui/routes/                      — Modular route files (brain.py, briefing.py, etc.)
ui/db_managers.py               — Database managers (voice log, etc.)
```

## Design Theme

- **Colors**: Dark navy bg (#050d1a), cyan primary (#00c8e8), amber warning (#ffa726), green success (#00e676), purple (#b388ff), red error (#ff5252)
- **Fonts**: `Orbitron` (headings, labels), `Share Tech Mono` (body, data, terminal)
- **Effects**: Frosted glass (`backdrop-filter: blur()`), corner bracket decorations on panels, subtle glow on interactive elements
- **CSS vars**: `--bg-dark`, `--accent-cyan`, `--accent-amber`, `--accent-red`, `--accent-green`, `--accent-purple`, `--text-main`, `--text-muted`, `--transition-speed: 350ms`, `--font-heading`, `--font-body`

---

## Current Architecture: Neural Hub Navigation

The sidebar was removed. Navigation is now a neural network layout:

### Level 0 — The Hub (home screen)

The entire screen is `#page-home`, which contains:

1. **Background effects** (all working, don't touch):
   - `.hud-grid-bg` — faint cyan grid lines
   - `.hud-particles` — 25 floating dots (spawned by JS in home.js)
   - `.hud-scanline` — horizontal sweep line every 8s
   - `.hud-corner` — L-shaped bracket decorations in all 4 viewport corners

2. **Arc Reactor** (center, working):
   - `.arc-reactor-container` — 400x400 SVG in the center of the screen
   - Contains concentric rings: calendar arc (24h clock), CPU (purple), RAM (cyan), GPU (green)
   - Decorative spinning rings, pulsing core, glow filter
   - Center text overlay: STANDBY status, uptime, interaction count
   - Ring labels float to the right: "CPU 41%", "RAM 58%", "GPU 0%"
   - All driven by `home.js` functions: `setArcProgress()`, `updateTimeMarker()`, `pollSystem()`

3. **6 Navigation Nodes** (hexagonal around reactor):
   - `.nav-nodes-container` holds 6 `.nav-node` elements
   - Each has: `.nav-node-circle` (65px, frosted glass, corner brackets), icon, label
   - Positioned via inline `style="top: X%; left: Y%"` with `transform: translate(-50%, -50%)`
   - Nodes: HOME DATA (top, active by default), BRAIN (top-right), BRIEFING (bottom-right), PROJECTS (bottom), CLAUDE IDE (bottom-left, `data-fullscreen="true"`), SETTINGS (top-left)
   - Hover: glow + scale(1.1) on circle, label brightens

4. **Synaptic Lines** (`.synapse-svg`):
   - Full-viewport SVG overlay for lines connecting nodes to center
   - Currently an empty `<svg>` — lines are supposed to be drawn by JS but this is NOT YET IMPLEMENTED

5. **Satellite Data Panels** (6 panels, all working):
   - `.sat-weather` (top-left): weather icon, temp, description, details
   - `.sat-calendar` (top-right): countdown to next event, event name
   - `.sat-email` (left): email stack with sender avatars, badge count
   - `.sat-spotify` (right): vinyl disc (spins when playing), track/artist, play/pause/skip
   - `.sat-lights` (bottom-left): colored orbs per light bulb
   - `.sat-system` (bottom-right): 3 mini ring gauges (CPU/RAM/GPU), uptime
   - Each has a `.sat-bracket` with frosted glass + corner decorations
   - Each has a color variant: `.sat-bracket-green`, `-red`, `-spotify`, `-yellow`, `-purple`
   - Data loaded by `home.js` → `loadHomeData()` which calls `/api/dashboard`

6. **Bottom Ticker** (`.hud-ticker`): scrolling data bar with weather, track, time
7. **Radial Quick Actions** (`.radial-actions`): 4 circular buttons (lights, music, email, lock)

### Level 1 — Expanded Panel

When a nav node is clicked, a panel expands to show that page's content:

- `#expanded-panel` — fixed position overlay with frosted glass, corner brackets
- Has header with title + close button, body where page content is injected
- CSS: starts at `opacity: 0; transform: scale(0.3); pointer-events: none;`
- `.visible` class: `opacity: 1; transform: scale(1); pointer-events: auto;`
- `.fullscreen` class: removes margins (for IDE)
- When expanded: `#page-home` gets `.panel-expanded` class which fades out satellites, nodes, synapses, ticker, radial actions
- Arc reactor gets `.dimmed` class: 25% opacity, scale(0.8), acts as back button

The page `<section>` elements (page-brain, page-briefing, etc.) live inside `.pages-container` which is `display: none`. On expand, JS moves the target section into `.expanded-panel-body`. On collapse, JS moves it back.

---

## What's Currently BROKEN or INCOMPLETE

### 1. main.js has dead sidebar code
The routing logic in `main.js` still references `.nav-item` and `#sidebar` which no longer exist. These throw console errors. The sidebar toggle listener will crash.

**FIX**: Replace the routing section in `main.js` with the neural hub expand/collapse logic:
- `expandNode(nodeId)`: adds `.panel-expanded` to `#page-home`, adds `.dimmed` to `.arc-reactor-container`, moves target `<section>` into `#expanded-panel-body`, adds `.visible` (and `.fullscreen` if applicable) to `#expanded-panel`, sets title
- `collapseToHub()`: reverse of above — removes `.visible`, moves section back into `.pages-container`, removes `.panel-expanded` and `.dimmed`
- Wire up: nav node clicks call `expandNode()`, close button and dimmed reactor click call `collapseToHub()`
- HOME DATA node click: does nothing (it's the current view, satellites are already showing)

### 2. Synaptic lines are not drawn
The `#synapse-svg` is empty. Need JS to:
- Calculate center of arc reactor and center of each nav node
- Draw an SVG `<line>` with class `synapse-line` between each pair
- Add an animated pulse dot (`<circle>` with class `synapse-pulse`) that travels along each line
- Recalculate on window resize
- Pulse animation: small cyan dot (r=3, filter=glow) travels from center to node, 3-4s duration, each line offset by ~0.5s, infinite loop
- Use SVG `<animateMotion>` along a `<path>` or CSS animation on the circle's position

### 3. No visual feedback on node click
When you click a nav node, it should briefly "activate" (flash/pulse) before the panel expands. Add a short animation: the node circle briefly glows bright and scales to 1.2 for 200ms, then the panel transition begins.

### 4. Pages inside expanded panel may have sizing issues
The IDE page (`#page-ide.file-panel-layout`) needs `display: flex; height: 100%;` when inside the expanded panel body. Other pages need their content to scroll within `.expanded-panel-body`. Test each page:
- BRAIN: has Chart.js canvases — may need re-initialization after being moved in DOM
- IDE: needs full height, 3 panels side by side
- Others: should just scroll

---

## Detailed Fix Instructions

### main.js — Replace routing logic

Remove everything from the `// Routing logic` comment through the `// Sidebar Toggle` section (lines 27-47). Replace with:

```javascript
// ── Neural Hub Navigation ──
let _currentPanel = null;

function expandNode(pageId) {
    if (pageId === 'home-data' || !pageId) return; // HOME DATA = current view
    
    const section = document.getElementById(pageId);
    if (!section) return;
    
    const panel = document.getElementById('expanded-panel');
    const body = document.getElementById('expanded-panel-body');
    const home = document.getElementById('page-home');
    const reactor = document.querySelector('.arc-reactor-container');
    
    // Get page title from the node
    const node = document.querySelector(`[data-page="${pageId}"]`);
    const title = node ? node.querySelector('.nav-node-label').textContent : pageId;
    document.getElementById('expanded-panel-title').textContent = title;
    
    // Move section into panel
    body.innerHTML = '';
    body.appendChild(section);
    section.classList.add('active');
    
    // Check fullscreen
    const isFullscreen = node && node.getAttribute('data-fullscreen') === 'true';
    panel.classList.toggle('fullscreen', isFullscreen);
    
    // Animate
    home.classList.add('panel-expanded');
    reactor.classList.add('dimmed');
    panel.classList.add('visible');
    
    _currentPanel = pageId;
}

function collapseToHub() {
    if (!_currentPanel) return;
    
    const panel = document.getElementById('expanded-panel');
    const body = document.getElementById('expanded-panel-body');
    const home = document.getElementById('page-home');
    const reactor = document.querySelector('.arc-reactor-container');
    const container = document.querySelector('.pages-container');
    
    // Move section back
    const section = body.querySelector('.page');
    if (section) {
        section.classList.remove('active');
        container.appendChild(section);
    }
    
    // Animate
    panel.classList.remove('visible', 'fullscreen');
    home.classList.remove('panel-expanded');
    reactor.classList.remove('dimmed');
    
    _currentPanel = null;
}

// Wire up nav nodes
document.querySelectorAll('.nav-node').forEach(node => {
    node.addEventListener('click', () => {
        const pageId = node.getAttribute('data-page');
        expandNode(pageId);
    });
});

// Close button
document.getElementById('expanded-panel-close').addEventListener('click', collapseToHub);

// Dimmed reactor = back button
document.querySelector('.arc-reactor-container').addEventListener('click', () => {
    if (_currentPanel) collapseToHub();
});
```

### home.js — Add synaptic line drawing

Add this function and call it after DOMContentLoaded setup:

```javascript
function drawSynapseLines() {
    const svg = document.getElementById('synapse-svg');
    if (!svg) return;
    svg.innerHTML = '';
    
    const reactor = document.querySelector('.arc-reactor-container');
    if (!reactor) return;
    const rRect = reactor.getBoundingClientRect();
    const home = document.getElementById('page-home');
    const hRect = home.getBoundingClientRect();
    
    const cx = rRect.left + rRect.width / 2 - hRect.left;
    const cy = rRect.top + rRect.height / 2 - hRect.top;
    
    document.querySelectorAll('.nav-node').forEach((node, i) => {
        const nRect = node.getBoundingClientRect();
        const nx = nRect.left + nRect.width / 2 - hRect.left;
        const ny = nRect.top + nRect.height / 2 - hRect.top;
        
        // Line
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', cx);
        line.setAttribute('y1', cy);
        line.setAttribute('x2', nx);
        line.setAttribute('y2', ny);
        line.setAttribute('class', 'synapse-line');
        svg.appendChild(line);
        
        // Pulse dot
        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        circle.setAttribute('r', '3');
        circle.setAttribute('class', 'synapse-pulse');
        
        const anim = document.createElementNS('http://www.w3.org/2000/svg', 'animateMotion');
        anim.setAttribute('dur', '3.5s');
        anim.setAttribute('repeatCount', 'indefinite');
        anim.setAttribute('begin', (i * 0.6) + 's');
        anim.setAttribute('path', `M${cx},${cy} L${nx},${ny}`);
        
        circle.appendChild(anim);
        svg.appendChild(circle);
    });
}

// Call after a short delay so layout is settled
setTimeout(drawSynapseLines, 500);
window.addEventListener('resize', () => { clearTimeout(window._synResize); window._synResize = setTimeout(drawSynapseLines, 200); });
```

---

## Backend API Endpoints (already implemented, don't change)

| Endpoint | Method | Returns |
|---|---|---|
| `/api/dashboard` | GET | weather, calendar, emails, spotify, lights, system info |
| `/api/system` | GET | cpu_percent, ram_percent, ram_used_gb, gpu_percent, time |
| `/api/claude-limit` | GET | Claude session usage (utilization, resetsAt, rateLimitType) |
| `/api/quick-action` | POST | Execute a Jarvis tool (lights off, play music, etc.) |
| `/api/voice-log` | GET | Today's voice interaction timestamps |
| `/ws/claude` | WS | Claude Code terminal (streaming, history, commands) |

Route modules in `ui/routes/`: brain.py, briefing.py, projects.py, ide.py, settings.py — each registers its own endpoints.

---

## Critical Rules

1. **Don't break working features**: arc reactor rings, satellite data panels, particles, scanline, ticker, quick actions, spotify controls, system polling — all work. Test after changes.
2. **Don't modify dashboard.py** unless adding a genuinely new endpoint.
3. **Keep vanilla JS** — no React, Vue, or any framework. No build step.
4. **CSS animations only** — use `transition` and `@keyframes`, not JS-driven requestAnimationFrame for visual effects.
5. **All existing element IDs must remain** — home.js and other page scripts reference specific IDs for data binding.
6. **The `<section>` elements for pages must be movable** — the expand/collapse logic moves them between `.pages-container` and `.expanded-panel-body`. Don't add event listeners that break when elements are reparented (use event delegation or re-attach after move).
7. **Chart.js canvases** (brain page) may need `Chart.destroy()` and re-creation when the canvas is moved in DOM. Handle this in the expand/collapse logic or in brain.js.
8. **IDE page** gets `data-fullscreen="true"` — expanded panel uses `.fullscreen` class (no margins, no padding on body) so the 3-panel layout fills the space.
9. **Test navigation cycle**: Hub → Brain → close → IDE → close → Settings → close. No state leaks, no broken animations, no orphaned elements.
