"use strict";
(() => {
  const root = document.documentElement;
  const form = document.querySelector('[data-theme-form]');
  const select = form.querySelector('select');
  const media = matchMedia('(prefers-color-scheme: dark)');
  const error = document.querySelector('[data-theme-error]');
  const apply = (preference) => {
    root.dataset.themePreference = preference;
    root.dataset.theme = preference === 'system' ? (media.matches ? 'dark' : 'light') : preference;
    select.value = preference;
    try { localStorage.setItem('theme', preference); } catch (_) {}
  };
  apply(root.dataset.themePreference);
  media.addEventListener('change', () => apply(root.dataset.themePreference));
  form.addEventListener('submit', (event) => event.preventDefault());
  select.addEventListener('change', async () => {
    const previous = root.dataset.themePreference;
    const preference = select.value;
    apply(preference);
    error.hidden = true;
    if (form.dataset.signedIn !== 'true') return;
    const data = new FormData(form);
    select.disabled = true;
    try {
      const response = await fetch('/account/theme', {method: 'POST', body: data});
      if (!response.ok || response.redirected) throw new Error('Theme could not be saved.');
    } catch (_) {
      apply(previous);
      error.textContent = 'Theme could not be saved. Try again.';
      error.hidden = false;
    } finally { select.disabled = false; }
  });
})();
