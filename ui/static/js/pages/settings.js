document.addEventListener('DOMContentLoaded', () => {

    async function loadStatus() {
        const statuses = await window.apiFetch('/api/settings/status');
        const container = document.getElementById('settings-api-status');
        container.innerHTML = '';
        if(statuses) {
            for(const [api, status] of Object.entries(statuses)) {
                const color = status === "Connected" ? "var(--accent-green)" : "var(--accent-red)";
                container.innerHTML += `
                    <div style="display:flex; justify-content:space-between; margin-bottom:10px; border-bottom:1px solid rgba(255,255,255,0.05); padding-bottom:5px;">
                        <span>${api}</span>
                        <span style="color:${color}">${status}</span>
                    </div>
                `;
            }
        }
    }

    async function loadSettings() {
        const config = await window.apiFetch('/api/settings');
        if(!config) return;

        if(config.tts_engine) document.getElementById('set-tts-engine').value = config.tts_engine;
        if(config.language) document.getElementById('set-language').value = config.language;
    }

    document.getElementById('btn-save-settings').addEventListener('click', async () => {
        const data = {
            tts_engine: document.getElementById('set-tts-engine').value,
            language: document.getElementById('set-language').value,
        };

        const res = await window.apiFetch('/api/settings', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data)
        });

        if(res && res.status === "success") {
            window.showToast("Configuration saved successfully", "success");
        } else {
            window.showToast("Failed to save configuration", "error");
        }
    });

    document.getElementById('btn-refresh-status').addEventListener('click', () => {
        window.showToast("Checking API connections...", "info");
        loadStatus();
    });

    window.addEventListener('page-expanded', (e) => {
        if (e.detail.pageId === 'page-settings') {
            loadStatus();
            loadSettings();
        }
    });
});
