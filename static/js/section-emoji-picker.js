(function () {
    const {pickerModule, iconOptions} = document.currentScript.dataset;
    let moduleRequest;
    let catalogRequest;

    function loadModule() {
        moduleRequest ??= new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.type = 'module';
            script.src = pickerModule;
            script.addEventListener('load', resolve, {once: true});
            script.addEventListener('error', () => {
                script.remove();
                reject(new Error('Could not load the emoji picker.'));
            }, {once: true});
            document.head.appendChild(script);
        }).catch(error => {
            moduleRequest = undefined;
            throw error;
        });
        return moduleRequest;
    }

    function loadCatalog() {
        catalogRequest ??= fetch(iconOptions).then(response => {
            if (!response.ok) throw new Error('Could not load the icon catalog.');
            return response.json();
        }).then(icons => ({icons, byName: new Map(icons.map(icon => [icon.name, icon]))}))
            .catch(error => {
                catalogRequest = undefined;
                throw error;
            });
        return catalogRequest;
    }

    function stylePicker(picker, iconsByName) {
        const root = picker.shadowRoot;
        const style = document.createElement('style');
        style.textContent = `
            .section-icon-filters:not([hidden]) {
                display: flex;
                flex: 0 0 auto;
                min-width: 0;
                gap: 0.375rem;
                overflow-x: auto;
                scrollbar-width: none;
                box-sizing: border-box;
                padding: 0.375rem var(--emoji-padding);
            }
            .section-icon-filters::-webkit-scrollbar {
                display: none;
            }
            .section-icon-filters button {
                flex-shrink: 0;
                padding: 0.25rem 0.5rem;
                border: 1px solid var(--input-border-color);
                border-radius: var(--input-border-radius);
                color: var(--input-font-color);
                font: inherit;
                font-size: 0.875rem;
                line-height: 1.25;
                white-space: nowrap;
                cursor: pointer;
            }
            .section-icon-filters button:hover {
                background: var(--button-hover-background);
            }
            .section-icon-filters button[aria-pressed="true"] {
                background: var(--button-active-background);
                border-color: var(--indicator-color);
            }
            .section-icon-filters button:focus-visible {
                outline: 2px solid var(--outline-color);
            }
            button.custom-emoji[id*="heroicons:"]::after {
                filter: var(--heroicon-filter, none);
            }
            button.custom-emoji[id*="devicon:"]::after {
                background-color: var(--devicon-background, transparent);
                border-radius: 0.15rem;
            }
        `;
        root.appendChild(style);

        // emoji-picker-element observes whole grids. Gate the background URLs per button
        // instead, including when a search replaces the grid. Leave visible favorites alone.
        const panel = root.querySelector('.tabpanel');
        if (!panel) return;

        const pending = new Set();
        const selector = 'button.custom-emoji:not([data-section-icon-ready])';
        const observer = new IntersectionObserver(entries => {
            for (const {target, isIntersecting} of entries) {
                if (!isIntersecting || !panel.contains(target)) continue;
                target.setAttribute('data-section-icon-ready', '');
                observer.unobserve(target);
                pending.delete(target);
            }
        }, {root: panel, rootMargin: '38px 0px'});

        function observeIcons() {
            for (const button of pending) {
                if (panel.contains(button)) continue;
                observer.unobserve(button);
                pending.delete(button);
            }
            panel.querySelectorAll(selector).forEach(button => {
                // The picker prefixes the stable icon name with "emo-" in its result grid.
                if (iconsByName.get(button.id.slice(4))?.browse === false) {
                    button.setAttribute('data-section-icon-search-only', '');
                }
                if (pending.has(button)) return;
                pending.add(button);
                observer.observe(button);
            });
        }

        style.textContent += `
            .tabpanel ${selector}::after { background-image: none; }
            .tabpanel[role="tabpanel"] button[data-section-icon-search-only] { display: none; }
        `;
        new MutationObserver(observeIcons).observe(panel, {childList: true, subtree: true});
        observeIcons();
    }

    function bindFilters(filters, picker, icons) {
        const root = picker.shadowRoot;
        const tabs = root.querySelector('[role="tablist"]');
        const panel = root.querySelector('.tabpanel');
        if (!tabs || !panel) return;
        panel.before(filters);

        function syncVisibility() {
            const activeTab = tabs.querySelector('[aria-selected="true"]');
            // The picker clears aria-selected during search; keep the last tab's visibility.
            if (activeTab) filters.hidden = activeTab.dataset.groupId !== '-1';
        }

        new MutationObserver(syncVisibility).observe(tabs, {
            attributes: true, attributeFilter: ['aria-selected'], childList: true, subtree: true,
        });
        syncVisibility();

        const buttons = filters.querySelectorAll('[data-icon-filter]');
        let current = 'all';
        buttons.forEach(button => button.addEventListener('click', () => {
            const filter = button.dataset.iconFilter;
            if (filter !== current) {
                current = filter;
                picker.customEmoji = filter === 'all' ? icons : icons.filter(icon => icon.filter === filter);
                buttons.forEach(other => {
                    const active = other === button;
                    other.setAttribute('aria-pressed', String(active));
                });
            }
            tabs.querySelector('[data-group-id="-1"]')?.click();
            panel.scrollTop = 0;
        }));
    }

    document.querySelectorAll('[data-section-emoji-field]').forEach(field => {
        const input = field.querySelector('input[name="emoji"]');
        const details = field.querySelector('[data-emoji-details]');
        const preview = field.querySelector('[data-emoji-preview]');
        const clear = field.querySelector('[data-emoji-clear]');
        const filters = field.querySelector('[data-icon-filters]');
        const host = field.querySelector('[data-emoji-picker-host]');
        const status = field.querySelector('[data-emoji-picker-status]');
        const summary = field.querySelector('summary');
        let mounted = false;
        let loading = false;

        function syncPreview() {
            const iconUrl = input.dataset.iconUrl;
            preview.textContent = iconUrl ? '' : input.value || '📁';
            if (iconUrl) {
                const image = document.createElement('img');
                image.src = iconUrl;
                image.width = 24;
                image.height = 24;
                image.alt = '';
                image.className = 'section-icon' + (
                    input.value.startsWith('heroicons:') ? ' section-icon-heroicons' : ' section-icon-devicon'
                );
                preview.appendChild(image);
            }
            clear.disabled = !input.value;
        }

        function closePicker() {
            details.open = false;
        }

        function selectEmoji(emoji, iconUrl = '') {
            input.value = emoji;
            input.dataset.iconUrl = iconUrl;
            input.dispatchEvent(new Event('change', {bubbles: true}));
            closePicker();
            summary.focus();
        }

        details.addEventListener('toggle', async () => {
            if (!details.open || mounted || loading) return;
            loading = true;
            status.textContent = 'Loading icons…';
            try {
                const [, catalog] = await Promise.all([loadModule(), loadCatalog()]);
                status.textContent = '';
                if (!details.open) return;

                const picker = document.createElement('emoji-picker');
                picker.dataset.source = host.dataset.source;
                picker.customEmoji = catalog.icons;
                picker.addEventListener('emoji-click', event => {
                    const {unicode, emoji} = event.detail;
                    const icon = catalog.byName.get(emoji?.name);
                    if (unicode) selectEmoji(unicode);
                    else if (icon) selectEmoji(icon.name, icon.url);
                });
                host.appendChild(picker);
                stylePicker(picker, catalog.byName);
                bindFilters(filters, picker, catalog.icons);
                mounted = true;
            } catch {
                status.textContent = 'Could not load icons. Close and reopen to try again.';
            } finally {
                loading = false;
            }
        });
        clear.addEventListener('click', () => selectEmoji(''));
        input.addEventListener('change', syncPreview);
        details.addEventListener('keydown', event => {
            if (event.key === 'Escape' && details.open && !event.defaultPrevented) {
                event.preventDefault();
                event.stopPropagation();
                closePicker();
                summary.focus();
            }
        });
        const modal = field.closest('.modal');
        modal.addEventListener('show.bs.modal', () => {
            closePicker();
            syncPreview();
        });
        modal.addEventListener('hidden.bs.modal', closePicker);
        syncPreview();
    });
})();
