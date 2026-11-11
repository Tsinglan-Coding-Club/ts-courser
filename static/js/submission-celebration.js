/* Shared, optional feedback: animation failures must never interrupt submission. */
(function () {
    'use strict';

    const iconBase = document.currentScript?.dataset.deviconBase;
    const storageKey = 'ts-courser:submission-celebration';
    const colors = ['#3b82f6', '#fbbf24', '#34d399', '#a78bfa', '#fb7185'];
    const scalar = 3;
    let shapesPromise;
    let playing = false;

    function reducedMotion() {
        return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }

    async function iconShape(name) {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 800);
        try {
            const response = await fetch(iconBase + name + '/' + name + '-plain.svg', {
                signal: controller.signal,
            });
            if (!response.ok) return null;
            const svg = new DOMParser().parseFromString(await response.text(), 'image/svg+xml');
            const path = svg.querySelector('path')?.getAttribute('d');
            // These Devicon plain icons use a single path in a 128 × 128 viewBox.
            return path ? window.confetti.shapeFromPath({
                path, matrix: [0.08, 0, 0, 0.08, -5.12, -5.12],
            }) : null;
        } catch (_) {
            return null;
        } finally {
            clearTimeout(timeout);
        }
    }

    function getShapes() {
        if (!shapesPromise) {
            shapesPromise = (async function () {
                const symbols = ['{}', '</>', '()', '=>'].map((text, index) =>
                    window.confetti.shapeFromText({
                        text, scalar, color: colors[index], fontFamily: 'monospace',
                    })
                );
                const icons = iconBase && window.Path2D
                    ? await Promise.all(['python', 'git'].map(iconShape)) : [];
                return symbols.concat(icons.filter(Boolean));
            })();
        }
        return shapesPromise;
    }

    async function play() {
        if (playing || !window.confetti || reducedMotion()) return;
        playing = true;
        try {
            const shapes = await getShapes();
            if (reducedMotion() || document.hidden) return;
            const options = {
                shapes, colors, scalar, particleCount: 48, spread: 80,
                // Longer lifetime and slower falling keep the larger burst visible.
                startVelocity: 50, gravity: 0.45, ticks: 360,
                disableForReducedMotion: true, zIndex: 2000,
            };
            await Promise.all([
                window.confetti({ ...options, angle: 60, origin: { x: 0.15, y: 0.72 } }),
                window.confetti({ ...options, angle: 120, origin: { x: 0.85, y: 0.72 } }),
            ]);
        } catch (_) {
            // Celebration is decorative; saving and feedback remain independent.
        } finally {
            playing = false;
        }
    }

    function afterReload() {
        try {
            if (!reducedMotion()) {
                sessionStorage.setItem(storageKey, JSON.stringify({
                    path: location.pathname, time: Date.now(),
                }));
            }
        } catch (_) {
            // Storage can be unavailable in private or restricted browsing.
        }
    }

    function resume() {
        try {
            const pending = JSON.parse(sessionStorage.getItem(storageKey));
            sessionStorage.removeItem(storageKey);
            if (pending?.path === location.pathname && Date.now() - pending.time < 15000) {
                void play();
            }
        } catch (_) {}
    }

    window.SubmissionCelebration = { play, afterReload };
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', resume, { once: true });
    } else {
        resume();
    }
})();
