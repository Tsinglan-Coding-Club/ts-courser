(function () {
    'use strict';

    const canvas = document.querySelector('.auth-fluid-background');
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (!canvas || reduceMotion.matches || typeof window.WebGLFluid !== 'function') {
        return;
    }

    const primaryColor = getComputedStyle(document.documentElement)
        .getPropertyValue('--primary-color')
        .trim();
    const hex = primaryColor.match(/^#([0-9a-f]{6})$/i);
    const colorValue = hex ? Number.parseInt(hex[1], 16) : 0x883890;
    const fluidColor = {
        r: ((colorValue >> 16) & 255) / 255,
        g: ((colorValue >> 8) & 255) / 255,
        b: (colorValue & 255) / 255,
    };

    try {
        window.WebGLFluid(canvas, {
            TRIGGER: 'hover',
            IMMEDIATE: false,
            AUTO: false,
            SIM_RESOLUTION: 64,
            DYE_RESOLUTION: 512,
            DENSITY_DISSIPATION: 2.0,
            VELOCITY_DISSIPATION: 0.5,
            PRESSURE_ITERATIONS: 12,
            CURL: 18,
            SPLAT_RADIUS: 0.15,
            SPLAT_FORCE: 2000,
            SPLAT_COLOR: fluidColor,
            COLORFUL: false,
            SHADING: true,
            TRANSPARENT: true,
            BLOOM: false,
            SUNRAYS: false,
        });
    } catch (error) {
        canvas.hidden = true;
    }
}());
