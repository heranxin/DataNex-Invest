/**
 * 全局悬浮 AI 助手（右下角 FAB + 右侧抽屉）
 */
(function () {
    const QUICK = [
        '什么是市盈率 PE？',
        'A股涨跌停规则是什么？',
        '贵州茅台的投资价值',
        '分析一下 600519',
    ];

    const fab = document.getElementById('ai-fab');
    const drawer = document.getElementById('ai-drawer');
    const overlay = document.getElementById('ai-drawer-overlay');
    const closeBtn = document.getElementById('ai-drawer-close');
    const chatContainer = document.getElementById('aiw-chat-container');
    const userInput = document.getElementById('aiw-input');
    const sendBtn = document.getElementById('aiw-send-btn');
    const quickWrap = document.getElementById('aiw-quick-questions');
    const sourcesPanel = document.getElementById('aiw-sources-panel');
    const contextHint = document.getElementById('aiw-context-hint');

    if (!fab || !drawer) return;

    let uiSynced = false;
    let initialized = false;

    function escapeHtml(t) {
        const d = document.createElement('div');
        d.textContent = t;
        return d.innerHTML;
    }

    function renderMarkdownLite(text) {
        return typeof renderAiMarkdown === 'function'
            ? renderAiMarkdown(text)
            : escapeHtml(text).replace(/\n/g, '<br>');
    }

    function scrollChat() {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function addUserMsg(text) {
        const el = document.createElement('div');
        el.className = 'flex justify-end ai-msg-in';
        el.innerHTML = `<div class="chat-bubble-user p-3 rounded-2xl rounded-tr-md max-w-[88%] shadow-md"><p class="text-sm">${escapeHtml(text)}</p></div>`;
        chatContainer.appendChild(el);
        scrollChat();
    }

    function addThinking() {
        const el = document.createElement('div');
        el.id = 'aiw-thinking';
        el.className = 'flex justify-start ai-msg-in';
        el.innerHTML = `<div class="chat-bubble-ai p-3 rounded-2xl rounded-tl-md shadow-sm border-l-4 border-primary">
            <div class="font-semibold text-primary text-xs mb-1">AI 助手</div>
            <div class="flex items-center text-slate-500 text-xs">
                <div class="flex space-x-1 mr-2">
                    <span class="thinking-dot inline-block h-1.5 w-1.5 rounded-full bg-primary"></span>
                    <span class="thinking-dot inline-block h-1.5 w-1.5 rounded-full bg-primary"></span>
                    <span class="thinking-dot inline-block h-1.5 w-1.5 rounded-full bg-primary"></span>
                </div>
                思考中…
            </div>
        </div>`;
        chatContainer.appendChild(el);
        scrollChat();
        return el;
    }

    function buildAiTags(meta) {
        let tags = '';
        if (!meta) return tags;
        if (meta.has_knowledge) tags += '<span class="text-[10px] bg-teal-50 text-teal-600 px-1.5 py-0.5 rounded-full mr-1">知识库</span>';
        if (meta.has_live_data) tags += '<span class="text-[10px] bg-emerald-50 text-emerald-600 px-1.5 py-0.5 rounded-full mr-1">实时</span>';
        if (meta.used_llm) {
            const modelName = (meta.model || '大模型').split('/').pop();
            tags += '<span class="text-[10px] bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded-full">' + escapeHtml(modelName) + '</span>';
        } else if (meta.used_llm === false) {
            tags += '<span class="text-[10px] bg-amber-50 text-amber-600 px-1.5 py-0.5 rounded-full">检索模式</span>';
        }
        return tags;
    }

    function createStreamingAiMsg() {
        const el = document.createElement('div');
        el.className = 'flex justify-start ai-msg-in';
        el.innerHTML = `<div class="chat-bubble-ai p-3 rounded-2xl rounded-tl-md max-w-[92%] shadow-sm border border-slate-100">
            <div class="flex items-center gap-1.5 mb-1.5 flex-wrap">
                <span class="font-semibold text-primary text-xs">AI 助手</span>
                <span class="ai-stream-tags"></span>
            </div>
            <div class="ai-stream-body text-slate-700 text-xs leading-relaxed"></div>
        </div>`;
        chatContainer.appendChild(el);
        scrollChat();
        return {
            root: el,
            tagsEl: el.querySelector('.ai-stream-tags'),
            bodyEl: el.querySelector('.ai-stream-body'),
            setMeta(meta) {
                this.tagsEl.innerHTML = buildAiTags(meta);
            },
            appendToken(token) {
                const cur = this.bodyEl.textContent || '';
                this.bodyEl.textContent = cur + token;
                scrollChat();
            },
            setFinal(text, meta) {
                this.setMeta(meta);
                this.bodyEl.innerHTML = renderMarkdownLite(text);
                scrollChat();
            },
        };
    }

    function addAiMsg(text, meta) {
        const el = document.createElement('div');
        el.className = 'flex justify-start ai-msg-in';
        el.innerHTML = `<div class="chat-bubble-ai p-3 rounded-2xl rounded-tl-md max-w-[92%] shadow-sm border border-slate-100">
            <div class="flex items-center gap-1.5 mb-1.5 flex-wrap">
                <span class="font-semibold text-primary text-xs">AI 助手</span>${buildAiTags(meta)}
            </div>
            <div class="text-slate-700 text-xs leading-relaxed">${renderMarkdownLite(text)}</div>
        </div>`;
        chatContainer.appendChild(el);
        scrollChat();
    }

    function addError(msg) {
        const el = document.createElement('div');
        el.className = 'flex justify-start';
        el.innerHTML = `<div class="bg-red-50 text-red-700 p-3 rounded-xl text-xs border border-red-100">${escapeHtml(msg)}</div>`;
        chatContainer.appendChild(el);
        scrollChat();
    }

    function renderSources(sources) {
        if (!sourcesPanel) return;
        if (!sources || !sources.length) {
            sourcesPanel.innerHTML = '<p class="text-slate-400 text-xs">暂无参考来源</p>';
            return;
        }
        sourcesPanel.innerHTML = sources.slice(0, 5).map(s => {
            const link = s.link ? `href="${s.link}" target="_blank" rel="noopener"` : '';
            const tag = s.category ? `<span class="text-teal-500">${escapeHtml(s.category)}</span> · ` : '';
            if (link) {
                return `<a ${link} class="block p-2 rounded-lg bg-slate-50 hover:bg-teal-50 text-xs">
                    <div class="font-medium text-slate-700 line-clamp-2">${escapeHtml(s.title)}</div>
                    <div class="text-slate-400 mt-0.5">${tag}${escapeHtml(s.source || '')}</div>
                </a>`;
            }
            return `<div class="p-2 rounded-lg bg-slate-50 text-xs">
                <div class="font-medium text-slate-700">${escapeHtml(s.title)}</div>
                <div class="text-slate-400 mt-0.5">${tag}${escapeHtml(s.source || '')}</div>
            </div>`;
        }).join('');
    }

    function detectPageStockCode() {
        const inputs = ['stockCode', 'stock-code', 'stock_code'];
        for (const id of inputs) {
            const el = document.getElementById(id);
            if (el && el.value && /^\d{6}$/.test(el.value.trim())) {
                return el.value.trim();
            }
        }
        const params = new URLSearchParams(window.location.search);
        const fromUrl = params.get('code') || params.get('stockCode');
        if (fromUrl && /^\d{6}$/.test(fromUrl.trim())) return fromUrl.trim();
        return null;
    }

    function updateContextHint() {
        if (!contextHint) return;
        const code = detectPageStockCode();
        if (code) {
            contextHint.textContent = `当前页面股票 ${code}，可问「分析一下 ${code}」`;
            contextHint.classList.remove('hidden');
            userInput.placeholder = `例：分析一下 ${code}`;
        } else {
            contextHint.classList.add('hidden');
            userInput.placeholder = '输入问题，如：什么是市盈率？';
        }
    }

    function syncChatFromStore() {
        if (uiSynced || typeof AiChatStore === 'undefined') return;
        uiSynced = true;
        const turns = AiChatStore.getTurns();
        if (!turns.length) return;
        chatContainer.innerHTML = '';
        turns.forEach(turn => {
            addUserMsg(turn.user);
            addAiMsg(turn.assistant, turn.meta || {});
        });
        renderSources(AiChatStore.getLastSources());
        scrollChat();
    }

    function persistTurn(user, answer, meta) {
        if (typeof AiChatStore !== 'undefined') {
            AiChatStore.addTurn(user, answer, meta || {});
        }
    }

    function getApiHistory() {
        return typeof AiChatStore !== 'undefined' ? AiChatStore.getApiHistory() : [];
    }

    function initQuickQuestions() {
        if (!quickWrap) return;
        quickWrap.innerHTML = QUICK.map(q =>
            `<button type="button" class="aiw-quick-q">${escapeHtml(q)}</button>`
        ).join('');
        quickWrap.querySelectorAll('.aiw-quick-q').forEach(btn => {
            btn.addEventListener('click', () => {
                userInput.value = btn.textContent;
                sendMessage();
            });
        });
    }

    async function sendMessage() {
        const text = userInput.value.trim();
        if (!text) return;

        addUserMsg(text);
        userInput.value = '';
        sendBtn.disabled = true;
        const thinking = addThinking();
        let streamBox = null;

        const finish = (answer, meta) => {
            thinking.remove();
            if (streamBox) {
                streamBox.setFinal(answer, meta);
            } else {
                addAiMsg(answer, meta);
            }
            renderSources(meta.sources || []);
            persistTurn(text, answer, meta);
            sendBtn.disabled = false;
            scrollChat();
        };

        const fail = (msg) => {
            thinking.remove();
            if (streamBox) streamBox.root.remove();
            addError(msg);
            sendBtn.disabled = false;
            scrollChat();
        };

        if (typeof requestAiChat !== 'function') {
            fail('AI 客户端未加载，请刷新页面');
            return;
        }

        await requestAiChat({
            message: text,
            history: getApiHistory(),
            onMeta(meta) {
                thinking.remove();
                streamBox = createStreamingAiMsg();
                streamBox.setMeta(meta);
                renderSources(meta.sources || []);
            },
            onToken(token) {
                if (!streamBox) {
                    thinking.remove();
                    streamBox = createStreamingAiMsg();
                }
                streamBox.appendToken(token);
            },
            onDone(data) {
                finish(data.answer, data);
            },
            onError(msg) {
                fail(msg);
            },
        });
    }

    function openDrawer() {
        drawer.classList.add('open');
        overlay.classList.add('open');
        document.body.classList.add('ai-drawer-open');
        syncChatFromStore();
        if (!initialized) {
            initQuickQuestions();
            initialized = true;
        }
        updateContextHint();
        setTimeout(() => userInput.focus(), 300);
    }

    function closeDrawer() {
        drawer.classList.remove('open');
        overlay.classList.remove('open');
        document.body.classList.remove('ai-drawer-open');
    }

    fab.addEventListener('click', openDrawer);
    closeBtn.addEventListener('click', closeDrawer);
    overlay.addEventListener('click', closeDrawer);
    sendBtn.addEventListener('click', sendMessage);
    userInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && drawer.classList.contains('open')) closeDrawer();
    });
})();
