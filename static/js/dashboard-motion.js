/**
 * 工作台入场动效（热股滚动条由服务端直出，此处不再请求行情）
 */
(function () {
    function prefersReducedMotion() {
        return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }

    function revealEl(el) {
        if (!el || el.classList.contains('dash-visible')) return;
        el.classList.add('dash-visible');
        el.querySelectorAll('.dash-stagger-item').forEach(function (child, i) {
            child.style.setProperty('--dash-i', String(i));
        });
    }

    function initReveal() {
        var targets = document.querySelectorAll('.dash-reveal');
        if (!targets.length) return;
        if (prefersReducedMotion()) {
            targets.forEach(revealEl);
            return;
        }
        targets.forEach(function (el, i) {
            setTimeout(function () { revealEl(el); }, 180 + i * 140);
        });
    }

    function staggerListItems(container, itemSelector, baseDelay) {
        if (!container || prefersReducedMotion()) return;
        container.querySelectorAll(itemSelector).forEach(function (item, i) {
            item.classList.add('dash-list-in');
            item.style.animationDelay = (baseDelay + i * 0.08) + 's';
        });
    }

    window.DashboardMotion = { init: initReveal, staggerList: staggerListItems };

    document.addEventListener('DOMContentLoaded', initReveal);
})();
