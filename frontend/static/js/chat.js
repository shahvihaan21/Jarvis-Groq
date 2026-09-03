// Jarvis AI Technical Workbench — Groq Provider Frontend Engine
// State management, SSE resilience, resizable sidebar, and privacy-safe context ingestion.

let chatHistory = [];
let activeConversationId = null;
let uiState = 'idle'; // 'idle' | 'connecting' | 'generating' | 'completed' | 'error'
let activeController = null;
let shouldStickToBottom = true;
let ingestedArtifacts = []; // Array of attached context items { id, name, type, content }

const MAX_HISTORY_TURNS = 12;
const MAX_MESSAGE_CHARS = 8000;
const STORAGE_KEY = 'jarvisConversations';
const SETTINGS_KEY = 'jarvisSettings';
const SIDEBAR_WIDTH_KEY = 'jarvisSidebarWidth';
const PROJECT_META_KEY = 'jarvisProjectMeta';

const MIN_SIDEBAR_WIDTH = 220;
const MAX_SIDEBAR_WIDTH = 480;
const DEFAULT_SIDEBAR_WIDTH = 280;

const defaultSettings = { theme: 'dark', font: 'medium', density: 'comfortable', timestamps: false };

// ---------------------------------------------------------------------------
// Security & Secret Redaction (Req 21)
// ---------------------------------------------------------------------------

const SECRET_PATTERNS = [
    /gsk_[a-zA-Z0-9]{20,}/g,                        // Groq API keys
    /sk-[a-zA-Z0-9]{20,}/g,                         // OpenAI API keys
    /AKIA[0-9A-Z]{16}/g,                             // AWS Access Key IDs
    /Bearer\s+[a-zA-Z0-9\._\-]{20,}/gi,              // Authorization Bearer tokens
    /-----BEGIN\s+[A-Z\s]+PRIVATE\s+KEY-----[\s\S]*?-----END\s+[A-Z\s]+PRIVATE\s+KEY-----/g, // Private keys
    /(?:password|secret|api_key|token|access_key)\s*[:=]\s*["']?([^\s"']{8,})["']?/gi, // Secret assignments
];

function detectAndRedactSecrets(text) {
    if (!text || typeof text !== 'string') return { hasSecrets: false, redactedText: text || '' };
    let hasSecrets = false;
    let redacted = text;

    SECRET_PATTERNS.forEach(pattern => {
        if (pattern.test(redacted)) {
            hasSecrets = true;
            redacted = redacted.replace(pattern, '[REDACTED_SECRET]');
        }
    });

    return { hasSecrets, redactedText: redacted };
}

function updateSecretAlert(hasSecrets) {
    const banner = document.getElementById('secretAlertBanner');
    if (banner) {
        banner.classList.toggle('d-none', !hasSecrets);
    }
}

// ---------------------------------------------------------------------------
// LocalStorage Persistence & Settings (Req 5)
// ---------------------------------------------------------------------------

function getSettings() {
    try {
        return { ...defaultSettings, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}') };
    } catch (_) {
        return { ...defaultSettings };
    }
}

function saveSettings(s) {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
    applySettings(s);
}

function getConversations() {
    try {
        const data = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
        return Array.isArray(data) ? data : [];
    } catch (_) {
        return [];
    }
}

function saveConversations(list) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
    renderConversationList();
}

function makeConversation(messages = []) {
    return {
        id: crypto.randomUUID(),
        title: titleFor(messages),
        messages,
        createdAt: Date.now(),
        updatedAt: Date.now()
    };
}

function titleFor(messages) {
    const userMsg = messages.find(x => x.role === 'user');
    return userMsg ? userMsg.content.replace(/\s+/g, ' ').trim().slice(0, 48) : 'Technical Session';
}

function activeConversation() {
    return getConversations().find(x => x.id === activeConversationId);
}

function syncActiveConversation() {
    const all = getConversations();
    const idx = all.findIndex(x => x.id === activeConversationId);
    if (idx < 0 || !chatHistory.length) return;
    all[idx].messages = chatHistory;
    all[idx].title = titleFor(chatHistory);
    all[idx].updatedAt = Date.now();
    saveConversations(all);
}

// ---------------------------------------------------------------------------
// Resizable Sidebar (Req 22)
// ---------------------------------------------------------------------------

function initSidebarResizer() {
    const resizer = document.getElementById('sidebarResizer');
    const appWrapper = document.getElementById('appWrapper');
    if (!resizer || !appWrapper) return;

    // Load saved width
    const savedWidth = parseInt(localStorage.getItem(SIDEBAR_WIDTH_KEY), 10);
    const initialWidth = (savedWidth >= MIN_SIDEBAR_WIDTH && savedWidth <= MAX_SIDEBAR_WIDTH) ? savedWidth : DEFAULT_SIDEBAR_WIDTH;
    setSidebarWidth(initialWidth);

    let isDragging = false;

    function onPointerDown(e) {
        if (window.innerWidth <= 768) return; // Disable resizer on mobile overlay view
        isDragging = true;
        resizer.classList.add('is-dragging');
        document.body.classList.add('is-resizing');
        e.preventDefault();
    }

    function onPointerMove(e) {
        if (!isDragging) return;
        const clientX = e.touches ? e.touches[0].clientX : e.clientX;
        let newWidth = clientX;
        if (newWidth < MIN_SIDEBAR_WIDTH) newWidth = MIN_SIDEBAR_WIDTH;
        if (newWidth > MAX_SIDEBAR_WIDTH) newWidth = MAX_SIDEBAR_WIDTH;
        setSidebarWidth(newWidth);
    }

    function onPointerUp() {
        if (!isDragging) return;
        isDragging = false;
        resizer.classList.remove('is-dragging');
        document.body.classList.remove('is-resizing');
    }

    resizer.addEventListener('mousedown', onPointerDown);
    resizer.addEventListener('touchstart', onPointerDown);
    window.addEventListener('mousemove', onPointerMove);
    window.addEventListener('touchmove', onPointerMove);
    window.addEventListener('mouseup', onPointerUp);
    window.addEventListener('touchend', onPointerUp);
}

function setSidebarWidth(width) {
    const appWrapper = document.getElementById('appWrapper');
    if (appWrapper) {
        appWrapper.style.setProperty('--sidebar-width', `${width}px`);
        localStorage.setItem(SIDEBAR_WIDTH_KEY, width);
    }
}

// ---------------------------------------------------------------------------
// UI State Management (Req 2)
// ---------------------------------------------------------------------------

function setUIState(newState, detailMessage = '') {
    uiState = newState;
    const badge = document.getElementById('uiStatusBadge');
    const textEl = document.getElementById('statusIndicatorText');
    const promptInput = document.getElementById('promptInput');
    const sendBtn = document.getElementById('sendBtn');
    const stopBtn = document.getElementById('stopBtn');

    const isBusy = (newState === 'connecting' || newState === 'generating');

    if (promptInput) promptInput.disabled = isBusy;
    if (sendBtn) sendBtn.disabled = isBusy;
    if (stopBtn) stopBtn.hidden = !isBusy;

    if (badge) {
        badge.className = `ui-status-badge status-${newState}`;
    }

    if (textEl) {
        switch (newState) {
            case 'connecting':
                textEl.textContent = detailMessage || 'Connecting...';
                break;
            case 'generating':
                textEl.textContent = detailMessage || 'Generating...';
                break;
            case 'completed':
                textEl.textContent = 'Completed';
                break;
            case 'error':
                textEl.textContent = detailMessage || 'Error';
                break;
            case 'idle':
            default:
                textEl.textContent = 'Ready';
                break;
        }
    }

    if (!isBusy && promptInput) {
        promptInput.focus();
        resizeComposer();
    }
}

// ---------------------------------------------------------------------------
const INGESTION_COLLAPSED_KEY = 'jarvisIngestionCollapsed';

function toggleIngestionZone() {
    const zone = document.getElementById('ingestionZone');
    if (zone) {
        const isCollapsed = zone.classList.toggle('collapsed');
        localStorage.setItem(INGESTION_COLLAPSED_KEY, isCollapsed ? 'true' : 'false');
    }
}

function loadIngestionState() {
    const zone = document.getElementById('ingestionZone');
    if (!zone) return;
    const isCollapsed = localStorage.getItem(INGESTION_COLLAPSED_KEY);
    if (isCollapsed === 'false') {
        zone.classList.remove('collapsed');
    } else if (isCollapsed === 'true') {
        zone.classList.add('collapsed');
    }
}


async function extractPdfText(arrayBuffer) {
    try {
        if (window.pdfjsLib) {
            window.pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
            const pdf = await window.pdfjsLib.getDocument({ data: arrayBuffer }).promise;
            const textParts = [];
            for (let i = 1; i <= pdf.numPages; i++) {
                const page = await pdf.getPage(i);
                const content = await page.getTextContent();
                const pageText = content.items.map(item => item.str).join(' ');
                if (pageText.trim()) textParts.push(`--- Page ${i} ---\n${pageText.trim()}`);
            }
            return textParts.join('\n\n');
        }
    } catch (e) {
        console.warn('PDF extraction fallback:', e);
    }
    return '';
}

async function extractDocxText(arrayBuffer) {
    try {
        if (window.JSZip) {
            const zip = await window.JSZip.loadAsync(arrayBuffer);
            const docXml = await zip.file("word/document.xml")?.async("text");
            if (docXml) {
                const parser = new DOMParser();
                const xmlDoc = parser.parseFromString(docXml, "text/xml");
                const paragraphs = Array.from(xmlDoc.getElementsByTagName("w:p"));
                return paragraphs.map(p => p.textContent.trim()).filter(Boolean).join('\n');
            }
        }
    } catch (e) {
        console.warn('DOCX extraction fallback:', e);
    }
    return '';
}

async function extractPptxText(arrayBuffer) {
    try {
        if (window.JSZip) {
            const zip = await window.JSZip.loadAsync(arrayBuffer);
            const slideFiles = Object.keys(zip.files).filter(f => f.startsWith("ppt/slides/slide") && f.endsWith(".xml"));
            slideFiles.sort((a, b) => {
                const numA = parseInt((a.match(/\d+/) || [0])[0], 10);
                const numB = parseInt((b.match(/\d+/) || [0])[0], 10);
                return numA - numB;
            });

            const slideTexts = [];
            for (let i = 0; i < slideFiles.length; i++) {
                const xmlText = await zip.file(slideFiles[i]).async("text");
                const parser = new DOMParser();
                const xmlDoc = parser.parseFromString(xmlText, "text/xml");
                const textNodes = Array.from(xmlDoc.getElementsByTagName("a:t"));
                const text = textNodes.map(node => node.textContent.trim()).filter(Boolean).join(' ');
                if (text) {
                    slideTexts.push(`--- Slide ${i + 1} ---\n${text}`);
                }
            }
            return slideTexts.join('\n\n');
        }
    } catch (e) {
        console.warn('PPTX extraction fallback:', e);
    }
    return '';
}

async function parseFileContent(file) {
    const fileName = file.name.toLowerCase();
    return new Promise((resolve) => {
        const reader = new FileReader();

        if (fileName.endsWith('.pdf')) {
            reader.onload = async (e) => {
                const text = await extractPdfText(e.target.result);
                resolve(text || `[PDF File attached: ${file.name} (${file.size} bytes)]`);
            };
            reader.readAsArrayBuffer(file);
        } else if (fileName.endsWith('.docx') || fileName.endsWith('.doc')) {
            reader.onload = async (e) => {
                const text = await extractDocxText(e.target.result);
                resolve(text || `[DOCX Document attached: ${file.name} (${file.size} bytes)]`);
            };
            reader.readAsArrayBuffer(file);
        } else if (fileName.endsWith('.pptx') || fileName.endsWith('.ppt')) {
            reader.onload = async (e) => {
                const text = await extractPptxText(e.target.result);
                resolve(text || `[PPTX Presentation attached: ${file.name} (${file.size} bytes)]`);
            };
            reader.readAsArrayBuffer(file);
        } else {
            reader.onload = (e) => {
                resolve(e.target.result || '');
            };
            reader.readAsText(file);
        }
    });
}

async function handleFileIngestion(event) {
    const files = event.target.files;
    if (!files || !files.length) return;

    let foundSecrets = false;
    for (const file of Array.from(files)) {
        const rawContent = await parseFileContent(file);
        const { hasSecrets, redactedText } = detectAndRedactSecrets(rawContent);
        if (hasSecrets) foundSecrets = true;

        ingestedArtifacts.push({
            id: crypto.randomUUID(),
            name: file.name,
            type: 'file',
            content: redactedText
        });
    }

    renderArtifactChips();
    updateSecretAlert(foundSecrets);
    event.target.value = '';
}

function handleScratchpadInput() {
    const el = document.getElementById('scratchpadInput');
    if (!el) return;
    const val = el.value || '';
    const { hasSecrets } = detectAndRedactSecrets(val);
    updateSecretAlert(hasSecrets);
}

function handleLogInput() {
    const el = document.getElementById('logIngestionInput');
    if (!el) return;
    const val = el.value || '';
    const { hasSecrets } = detectAndRedactSecrets(val);
    updateSecretAlert(hasSecrets);
}

function handleEnvConfigInput() {
    const el = document.getElementById('envConfigInput');
    if (!el) return;
    const val = el.value || '';
    const { hasSecrets, redactedText } = detectAndRedactSecrets(val);
    if (hasSecrets) {
        el.value = redactedText; // Auto-redact secrets in field
    }
    updateSecretAlert(hasSecrets);
}

function saveProjectMeta() {
    const proj = document.getElementById('metaProjectName')?.value || '';
    const stack = document.getElementById('metaTechStack')?.value || '';
    const env = document.getElementById('metaTargetEnv')?.value || '';
    localStorage.setItem(PROJECT_META_KEY, JSON.stringify({ proj, stack, env }));
}

function loadProjectMeta() {
    try {
        const meta = JSON.parse(localStorage.getItem(PROJECT_META_KEY) || '{}');
        if (meta.proj && document.getElementById('metaProjectName')) document.getElementById('metaProjectName').value = meta.proj;
        if (meta.stack && document.getElementById('metaTechStack')) document.getElementById('metaTechStack').value = meta.stack;
        if (meta.env && document.getElementById('metaTargetEnv')) document.getElementById('metaTargetEnv').value = meta.env;
    } catch (_) {}
}

function removeArtifactChip(id) {
    ingestedArtifacts = ingestedArtifacts.filter(a => a.id !== id);
    renderArtifactChips();
}

function clearIngestionContext() {
    ingestedArtifacts = [];
    if (document.getElementById('scratchpadInput')) document.getElementById('scratchpadInput').value = '';
    if (document.getElementById('logIngestionInput')) document.getElementById('logIngestionInput').value = '';
    if (document.getElementById('envConfigInput')) document.getElementById('envConfigInput').value = '';
    renderArtifactChips();
    updateSecretAlert(false);
}

function renderArtifactChips() {
    const container = document.getElementById('artifactsChipsContainer');
    const badge = document.getElementById('activeContextCount');
    if (!container) return;

    const count = ingestedArtifacts.length;
    if (badge) badge.textContent = `${count} item${count === 1 ? '' : 's'} attached`;

    if (!count) {
        container.innerHTML = '<span class="text-secondary fs-8 italic opacity-75">No context items attached. Drag files or paste notes above.</span>';
        return;
    }

    container.innerHTML = '';
    ingestedArtifacts.forEach(item => {
        const ext = item.name.split('.').pop().toLowerCase();
        let iconClass = 'fa-file-code text-success';
        if (ext === 'pdf') iconClass = 'fa-file-pdf text-danger';
        else if (ext === 'pptx' || ext === 'ppt') iconClass = 'fa-file-powerpoint text-warning';
        else if (ext === 'docx' || ext === 'doc') iconClass = 'fa-file-word text-info';

        const chip = document.createElement('span');
        chip.className = 'artifact-chip';
        chip.innerHTML = `<i class="fa-solid ${iconClass}"></i> ${escapeHtml(item.name)} <i class="fa-solid fa-xmark remove-chip" onclick="removeArtifactChip('${item.id}')" title="Remove context"></i>`;
        container.appendChild(chip);
    });
}


function assembleAttachedContextPayload() {
    const parts = [];

    // Project Metadata
    const proj = document.getElementById('metaProjectName')?.value.trim();
    const stack = document.getElementById('metaTechStack')?.value.trim();
    const env = document.getElementById('metaTargetEnv')?.value.trim();
    if (proj || stack || env) {
        parts.push(`[PROJECT METADATA]\nProject: ${proj || 'N/A'} | Tech Stack: ${stack || 'N/A'} | Target Env: ${env || 'N/A'}`);
    }

    // Ingested Files
    ingestedArtifacts.forEach(file => {
        const { redactedText } = detectAndRedactSecrets(file.content);
        parts.push(`[ATTACHED FILE: ${file.name}]\n\`\`\`\n${redactedText}\n\`\`\``);
    });

    // Scratchpad Notes
    const scratch = document.getElementById('scratchpadInput')?.value.trim();
    if (scratch) {
        const { redactedText } = detectAndRedactSecrets(scratch);
        parts.push(`[TECHNICAL SCRATCHPAD NOTES]\n${redactedText}`);
    }

    // Log / Stacktrace
    const logs = document.getElementById('logIngestionInput')?.value.trim();
    if (logs) {
        const { redactedText } = detectAndRedactSecrets(logs);
        parts.push(`[LOG / STACKTRACE CONTEXT]\n\`\`\`\n${redactedText}\n\`\`\``);
    }

    // Environment & Configuration
    const envConf = document.getElementById('envConfigInput')?.value.trim();
    if (envConf) {
        const { redactedText } = detectAndRedactSecrets(envConf);
        parts.push(`[ENVIRONMENT / CONFIG CONTEXT]\n\`\`\`\n${redactedText}\n\`\`\``);
    }

    return parts.length ? parts.join('\n\n') + '\n\n' : '';
}

function triggerQuickCommand(commandName) {
    const promptInput = document.getElementById('promptInput');
    if (!promptInput || uiState === 'connecting' || uiState === 'generating') return;

    const contextPrefix = assembleAttachedContextPayload();
    let promptText = '';

    switch (commandName) {
        case 'Explain Architecture':
            promptText = 'Please provide a detailed architecture breakdown and structural analysis based on the attached technical context.';
            break;
        case 'Debug Stacktrace':
            promptText = 'Please analyze the attached stack traces/logs, identify the root cause of failure, and provide exact code fixes.';
            break;
        case 'Refactor Code':
            promptText = 'Review the attached code for refactoring opportunities focusing on performance, maintainability, and clean architecture.';
            break;
        case 'Security Audit':
            promptText = 'Perform a security audit on the attached technical context, checking for vulnerabilities, sanitization issues, and flaws.';
            break;
        case 'Generate Tests':
            promptText = 'Generate a comprehensive unit and integration test suite with high edge-case coverage for the attached code.';
            break;
        default:
            promptText = `Execute technical action: ${commandName}`;
            break;
    }

    promptInput.value = promptText;
    resizeComposer();
    document.getElementById('chatForm')?.requestSubmit();
}

// ---------------------------------------------------------------------------
// Markdown & Syntax Highlighting (Req 8, 9)
// ---------------------------------------------------------------------------

function safeMarkdown(text) {
    return DOMPurify.sanitize(marked.parse(text || '', { breaks: true, gfm: true }), { USE_PROFILES: { html: true } });
}

function renderMarkdown(text) {
    if (!text) return '';
    const el = document.createElement('div');
    el.innerHTML = safeMarkdown(text);
    el.querySelectorAll('pre code').forEach(x => {
        try { hljs.highlightElement(x); } catch (_) {}
    });
    addCopyButtons(el);
    return el.innerHTML;
}

function addCopyButtons(container) {
    container.querySelectorAll('pre').forEach(pre => {
        if (pre.querySelector('.copy-btn')) return;
        const code = pre.querySelector('code');
        const lang = (code?.className.match(/language-([\w-]+)/) || [])[1];
        const bar = document.createElement('div');
        bar.className = 'code-toolbar';

        if (lang) {
            const label = document.createElement('span');
            label.className = 'code-language';
            label.textContent = lang;
            bar.appendChild(label);
        }

        const b = document.createElement('button');
        b.className = 'copy-btn';
        b.type = 'button';
        b.innerHTML = '<i class="fa-regular fa-copy"></i> Copy';
        b.setAttribute('aria-label', 'Copy code snippet');
        b.onclick = async () => {
            const codeText = code ? code.innerText : pre.innerText;
            const success = await copyText(codeText);
            if (success) {
                b.innerHTML = '<i class="fa-solid fa-check text-success"></i> Copied!';
                setTimeout(() => b.innerHTML = '<i class="fa-regular fa-copy"></i> Copy', 1800);
            } else {
                b.textContent = 'Copy failed';
            }
        };

        bar.appendChild(b);
        pre.prepend(bar);
    });
}

async function copyText(text) {
    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(text);
            return true;
        }
    } catch (_) {}

    // Fallback using temporary textarea
    try {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        const success = document.execCommand('copy');
        document.body.removeChild(textarea);
        return success;
    } catch (_) {
        return false;
    }
}

// ---------------------------------------------------------------------------
// Chat Rendering & Helper Functions
// ---------------------------------------------------------------------------

function scrollToBottom(force = false) {
    const c = document.getElementById('messagesContainer');
    if (c && (force || shouldStickToBottom)) c.scrollTop = c.scrollHeight;
}

function checkScrollPosition() {
    const c = document.getElementById('messagesContainer');
    if (c) shouldStickToBottom = c.scrollHeight - c.scrollTop - c.clientHeight < 100;
}

function resizeComposer() {
    const x = document.getElementById('promptInput');
    if (x) {
        x.style.height = 'auto';
        x.style.height = `${Math.min(x.scrollHeight, 160)}px`;
    }
}

function checkEnter(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        document.getElementById('chatForm')?.requestSubmit();
    }
}

function closeSidebar() {
    document.getElementById('appWrapper')?.classList.remove('sidebar-visible');
}

function openSidebar() {
    document.getElementById('appWrapper')?.classList.add('sidebar-visible');
}

function openModal(id) {
    const m = document.getElementById(id);
    if (m) {
        m.hidden = false;
        m.querySelector('button,select,input')?.focus();
    }
}

function closeModals() {
    document.querySelectorAll('.modal-shell').forEach(x => x.hidden = true);
}

function applySettings(s) {
    document.body.classList.toggle('light-theme', s.theme === 'light');
    document.body.dataset.font = s.font;
    document.body.dataset.density = s.density;
    const icon = document.querySelector('#themeToggle i');
    if (icon) {
        icon.classList.toggle('fa-sun', s.theme !== 'light');
        icon.classList.toggle('fa-moon', s.theme === 'light');
    }
    const map = { themeSetting: s.theme, fontSetting: s.font, densitySetting: s.density, timestampsSetting: s.timestamps };
    Object.entries(map).forEach(([id, v]) => {
        const e = document.getElementById(id);
        if (e) e[e.type === 'checkbox' ? 'checked' : 'value'] = v;
    });
}

function toggleTheme() {
    const s = getSettings();
    s.theme = s.theme === 'light' ? 'dark' : 'light';
    saveSettings(s);
}

function renderConversationList() {
    const list = document.getElementById('threadsItems');
    const empty = document.getElementById('threadsEmpty');
    const q = (document.getElementById('conversationSearch')?.value || '').toLowerCase();
    if (!list) return;
    list.innerHTML = '';
    const items = getConversations().filter(c => (c.title || '').toLowerCase().includes(q)).sort((a, b) => b.updatedAt - a.updatedAt);
    document.getElementById('threadCount').textContent = items.length;
    if (empty) empty.hidden = items.length > 0;

    items.forEach(c => {
        const item = document.createElement('div');
        item.className = `thread-item ${c.id === activeConversationId ? 'active' : ''}`;
        item.tabIndex = 0;
        item.setAttribute('role', 'button');

        const t = document.createElement('span');
        t.className = 'thread-title';
        t.textContent = c.title || 'Technical Session';

        const actions = document.createElement('span');
        actions.className = 'thread-actions';
        const r = actionButton('Rename session', 'fa-pen', e => { e.stopPropagation(); renameConversation(c.id); });
        const d = actionButton('Delete session', 'fa-trash', e => { e.stopPropagation(); deleteConversation(c.id); });
        r.className = 'thread-action';
        d.className = 'thread-action danger';
        actions.append(r, d);

        item.append(t, actions);
        item.onclick = () => selectConversation(c.id);
        item.onkeydown = e => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                selectConversation(c.id);
            }
        };
        list.appendChild(item);
    });
}

function selectConversation(id) {
    if (uiState === 'connecting' || uiState === 'generating') return;
    activeConversationId = id;
    chatHistory = activeConversation()?.messages || getConversations().find(x => x.id === id)?.messages || [];
    renderMessages();
    renderConversationList();
    closeSidebar();
}

function startNewChat() {
    if (uiState === 'connecting' || uiState === 'generating') stopGeneration();
    activeConversationId = null;
    chatHistory = [];
    renderMessages();
    renderConversationList();
    document.getElementById('promptInput')?.focus();
    closeSidebar();
}

function renameConversation(id) {
    const all = getConversations();
    const c = all.find(x => x.id === id);
    if (!c) return;
    const name = window.prompt('Session name', c.title);
    if (name?.trim()) {
        c.title = name.trim().slice(0, 80);
        c.updatedAt = Date.now();
        saveConversations(all);
    }
}

function deleteConversation(id) {
    const c = getConversations().find(x => x.id === id);
    if (!c || !window.confirm(`Delete “${c.title}”?`)) return;
    saveConversations(getConversations().filter(x => x.id !== id));
    if (id === activeConversationId) startNewChat();
    else renderConversationList();
}

function clearCurrentConversation() {
    if (!chatHistory.length) return;
    if (window.confirm('Clear this technical session? All session history will be reset.')) {
        saveConversations(getConversations().filter(x => x.id !== activeConversationId));
        startNewChat();
    }
}

function actionButton(label, icon, fn) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'message-action';
    b.title = label;
    b.setAttribute('aria-label', label);
    b.innerHTML = `<i class="fa-solid ${icon}"></i>`;
    b.onclick = fn;
    return b;
}

function messageElement(m, index) {
    const w = document.createElement('div');
    w.className = `msg-wrapper ${m.role === 'user' ? 'user' : 'ai'}`;
    w.dataset.index = index;

    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';

    const content = document.createElement('div');
    content.className = 'msg-content';
    content.innerHTML = renderMarkdown(m.content);
    bubble.appendChild(content);

    const footer = document.createElement('div');
    footer.className = 'message-footer';

    if (getSettings().timestamps && m.time) {
        const time = document.createElement('time');
        time.textContent = m.time;
        footer.appendChild(time);
    }

    const actions = document.createElement('div');
    actions.className = 'message-actions';

    if (m.role === 'user') {
        actions.appendChild(actionButton('Edit message', 'fa-pen', () => editUserMessage(index)));
    } else {
        const copyBtn = actionButton('Copy response', 'fa-copy', async (e) => {
            const btn = e.currentTarget;
            const success = await copyText(m.content);
            if (success) {
                btn.innerHTML = '<i class="fa-solid fa-check text-success"></i>';
                setTimeout(() => btn.innerHTML = '<i class="fa-solid fa-copy"></i>', 1600);
            }
        });
        actions.append(copyBtn, actionButton('Retry response', 'fa-rotate-right', () => regenerate(index)));
    }

    footer.appendChild(actions);
    bubble.appendChild(footer);

    w.innerHTML = `<div class="avatar"><i class="fa-solid fa-${m.role === 'user' ? 'user' : 'brain'}"></i></div>`;
    w.appendChild(bubble);
    return w;
}

function emptyHeroState() {
    const d = document.createElement('div');
    d.className = 'hero-state';
    d.id = 'heroWelcomeState';
    d.innerHTML = `
        <div class="hero-icon"><i class="fa-solid fa-terminal"></i></div>
        <p class="eyebrow">JARVIS WORKBENCH // STATELESS INFERENCE</p>
        <h2 class="fw-bold mb-2">Technical AI Engineering Environment</h2>
        <p class="text-secondary mb-3">Attach code, paste stack traces, configure context above, or ask any technical prompt.</p>
    `;
    return d;
}

function renderMessages() {
    const c = document.getElementById('messagesContainer');
    if (!c) return;
    c.innerHTML = '';
    if (!chatHistory.length) {
        c.appendChild(emptyHeroState());
        return;
    }
    chatHistory.forEach((m, i) => c.appendChild(messageElement(m, i)));
    scrollToBottom(true);
}

function ensureActiveConversation() {
    if (activeConversationId) return;
    const c = makeConversation();
    activeConversationId = c.id;
    saveConversations([c, ...getConversations()]);
}

// ---------------------------------------------------------------------------
// Stop & Retry Generation Functions (Req 3, 4)
// ---------------------------------------------------------------------------

function stopGeneration() {
    if (activeController) {
        activeController.abort();
        activeController = null;
    }
    const aiBubble = document.getElementById('aiTypingBubble');
    if (aiBubble) {
        const content = aiBubble.querySelector('.msg-content');
        if (content && content.innerText.trim()) {
            // Keep partial text
            const partialText = content.innerText.trim();
            chatHistory.push({
                role: 'assistant',
                content: partialText + ' *(Generation stopped by user)*',
                time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            });
            syncActiveConversation();
        }
        aiBubble.remove();
    }
    setUIState('idle');
}

function editUserMessage(i) {
    if (uiState === 'connecting' || uiState === 'generating' || !chatHistory[i] || chatHistory[i].role !== 'user') return;
    const input = document.getElementById('promptInput');
    if (input) {
        input.value = chatHistory[i].content;
        chatHistory = chatHistory.slice(0, i);
        syncActiveConversation();
        renderMessages();
        resizeComposer();
        input.focus();
    }
}

function regenerate(i) {
    if (uiState === 'connecting' || uiState === 'generating' || i < 1 || chatHistory[i].role !== 'assistant') return;
    const promptMsg = chatHistory[i - 1];
    if (!promptMsg || promptMsg.role !== 'user') return;
    chatHistory = chatHistory.slice(0, i - 1);
    renderMessages();
    sendPrompt(promptMsg.content, false);
}

// ---------------------------------------------------------------------------
// Main Prompt Dispatch & SSE Parsing (Req 1, 10, 17, 18)
// ---------------------------------------------------------------------------

async function handleSend(e) {
    if (e) e.preventDefault();
    if (uiState === 'connecting' || uiState === 'generating') return;

    const input = document.getElementById('promptInput');
    const rawPrompt = input?.value.trim() || '';

    const attachedContext = assembleAttachedContextPayload();
    const fullPrompt = (attachedContext + rawPrompt).trim();

    if (!fullPrompt) return;
    if (fullPrompt.length > MAX_MESSAGE_CHARS) {
        window.alert(`Please keep messages under ${MAX_MESSAGE_CHARS} characters.`);
        return;
    }

    input.value = '';
    resizeComposer();
    sendPrompt(fullPrompt, true);
}

async function sendPrompt(prompt, isNewSubmission = true) {
    ensureActiveConversation();
    setUIState('connecting', 'Connecting to Jarvis...');

    const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    const requestId = crypto.randomUUID();
    const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    if (isNewSubmission) {
        chatHistory.push({ role: 'user', content: prompt, time: timestamp });
        renderMessages();
    }

    const aiBubble = document.createElement('div');
    aiBubble.className = 'msg-wrapper ai';
    aiBubble.id = 'aiTypingBubble';
    aiBubble.innerHTML = `
        <div class="avatar"><i class="fa-solid fa-brain"></i></div>
        <div class="msg-bubble">
            <div class="msg-content">
                <div class="typing-indicator" aria-label="Jarvis is generating">
                    <span></span><span></span><span></span><em>Initializing model connection...</em>
                </div>
            </div>
        </div>
    `;
    document.getElementById('messagesContainer')?.appendChild(aiBubble);
    scrollToBottom(true);

    activeController = new AbortController();
    let accumulatedText = '';

    try {
        const response = await fetch('/api/chat/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrf,
                'X-Request-ID': requestId,
            },
            body: JSON.stringify({
                message: prompt,
                history: chatHistory.slice(-MAX_HISTORY_TURNS),
                request_id: requestId,
                stream: true
            }),
            signal: activeController.signal
        });

        if (!response.ok) {
            let errText = `Server returned HTTP ${response.status}`;
            try {
                const errJson = await response.json();
                if (errJson.error) errText = errJson.error;
            } catch (_) {}
            throw new Error(errText);
        }

        setUIState('generating', 'Generating response...');
        const contentEl = aiBubble.querySelector('.msg-content');

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || ''; // Keep incomplete trailing chunk

            for (const line of lines) {
                const trimmed = line.trim();
                if (trimmed.startsWith('data: ')) {
                    try {
                        const event = JSON.parse(trimmed.slice(6));
                        if (event.type === 'chunk' || event.type === 'message_delta') {
                            accumulatedText += (event.delta || '');
                            if (contentEl) contentEl.innerHTML = renderMarkdown(accumulatedText);
                            scrollToBottom();
                        } else if (event.type === 'error' || event.type === 'message_error') {
                            throw new Error(event.error || 'AI service failure occurred.');
                        }
                    } catch (parseErr) {
                        if (trimmed.includes('"type": "error"') || trimmed.includes('"type": "message_error"')) {
                            throw parseErr;
                        }
                    }
                }
            }
        }


        if (accumulatedText) {
            chatHistory.push({ role: 'assistant', content: accumulatedText, time: timestamp });
            chatHistory = chatHistory.slice(-MAX_HISTORY_TURNS);
            syncActiveConversation();
        }

        aiBubble.remove();
        renderMessages();
        setUIState('completed');

    } catch (err) {
        if (err.name === 'AbortError') {
            setUIState('idle');
            return;
        }

        setUIState('error', 'Request Failed');
        if (aiBubble && aiBubble.querySelector('.msg-content')) {
            aiBubble.querySelector('.msg-content').innerHTML = `
                <div class="error-state">
                    <i class="fa-solid fa-triangle-exclamation text-danger fs-5 me-2"></i>
                    <span>${escapeHtml(err.message || 'Connection interrupted.')}</span>
                </div>
            `;
        }
    } finally {
        activeController = null;
        if (uiState !== 'error') {
            setTimeout(() => { if (uiState === 'completed') setUIState('idle'); }, 2000);
        }
    }
}

function escapeHtml(text) {
    return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ---------------------------------------------------------------------------
// Conversation Export as Markdown & JSON (Req 6)
// ---------------------------------------------------------------------------

function downloadChat(format = 'markdown') {
    const session = activeConversation();
    const title = session?.title || 'Jarvis-Session';
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');

    if (format === 'json') {
        const jsonBlob = new Blob([JSON.stringify({
            version: 1,
            exportedAt: new Date().toISOString(),
            title,
            messages: chatHistory
        }, null, 2)], { type: 'application/json' });

        const a = document.createElement('a');
        a.href = URL.createObjectURL(jsonBlob);
        a.download = `jarvis-session-${timestamp}.json`;
        a.click();
        URL.revokeObjectURL(a.href);
    } else {
        // Markdown Export
        let md = `# ${title}\n\n*Exported on ${new Date().toLocaleString()}*\n\n---\n\n`;
        chatHistory.forEach(m => {
            const roleName = m.role === 'user' ? '👤 **User**' : '🤖 **Jarvis AI**';
            md += `${roleName} *(${m.time || ''})*\n\n${m.content}\n\n---\n\n`;
        });

        const mdBlob = new Blob([md], { type: 'text/markdown' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(mdBlob);
        a.download = `jarvis-session-${timestamp}.md`;
        a.click();
        URL.revokeObjectURL(a.href);
    }

    closeModals();
}

function importChat(event) {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
        try {
            const data = JSON.parse(reader.result);
            const messages = Array.isArray(data) ? data : data.messages;
            if (!Array.isArray(messages) || messages.some(m => !['user', 'assistant'].includes(m.role) || typeof m.content !== 'string')) {
                throw new Error();
            }
            const c = makeConversation(messages.map(m => ({ role: m.role, content: m.content.slice(0, MAX_MESSAGE_CHARS) })));
            saveConversations([c, ...getConversations()]);
            activeConversationId = c.id;
            chatHistory = c.messages;
            renderMessages();
            renderConversationList();
        } catch (_) {
            window.alert('Selected file is not a valid Jarvis session export.');
        }
        event.target.value = '';
    };
    reader.readAsText(file);
}

// ---------------------------------------------------------------------------
// Initialization & Event Listeners
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
    marked.setOptions({ headerIds: false, mangle: false });
    applySettings(getSettings());
    initSidebarResizer();
    loadProjectMeta();
    loadIngestionState();


    // Setup drag and drop for context zone
    const dragArea = document.getElementById('dragDropArea');
    if (dragArea) {
        ['dragenter', 'dragover'].forEach(eventName => {
            dragArea.addEventListener(eventName, e => {
                e.preventDefault();
                dragArea.classList.add('drag-over');
            });
        });
        ['dragleave', 'drop'].forEach(eventName => {
            dragArea.addEventListener(eventName, e => {
                e.preventDefault();
                dragArea.classList.remove('drag-over');
            });
        });
        dragArea.addEventListener('drop', e => {
            const dt = e.dataTransfer;
            if (dt && dt.files && dt.files.length) {
                handleFileIngestion({ target: { files: dt.files } });
            }
        });
    }

    const list = getConversations();
    if (list.length) {
        activeConversationId = list[0].id;
        chatHistory = list[0].messages || [];
    }

    renderMessages();
    renderConversationList();

    document.getElementById('messagesContainer')?.addEventListener('scroll', checkScrollPosition);
    document.getElementById('promptInput')?.addEventListener('input', resizeComposer);
    document.getElementById('conversationSearch')?.addEventListener('input', renderConversationList);

    document.getElementById('sidebarOpen')?.addEventListener('click', openSidebar);
    document.getElementById('sidebarClose')?.addEventListener('click', closeSidebar);
    document.getElementById('sidebarBackdrop')?.addEventListener('click', closeSidebar);

    document.getElementById('stopBtn')?.addEventListener('click', stopGeneration);
    document.getElementById('clearChatBtn')?.addEventListener('click', clearCurrentConversation);
    document.getElementById('settingsBtn')?.addEventListener('click', () => openModal('settingsModal'));
    document.getElementById('shortcutsBtn')?.addEventListener('click', () => openModal('shortcutsModal'));

    document.querySelectorAll('[data-close-modal]').forEach(b => b.addEventListener('click', closeModals));
    document.querySelectorAll('.modal-shell').forEach(m => m.addEventListener('click', e => { if (e.target === m) closeModals(); }));

    ['themeSetting', 'fontSetting', 'densitySetting', 'timestampsSetting'].forEach(id => {
        document.getElementById(id)?.addEventListener('change', () => {
            const s = getSettings();
            s.theme = document.getElementById('themeSetting').value;
            s.font = document.getElementById('fontSetting').value;
            s.density = document.getElementById('densitySetting').value;
            s.timestamps = document.getElementById('timestampsSetting').checked;
            saveSettings(s);
            renderMessages();
        });
    });

    document.addEventListener('keydown', e => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            openCommandPalette();
        }
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'i') {
            e.preventDefault();
            toggleIngestionZone();
        }
        if (e.key === 'Escape') {
            closeModals();
            closeSidebar();
        }
    });

    resizeComposer();
});

// ---------------------------------------------------------------------------
// Developer Command Palette Handlers (Phase 15)
// ---------------------------------------------------------------------------

function openCommandPalette() {
    openModal('commandPaletteModal');
    const input = document.getElementById('paletteSearchInput');
    if (input) {
        input.value = '';
        input.focus();
        filterCommandPalette();
    }
}

function filterCommandPalette() {
    const query = (document.getElementById('paletteSearchInput')?.value || '').toLowerCase().trim();
    const items = document.querySelectorAll('.palette-item');
    items.forEach(item => {
        const text = item.innerText.toLowerCase();
        if (!query || text.includes(query)) {
            item.style.display = 'flex';
        } else {
            item.style.display = 'none';
        }
    });
}

function executePaletteCommand(cmd) {
    closeModals();
    switch (cmd) {
        case '/new':
            startNewChat();
            break;
        case '/context':
            toggleIngestionZone();
            break;
        case '/tools':
            fetchToolsSummary();
            break;
        case '/export':
            openModal('exportModal');
            break;
        case '/clear':
            clearCurrentConversation();
            break;
        case '/settings':
            openModal('settingsModal');
            break;
        case '/status':
            checkSystemStatus();
            break;
        default:
            break;
    }
}

async function fetchToolsSummary() {
    try {
        const resp = await fetch('/api/tools/');
        const data = await resp.json();
        const toolsList = (data.tools || []).map(t => `• ${t.name}: ${t.description}`).join('\n');
        alert(`Registered Workspace Tools:\n\n${toolsList || 'No tools registered.'}`);
    } catch (_) {
        alert('Unable to fetch tools schema.');
    }
}

async function checkSystemStatus() {
    try {
        const resp = await fetch('/api/health/');
        const data = await resp.json();
        alert(`System Readiness Status:\n\nService: ${data.service}\nProvider: ${data.provider}\nProvider Configured: ${data.provider_configured}\nStatus: ${data.status}`);
    } catch (_) {
        alert('System health check failed or endpoint unreachable.');
    }
}

