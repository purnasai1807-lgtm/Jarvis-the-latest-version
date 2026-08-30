let costChart, tokenChart;

document.addEventListener('DOMContentLoaded', () => {

    async function loadBrainStats() {
        const stats = await window.apiFetch('/api/brain/stats');
        if(!stats) return;
        document.getElementById('brain-cost').textContent = `$${stats.cost_today.toFixed(2)}`;
        document.getElementById('brain-tokens').textContent = `${(stats.tokens_today / 1000).toFixed(1)}k`;
        document.getElementById('brain-latency').textContent = `${stats.avg_latency.toFixed(1)}s`;
        document.getElementById('brain-calls').textContent = `${stats.calls_today}`;
    }

    async function loadCharts() {
        // Cost Chart
        const costData = await window.apiFetch('/api/brain/cost-over-time');
        if(costData && costData.length > 0) {
            const ctxCost = document.getElementById('cost-chart').getContext('2d');
            if(costChart) costChart.destroy();
            costChart = new Chart(ctxCost, {
                type: 'line',
                data: {
                    labels: costData.map(d => d.date),
                    datasets: [{
                        label: 'Daily Cost ($)',
                        data: costData.map(d => d.cost),
                        borderColor: '#00c8e8',
                        backgroundColor: 'rgba(0, 200, 232, 0.1)',
                        fill: true,
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true,
                    scales: {
                        y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.05)' } },
                        x: { grid: { color: 'rgba(255,255,255,0.05)' } }
                    },
                    plugins: { legend: { display: false } }
                }
            });
        }

        // Token Breakdown Stacked Bar
        const tokenData = await window.apiFetch('/api/brain/token-breakdown');
        if(tokenData && tokenData.length > 0) {
            const ctxToken = document.getElementById('token-chart').getContext('2d');
            if(tokenChart) tokenChart.destroy();
            tokenChart = new Chart(ctxToken, {
                type: 'bar',
                data: {
                    labels: tokenData.map(d => d.date),
                    datasets: [
                        { label: 'Prompt', data: tokenData.map(d => d.prompt), backgroundColor: '#b388ff' },
                        { label: 'Completion', data: tokenData.map(d => d.completion), backgroundColor: '#00e676' }
                    ]
                },
                options: {
                    responsive: true,
                    scales: {
                        y: { stacked: true, grid: { color: 'rgba(255,255,255,0.05)' } },
                        x: { stacked: true, grid: { color: 'rgba(255,255,255,0.05)' } }
                    }
                }
            });
        }
    }

    async function loadVoiceHistory() {
        const hist = await window.apiFetch('/api/brain/voice-history');
        if(!hist) return;
        const tbody = document.querySelector('#voice-history-table tbody');
        tbody.innerHTML = '';
        hist.forEach(row => {
            const tr = document.createElement('tr');
            const isUser = row.direction === 'user';
            const time = row.timestamp ? row.timestamp.split('T')[1]?.substring(0, 8) || '' : '';
            tr.innerHTML = `
                <td style="color: ${isUser ? '#ffa726' : '#00c8e8'}">${isUser ? 'YOU' : 'JARVIS'}</td>
                <td><div style="max-height: 50px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 400px;">${row.text || ''}</div></td>
                <td><span class="badge">${time}</span></td>
            `;
            tbody.appendChild(tr);
        });
    }

    // Load when brain page is expanded
    window.addEventListener('page-expanded', (e) => {
        if (e.detail.pageId === 'page-brain') {
            loadBrainStats();
            loadCharts();
            loadVoiceHistory();
        }
    });
});
