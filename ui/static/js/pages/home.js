// ═══════════════════════════════════════════════
// HOME PAGE — Iron Man HUD Controller
// ═══════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {

    // ── Spawn dense background particles ──
    const particleContainer = document.getElementById('hud-particles');
    if (particleContainer) {
        for (let i = 0; i < 100; i++) {
            const p = document.createElement('div');
            p.className = 'hud-particle';
            p.style.left = Math.random() * 100 + '%';
            p.style.bottom = '-5px';
            p.style.animationDuration = (10 + Math.random() * 25) + 's';
            p.style.animationDelay = (Math.random() * 20) + 's';
            p.style.opacity = (0.15 + Math.random() * 0.5);
            const size = (1 + Math.random() * 2.5);
            p.style.width = p.style.height = size + 'px';
            // Some particles glow different colors
            const roll = Math.random();
            if (roll > 0.9) {
                p.style.background = 'rgba(179,136,255,0.4)';
            } else if (roll > 0.8) {
                p.style.background = 'rgba(0,230,118,0.4)';
            }
            particleContainer.appendChild(p);
        }
    }

    // ── Generate tick marks on outer arc ring ──
    const ticksGroup = document.getElementById('arc-ticks');
    if (ticksGroup) {
        for (let i = 0; i < 72; i++) {
            const angle = (i * 5) * Math.PI / 180;
            const r1 = 192, r2 = (i % 6 === 0) ? 198 : 195;
            const x1 = 200 + r1 * Math.cos(angle);
            const y1 = 200 + r1 * Math.sin(angle);
            const x2 = 200 + r2 * Math.cos(angle);
            const y2 = 200 + r2 * Math.sin(angle);
            const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            line.setAttribute('x1', x1);
            line.setAttribute('y1', y1);
            line.setAttribute('x2', x2);
            line.setAttribute('y2', y2);
            line.setAttribute('stroke', 'rgba(0,200,232,0.15)');
            line.setAttribute('stroke-width', (i % 6 === 0) ? '1.5' : '0.5');
            ticksGroup.appendChild(line);
        }
    }

    // ── Helper: set arc ring progress ──
    function setArcProgress(elementId, percent, circumference) {
        const el = document.getElementById(elementId);
        if (!el) return;
        const offset = circumference - (percent / 100) * circumference;
        el.style.strokeDashoffset = offset;
    }

    // ── Helper: set mini ring progress ──
    function setMiniRing(elementId, percent) {
        const el = document.getElementById(elementId);
        if (!el) return;
        const circ = 150.8;
        el.style.strokeDashoffset = circ - (percent / 100) * circ;
    }

    // ── Weather icon mapping ──
    function getWeatherIcon(description) {
        const d = (description || '').toLowerCase();
        if (d.includes('clear') || d.includes('sunny')) return '☀';
        if (d.includes('partly cloudy') || d.includes('partly')) return '⛅';
        if (d.includes('cloud') || d.includes('overcast')) return '☁';
        if (d.includes('rain') || d.includes('drizzle') || d.includes('shower')) return '🌧';
        if (d.includes('thunder') || d.includes('storm')) return '⛈';
        if (d.includes('snow') || d.includes('sleet')) return '❄';
        if (d.includes('fog') || d.includes('mist') || d.includes('haze')) return '🌫';
        if (d.includes('wind')) return '💨';
        return '🌤';
    }

    // ── Parse email data ──
    function renderEmails(emailData) {
        const stack = document.getElementById('email-stack');
        const badge = document.getElementById('email-badge');
        if (!stack) return;

        if (typeof emailData === 'string') {
            // Try to count emails from the string
            const lines = emailData.split('\n').filter(l => l.trim());
            badge.textContent = lines.length;
            stack.innerHTML = '';
            // Parse "From: X Subject: Y" patterns
            const emailRegex = /(?:From|from)[:\s]+([^\n]+?)(?:\s*Subject[:\s]+(.+?))?(?:\n|$)/gi;
            let match;
            let found = false;
            while ((match = emailRegex.exec(emailData)) !== null) {
                found = true;
                const sender = match[1].trim().substring(0, 30);
                const subject = (match[2] || '').trim().substring(0, 40);
                const initial = sender.charAt(0).toUpperCase();
                stack.innerHTML += `
                    <div class="email-item">
                        <div class="email-avatar">${initial}</div>
                        <div class="email-text">
                            <div class="email-sender">${sender}</div>
                            <div class="email-subject">${subject || 'No subject'}</div>
                        </div>
                    </div>`;
            }
            if (!found) {
                // Fallback: just show first few lines
                lines.slice(0, 4).forEach(line => {
                    const trimmed = line.trim().substring(0, 50);
                    stack.innerHTML += `
                        <div class="email-item">
                            <div class="email-avatar">@</div>
                            <div class="email-text">
                                <div class="email-sender">${trimmed}</div>
                            </div>
                        </div>`;
                });
                badge.textContent = lines.length;
            }
        } else {
            badge.textContent = '0';
            stack.innerHTML = '<div class="email-item"><div class="email-text"><div class="email-sender" style="color:var(--text-muted)">No emails</div></div></div>';
        }
    }

    // ── Parse light data ──
    function renderLights(lightData) {
        const container = document.getElementById('light-bulbs');
        if (!container) return;

        if (typeof lightData === 'string') {
            // Parse "Lamp X: on/off, brightness" patterns
            const lights = [];
            const regex = /(?:color\s+)?lamp\s*(\d+)[:\s]+(\w+)/gi;
            let match;
            while ((match = regex.exec(lightData)) !== null) {
                lights.push({
                    id: match[1],
                    state: match[2].toLowerCase() === 'on' ? 'on' : 'off'
                });
            }

            if (lights.length === 0) {
                // Fallback: just show generic orbs
                container.innerHTML = `
                    <div class="light-orb on" style="background:#ffa726; color:#ffa726;">
                        <span class="light-orb-label">Lamp 1</span>
                    </div>
                    <div class="light-orb on" style="background:#ffa726; color:#ffa726;">
                        <span class="light-orb-label">Lamp 2</span>
                    </div>`;
                return;
            }

            container.innerHTML = '';
            const colors = ['#ffa726', '#00c8e8', '#e040fb', '#1db954', '#ff5252'];
            lights.forEach((l, i) => {
                const color = colors[i % colors.length];
                container.innerHTML += `
                    <div class="light-orb ${l.state}" style="background:${color}; color:${color};">
                        <span class="light-orb-label">Lamp ${l.id}</span>
                    </div>`;
            });
        } else {
            container.innerHTML = '<span style="color:var(--text-muted); font-size:0.75rem;">Lights unavailable</span>';
        }
    }

    // ── Update time marker position on calendar arc ──
    function updateTimeMarker() {
        const marker = document.getElementById('time-marker');
        if (!marker) return;
        const now = new Date();
        const minutesSinceMidnight = now.getHours() * 60 + now.getMinutes();
        const dayFraction = minutesSinceMidnight / 1440;
        const angle = (dayFraction * 360 - 90) * Math.PI / 180;
        const r = 175;
        marker.setAttribute('cx', 200 + r * Math.cos(angle));
        marker.setAttribute('cy', 200 + r * Math.sin(angle));

        // Also set the calendar ring progress
        setArcProgress('arc-calendar', dayFraction * 100, 1099.56);
    }

    // ── Parse calendar for next event ──
    function renderCalendar(calData) {
        const countdownEl = document.getElementById('cal-countdown');
        const nameEl = document.getElementById('cal-event-name');
        const timeEl = document.getElementById('cal-event-time');

        if (typeof calData === 'string') {
            if (calData.toLowerCase().includes('no event') || calData.toLowerCase().includes('no schedule') || calData.toLowerCase().includes('nothing')) {
                countdownEl.textContent = 'FREE';
                nameEl.textContent = 'No events scheduled';
                timeEl.textContent = 'for today';
            } else {
                // Try to extract first event
                const timeMatch = calData.match(/(\d{1,2}:\d{2})/);
                if (timeMatch) {
                    timeEl.textContent = timeMatch[1];
                    // Calculate countdown
                    const now = new Date();
                    const [h, m] = timeMatch[1].split(':').map(Number);
                    const eventTime = new Date(now);
                    eventTime.setHours(h, m, 0, 0);
                    const diff = eventTime - now;
                    if (diff > 0) {
                        const mins = Math.floor(diff / 60000);
                        if (mins > 60) {
                            countdownEl.textContent = `${Math.floor(mins/60)}h ${mins%60}m`;
                        } else {
                            countdownEl.textContent = `${mins}min`;
                        }
                    } else {
                        countdownEl.textContent = 'NOW';
                    }
                    // Get event name - text after the time
                    const afterTime = calData.substring(calData.indexOf(timeMatch[1]) + timeMatch[1].length);
                    nameEl.textContent = afterTime.split('\n')[0].replace(/^[\s\-:]+/, '').substring(0, 40) || 'Event';
                } else {
                    countdownEl.textContent = '--';
                    nameEl.textContent = calData.substring(0, 50);
                    timeEl.textContent = '';
                }
            }
        } else {
            countdownEl.textContent = 'FREE';
            nameEl.textContent = 'No events scheduled';
            timeEl.textContent = '';
        }
    }

    // ── Build ticker text from data ──
    function updateTicker(data) {
        const ticker = document.getElementById('ticker-content');
        if (!ticker) return;

        const parts = ['JARVIS SYSTEMS ONLINE'];

        if (data.weather) {
            parts.push(`WEATHER: ${data.weather.temp_c}C ${data.weather.description}`);
        }
        if (data.spotify && typeof data.spotify === 'string' && !data.spotify.includes('Could not')) {
            const trackMatch = data.spotify.match(/Playing[:\s]+(.+?)(?:\n|$)/i);
            if (trackMatch) parts.push(`NOW PLAYING: ${trackMatch[1].substring(0, 50)}`);
        }
        if (data.calendar && typeof data.calendar === 'string' && !data.calendar.toLowerCase().includes('no')) {
            parts.push(`AGENDA: ${data.calendar.substring(0, 60)}`);
        }

        const now = new Date();
        parts.push(`LOCAL TIME: ${now.toLocaleTimeString()}`);
        parts.push(`DATE: ${now.toLocaleDateString('en-US', {weekday:'long', year:'numeric', month:'long', day:'numeric'})}`);

        ticker.textContent = parts.join('  ──  ') + '  ──  ' + parts.join('  ──  ');
    }

    // ── Spotify rendering ──
    function renderSpotify(spotifyData) {
        const track = document.getElementById('spotify-track');
        const artist = document.getElementById('spotify-artist');
        const vinyl = document.getElementById('vinyl-disc');

        if (typeof spotifyData === 'string') {
            const playingMatch = spotifyData.match(/Playing[:\s]+(.+?)(?:\s+by\s+(.+?))?(?:\s*[\(\[]|$|\n)/i);
            if (playingMatch) {
                track.textContent = playingMatch[1].trim();
                artist.textContent = playingMatch[2] ? playingMatch[2].trim() : '';
                vinyl.classList.add('spinning');
            } else if (spotifyData.toLowerCase().includes('playing')) {
                // Generic playing state
                track.textContent = spotifyData.substring(0, 40);
                artist.textContent = '';
                vinyl.classList.add('spinning');
            } else {
                track.textContent = spotifyData.substring(0, 40) || 'Nothing playing';
                artist.textContent = '';
                vinyl.classList.remove('spinning');
            }
        } else {
            track.textContent = 'Nothing playing';
            artist.textContent = '';
            vinyl.classList.remove('spinning');
        }
    }

    // ── Load all home data ──
    async function loadHomeData() {
        const data = await window.apiFetch('/api/dashboard');
        if (!data) return;

        // Uptime + interactions
        if (data.system) {
            document.getElementById('arc-uptime').textContent = data.system.uptime_hours.toFixed(1) + 'h';
            document.getElementById('tele-uptime').textContent = 'Uptime: ' + data.system.uptime_hours.toFixed(1) + 'h';
        }

        const voiceLog = await window.apiFetch('/api/voice-log');
        if (voiceLog) {
            document.getElementById('arc-interactions').textContent = voiceLog.length + ' interactions';
        }

        // Weather
        if (data.weather) {
            document.getElementById('weather-icon').textContent = getWeatherIcon(data.weather.description);
            document.getElementById('weather-temp').textContent = data.weather.temp_c + '°C';
            document.getElementById('weather-desc').textContent = data.weather.description;
            document.getElementById('weather-details').textContent =
                `Feels ${data.weather.feels_like}°C | ${data.weather.humidity}% humidity | ${data.weather.wind_kmph} km/h wind`;
        } else {
            document.getElementById('weather-icon').textContent = '?';
            document.getElementById('weather-temp').textContent = '--°';
            document.getElementById('weather-desc').textContent = 'Offline';
        }

        // Calendar
        renderCalendar(data.calendar);

        // Email
        renderEmails(data.emails);

        // Spotify
        renderSpotify(data.spotify);

        // Lights
        renderLights(data.lights);

        // Ticker
        updateTicker(data);
    }

    // ── Poll system stats (CPU/RAM/GPU) ──
    async function pollSystem() {
        const sys = await window.apiFetch('/api/system');
        if (!sys) return;

        const cpu = sys.cpu_percent || 0;
        const ram = sys.ram_percent || 0;
        const gpu = sys.gpu_percent || 0;

        // Arc reactor rings
        setArcProgress('arc-cpu', cpu, 911.06);
        setArcProgress('arc-ram', ram, 785.4);
        setArcProgress('arc-gpu', gpu, 659.73);

        // Ring labels
        document.getElementById('ring-label-cpu').textContent = `CPU ${Math.round(cpu)}%`;
        document.getElementById('ring-label-ram').textContent = `RAM ${Math.round(ram)}%`;
        document.getElementById('ring-label-gpu').textContent = `GPU ${Math.round(gpu)}%`;

        // Mini rings in telemetry panel
        setMiniRing('mini-cpu', cpu);
        setMiniRing('mini-ram', ram);
        setMiniRing('mini-gpu', gpu);

        // Mini ring value labels
        document.getElementById('tele-cpu').textContent = Math.round(cpu) + '%';
        document.getElementById('tele-ram').textContent = Math.round(ram) + '%';
        document.getElementById('tele-gpu').textContent = Math.round(gpu) + '%';
    }

    // ── Claude session usage ──
    async function pollClaudeUsage() {
        const stats = await window.apiFetch('/api/session-stats');
        if (!stats) return;

        const pctEl = document.getElementById('claude-usage-pct');
        const modelEl = document.getElementById('claude-usage-model');
        const resetEl = document.getElementById('claude-reset-timer');
        const barEl = document.getElementById('claude-usage-bar');
        const costEl = document.getElementById('claude-cost-line');
        if (!pctEl) return;

        // Model name (shorten)
        const model = stats.model || '--';
        const shortModel = model.replace('claude-', '').replace(/-/g, ' ');
        modelEl.textContent = shortModel;

        // Cost
        const cost = stats.total_cost_usd || 0;
        costEl.textContent = '$' + cost.toFixed(2);

        // Rate limit info
        const rl = stats.rate_limit || {};
        const resetTs = rl.five_hour_reset || rl.resetsAt;
        if (resetTs) {
            const resetDate = new Date(resetTs * 1000);
            const now = new Date();
            const diffMin = Math.max(0, Math.round((resetDate - now) / 60000));
            const h = Math.floor(diffMin / 60), m = diffMin % 60;
            resetEl.textContent = 'Resets ' + (h > 0 ? h + 'h ' : '') + m + 'm';
        } else {
            resetEl.textContent = '--';
        }

        // Plan usage percentage from Anthropic API utilization headers
        const utilization = rl.five_hour_utilization;
        const usagePct = utilization != null ? Math.round(utilization * 100) : null;

        if (usagePct != null) {
            pctEl.textContent = usagePct + '%';
        } else {
            pctEl.textContent = '--%';
        }

        // Bar matches the percentage
        const barPct = usagePct != null ? usagePct : 0;
        barEl.style.width = Math.max(2, barPct) + '%';
        barEl.classList.remove('warn', 'critical');
        if (barPct > 70) barEl.classList.add('warn');
        if (barPct > 90) barEl.classList.add('critical');
    }

    // ── Quick actions ──
    document.querySelectorAll('.radial-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const action = btn.getAttribute('data-action');
            btn.style.transform = 'translateY(-4px) scale(0.9)';
            setTimeout(() => btn.style.transform = '', 200);

            const res = await window.apiFetch('/api/quick-action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action })
            });
            if (res && res.status === 'success') {
                window.showToast(res.message, 'success');
            } else {
                window.showToast('Action failed', 'error');
            }
        });
    });

    // ── Spotify controls ──
    document.querySelectorAll('.sp-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const action = btn.getAttribute('data-action');
            await window.apiFetch('/api/quick-action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: action === 'play' ? 'play music' : action + ' track' })
            });
        });
    });

    // ── Initialize ──
    loadHomeData();
    pollSystem();
    pollClaudeUsage();
    updateTimeMarker();

    // Refresh intervals
    setInterval(pollSystem, 5000);
    setInterval(pollClaudeUsage, 15000);
    setInterval(updateTimeMarker, 30000);
    setInterval(loadHomeData, 60000);
});
