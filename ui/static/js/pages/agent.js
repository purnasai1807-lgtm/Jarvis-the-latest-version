// Agent state — populates the live top-right strip on page-home
// AND the new panels on page-briefing (pending plan, tasks, watches,
// routines, scheduler).

(function () {
    const POLL_MS = 8000;
    let timer = null;
    let lastData = null;

    function el(id) { return document.getElementById(id); }
    function show(node, on) { if (node) node.style.display = on ? '' : 'none'; }

    function setChip(node, text, classes) {
        if (!node) return;
        node.textContent = text;
        node.className = 'agent-chip ' + (classes || '');
    }

    function updateStrip(d) {
        if (!d) return;

        // Presence
        const presence = d.presence || {};
        const state = presence.state || 'unknown';
        const quiet = presence.quiet_hours;
        let label = '—', cls = '';
        if (quiet)            { label = '🌙 QUIET';   cls = 'quiet';    }
        else if (state === 'at_pc')      { label = 'AT PC';     cls = 'at-pc'; }
        else if (state === 'phone_only') { label = 'ON PHONE';  cls = 'on-phone'; }
        else if (state === 'away')       { label = 'AWAY';      cls = 'away'; }
        setChip(el('agent-strip-presence'), label, cls);

        // Tasks
        const tasks = d.tasks || {};
        const running = tasks.running_count || 0;
        const tNode = el('agent-strip-tasks');
        if (tNode) {
            tNode.style.display = running > 0 ? '' : 'none';
            tNode.textContent = `⚙ ${running}`;
        }

        // Watches
        const watches = d.watches || [];
        const fired = watches.filter(w => w.status === 'fired').length;
        const active = watches.filter(w => w.status === 'active').length;
        const wNode = el('agent-strip-watches');
        if (wNode) {
            if (fired > 0)       { wNode.style.display = ''; wNode.textContent = `🔔 ${fired}`; wNode.className = 'agent-chip plan-pending'; }
            else if (active > 0) { wNode.style.display = ''; wNode.textContent = `👁 ${active}`; wNode.className = 'agent-chip'; }
            else                 { wNode.style.display = 'none'; }
        }

        // Pending plan
        const planNode = el('agent-strip-plan');
        if (planNode) {
            planNode.style.display = d.pending_plan ? '' : 'none';
        }

        // Meeting
        const inMeeting = (d.active_brief || '').includes('in a meeting');
        const mNode = el('agent-strip-meeting');
        if (mNode) mNode.style.display = inMeeting ? '' : 'none';
    }

    function renderTasks(list) {
        const container = el('agent-tasks-list');
        if (!container) return;
        if (!list || list.length === 0) {
            container.innerHTML = '<div style="opacity:0.5">No tasks yet.</div>';
            return;
        }
        container.innerHTML = list.slice(0, 6).map(t => {
            const prompt = (t.prompt || '').replace(/</g, '&lt;');
            return `
                <div class="agent-task-row status-${t.status}">
                    <span class="status-dot"></span>
                    <span class="row-label">#${t.id} · ${prompt}</span>
                    <span class="row-meta">${(t.status || '').toUpperCase()}</span>
                </div>`;
        }).join('');
    }

    function renderWatches(list) {
        const container = el('agent-watches-list');
        if (!container) return;
        if (!list || list.length === 0) {
            container.innerHTML = '<div style="opacity:0.5">No watches set.</div>';
            return;
        }
        container.innerHTML = list.slice(0, 8).map(w => {
            const url = (w.url || '').replace(/</g, '&lt;');
            const cond = (w.condition || '').replace(/</g, '&lt;');
            const label = (w.label || '').replace(/</g, '&lt;') ||
                          url.replace(/^https?:\/\//, '').slice(0, 40);
            const last = w.last_message ? ` · ${(w.last_message || '').replace(/</g, '&lt;').slice(0, 60)}` : '';
            return `
                <div class="agent-watch-row status-${w.status}">
                    <span class="status-dot"></span>
                    <span class="row-label">#${w.id} · ${label}${last}</span>
                    <span class="row-meta">${w.interval_minutes}m · ${(w.status || '').toUpperCase()}</span>
                </div>`;
        }).join('');
    }

    function renderRoutines(list) {
        const container = el('agent-routines-list');
        if (!container) return;
        if (!list || list.length === 0) {
            container.innerHTML = '<div style="opacity:0.5">No routines defined.</div>';
            return;
        }
        container.innerHTML = list.map(r => {
            const phrases = (r.voice_phrases || []).slice(0, 1).join(', ');
            const sched = (r.schedule || []).map(s => `${s.time} ${s.days}`).join(', ');
            const meta = phrases ? `🎙 ${phrases}` : (sched ? `⏰ ${sched}` : '');
            return `
                <button class="agent-routine-pill" data-routine="${r.name}">
                    <span>▶ ${r.name}</span>
                    <span class="routine-trigger">${meta}</span>
                </button>`;
        }).join('');
        container.querySelectorAll('[data-routine]').forEach(btn => {
            btn.addEventListener('click', async () => {
                const name = btn.dataset.routine;
                btn.style.opacity = '0.5';
                try {
                    await window.apiFetch('/api/routines/run', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name })
                    });
                    if (window.showToast) window.showToast(`Running "${name}"…`);
                } catch (e) {
                    if (window.showToast) window.showToast(`Run failed: ${e}`, 'error');
                }
                btn.style.opacity = '';
            });
        });
    }

    function renderScheduler(jobs) {
        const container = el('agent-scheduler-list');
        if (!container) return;
        if (!jobs || jobs.length === 0) {
            container.innerHTML = '<div style="opacity:0.5">Scheduler not running.</div>';
            return;
        }
        const lines = jobs.map(j => {
            const sec = j.next_fire_in || 0;
            const eta = sec >= 3600
                ? `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`
                : sec >= 60
                    ? `${Math.floor(sec / 60)}m ${sec % 60}s`
                    : `${sec}s`;
            return `· ${j.name.padEnd(28, ' ')}  next in ${eta}`;
        }).join('<br>');
        container.innerHTML = lines;
    }

    function renderPendingPlan(plan) {
        const card = el('agent-pending-plan-card');
        if (!card) return;
        if (!plan) { card.style.display = 'none'; return; }
        card.style.display = '';
        const summary = (plan.summary || '').replace(/</g, '&lt;');
        el('agent-plan-summary').innerHTML = `<span style="opacity:0.6">#${plan.id}:</span> ${summary}`;
        el('agent-plan-steps').innerHTML = (plan.step_summaries || [])
            .map(s => `<li>${(s || '').replace(/</g, '&lt;')}</li>`).join('');
    }

    async function tick() {
        try {
            const data = await window.apiFetch('/api/dashboard');
            if (!data) return;
            lastData = data;
            updateStrip(data);
            renderTasks((data.tasks && data.tasks.recent) || []);
            renderWatches(data.watches || []);
            renderRoutines(data.routines || []);
            renderScheduler(data.scheduler || []);
            renderPendingPlan(data.pending_plan || null);
        } catch (_) {}
    }

    function wirePlanButtons() {
        const ok = el('btn-plan-confirm');
        const no = el('btn-plan-cancel');
        if (ok) ok.addEventListener('click', async () => {
            try {
                const r = await window.apiFetch('/api/plan/confirm', { method: 'POST' });
                if (window.showToast) window.showToast(r?.result || 'Confirmed');
                tick();
            } catch (e) {
                if (window.showToast) window.showToast(`Confirm failed: ${e}`, 'error');
            }
        });
        if (no) no.addEventListener('click', async () => {
            try {
                const r = await window.apiFetch('/api/plan/cancel', { method: 'POST' });
                if (window.showToast) window.showToast(r?.result || 'Cancelled');
                tick();
            } catch (e) {
                if (window.showToast) window.showToast(`Cancel failed: ${e}`, 'error');
            }
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        wirePlanButtons();
        tick();
        timer = setInterval(tick, POLL_MS);

        // Refresh immediately when the user opens the briefing page
        window.addEventListener('page-expanded', (e) => {
            if (e?.detail?.pageId === 'page-briefing') tick();
        });
    });

    // Expose for debugging from console
    window.__agentTick = tick;
    window.__agentLast = () => lastData;
})();
