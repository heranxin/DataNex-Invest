/**
 * AI 助手回答轻量 Markdown 渲染（避免裸露 # 号）
 */
(function (global) {
    function escapeHtml(t) {
        const d = document.createElement('div');
        d.textContent = t == null ? '' : String(t);
        return d.innerHTML;
    }

    function renderAiMarkdown(text) {
        if (!text) return '';
        let s = escapeHtml(text);
        // 去掉孤立 # / ## / ### 行
        s = s.replace(/^(#{1,6})\s*$/gm, '');
        s = s.replace(/^#{1,6}\s+(.+)$/gm, '<h4 class="font-bold text-slate-800 mt-2 mb-1 text-sm">$1</h4>');
        s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        s = s.replace(/^---$/gm, '<hr class="my-2 border-slate-200">');
        s = s.replace(/^(\d+)[\.、]\s+(.+)$/gm, '<p class="ml-1 mb-1"><span class="font-semibold text-teal-700">$1.</span> $2</p>');
        s = s.replace(/^[-•]\s+(.+)$/gm, '<p class="ml-2 mb-1 pl-2 border-l-2 border-teal-100">$1</p>');
        s = s.replace(/\n/g, '<br>');
        return s;
    }

    global.renderAiMarkdown = renderAiMarkdown;
})(window);
