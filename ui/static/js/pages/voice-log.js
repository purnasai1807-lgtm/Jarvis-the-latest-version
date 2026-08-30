// ═══════════════════════════════════════════════
// VOICE LOG PAGE — Conversation feed
// ═══════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {

    let _loaded = false;

    async function loadVoiceLog() {
        const logs = await window.apiFetch('/api/voice-log');
        if (!logs) return;

        const feed = document.getElementById('vlog-feed');
        const countEl = document.getElementById('vlog-count');
        const lastEl = document.getElementById('vlog-last-time');
        if (!feed) return;

        countEl.textContent = logs.length;

        if (logs.length === 0) {
            feed.innerHTML = '<div style="color: var(--text-muted); padding: 2rem; text-align: center;">No voice interactions today.</div>';
            lastEl.textContent = '--';
            return;
        }

        // Logs come newest-first from API, reverse for chronological display
        const sorted = [...logs].reverse();

        // Last interaction time
        const lastTs = new Date(sorted[sorted.length - 1].timestamp);
        lastEl.textContent = lastTs.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

        feed.innerHTML = '';
        sorted.forEach(entry => {
            const isUser = entry.direction === 'user';
            const time = new Date(entry.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            const bubble = document.createElement('div');
            bubble.className = 'vlog-bubble ' + (isUser ? 'vlog-user' : 'vlog-jarvis');
            bubble.innerHTML = `
                <div class="vlog-meta">
                    <span class="vlog-who">${isUser ? 'YOU' : 'JARVIS'}</span>
                    <span class="vlog-time">${time}</span>
                </div>
                <div class="vlog-text">${escapeHtml(entry.text)}</div>
            `;
            feed.appendChild(bubble);
        });

        // Scroll to bottom
        const card = feed.closest('.card');
        if (card) card.scrollTop = card.scrollHeight;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Load when page is expanded
    window.addEventListener('page-expanded', (e) => {
        if (e.detail.pageId === 'page-voice-log') {
            loadVoiceLog();
            _loaded = true;
        }
    });
});
