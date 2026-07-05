/**
 * 自选股盯盘面板
 */
(function (global) {
    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function changeClass(pct) {
        if (pct > 0) return 'fav-up';
        if (pct < 0) return 'fav-down';
        return 'fav-flat';
    }

    function renderQuoteRow(q, opts) {
        const pct = q.change_pct || 0;
        const cls = changeClass(pct);
        const price = q.price != null ? q.price.toFixed(2) : '--';
        const compact = opts && opts.compact;
        const actions = compact
            ? '<a href="/stock-chart?code=' + q.code + '" class="fav-action" title="行情"><i class="fa fa-line-chart"></i></a>'
            : '<div class="fav-row-actions">' +
                '<a href="/stock-chart?code=' + q.code + '" class="fav-action-btn"><i class="fa fa-line-chart"></i> 行情</a>' +
                '<a href="/stock-news?code=' + q.code + '" class="fav-action-btn"><i class="fa fa-newspaper-o"></i> 资讯</a>' +
                '<a href="/stock-prediction?code=' + q.code + '" class="fav-action-btn"><i class="fa fa-magic"></i> 预测</a>' +
                '<button type="button" class="fav-remove-btn" data-code="' + escapeHtml(q.code) + '"><i class="fa fa-times"></i></button>' +
              '</div>';

        return '<div class="fav-quote-row ' + cls + (compact ? ' fav-quote-row-compact' : '') + '" data-code="' + escapeHtml(q.code) + '">' +
            '<div class="fav-quote-main">' +
                '<div class="fav-quote-name">' + escapeHtml(q.name) + '<span class="fav-quote-code">' + escapeHtml(q.code) + '</span></div>' +
                '<div class="fav-quote-price">' + price + '</div>' +
                '<div class="fav-quote-change">' + escapeHtml(q.change_display || '--') + '</div>' +
            '</div>' +
            actions +
            '</div>';
    }

    async function loadFavoriteQuotes(container, opts) {
        if (!container) return;
        const sort = (opts && opts.sort) || 'change_pct';
        const compact = opts && opts.compact;
        const emptyHtml = opts && opts.emptyHtml;
        const onMeta = opts && opts.onMeta;
        const background = opts && opts.background;

        if (!background) {
            container.innerHTML = '<div class="fav-loading"><div class="app-spinner mr-2"></div>加载行情中...</div>';
        }
        try {
            const res = await fetch('/api/favorite-quotes?sort=' + encodeURIComponent(sort));
            if (res.status === 401) {
                container.innerHTML = '<p class="text-sm text-slate-400 text-center py-6">请先登录查看自选股</p>';
                return;
            }
            const data = await res.json();
            if (onMeta) onMeta(data);
            const items = data.items || [];
            if (!items.length) {
                container.innerHTML = emptyHtml || '<p class="text-sm text-slate-400 text-center py-8">暂无自选股</p>';
                return;
            }
            container.innerHTML = items.map(function (q) {
                return renderQuoteRow(q, { compact: compact });
            }).join('');

            if (opts && opts.onLoaded) opts.onLoaded(container);

            container.querySelectorAll('.fav-remove-btn').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    const code = btn.getAttribute('data-code');
                    if (!code) return;
                    fetch('/api/remove-favorite-stock?code=' + encodeURIComponent(code), { method: 'POST' })
                        .then(function (r) { return r.json(); })
                        .then(function (d) {
                            if (d.success && opts && opts.onRemoved) opts.onRemoved(code);
                            else if (d.success) loadFavoriteQuotes(container, opts);
                            else alert(d.error || '移除失败');
                        });
                });
            });
        } catch (e) {
            container.innerHTML = '<p class="text-sm text-red-500 text-center py-6">行情加载失败</p>';
        }
    }

    global.FavoriteBoard = {
        load: loadFavoriteQuotes,
        renderRow: renderQuoteRow,
    };
})(window);
