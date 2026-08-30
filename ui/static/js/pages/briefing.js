document.addEventListener('DOMContentLoaded', () => {

    async function loadBriefing() {
        const data = await window.apiFetch('/api/briefing');
        if(!data) return;

        document.getElementById('briefing-greeting').textContent = data.greeting;
        document.getElementById('briefing-weather').textContent = data.weather_summary;

        // Agenda
        const agendaContainer = document.getElementById('briefing-agenda-list');
        agendaContainer.innerHTML = '';
        if(data.agenda) {
            data.agenda.forEach(ev => {
                agendaContainer.innerHTML += `
                    <div class="timeline-item">
                        <div class="timeline-time">${ev.time}</div>
                        <div class="timeline-content">${ev.title} <span class="badge">${ev.location}</span></div>
                    </div>`;
            });
        }

        // News
        const newsContainer = document.getElementById('briefing-news-list');
        newsContainer.innerHTML = '';
        if(data.news) {
            data.news.forEach(cat => {
                let html = `<h4 class="text-cyan" style="margin: 10px 0 5px 0;">${cat.category}</h4><ul class="tree-ul" style="padding-left:10px;">`;
                cat.articles.forEach(art => {
                    html += `<li style="margin-bottom:5px;">• ${art.title} <span class="badge" style="opacity:0.7">${art.source}</span></li>`;
                });
                html += `</ul>`;
                newsContainer.innerHTML += html;
            });
        }

        // Memory
        const memContainer = document.getElementById('briefing-memory-list');
        memContainer.innerHTML = '';
        if(data.memory) {
            data.memory.forEach(m => {
                memContainer.innerHTML += `<li><span>${m}</span></li>`;
            });
        }

        // Suggestions
        const suggContainer = document.getElementById('briefing-suggestions-list');
        suggContainer.innerHTML = '';
        if(data.suggestions) {
            data.suggestions.forEach(s => {
                suggContainer.innerHTML += `
                    <div style="background: rgba(255,255,255,0.05); padding: 15px; border-radius: 4px; border-left: 2px solid var(--accent-green);">
                        <p style="margin-bottom: 10px">${s.text}</p>
                        <button class="action-btn" data-action="${s.action}">Execute</button>
                    </div>`;
            });
        }
    }

    document.getElementById('btn-refresh-briefing').addEventListener('click', loadBriefing);
    
    document.getElementById('btn-audio-briefing').addEventListener('click', async () => {
        window.showToast("Starting Audio Briefing...", "info");
        await window.apiFetch('/api/briefing/audio', { method: "POST" });
    });

    window.addEventListener('page-expanded', (e) => {
        if (e.detail.pageId === 'page-briefing') loadBriefing();
    });
});
