// ===================================================
// HiveFlow — UI Interactions
// ===================================================

document.addEventListener('DOMContentLoaded', () => {
    // Auto-dismiss flash messages after 5 seconds
    document.querySelectorAll('.flash').forEach(flash => {
        setTimeout(() => {
            flash.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
            flash.style.opacity = '0';
            flash.style.transform = 'translateY(-10px)';
            setTimeout(() => flash.remove(), 500);
        }, 5000);
    });

    // Add ripple effect to buttons
    document.querySelectorAll('.btn, .btn-small').forEach(btn => {
        btn.addEventListener('click', function (e) {
            const ripple = document.createElement('span');
            const rect = this.getBoundingClientRect();
            const size = Math.max(rect.width, rect.height);
            const x = e.clientX - rect.left - size / 2;
            const y = e.clientY - rect.top - size / 2;

            ripple.style.cssText = `
                position: absolute;
                width: ${size}px;
                height: ${size}px;
                left: ${x}px;
                top: ${y}px;
                background: rgba(255,255,255,0.15);
                border-radius: 50%;
                transform: scale(0);
                animation: rippleEffect 0.6s ease-out;
                pointer-events: none;
            `;

            this.style.position = 'relative';
            this.style.overflow = 'hidden';
            this.appendChild(ripple);

            setTimeout(() => ripple.remove(), 600);
        });
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

    document.querySelectorAll('.task-box, .auth-box').forEach(el => {
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

// Ripple animation keyframe (injected once)
const rippleStyle = document.createElement('style');
rippleStyle.textContent = `
    @keyframes rippleEffect {
        to { transform: scale(3); opacity: 0; }
    }
`;
document.head.appendChild(rippleStyle);
