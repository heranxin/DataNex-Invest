/**
 * AI 助手对话持久化：抽屉与全屏页共享，localStorage 保留历史。
 */
(function (global) {
    const STORAGE_KEY = 'sjzt_ai_chat_v1';
    const MAX_TURNS = 10;

    function loadState() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return { turns: [], lastSources: [] };
            const data = JSON.parse(raw);
            return {
                turns: Array.isArray(data.turns) ? data.turns : [],
                lastSources: Array.isArray(data.lastSources) ? data.lastSources : [],
            };
        } catch (e) {
            return { turns: [], lastSources: [] };
        }
    }

    function saveState(state) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
        } catch (e) {
            /* quota exceeded – ignore */
        }
    }

    const AiChatStore = {
        getTurns() {
            return loadState().turns;
        },

        getLastSources() {
            return loadState().lastSources;
        },

        /** 供 /api/ai-chat 使用的多轮上下文 */
        getApiHistory(maxMessages) {
            const limit = maxMessages || 12;
            const hist = [];
            loadState().turns.forEach(t => {
                if (t.user) hist.push({ role: 'user', content: t.user });
                if (t.assistant) hist.push({ role: 'assistant', content: t.assistant });
            });
            return hist.slice(-limit);
        },

        addTurn(user, assistant, meta) {
            const state = loadState();
            state.turns.push({
                user: String(user || ''),
                assistant: String(assistant || ''),
                meta: meta || {},
                ts: Date.now(),
            });
            if (state.turns.length > MAX_TURNS) {
                state.turns = state.turns.slice(-MAX_TURNS);
            }
            if (meta && meta.sources) {
                state.lastSources = meta.sources;
            }
            saveState(state);
        },

        clear() {
            saveState({ turns: [], lastSources: [] });
        },

        hasHistory() {
            return loadState().turns.length > 0;
        },
    };

    global.AiChatStore = AiChatStore;
})(window);
