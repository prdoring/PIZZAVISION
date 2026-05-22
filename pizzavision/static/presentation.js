/* Shared JS for fullscreen presentation pages (awards, guess-the-band).
   Exposes window.PVPresentation with the helpers that should look and sound
   identical across presentations. Page-specific state machines and slide
   builders stay in each template's inline <script>. */

(function () {
    // -------- Audio: party horn (random toot segment per reveal) --------
    const tootRanges = [
        { start: 1,    end: 3    },
        { start: 4.5,  end: 5.5  },
        { start: 6.75, end: 8.8  },
        { start: 9,    end: 11   },
        { start: 11.5, end: 13   },
        { start: 21.5, end: 21.4 },
        { start: 21.6, end: 23   },
    ];
    let pendingHornStop = null;

    function playPartyHorn() {
        const horn = document.getElementById('partyHornSound');
        if (!horn) return;
        const toot = tootRanges[Math.floor(Math.random() * tootRanges.length)];
        try {
            horn.currentTime = toot.start;
            const p = horn.play();
            if (p && p.catch) p.catch(() => {});
        } catch (e) { /* missing file or autoplay block — no-op */ }
        if (pendingHornStop) clearTimeout(pendingHornStop);
        const duration = Math.max(0.1, toot.end - toot.start);
        pendingHornStop = setTimeout(() => {
            try { horn.pause(); } catch (e) {}
            pendingHornStop = null;
        }, duration * 1000);
    }

    function stopPartyHorn() {
        const horn = document.getElementById('partyHornSound');
        if (!horn) return;
        try { horn.pause(); horn.currentTime = 0; } catch (e) {}
        if (pendingHornStop) { clearTimeout(pendingHornStop); pendingHornStop = null; }
    }

    // -------- Background swap (only restarts Ken Burns on image change) --------
    function applyBackgroundFor(slide, bgLayer) {
        bgLayer = bgLayer || document.getElementById('bg-layer');
        if (!bgLayer || !slide) return;
        const newBg = slide.dataset.bgUrl || '';
        const currentBg = bgLayer.dataset.currentBg || '';
        if (newBg === currentBg) return; // same image — let Ken Burns continue
        bgLayer.style.backgroundImage = newBg ? `url('${newBg}')` : '';
        bgLayer.dataset.currentBg = newBg;
        bgLayer.classList.remove('zooming');
        void bgLayer.offsetWidth; // force reflow so animation restarts
        bgLayer.classList.add('zooming');
    }

    // -------- Count-up animation for big totals --------
    function animateCountUp(element, target, formatter, duration) {
        duration = duration || 1400;
        const start = performance.now();
        function frame(now) {
            const t = Math.min((now - start) / duration, 1);
            const eased = 1 - Math.pow(1 - t, 3); // ease-out cubic
            element.textContent = formatter(target * eased);
            if (t < 1) requestAnimationFrame(frame);
            else element.textContent = formatter(target);
        }
        requestAnimationFrame(frame);
    }

    // -------- Themed confetti --------
    const CONFETTI_THEMES = {
        money:  { emojis: ['💰', '💵', '💸', '🪙'], colors: ['#2ecc71', '#27ae60', '#ffd700'] },
        people: { emojis: ['👥', '🗣️', '🎉'],       colors: ['#3498db', '#9b59b6', '#ffd700'] },
        nordic: { emojis: ['❄️', '⛄', '🌨️'],       colors: ['#ecf0f1', '#3498db', '#ffd700'] },
        pop:    { emojis: ['🎤', '✨', '💖'],         colors: ['#e91e63', '#9b59b6', '#ffd700'] },
        rock:   { emojis: ['🎸', '🤘', '🔥'],         colors: ['#c0392b', '#8e44ad', '#ffd700'] },
        folk:   { emojis: ['🪕', '🌾', '🍂'],         colors: ['#d35400', '#8b4513', '#ffd700'] },
        techno: { emojis: ['🤖', '⚡', '🎛️'],         colors: ['#9b59b6', '#1abc9c', '#ffd700'] },
        ballad: { emojis: ['🎙️', '💔', '🌹'],         colors: ['#e74c3c', '#34495e', '#ffd700'] },
        wine_r: { emojis: ['🍷', '🍇', '🌹'],         colors: ['#8e0000', '#5d0000', '#ffd700'] },
        wine_w: { emojis: ['🥂', '🍾', '✨'],         colors: ['#f1c40f', '#ecf0f1', '#ffd700'] },
        beer:   { emojis: ['🍺', '🥨', '🌭'],         colors: ['#f39c12', '#d35400', '#ffd700'] },
        girls:  { emojis: ['👩', '💃', '💖'],         colors: ['#e91e63', '#f06292', '#ffd700'] },
        lang:   { emojis: ['🌍', '🗣️', '📚'],         colors: ['#1abc9c', '#3498db', '#ffd700'] },
        soviet: { emojis: ['🚩', '⚒️', '⭐'],         colors: ['#c0392b', '#7f0000', '#ffd700'] },
        solo:   { emojis: ['🐺', '🌙', '⭐'],         colors: ['#34495e', '#7f8c8d', '#ffd700'] },
        squad:  { emojis: ['👯', '🤝', '🎉'],         colors: ['#e67e22', '#16a085', '#ffd700'] },
        vote:   { emojis: ['🗳️', '✅', '📊'],         colors: ['#3498db', '#2ecc71', '#ffd700'] },
        back:   { emojis: ['👋', '🔄', '🎉'],         colors: ['#f39c12', '#16a085', '#ffd700'] },
        meta:   { emojis: ['👑', '🏆', '✨'],         colors: ['#f1c40f', '#9b59b6', '#ffd700'] },
        twin:   { emojis: ['👯', '👯‍♂️', '✨'],         colors: ['#9b59b6', '#3498db', '#ffd700'] },
        big5:   { emojis: ['5️⃣', '🇪🇺', '⭐'],         colors: ['#003399', '#ffcc00', '#ffd700'] },
        default:{ emojis: ['🍕', '🎉', '✨', '🏆'],   colors: ['#f94144', '#f3722c', '#f9c74f'] },
    };

    function createConfetti(themeName) {
        const theme = CONFETTI_THEMES[themeName] || CONFETTI_THEMES.default;

        // Solid color squares
        for (let i = 0; i < 40; i++) {
            const piece = document.createElement('div');
            piece.className = 'confetti';
            piece.style.left = Math.random() * 100 + 'vw';
            piece.style.top = -Math.random() * 200 + 'px';
            piece.style.backgroundColor = theme.colors[Math.floor(Math.random() * theme.colors.length)];
            piece.style.opacity = Math.random() * 0.6 + 0.4;
            const size = Math.random() * 18 + 8;
            piece.style.width = `${size}px`;
            piece.style.height = `${size}px`;
            document.body.appendChild(piece);

            piece.animate([
                { transform: 'translate3d(0, 0, 0) rotate(0deg)', opacity: 1 },
                { transform: `translate3d(${Math.random()*600-300}px, ${window.innerHeight + 200}px, 0) rotate(${Math.random()*720-360}deg)`, opacity: 0 }
            ], {
                duration: Math.random() * 2500 + 2500,
                easing: 'cubic-bezier(.40,.10,.55,.95)'
            }).onfinish = () => piece.remove();
        }

        // Emoji confetti — the themed flair
        for (let i = 0; i < 30; i++) {
            const piece = document.createElement('div');
            piece.className = 'confetti emoji-confetti';
            piece.textContent = theme.emojis[Math.floor(Math.random() * theme.emojis.length)];
            piece.style.left = Math.random() * 100 + 'vw';
            piece.style.top = -Math.random() * 200 + 'px';
            piece.style.fontSize = (Math.random() * 30 + 30) + 'px';
            piece.style.background = 'transparent';
            piece.style.width = 'auto';
            piece.style.height = 'auto';
            piece.style.opacity = Math.random() * 0.3 + 0.7;
            document.body.appendChild(piece);

            piece.animate([
                { transform: 'translate3d(0, 0, 0) rotate(0deg)', opacity: 1 },
                { transform: `translate3d(${Math.random()*600-300}px, ${window.innerHeight + 200}px, 0) rotate(${Math.random()*720-360}deg)`, opacity: 0 }
            ], {
                duration: Math.random() * 3000 + 3000,
                easing: 'cubic-bezier(.40,.10,.55,.95)'
            }).onfinish = () => piece.remove();
        }
    }

    // -------- Navigation glue --------
    //   onForward / onBack: page-supplied callbacks
    //   clickMode: 'half'    — left half = back, right half = forward (awards)
    //              'forward' — any click = forward (guess)
    //              'off'     — page wires its own click handler
    function registerNavigation({ onForward, onBack, clickMode } = {}) {
        clickMode = clickMode || 'off';

        document.addEventListener('keydown', function (event) {
            if (event.key === 'ArrowRight' || event.key === ' ' || event.key === 'Enter') {
                if (onForward) onForward();
            } else if (event.key === 'ArrowLeft') {
                if (onBack) onBack();
            }
        });

        if (clickMode === 'half') {
            document.addEventListener('click', function (event) {
                if (event.clientX > window.innerWidth / 2) {
                    if (onForward) onForward();
                } else {
                    if (onBack) onBack();
                }
            });
        } else if (clickMode === 'forward') {
            document.addEventListener('click', function () {
                if (onForward) onForward();
            });
        }
    }

    window.PVPresentation = {
        playPartyHorn,
        stopPartyHorn,
        applyBackgroundFor,
        animateCountUp,
        createConfetti,
        CONFETTI_THEMES,
        registerNavigation,
    };
})();
