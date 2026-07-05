/**
 * AI 助手对话客户端：默认流式输出，缩短首字等待时间。
 */
(function (global) {
    async function requestAiChat({ message, history, onMeta, onToken, onDone, onError }) {
        const res = await fetch('/api/ai-chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, history, stream: true }),
        });

        const ct = (res.headers.get('content-type') || '').toLowerCase();
        if (!ct.includes('text/event-stream')) {
            let data = {};
            try {
                data = await res.json();
            } catch (e) {
                onError('响应解析失败');
                return;
            }
            if (!res.ok || !data.success) {
                onError(data.error || '请求失败');
                return;
            }
            onMeta(data);
            onDone(data);
            return;
        }

        if (!res.ok || !res.body) {
            onError('请求失败');
            return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const parts = buffer.split('\n\n');
            buffer = parts.pop() || '';
            for (const part of parts) {
                const line = part.trim();
                if (!line.startsWith('data:')) continue;
                try {
                    const evt = JSON.parse(line.slice(5).trim());
                    if (evt.event === 'meta' && onMeta) onMeta(evt.data);
                    else if (evt.event === 'token' && onToken) onToken(evt.data);
                    else if (evt.event === 'done' && onDone) onDone(evt.data);
                    else if (evt.event === 'error' && onError) onError(evt.data.error || 'AI 服务异常');
                } catch (e) {
                    /* ignore malformed chunk */
                }
            }
        }
    }

    global.requestAiChat = requestAiChat;
})(window);
