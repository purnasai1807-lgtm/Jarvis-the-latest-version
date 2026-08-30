document.addEventListener('DOMContentLoaded', () => {

    let currentProjects = [];
    let activeProjectId = null;

    async function loadProjects() {
        const projs = await window.apiFetch('/api/projects');
        if(!projs || projs.length === 0) return;
        currentProjects = projs;
        
        const switcher = document.getElementById('project-switcher');
        switcher.innerHTML = '';
        projs.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.name;
            switcher.appendChild(opt);
        });
        
        if(!activeProjectId) activeProjectId = projs[0].id;
        switcher.value = activeProjectId;
        
        renderActiveProject();
    }

    async function renderActiveProject() {
        const proj = currentProjects.find(p => p.id === activeProjectId);
        if(!proj) return;
        
        document.getElementById('proj-name').textContent = proj.name;
        document.getElementById('proj-desc').textContent = proj.description;
        document.getElementById('proj-path').textContent = proj.path;
        document.getElementById('proj-status').textContent = proj.status || 'Active';
        
        renderTodos(proj.todos || []);
        loadGitActivity(proj.id);
    }

    function renderTodos(todos) {
        const list = document.getElementById('todo-list');
        list.innerHTML = '';
        todos.forEach((t, i) => {
            const li = document.createElement('li');
            li.innerHTML = `
                <div style="display:flex; align-items:center; gap:10px;">
                    <input type="checkbox" ${t.done ? 'checked' : ''} data-index="${i}">
                    <span style="text-decoration: ${t.done ? 'line-through' : 'none'}; opacity: ${t.done ? 0.5 : 1}">${t.text}</span>
                </div>
                <button class="sm-btn btn-del" data-index="${i}">X</button>
            `;
            list.appendChild(li);
        });

        // Attach events
        list.querySelectorAll('input[type="checkbox"]').forEach(chk => {
            chk.addEventListener('change', async (e) => {
                const idx = e.target.getAttribute('data-index');
                const p = await window.apiFetch(`/api/projects/${activeProjectId}/todos/${idx}`, {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({done: e.target.checked})
                });
                if(p) {
                    const proj = currentProjects.find(pr => pr.id === activeProjectId);
                    proj.todos = p;
                    renderTodos(p);
                }
            });
        });

        list.querySelectorAll('.btn-del').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const idx = e.target.getAttribute('data-index');
                const p = await window.apiFetch(`/api/projects/${activeProjectId}/todos/${idx}`, {
                    method: 'DELETE'
                });
                if(p) {
                    const proj = currentProjects.find(pr => pr.id === activeProjectId);
                    proj.todos = p;
                    renderTodos(p);
                }
            });
        });
    }

    async function loadGitActivity(pid) {
        const git = await window.apiFetch(`/api/projects/${pid}/git`);
        document.getElementById('proj-branch').textContent = git ? git.branch : 'N/A';
        
        const gitLogContainer = document.getElementById('git-log');
        gitLogContainer.innerHTML = '';
        if(git && git.commits && git.commits.length > 0) {
            git.commits.forEach(c => {
                gitLogContainer.innerHTML += `
                    <div class="timeline-item">
                        <div class="timeline-time text-cyan">${c.hash}</div>
                        <div class="timeline-content" style="font-size:0.9rem">${c.message} <br><span style="opacity:0.6; font-size:0.8rem">- ${c.author}, ${c.time}</span></div>
                    </div>`;
            });
        } else {
            gitLogContainer.innerHTML = `<p style="opacity:0.5">${git?.error || "No commits found."}</p>`;
        }
    }

    document.getElementById('project-switcher').addEventListener('change', (e) => {
        activeProjectId = e.target.value;
        renderActiveProject();
    });

    document.getElementById('btn-add-todo').addEventListener('click', async () => {
        const input = document.getElementById('new-todo-input');
        if(!input.value.trim()) return;
        const p = await window.apiFetch(`/api/projects/${activeProjectId}/todos`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({text: input.value})
        });
        if(p) {
            input.value = '';
            const proj = currentProjects.find(pr => pr.id === activeProjectId);
            proj.todos = p;
            renderTodos(p);
        }
    });

    window.addEventListener('page-expanded', (e) => {
        if (e.detail.pageId === 'page-projects') loadProjects();
    });
});
