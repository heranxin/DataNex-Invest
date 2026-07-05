(function () {
    const overlay = document.getElementById('onboarding-overlay');
    if (!overlay) return;

    const steps = overlay.querySelectorAll('.onboarding-step');
    const dots = overlay.querySelectorAll('.onboarding-dot');
    const btnPrev = document.getElementById('onboarding-prev');
    const btnNext = document.getElementById('onboarding-next');
    const btnSkip = document.getElementById('onboarding-skip');
    const stepLabel = document.getElementById('onboarding-step-label');
    const total = steps.length;
    let current = 0;
    let isReplay = false;

    function showStep(index) {
        current = Math.max(0, Math.min(index, total - 1));
        steps.forEach((el, i) => el.classList.toggle('active', i === current));
        dots.forEach((el, i) => {
            el.classList.toggle('active', i === current);
            el.classList.toggle('done', i < current);
        });
        if (btnPrev) btnPrev.classList.toggle('hidden', current === 0);
        if (btnNext) {
            const isLast = current === total - 1;
            btnNext.innerHTML = isLast
                ? '<i class="fa fa-check mr-1"></i> 开始使用'
                : '下一步 <i class="fa fa-angle-right ml-1"></i>';
        }
        if (stepLabel) stepLabel.textContent = (current + 1) + ' / ' + total;
    }

    function openGuide(replay) {
        isReplay = !!replay;
        current = 0;
        showStep(0);
        overlay.classList.remove('hidden');
        overlay.setAttribute('aria-hidden', 'false');
        document.body.classList.add('onboarding-open');
    }

    function closeGuide(markComplete) {
        overlay.classList.add('hidden');
        overlay.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('onboarding-open');
        if (markComplete && !isReplay) {
            fetch('/api/complete-guide', { method: 'POST', credentials: 'same-origin' }).catch(function () {});
        }
    }

    if (btnPrev) {
        btnPrev.addEventListener('click', function () {
            showStep(current - 1);
        });
    }

    if (btnNext) {
        btnNext.addEventListener('click', function () {
            if (current < total - 1) {
                showStep(current + 1);
            } else {
                closeGuide(true);
            }
        });
    }

    if (btnSkip) {
        btnSkip.addEventListener('click', function () {
            closeGuide(true);
        });
    }

    overlay.addEventListener('click', function (e) {
        if (e.target === overlay) return;
    });

    document.addEventListener('keydown', function (e) {
        if (overlay.classList.contains('hidden')) return;
        if (e.key === 'Escape') closeGuide(true);
        if (e.key === 'ArrowRight' && current < total - 1) showStep(current + 1);
        if (e.key === 'ArrowLeft' && current > 0) showStep(current - 1);
    });

    const openBtn = document.getElementById('open-user-guide');
    if (openBtn) {
        openBtn.addEventListener('click', function (e) {
            e.preventDefault();
            openGuide(true);
        });
    }

    if (overlay.dataset.autoShow === '1') {
        setTimeout(function () {
            openGuide(false);
        }, 400);
    }
})();
