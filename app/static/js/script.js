// ===================================================
// HiveFlow — UI Interactions
// ===================================================

document.addEventListener('DOMContentLoaded', () => {
    // Auto-dismiss flash messages — dev messages with OTP/links get extra time
    document.querySelectorAll('.flash').forEach(flash => {
        var delay = flash.textContent.indexOf('[DEV]') !== -1 ? 15000 : 5000;
        setTimeout(() => {
            flash.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
            flash.style.opacity = '0';
            flash.style.transform = 'translateY(-10px)';
            setTimeout(() => flash.remove(), 500);
        }, delay);
    });

    // Smooth scroll reveal for task-box
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.style.opacity = '1';
                entry.target.style.transform = 'translateY(0)';
            }
        });
    }, { threshold: 0.1 });

    document.querySelectorAll('.task-box').forEach(el => {
        observer.observe(el);
    });

    // Convert UTC <time data-fmt> elements to the viewer's local timezone.
    // Server emits ...Z ISO strings; we reformat in the user's locale.
    document.querySelectorAll('time[data-fmt]').forEach(el => {
        const iso = el.getAttribute('datetime');
        if (!iso) return;
        const d = new Date(iso);
        if (isNaN(d.getTime())) return;
        const fmt = el.getAttribute('data-fmt');
        let opts;
        if (fmt === 'long') {
            opts = { month: 'short', day: '2-digit', year: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true };
            const parts = new Intl.DateTimeFormat(undefined, opts).formatToParts(d);
            const get = t => (parts.find(p => p.type === t) || {}).value || '';
            el.textContent = `${get('month')} ${get('day')}, ${get('year')} at ${get('hour')}:${get('minute')} ${get('dayPeriod')}`;
        } else if (fmt === 'short') {
            opts = { month: 'short', day: '2-digit', hour: 'numeric', minute: '2-digit', hour12: true };
            const parts = new Intl.DateTimeFormat(undefined, opts).formatToParts(d);
            const get = t => (parts.find(p => p.type === t) || {}).value || '';
            el.textContent = `${get('month')} ${get('day')}, ${get('hour')}:${get('minute')} ${get('dayPeriod')}`;
        } else if (fmt === 'compact') {
            opts = { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false };
            const parts = new Intl.DateTimeFormat(undefined, opts).formatToParts(d);
            const get = t => (parts.find(p => p.type === t) || {}).value || '';
            el.textContent = `${get('month')} ${get('day')}, ${get('hour')}:${get('minute')}`;
        }
        el.setAttribute('title', d.toLocaleString());
    });
});

// In-app confirmation modal (replaces native confirm() calls)
// Any <form> with a data-confirm="message" attribute will auto-trigger this.
window.showConfirm = function (message, onConfirm, options) {
    options = options || {};
    const overlay = document.getElementById('globalConfirm');
    if (!overlay) {
        // Fallback if base.html didn't include the modal (e.g., logged-out pages)
        if (window.confirm(message)) onConfirm();
        return;
    }
    const titleEl = document.getElementById('confirmTitle');
    const messageEl = document.getElementById('confirmMessage');
    const okBtn = document.getElementById('confirmOk');
    const cancelBtn = document.getElementById('confirmCancel');

    titleEl.textContent = options.title || 'Are you sure?';
    messageEl.textContent = message;
    okBtn.textContent = options.okText || 'Yes, delete';
    cancelBtn.textContent = options.cancelText || 'Cancel';

    overlay.classList.add('open');
    overlay.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    setTimeout(() => okBtn.focus(), 50);

    const cleanup = () => {
        overlay.classList.remove('open');
        overlay.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
        okBtn.removeEventListener('click', onOk);
        cancelBtn.removeEventListener('click', onCancel);
        overlay.removeEventListener('click', onOverlayClick);
        document.removeEventListener('keydown', onKey);
    };
    const onOk = () => { cleanup(); onConfirm(); };
    const onCancel = () => { cleanup(); };
    const onOverlayClick = (e) => { if (e.target === overlay) onCancel(); };
    const onKey = (e) => {
        if (e.key === 'Escape') onCancel();
        if (e.key === 'Enter') onOk();
    };

    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
    overlay.addEventListener('click', onOverlayClick);
    document.addEventListener('keydown', onKey);
};

// Auto-intercept any form with data-confirm
document.addEventListener('submit', function (e) {
    const form = e.target;
    if (!form.matches('form[data-confirm]')) return;
    if (form.dataset.confirmed === 'true') return; // user already confirmed
    e.preventDefault();
    showConfirm(form.dataset.confirm, () => {
        form.dataset.confirmed = 'true';
        form.submit();
    });
});

// Premium submit feedback — swap the clicked submit button for a spinner.
// Skips GET forms and data-confirm forms that haven't been confirmed yet.
document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    if ((form.getAttribute('method') || 'get').toLowerCase() !== 'post') return;
    if (form.matches('[data-confirm]') && form.dataset.confirmed !== 'true') return;
    var btn = e.submitter || form.querySelector('button[type="submit"]');
    if (btn && btn.classList.contains('ui-btn') && !btn.classList.contains('is-loading')) {
        btn.classList.add('is-loading');
        btn.innerHTML = '<span class="ui-spinner"></span>';
    }
}, false);

// In-app toast (replaces native alert() calls)
window.showToast = function (message, type) {
    type = type || 'success';
    const toast = document.createElement('div');
    toast.className = 'toast toast-' + type;
    toast.setAttribute('role', 'status');
    toast.textContent = message;
    document.body.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('toast-show'));
    setTimeout(() => {
        toast.classList.remove('toast-show');
        setTimeout(() => toast.remove(), 300);
    }, 2500);
};
