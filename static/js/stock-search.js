/**
 * 股票名称/代码/拼音联想搜索
 */
(function (global) {
    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    function debounce(fn, ms) {
        let t;
        return function () {
            const args = arguments;
            const ctx = this;
            clearTimeout(t);
            t = setTimeout(function () { fn.apply(ctx, args); }, ms);
        };
    }

    /**
     * @param {Object} opts
     * @param {HTMLInputElement} opts.input
     * @param {HTMLElement} opts.dropdown
     * @param {function(string):void} [opts.onSelect]
     * @param {function(string):void} [opts.onResolved]
     */
    function initStockSearch(opts) {
        const input = opts.input;
        const dropdown = opts.dropdown;
        if (!input || !dropdown) return;

        let activeIdx = -1;
        let items = [];

        function hideDropdown() {
            dropdown.classList.add('hidden');
            dropdown.innerHTML = '';
            activeIdx = -1;
            items = [];
        }

        function showDropdown() {
            dropdown.classList.remove('hidden');
        }

        function renderList(list) {
            items = list || [];
            if (!items.length) {
                hideDropdown();
                return;
            }
            dropdown.innerHTML = items.map(function (item, i) {
                return '<button type="button" class="stock-suggest-item' + (i === activeIdx ? ' active' : '') + '" data-code="' + escapeHtml(item.code) + '" data-name="' + escapeHtml(item.name) + '">' +
                    '<span class="stock-suggest-code">' + escapeHtml(item.code) + '</span>' +
                    '<span class="stock-suggest-name">' + escapeHtml(item.name) + '</span>' +
                    '<span class="stock-suggest-tag">' + escapeHtml(item.match_type || '') + '</span>' +
                    '</button>';
            }).join('');
            showDropdown();
        }

        async function fetchSuggestions(q) {
            if (!q || q.length < 1) {
                hideDropdown();
                return;
            }
            try {
                const res = await fetch('/api/stock-search?q=' + encodeURIComponent(q) + '&limit=8');
                const data = await res.json();
                renderList(data.items || []);
            } catch (e) {
                hideDropdown();
            }
        }

        const debouncedFetch = debounce(function () {
            fetchSuggestions(input.value.trim());
        }, 220);

        input.addEventListener('input', debouncedFetch);

        input.addEventListener('keydown', function (e) {
            if (dropdown.classList.contains('hidden') || !items.length) return;
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                activeIdx = Math.min(activeIdx + 1, items.length - 1);
                renderList(items);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                activeIdx = Math.max(activeIdx - 1, 0);
                renderList(items);
            } else if (e.key === 'Enter' && activeIdx >= 0) {
                e.preventDefault();
                selectItem(items[activeIdx]);
            } else if (e.key === 'Escape') {
                hideDropdown();
            }
        });

        function selectItem(item) {
            input.value = item.code;
            input.dataset.stockName = item.name;
            hideDropdown();
            if (opts.onSelect) opts.onSelect(item);
            if (opts.onResolved) opts.onResolved(item.code);
        }

        dropdown.addEventListener('click', function (e) {
            const btn = e.target.closest('.stock-suggest-item');
            if (!btn) return;
            selectItem({ code: btn.dataset.code, name: btn.dataset.name });
        });

        document.addEventListener('click', function (e) {
            if (!input.contains(e.target) && !dropdown.contains(e.target)) {
                hideDropdown();
            }
        });

        return {
            resolve: async function () {
                const q = input.value.trim();
                if (!q) return null;
                if (/^\d{6}$/.test(q)) return q;
                const res = await fetch('/api/resolve-stock?q=' + encodeURIComponent(q));
                const data = await res.json();
                if (data.success) {
                    input.value = data.code;
                    return data.code;
                }
                throw new Error(data.error || '无法解析股票');
            },
            hide: hideDropdown,
        };
    }

    global.StockSearch = { init: initStockSearch };
})(window);
