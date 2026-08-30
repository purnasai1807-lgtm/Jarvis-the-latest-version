// ═══════════════════════════════════════════════
// NEURAL NETWORK — Living Brain Engine
// ═══════════════════════════════════════════════

(function() {
    'use strict';

    let _expandedPageId = null;
    let _transitioning = false;

    const PAGE_TITLES = {
        'page-brain':     'BRAIN ANALYTICS',
        'page-briefing':  'DAILY BRIEFING',
        'page-projects':  'PROJECT TRACKER',
        'page-ide':       'CLAUDE IDE',
        'page-settings':  'SYSTEM SETTINGS',
        'page-voice-log': 'VOICE LOG',
    };

    // Toast
    window.showToast = function(message, type="info") {
        const c = document.getElementById("toast-container");
        const t = document.createElement("div");
        t.className = `toast ${type}`;
        t.textContent = message;
        c.appendChild(t);
        setTimeout(() => { t.style.animation = "slideInRight 0.3s reverse forwards"; setTimeout(() => t.remove(), 300); }, 3000);
    };

    // Clock
    function updateClock() {
        const now = new Date();
        const d = document.getElementById("header-date");
        const t = document.getElementById("header-time");
        if (d) d.textContent = now.toISOString().split("T")[0];
        if (t) t.textContent = now.toTimeString().split(" ")[0];
    }
    setInterval(updateClock, 1000);
    updateClock();

    // API
    window.apiFetch = async function(url, opts={}) {
        try { const r = await fetch(url, opts); if (!r.ok) throw new Error(`HTTP ${r.status}`); return await r.json(); }
        catch(e) { console.error("API Error:", e); return null; }
    };

    // ══════════════════════════════════════
    //  ENERGY RAYS + NEURAL WEB IN REACTOR
    // ══════════════════════════════════════

    function buildEnergyRays() {
        const g = document.getElementById('energy-rays');
        if (!g) return;
        for (let i = 0; i < 24; i++) {
            const a = (i * 15) * Math.PI / 180;
            const r1 = 55, r2 = 100 + Math.random() * 90;
            const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            line.setAttribute('x1', 200 + r1*Math.cos(a)); line.setAttribute('y1', 200 + r1*Math.sin(a));
            line.setAttribute('x2', 200 + r2*Math.cos(a)); line.setAttribute('y2', 200 + r2*Math.sin(a));
            line.classList.add('energy-ray');
            line.style.animationDelay = (Math.random()*3)+'s';
            line.style.animationDuration = (2+Math.random()*2)+'s';
            g.appendChild(line);
        }
    }

    function buildNeuralWeb() {
        const g = document.getElementById('neural-web');
        if (!g) return;
        const pts = [];
        for (let i = 0; i < 12; i++) {
            const a = Math.random()*Math.PI*2, r = 15+Math.random()*35;
            pts.push({ x: 200+r*Math.cos(a), y: 200+r*Math.sin(a) });
        }
        for (let i = 0; i < pts.length; i++) {
            for (let j = i+1; j < pts.length; j++) {
                const d = Math.hypot(pts[i].x-pts[j].x, pts[i].y-pts[j].y);
                if (d < 40) {
                    const l = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                    l.setAttribute('x1', pts[i].x); l.setAttribute('y1', pts[i].y);
                    l.setAttribute('x2', pts[j].x); l.setAttribute('y2', pts[j].y);
                    l.setAttribute('stroke', 'rgba(0,200,232,0.3)'); l.setAttribute('stroke-width', '0.5');
                    const an = document.createElementNS('http://www.w3.org/2000/svg', 'animate');
                    an.setAttribute('attributeName', 'opacity'); an.setAttribute('values', '0.1;0.6;0.1');
                    an.setAttribute('dur', (1.5+Math.random()*2)+'s'); an.setAttribute('repeatCount', 'indefinite');
                    l.appendChild(an); g.appendChild(l);
                }
            }
            const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            dot.setAttribute('cx', pts[i].x); dot.setAttribute('cy', pts[i].y);
            dot.setAttribute('r', '1'); dot.setAttribute('fill', '#00c8e8');
            const da = document.createElementNS('http://www.w3.org/2000/svg', 'animate');
            da.setAttribute('attributeName', 'r'); da.setAttribute('values', '0.5;1.5;0.5');
            da.setAttribute('dur', (1+Math.random()*2)+'s'); da.setAttribute('repeatCount', 'indefinite');
            dot.appendChild(da); g.appendChild(dot);
        }
    }

    // ══════════════════════════════════════
    //  MICRO-NODES
    // ══════════════════════════════════════

    function spawnMicroNodes() {
        const home = document.getElementById('page-home');
        if (!home) return;
        for (let i = 0; i < 25; i++) {
            const el = document.createElement('div');
            el.className = 'micro-node';
            el.style.left = (5+Math.random()*90)+'%';
            el.style.top = (5+Math.random()*90)+'%';
            el.style.width = el.style.height = (3+Math.random()*5)+'px';
            el.style.setProperty('--dx', (Math.random()*60-30)+'px');
            el.style.setProperty('--dy', (Math.random()*60-30)+'px');
            el.style.animationDuration = (15+Math.random()*25)+'s';
            el.style.animationDelay = (Math.random()*10)+'s';
            const r = Math.random();
            if (r > 0.85) { el.style.background = 'rgba(179,136,255,0.3)'; el.style.boxShadow = '0 0 6px rgba(179,136,255,0.2)'; }
            else if (r > 0.7) { el.style.background = 'rgba(0,230,118,0.3)'; el.style.boxShadow = '0 0 6px rgba(0,230,118,0.2)'; }
            home.appendChild(el);
        }
    }

    // ══════════════════════════════════════
    //  DATA ISLAND PHYSICS + DRAG
    // ══════════════════════════════════════

    // Each island: { el, homeX, homeY, x, y, vx, vy, phase, ... dragging }
    const islands = [];
    const navPhysicsNodes = [];
    let dragTarget = null;
    let dragOffX = 0, dragOffY = 0;
    let _dragMoved = false;
    let _dragStartX = 0, _dragStartY = 0;

    // Portrait detection
    const _isPortrait = window.innerHeight > window.innerWidth * 1.15;

    // Initial positions (% of viewport) — wide horizontal spread
    const ISLAND_INIT = {
        'island-weather':   { x: -25, y: 18 },
        'island-calendar':  { x: 120, y: 12 },
        'island-email':     { x: -30, y: 50 },
        'island-spotify':   { x: 125, y: 45 },
        'island-lights':    { x: -22, y: 80 },
        'island-telemetry': { x: 120, y: 78 },
        'island-claude':    { x: -15, y: 68 },
    };

    // Portrait: tighter horizontal, spread vertically around the core
    const ISLAND_INIT_PORTRAIT = {
        'island-weather':   { x: 15,  y: -18 },
        'island-calendar':  { x: 85,  y: -12 },
        'island-email':     { x: 105, y: 30 },
        'island-spotify':   { x: -5,  y: 30 },
        'island-lights':    { x: 105, y: 70 },
        'island-telemetry': { x: -5,  y: 75 },
        'island-claude':    { x: 50,  y: 108 },
    };

    function initIslands() {
        const home = document.getElementById('page-home');
        if (!home) return;

        document.querySelectorAll('.data-island').forEach(el => {
            const id = el.id;
            const initMap = _isPortrait ? ISLAND_INIT_PORTRAIT : ISLAND_INIT;
            const init = initMap[id] || { x: 50, y: 50 };
            const vw = home.clientWidth, vh = home.clientHeight;
            // Map % to viewport area (centered within the larger canvas)
            const viewL = (vw - window.innerWidth) / 2;
            const viewT = (vh - window.innerHeight) / 2;
            const px = viewL + init.x / 100 * window.innerWidth;
            const py = viewT + init.y / 100 * window.innerHeight;

            const island = {
                el,
                homeX: px, homeY: py,
                x: px, y: py,
                vx: 0, vy: 0,
                phase: Math.random() * Math.PI * 2,
                ampX: 8 + Math.random() * 15,
                ampY: 6 + Math.random() * 12,
                speedX: 0.3 + Math.random() * 0.4,
                speedY: 0.2 + Math.random() * 0.3,
                dragging: false,
            };
            islands.push(island);

            // Position
            el.style.position = 'absolute';
            el.style.left = '0'; el.style.top = '0';
            el.style.transform = `translate(${px}px, ${py}px) translate(-50%, -50%)`;

            // Drag start
            el.addEventListener('mousedown', (e) => {
                if (e.button !== 0) return;
                e.preventDefault();
                island.dragging = true;
                el.classList.add('dragging');
                dragTarget = island;
                _dragMoved = false;
                _dragStartX = e.clientX;
                _dragStartY = e.clientY;
                const rect = home.getBoundingClientRect();
                dragOffX = e.clientX - rect.left - island.x;
                dragOffY = e.clientY - rect.top - island.y;
            });
            el.addEventListener('touchstart', (e) => {
                island.dragging = true;
                el.classList.add('dragging');
                dragTarget = island;
                _dragMoved = false;
                const touch = e.touches[0];
                _dragStartX = touch.clientX;
                _dragStartY = touch.clientY;
                const rect = home.getBoundingClientRect();
                dragOffX = touch.clientX - rect.left - island.x;
                dragOffY = touch.clientY - rect.top - island.y;
            }, { passive: true });
        });

        // Global drag move + end
        const home2 = home;
        document.addEventListener('mousemove', (e) => {
            if (!dragTarget) return;
            if (!_dragMoved) {
                if (Math.hypot(e.clientX - _dragStartX, e.clientY - _dragStartY) < 5) return;
                _dragMoved = true;
            }
            const rect = home2.getBoundingClientRect();
            dragTarget.x = e.clientX - rect.left - dragOffX;
            dragTarget.y = e.clientY - rect.top - dragOffY;
            dragTarget.homeX = dragTarget.x;
            dragTarget.homeY = dragTarget.y;
        });
        document.addEventListener('mouseup', () => {
            if (dragTarget) { dragTarget.vx = 0; dragTarget.vy = 0; dragTarget.dragging = false; dragTarget.el.classList.remove('dragging'); dragTarget = null; }
        });
        document.addEventListener('touchmove', (e) => {
            if (!dragTarget) return;
            const t = e.touches[0];
            if (!_dragMoved) {
                if (Math.hypot(t.clientX - _dragStartX, t.clientY - _dragStartY) < 5) return;
                _dragMoved = true;
            }
            const rect = home2.getBoundingClientRect();
            dragTarget.x = t.clientX - rect.left - dragOffX;
            dragTarget.y = t.clientY - rect.top - dragOffY;
            dragTarget.homeX = dragTarget.x;
            dragTarget.homeY = dragTarget.y;
        }, { passive: true });
        document.addEventListener('touchend', () => {
            if (dragTarget) { dragTarget.vx = 0; dragTarget.vy = 0; dragTarget.dragging = false; dragTarget.el.classList.remove('dragging'); dragTarget = null; }
        });
    }

    // ══════════════════════════════════════
    //  NAV NODE PHYSICS + DRAG
    // ══════════════════════════════════════

    function initNavPhysics() {
        const home = document.getElementById('page-home');
        if (!home) return;
        const vw = home.clientWidth, vh = home.clientHeight;

        document.querySelectorAll('.nav-node').forEach(el => {
            const topPct = parseFloat(el.style.top) / 100;
            const leftPct = parseFloat(el.style.left) / 100;
            // Map % to viewport area (centered within the larger canvas)
            const viewL = (vw - window.innerWidth) / 2;
            const viewT = (vh - window.innerHeight) / 2;
            const px = viewL + leftPct * window.innerWidth;
            const py = viewT + topPct * window.innerHeight;

            // Switch from CSS % positioning to JS transform positioning
            el.style.top = '0';
            el.style.left = '0';
            el.style.animation = 'none';
            el.style.transform = `translate(${px}px, ${py}px) translate(-50%, -50%)`;

            const node = {
                el,
                homeX: px, homeY: py,
                x: px, y: py,
                vx: 0, vy: 0,
                phase: Math.random() * Math.PI * 2,
                speedX: 0.2 + Math.random() * 0.3,
                speedY: 0.15 + Math.random() * 0.2,
                dragging: false,
            };
            navPhysicsNodes.push(node);

            // Drag start (click disambiguation via _dragMoved)
            el.addEventListener('mousedown', (e) => {
                if (e.button !== 0) return;
                e.preventDefault();
                node.dragging = true;
                el.classList.add('dragging');
                dragTarget = node;
                _dragMoved = false;
                _dragStartX = e.clientX;
                _dragStartY = e.clientY;
                const rect = home.getBoundingClientRect();
                dragOffX = e.clientX - rect.left - node.x;
                dragOffY = e.clientY - rect.top - node.y;
            });
            el.addEventListener('touchstart', (e) => {
                node.dragging = true;
                el.classList.add('dragging');
                dragTarget = node;
                _dragMoved = false;
                const touch = e.touches[0];
                _dragStartX = touch.clientX;
                _dragStartY = touch.clientY;
                const rect = home.getBoundingClientRect();
                dragOffX = touch.clientX - rect.left - node.x;
                dragOffY = touch.clientY - rect.top - node.y;
            }, { passive: true });
        });
    }

    // ══════════════════════════════════════
    //  ANIMATION LOOP — float + connections
    // ══════════════════════════════════════

    // Persistent SVG connection elements (so SMIL pulses survive)
    let connectionEls = [];
    let connectionsBuilt = false;
    let loopTime = 0;
    let _islandNavLinks = [];
    let _islandIslandLinks = [];

    function buildConnections() {
        const svg = document.getElementById('synapse-svg');
        if (!svg) return;
        svg.innerHTML = '';

        const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
        defs.innerHTML = `
            <filter id="sg"><feGaussianBlur stdDeviation="2.5" result="b"/>
            <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
            <filter id="sg2"><feGaussianBlur stdDeviation="1.2" result="b"/>
            <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>`;
        svg.appendChild(defs);
        connectionEls = [];

        const homeRect = document.getElementById('page-home').getBoundingClientRect();

        // Get all connectable things
        const navCircles = [];
        document.querySelectorAll('.nav-node').forEach(n => {
            const c = n.querySelector('.nav-node-circle');
            if (c) navCircles.push(c);
        });

        // Core → each nav node
        navCircles.forEach((c, i) => {
            connectionEls.push(makeLine(svg, 'rgba(0,200,232,0.25)', 1.2, '6 4'));
            connectionEls.push(makePulse(svg, 3, 'url(#sg)', 3+i*0.4, 3.5));
            connectionEls.push(makePulse(svg, 2, 'url(#sg2)', 3+i*0.4+1.8, 4));
        });

        // Core → each island
        islands.forEach((isl, i) => {
            connectionEls.push(makeLine(svg, 'rgba(0,200,232,0.18)', 0.8, '3 6'));
            connectionEls.push(makePulse(svg, 2, 'url(#sg2)', i*0.7, 3));
        });

        // ── Logical connections: island → nav node ──
        // Nav: 0=voice-log, 1=brain, 2=briefing, 3=projects, 4=ide, 5=settings
        // Isl: 0=weather, 1=calendar, 2=email, 3=spotify, 4=claude, 5=lights, 6=telemetry
        _islandNavLinks = [
            [4, 4, 0.35, 1.0],   // claude → ide (PRIMARY)
            [6, 1, 0.30, 0.8],   // telemetry → brain
            [0, 2, 0.30, 0.8],   // weather → briefing
            [1, 2, 0.28, 0.8],   // calendar → briefing
            [3, 0, 0.28, 0.8],   // spotify → voice-log
            [5, 5, 0.28, 0.8],   // lights → settings
            [2, 2, 0.18, 0.6],   // email → briefing
            [5, 0, 0.14, 0.5],   // lights → voice-log
            [4, 1, 0.14, 0.5],   // claude → brain (cost/analytics)
            [6, 5, 0.12, 0.5],   // telemetry → settings
            [1, 3, 0.10, 0.4],   // calendar → projects (deadlines)
            [3, 5, 0.08, 0.4],   // spotify → settings
        ];
        _islandNavLinks.forEach(([iIdx, nIdx, opacity, width]) => {
            connectionEls.push(makeLine(svg, '#00c8e8', width, opacity > 0.2 ? '4 4' : '2 8'));
        });

        // ── Logical connections: island → island ──
        _islandIslandLinks = [
            [4, 6, 0.20, 0.7],   // claude ↔ telemetry (system)
            [1, 2, 0.18, 0.6],   // calendar ↔ email (comms)
            [0, 1, 0.14, 0.5],   // weather ↔ calendar (planning)
            [3, 5, 0.10, 0.4],   // spotify ↔ lights (home)
            [0, 5, 0.08, 0.3],   // weather ↔ lights (ambient)
            [2, 3, 0.06, 0.3],   // email ↔ spotify (side)
        ];
        _islandIslandLinks.forEach(([iIdx, jIdx, opacity, width]) => {
            connectionEls.push(makeLine(svg, '#00c8e8', width, opacity > 0.15 ? '3 6' : '2 10'));
        });

        connectionsBuilt = true;
    }

    function makeLine(svg, color, width, dash) {
        const l = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        l.setAttribute('stroke', color);
        l.setAttribute('stroke-width', width);
        if (dash) l.setAttribute('stroke-dasharray', dash);
        svg.appendChild(l);
        return { type: 'line', el: l };
    }

    function makePulse(svg, r, filter, delay, dur) {
        const p = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        p.setAttribute('r', r);
        p.setAttribute('fill', '#00c8e8');
        p.setAttribute('opacity', '0');
        if (filter) p.setAttribute('filter', filter);
        svg.appendChild(p);
        return { type: 'pulse', el: p, dur, delay };
    }

    // ══════════════════════════════════════
    //  FORCE-DIRECTED PHYSICS
    // ══════════════════════════════════════

    const PHYSICS = {
        springK:      0.002,   // soft springs
        springRest:   350,     // moderate rest length
        repulsion:    8000,    // soft repulsion at long range
        minDist:      280,     // hard exclusion radius between nodes (px)
        hardPush:     2.0,     // linear push force inside minDist
        centerRadius: 350,     // exclusion zone radius around reactor core
        centerK:      0.4,     // center repulsion strength
        homeK:        0.0008,  // weak gravity toward original home position
        damping:      0.35,    // extreme friction — barely drifting
        maxSpeed:     0.3,     // px/frame speed cap — glacial drift
        boundaryPad:  120,     // px inset from canvas edges
        boundaryK:    0.08,    // boundary spring constant
    };

    // Portrait overrides — tighter orbit, smaller exclusion zone
    if (_isPortrait) {
        PHYSICS.centerRadius = 240;
        PHYSICS.springRest   = 240;
        PHYSICS.minDist      = 190;
        PHYSICS.repulsion    = 5000;
        PHYSICS.boundaryPad  = 80;
    }

    function applyPhysics(cx, cy) {
        const home = document.getElementById('page-home');
        if (!home) return;
        const vw = home.clientWidth, vh = home.clientHeight;

        // All physics nodes = islands + nav nodes
        const allNodes = islands.concat(navPhysicsNodes);

        // Reset forces
        allNodes.forEach(n => { n.fx = 0; n.fy = 0; });

        // Spring attraction: island ↔ island connections
        _islandIslandLinks.forEach(([iIdx, jIdx]) => {
            if (iIdx >= islands.length || jIdx >= islands.length) return;
            const a = islands[iIdx], b = islands[jIdx];
            const dx = b.x - a.x, dy = b.y - a.y;
            const dist = Math.max(Math.hypot(dx, dy), 1);
            const f = PHYSICS.springK * (dist - PHYSICS.springRest);
            const ux = dx / dist, uy = dy / dist;
            a.fx += ux * f;  a.fy += uy * f;
            b.fx -= ux * f;  b.fy -= uy * f;
        });

        // Spring attraction: island ↔ nav node (both sides move)
        _islandNavLinks.forEach(([iIdx, nIdx]) => {
            if (iIdx >= islands.length || nIdx >= navPhysicsNodes.length) return;
            const a = islands[iIdx], b = navPhysicsNodes[nIdx];
            const dx = b.x - a.x, dy = b.y - a.y;
            const dist = Math.max(Math.hypot(dx, dy), 1);
            const f = PHYSICS.springK * (dist - PHYSICS.springRest);
            const ux = dx / dist, uy = dy / dist;
            a.fx += ux * f;  a.fy += uy * f;
            b.fx -= ux * f * 0.5;  b.fy -= uy * f * 0.5;
        });

        // Repulsion between ALL node pairs (islands + nav nodes)
        for (let i = 0; i < allNodes.length; i++) {
            for (let j = i + 1; j < allNodes.length; j++) {
                const a = allNodes[i], b = allNodes[j];
                const dx = b.x - a.x, dy = b.y - a.y;
                const dist = Math.max(Math.hypot(dx, dy), 10);
                let f;
                if (dist < PHYSICS.minDist) {
                    // Hard linear push — force field wall
                    f = -PHYSICS.hardPush * (PHYSICS.minDist - dist);
                } else {
                    // Soft inverse-square at long range
                    f = -PHYSICS.repulsion / (dist * dist);
                }
                const ux = dx / dist, uy = dy / dist;
                a.fx += ux * f;  a.fy += uy * f;
                b.fx -= ux * f;  b.fy -= uy * f;
            }
        }

        // Center exclusion zone — push all nodes away from reactor core
        allNodes.forEach(n => {
            const dx = n.x - cx, dy = n.y - cy;
            const dist = Math.max(Math.hypot(dx, dy), 1);
            if (dist < PHYSICS.centerRadius) {
                const pushForce = PHYSICS.centerK * (PHYSICS.centerRadius - dist);
                n.fx += (dx / dist) * pushForce;
                n.fy += (dy / dist) * pushForce;
            }
        });

        // Gravity toward home position — stronger for nav nodes
        islands.forEach(n => {
            n.fx += (n.homeX - n.x) * PHYSICS.homeK;
            n.fy += (n.homeY - n.y) * PHYSICS.homeK;
        });
        navPhysicsNodes.forEach(n => {
            n.fx += (n.homeX - n.x) * PHYSICS.homeK * 8;
            n.fy += (n.homeY - n.y) * PHYSICS.homeK * 8;
        });

        // Boundary forces — orientation-aware
        const pad = PHYSICS.boundaryPad, bk = PHYSICS.boundaryK;
        const viewL = (vw - window.innerWidth) / 2;
        const viewT = (vh - window.innerHeight) / 2;
        const viewR = viewL + window.innerWidth;
        const viewB = viewT + window.innerHeight;
        const vPad = 50;

        if (_isPortrait) {
            // Portrait: tight horizontal (keep in viewport), loose vertical (canvas edges)
            allNodes.forEach(n => {
                if (n.x < viewL + vPad)  n.fx += (viewL + vPad - n.x) * bk * 3;
                if (n.x > viewR - vPad)  n.fx -= (n.x - (viewR - vPad)) * bk * 3;
                if (n.y < pad)       n.fy += (pad - n.y) * bk * 0.3;
                if (n.y > vh - pad)  n.fy -= (n.y - (vh - pad)) * bk * 0.3;
            });
        } else {
            // Landscape: loose horizontal (canvas edges), tight vertical (viewport)
            allNodes.forEach(n => {
                if (n.x < pad)       n.fx += (pad - n.x) * bk * 0.3;
                if (n.x > vw - pad)  n.fx -= (n.x - (vw - pad)) * bk * 0.3;
                if (n.y < viewT + vPad)  n.fy += (viewT + vPad - n.y) * bk * 4;
                if (n.y > viewB - vPad)  n.fy -= (n.y - (viewB - vPad)) * bk * 4;
            });
        }

        if (_isPortrait) {
            // Vertical spread — push islands away from center Y
            const centerY = vh / 2;
            islands.forEach(n => {
                const dy = n.y - centerY;
                const absDy = Math.abs(dy);
                const spreadForce = Math.max(0, window.innerHeight - absDy) * 0.0008;
                n.fy += Math.sign(dy || 1) * spreadForce;
            });
        } else {
            // Horizontal spread — push islands away from center X
            const centerX = vw / 2;
            islands.forEach(n => {
                const dx = n.x - centerX;
                const absDx = Math.abs(dx);
                const spreadForce = Math.max(0, window.innerWidth - absDx) * 0.001;
                n.fx += Math.sign(dx || 1) * spreadForce;
            });
        }

        // Integrate velocity and update positions
        allNodes.forEach(n => {
            if (n.dragging) { n.vx = 0; n.vy = 0; return; }
            n.vx = (n.vx + n.fx) * PHYSICS.damping;
            n.vy = (n.vy + n.fy) * PHYSICS.damping;
            const speed = Math.hypot(n.vx, n.vy);
            if (speed > PHYSICS.maxSpeed) {
                n.vx = n.vx / speed * PHYSICS.maxSpeed;
                n.vy = n.vy / speed * PHYSICS.maxSpeed;
            }
            n.x += n.vx;
            n.y += n.vy;
        });
    }

    function animationLoop(ts) {
        if (_expandedPageId) { requestAnimationFrame(animationLoop); return; }

        loopTime = ts / 1000;

        const home = document.getElementById('page-home');
        if (!home) { requestAnimationFrame(animationLoop); return; }
        const homeRect = home.getBoundingClientRect();

        const reactor = document.querySelector('.arc-reactor-container');
        if (!reactor) { requestAnimationFrame(animationLoop); return; }
        const rr = reactor.getBoundingClientRect();
        const cx = rr.left + rr.width/2 - homeRect.left;
        const cy = rr.top + rr.height/2 - homeRect.top;

        // Physics: update all node positions
        applyPhysics(cx, cy);

        // Render islands with small organic wiggle
        islands.forEach(isl => {
            const visX = isl.x + Math.sin(loopTime * isl.speedX + isl.phase) * 4;
            const visY = isl.y + Math.cos(loopTime * isl.speedY + isl.phase * 1.3) * 4;
            isl.el.style.transform = `translate(${visX}px, ${visY}px) translate(-50%, -50%)`;
        });

        // Render nav nodes with small organic wiggle
        navPhysicsNodes.forEach(nav => {
            const visX = nav.x + Math.sin(loopTime * nav.speedX + nav.phase) * 3;
            const visY = nav.y + Math.cos(loopTime * nav.speedY + nav.phase * 1.3) * 3;
            nav.el.style.transform = `translate(${visX}px, ${visY}px) translate(-50%, -50%)`;
        });

        if (!connectionsBuilt) { requestAnimationFrame(animationLoop); return; }

        let idx = 0;

        // Core → nav nodes (line + 2 pulses each)
        navPhysicsNodes.forEach((n) => {
            setLinePos(connectionEls[idx++], cx, cy, n.x, n.y);
            setPulseEndpoints(connectionEls[idx++], cx, cy, n.x, n.y);
            setPulseEndpoints(connectionEls[idx++], cx, cy, n.x, n.y);
        });

        // Core → islands (line + 1 pulse each)
        islands.forEach((isl) => {
            setLinePos(connectionEls[idx++], cx, cy, isl.x, isl.y);
            setPulseEndpoints(connectionEls[idx++], cx, cy, isl.x, isl.y);
        });

        // Logical island → nav connections
        _islandNavLinks.forEach(([iIdx, nIdx, opacity]) => {
            if (iIdx < islands.length && nIdx < navPhysicsNodes.length) {
                setLinePos(connectionEls[idx], islands[iIdx].x, islands[iIdx].y, navPhysicsNodes[nIdx].x, navPhysicsNodes[nIdx].y);
                connectionEls[idx].el.style.opacity = opacity;
            }
            idx++;
        });

        // Logical island → island connections
        _islandIslandLinks.forEach(([iIdx, jIdx, opacity]) => {
            if (iIdx < islands.length && jIdx < islands.length) {
                setLinePos(connectionEls[idx], islands[iIdx].x, islands[iIdx].y, islands[jIdx].x, islands[jIdx].y);
                connectionEls[idx].el.style.opacity = opacity;
            }
            idx++;
        });

        requestAnimationFrame(animationLoop);
    }

    function setLinePos(conn, x1, y1, x2, y2) {
        if (!conn || conn.type !== 'line') return;
        conn.el.setAttribute('x1', x1); conn.el.setAttribute('y1', y1);
        conn.el.setAttribute('x2', x2); conn.el.setAttribute('y2', y2);
    }

    function setPulseEndpoints(conn, x1, y1, x2, y2) {
        if (!conn || conn.type !== 'pulse') return;
        const p = conn.el;
        // JS-driven pulse: calculate position along line from time
        const elapsed = loopTime - conn.delay;
        if (elapsed < 0) { p.setAttribute('opacity', '0'); return; }
        const progress = (elapsed % conn.dur) / conn.dur;
        p.setAttribute('cx', x1 + (x2 - x1) * progress);
        p.setAttribute('cy', y1 + (y2 - y1) * progress);
        // Fade in at start, fade out at end
        let opacity;
        if (progress < 0.1) opacity = (progress / 0.1) * 0.9;
        else if (progress > 0.85) opacity = ((1 - progress) / 0.15) * 0.9;
        else opacity = 0.9;
        p.setAttribute('opacity', opacity);
    }

    // ══════════════════════════════════════
    //  SYNAPSE FIRING (random bright flashes)
    // ══════════════════════════════════════

    function initSynapseFiring() {
        setInterval(() => {
            if (_expandedPageId) return;
            const svg = document.getElementById('synapse-svg');
            const home = document.getElementById('page-home');
            if (!svg || !home) return;
            const hr = home.getBoundingClientRect();
            const reactor = document.querySelector('.arc-reactor-container');
            if (!reactor) return;
            const rr = reactor.getBoundingClientRect();
            const cx = rr.left+rr.width/2-hr.left, cy = rr.top+rr.height/2-hr.top;

            // Pick random target: nav node or island
            const targets = [];
            navPhysicsNodes.forEach(n => targets.push({ x: n.x, y: n.y }));
            islands.forEach(isl => targets.push({ x: isl.x, y: isl.y }));
            if (!targets.length) return;
            const t = targets[Math.floor(Math.random()*targets.length)];

            const flash = document.createElementNS('http://www.w3.org/2000/svg','circle');
            flash.setAttribute('r','4'); flash.setAttribute('fill','#00c8e8');
            flash.setAttribute('filter','url(#sg)');
            const dur = 0.5+Math.random()*0.4;
            ['cx','cy','opacity','r'].forEach(attr => {
                const a = document.createElementNS('http://www.w3.org/2000/svg','animate');
                a.setAttribute('attributeName', attr);
                if (attr==='cx') { a.setAttribute('from',cx); a.setAttribute('to',t.x); }
                if (attr==='cy') { a.setAttribute('from',cy); a.setAttribute('to',t.y); }
                if (attr==='opacity') { a.setAttribute('from','1'); a.setAttribute('to','0'); }
                if (attr==='r') { a.setAttribute('from','4'); a.setAttribute('to','1'); }
                a.setAttribute('dur', dur+'s'); a.setAttribute('fill','freeze');
                flash.appendChild(a);
            });
            svg.appendChild(flash);
            setTimeout(() => flash.remove(), dur*1000+100);
        }, 1800+Math.random()*2500);
    }

    // ══════════════════════════════════════
    //  SPACE+DRAG PAN + MOUSE PARALLAX
    // ══════════════════════════════════════

    let _panX = 0, _panY = 0;
    let _spaceDown = false;
    let _panning = false;
    let _panStartX = 0, _panStartY = 0;
    let _panBaseX = 0, _panBaseY = 0;

    function initParallax() {
        const home = document.getElementById('page-home');
        if (!home) return;
        let mx = 0.5, my = 0.5;

        // Track space key
        document.addEventListener('keydown', e => {
            if (e.code === 'Space' && !e.repeat && !_expandedPageId) {
                // Don't hijack space if typing in an input
                const tag = document.activeElement?.tagName;
                if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
                e.preventDefault();
                _spaceDown = true;
                home.style.cursor = 'grab';
            }
        });
        document.addEventListener('keyup', e => {
            if (e.code === 'Space') {
                _spaceDown = false;
                _panning = false;
                home.style.cursor = '';
            }
        });

        // Pan start
        document.addEventListener('mousedown', e => {
            if (_spaceDown && !_expandedPageId) {
                e.preventDefault();
                _panning = true;
                _panStartX = e.clientX;
                _panStartY = e.clientY;
                _panBaseX = _panX;
                _panBaseY = _panY;
                home.style.cursor = 'grabbing';
            }
        });

        document.addEventListener('mousemove', e => {
            mx = e.clientX / window.innerWidth;
            my = e.clientY / window.innerHeight;

            if (_panning) {
                _panX = _panBaseX + (e.clientX - _panStartX);
                _panY = _panBaseY + (e.clientY - _panStartY);
            }
        });

        document.addEventListener('mouseup', () => {
            if (_panning) {
                _panning = false;
                home.style.cursor = _spaceDown ? 'grab' : '';
            }
        });

        (function pLoop() {
            if (!_expandedPageId) {
                const px = (mx-0.5)*-12 + _panX;
                const py = (my-0.5)*-12 + _panY;
                home.style.transform = `translate(${px}px, ${py}px)`;
            } else {
                home.style.transform = '';
            }
            requestAnimationFrame(pLoop);
        })();
    }

    // ══════════════════════════════════════
    //  NODE HOVER FOCUS
    // ══════════════════════════════════════

    function initNodeHoverFocus() {
        document.querySelectorAll('.nav-node').forEach(node => {
            node.addEventListener('mouseenter', () => {
                node.classList.add('focused');
                document.querySelectorAll('.nav-node').forEach(o => { if (o !== node) o.classList.add('dimmed-node'); });
            });
            node.addEventListener('mouseleave', () => {
                node.classList.remove('focused');
                document.querySelectorAll('.nav-node').forEach(o => o.classList.remove('dimmed-node'));
            });
        });
    }

    // ══════════════════════════════════════
    //  SUB-ISLAND HOVER SYSTEM
    // ══════════════════════════════════════

    // action: 'page:page-id' opens that page, anything else is a quick-action voice command
    const SUB_ISLAND_DATA = {
        'node-projects': [
            { icon: '📂', label: 'OPEN', color: 'cyan', action: 'page:page-projects' },
            { icon: '📋', label: 'TODOS', color: 'green', action: 'page:page-projects' },
            { icon: '🔀', label: 'GIT LOG', color: 'purple', action: 'page:page-projects' },
        ],
        'node-settings': [
            { icon: '🔧', label: 'CONFIGURE', color: 'cyan', action: 'page:page-settings' },
            { icon: '🔌', label: 'API STATUS', color: 'green', action: 'page:page-settings' },
            { icon: '🎤', label: 'TTS', color: 'purple', action: 'page:page-settings' },
        ],
        'node-brain': [
            { icon: '📊', label: 'ANALYTICS', color: 'green', action: 'page:page-brain' },
            { icon: '📜', label: 'VOICE LOG', color: 'purple', action: 'page:page-brain' },
            { icon: '💰', label: 'COSTS', color: 'cyan', action: 'page:page-brain' },
        ],
        'node-briefing': [
            { icon: '☀', label: 'BRIEF ME', color: 'amber', action: 'morning briefing' },
            { icon: '📅', label: 'AGENDA', color: 'green', action: 'page:page-briefing' },
            { icon: '📰', label: 'NEWS', color: 'cyan', action: 'page:page-briefing' },
        ],
        'island-lights': [
            { icon: '💡', label: 'LAMP 1', color: 'amber', action: 'toggle lamp 1' },
            { icon: '💡', label: 'LAMP 3', color: 'amber', action: 'toggle lamp 3' },
            { icon: '🌙', label: 'ALL OFF', color: 'red', action: 'lights off' },
        ],
        'island-spotify': [
            { icon: '⏮', label: 'PREVIOUS', color: 'green', action: 'previous track' },
            { icon: '⏯', label: 'PLAY', color: 'cyan', action: 'play music' },
            { icon: '⏭', label: 'NEXT', color: 'purple', action: 'next track' },
        ],
        'island-email': [
            { icon: '📥', label: 'READ', color: 'cyan', action: 'read emails' },
            { icon: '✉', label: 'COMPOSE', color: 'green', action: 'page:page-briefing' },
        ],
        'island-calendar': [
            { icon: '📅', label: 'SCHEDULE', color: 'green', action: 'get schedule' },
            { icon: '📋', label: 'OPEN', color: 'cyan', action: 'page:page-briefing' },
        ],
    };

    const _subIslandGroups = {};

    function initSubIslands() {
        const home = document.getElementById('page-home');
        if (!home) return;

        Object.entries(SUB_ISLAND_DATA).forEach(([parentId, items]) => {
            const group = { els: [], positions: [], lines: [], visible: false };

            items.forEach(item => {
                const el = document.createElement('div');
                el.className = 'sub-island';
                if (item.color) el.dataset.color = item.color;
                el.innerHTML = `
                    <div class="sub-island-circle">
                        <span class="sub-island-icon">${item.icon}</span>
                    </div>
                    <span class="sub-island-label">${item.label}</span>
                `;
                el.style.left = '0';
                el.style.top = '0';
                el.style.opacity = '0';
                el.style.transform = 'translate(0px, 0px) translate(-50%, -50%) scale(0)';

                // Click handler
                el.addEventListener('click', async () => {
                    if (!item.action) return;

                    // Visual feedback
                    const circle = el.querySelector('.sub-island-circle');
                    circle.style.transform = 'scale(0.85)';
                    setTimeout(() => { circle.style.transform = ''; }, 200);

                    if (item.action.startsWith('page:')) {
                        const pageId = item.action.slice(5);
                        hideSubIslands(parentId);
                        expandNode(pageId, pageId === 'page-ide');
                    } else {
                        // Send as voice quick-action
                        const res = await window.apiFetch('/api/quick-action', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ action: item.action })
                        });
                        if (res && res.status === 'success') {
                            window.showToast(res.message || item.action, 'success');
                        } else {
                            window.showToast('Sent: ' + item.action, 'info');
                        }
                    }
                });

                home.appendChild(el);
                group.els.push(el);
            });

            _subIslandGroups[parentId] = group;

            // Attach hover listeners with grace period for reaching sub-islands
            const parentEl = document.getElementById(parentId);
            if (!parentEl) return;

            let hoverTimeout, hideTimeout;

            function cancelHide() { clearTimeout(hideTimeout); }
            function scheduleHide() {
                hideTimeout = setTimeout(() => hideSubIslands(parentId), 300);
            }

            parentEl.addEventListener('mouseenter', () => {
                if (_expandedPageId || _panning) return;
                cancelHide();
                hoverTimeout = setTimeout(() => showSubIslands(parentId), 150);
            });
            parentEl.addEventListener('mouseleave', () => {
                clearTimeout(hoverTimeout);
                scheduleHide();
            });

            // Sub-islands keep the group alive while hovered
            group.els.forEach(el => {
                el.addEventListener('mouseenter', cancelHide);
                el.addEventListener('mouseleave', scheduleHide);
            });
        });
    }

    function getNodePos(parentId) {
        for (let i = 0; i < navPhysicsNodes.length; i++) {
            if (navPhysicsNodes[i].el.id === parentId) return navPhysicsNodes[i];
        }
        for (let i = 0; i < islands.length; i++) {
            if (islands[i].el.id === parentId) return islands[i];
        }
        return null;
    }

    function showSubIslands(parentId) {
        const group = _subIslandGroups[parentId];
        if (!group || group.visible) return;
        group.visible = true;

        const node = getNodePos(parentId);
        if (!node) return;

        // Evenly spaced around the parent like satellites orbiting a core
        const radius = 100;
        const count = group.els.length;

        group.positions = [];

        // Start from parent position (scale 0), then expand outward
        group.els.forEach((el, i) => {
            // Equal angular spacing around full circle
            const angle = (i / count) * Math.PI * 2 - Math.PI / 2;
            const tx = node.x + Math.cos(angle) * radius;
            const ty = node.y + Math.sin(angle) * radius;
            group.positions.push({ x: tx, y: ty });

            // Start at parent center
            el.style.transition = 'none';
            el.style.opacity = '0';
            el.style.transform = `translate(${node.x}px, ${node.y}px) translate(-50%, -50%) scale(0)`;

            // Animate outward with stagger
            setTimeout(() => {
                el.style.transition = 'opacity 0.35s ease, transform 0.5s cubic-bezier(0.2, 0.9, 0.3, 1)';
                el.style.opacity = '1';
                el.style.transform = `translate(${tx}px, ${ty}px) translate(-50%, -50%) scale(1)`;
                el.classList.add('visible');
            }, 30 + i * 60);
        });

        // Draw connection lines
        const svg = document.getElementById('synapse-svg');
        if (!svg) return;
        group.lines.forEach(l => l.remove());
        group.lines = [];

        group.positions.forEach((target, i) => {
            const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            line.setAttribute('x1', node.x);
            line.setAttribute('y1', node.y);
            line.setAttribute('x2', target.x);
            line.setAttribute('y2', target.y);
            line.setAttribute('stroke', 'rgba(0,200,232,0.3)');
            line.setAttribute('stroke-width', '0.8');
            line.setAttribute('stroke-dasharray', '3 5');
            line.style.opacity = '0';
            line.style.transition = 'opacity 0.3s ease';
            svg.appendChild(line);
            setTimeout(() => { line.style.opacity = '1'; }, i * 70);
            group.lines.push(line);
        });
    }

    function hideSubIslands(parentId) {
        const group = _subIslandGroups[parentId];
        if (!group || !group.visible) return;
        group.visible = false;

        const node = getNodePos(parentId);
        const fallX = node ? node.x : 0;
        const fallY = node ? node.y : 0;

        group.els.forEach((el, i) => {
            // Stagger collapse back into parent
            setTimeout(() => {
                el.style.transition = 'opacity 0.25s ease, transform 0.35s cubic-bezier(0.5, 0, 0.8, 0.2)';
                el.style.opacity = '0';
                el.style.transform = `translate(${fallX}px, ${fallY}px) translate(-50%, -50%) scale(0)`;
                el.classList.remove('visible');
            }, i * 30);
        });

        group.lines.forEach(line => {
            line.style.opacity = '0';
            setTimeout(() => line.remove(), 300);
        });
        group.lines = [];
    }

    // ══════════════════════════════════════
    //  EXPAND / COLLAPSE
    // ══════════════════════════════════════

    function isExpanded() { return _expandedPageId !== null; }

    function expandNode(pageId, fullscreen) {
        if (_transitioning || _expandedPageId === pageId) return;
        _transitioning = true;
        const panel = document.getElementById('expanded-panel');
        const body = document.getElementById('expanded-panel-body');
        const title = document.getElementById('expanded-panel-title');
        const home = document.getElementById('page-home');
        const reactor = document.querySelector('.arc-reactor-container');
        if (!panel||!body||!home) { _transitioning=false; return; }
        const src = document.getElementById(pageId);
        if (!src) { _transitioning=false; return; }
        title.textContent = PAGE_TITLES[pageId]||pageId.replace('page-','').toUpperCase();
        panel.classList.toggle('fullscreen', !!fullscreen);
        home.classList.add('panel-expanded');
        home.style.transform = '';
        reactor.classList.add('dimmed');
        setTimeout(() => {
            body.appendChild(src); src.classList.add('active');
            panel.classList.add('visible'); _expandedPageId = pageId;
            window.dispatchEvent(new CustomEvent('page-expanded', { detail: { pageId } }));
            setTimeout(() => { _transitioning=false; window.dispatchEvent(new Event('resize')); }, 420);
        }, 280);
    }

    function collapseToHub() {
        if (_transitioning || !_expandedPageId) return;
        _transitioning = true;
        const panel = document.getElementById('expanded-panel');
        const body = document.getElementById('expanded-panel-body');
        const home = document.getElementById('page-home');
        const reactor = document.querySelector('.arc-reactor-container');
        const pc = document.querySelector('.pages-container');
        if (!panel||!body||!home||!pc) { _transitioning=false; return; }
        const src = document.getElementById(_expandedPageId);
        panel.classList.remove('visible');
        setTimeout(() => {
            if (src) { src.classList.remove('active'); pc.appendChild(src); }
            home.classList.remove('panel-expanded');
            reactor.classList.remove('dimmed');
            panel.classList.remove('fullscreen'); _expandedPageId = null;
            setTimeout(() => { _transitioning=false; }, 320);
        }, 400);
    }

    // ══════════════════════════════════════
    //  INIT
    // ══════════════════════════════════════

    document.addEventListener('DOMContentLoaded', () => {
        const homePage = document.getElementById('page-home');
        if (homePage) homePage.classList.add('active');

        buildEnergyRays();
        buildNeuralWeb();
        spawnMicroNodes();
        initIslands();
        initNavPhysics();

        // Node clicks (skip if it was a drag)
        document.querySelectorAll('.nav-node').forEach(node => {
            node.addEventListener('click', () => {
                if (_dragMoved) { _dragMoved = false; return; }
                const pid = node.getAttribute('data-page');
                if (isExpanded()) { collapseToHub(); setTimeout(() => expandNode(pid, node.getAttribute('data-fullscreen')==='true'), 800); }
                else expandNode(pid, node.getAttribute('data-fullscreen')==='true');
            });
        });

        document.getElementById('expanded-panel-close')?.addEventListener('click', collapseToHub);
        document.getElementById('expanded-panel')?.addEventListener('click', e => { if (e.target.id==='expanded-panel') collapseToHub(); });
        document.addEventListener('keydown', e => { if (e.key==='Escape' && isExpanded()) collapseToHub(); });

        // Build connections, pre-settle physics, then start animation
        requestAnimationFrame(() => setTimeout(() => {
            buildConnections();

            // Pre-settle: run physics at high speed to find equilibrium
            const home = document.getElementById('page-home');
            const reactor = document.querySelector('.arc-reactor-container');
            if (home && reactor) {
                const hr = home.getBoundingClientRect();
                const rr = reactor.getBoundingClientRect();
                const cx = rr.left + rr.width/2 - hr.left;
                const cy = rr.top + rr.height/2 - hr.top;

                // Temporarily crank up speed for fast convergence
                const savedDamping = PHYSICS.damping;
                const savedMax = PHYSICS.maxSpeed;
                PHYSICS.damping = 0.6;
                PHYSICS.maxSpeed = 8;

                for (let i = 0; i < 800; i++) {
                    applyPhysics(cx, cy);
                }

                // Restore and zero all velocities
                PHYSICS.damping = savedDamping;
                PHYSICS.maxSpeed = savedMax;
                islands.concat(navPhysicsNodes).forEach(n => {
                    n.vx = 0; n.vy = 0;
                });

                // Snap render to settled positions
                islands.forEach(isl => {
                    isl.el.style.transform = `translate(${isl.x}px, ${isl.y}px) translate(-50%, -50%)`;
                });
                navPhysicsNodes.forEach(nav => {
                    nav.el.style.transform = `translate(${nav.x}px, ${nav.y}px) translate(-50%, -50%)`;
                });
            }

            requestAnimationFrame(animationLoop);
        }, 300));

        initParallax();
        initNodeHoverFocus();
        initSubIslands();
        setTimeout(initSynapseFiring, 1500);
    });

    window.neuralNav = { expandNode, collapseToHub, isExpanded };
})();
