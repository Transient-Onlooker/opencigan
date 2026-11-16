const media = window.matchMedia('(prefers-color-scheme: dark)');

function applyTheme() {
  let preference = 'light';
  try { preference = localStorage.getItem('opensigan-theme') ?? 'light'; } catch { /* Keep the default when storage is unavailable. */ }
  const dark = preference === 'dark' || (preference === 'system' && media.matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
}

applyTheme();
media.addEventListener('change', applyTheme);
window.addEventListener('storage', (event) => { if (event.key === 'opensigan-theme' || event.key === null) applyTheme(); });
