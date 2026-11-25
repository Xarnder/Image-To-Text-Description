// Run before styles load so a saved light preference does not flash dark.
(function () {
  const key = "caption-studio-theme";
  let theme = "dark";
  try {
    const saved = localStorage.getItem(key);
    if (saved === "light" || saved === "dark") theme = saved;
  } catch (_) {}
  document.documentElement.dataset.theme = theme;

  document.addEventListener("DOMContentLoaded", function () {
    const button = document.getElementById("themeToggle");
    const label = document.getElementById("themeLabel");
    const icon = document.getElementById("themeIcon");
    function render() {
      const dark = document.documentElement.dataset.theme === "dark";
      label.textContent = dark ? "Light mode" : "Dark mode";
      icon.textContent = dark ? "☀" : "☾";
      button.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
      button.title = button.getAttribute("aria-label");
    }
    button.addEventListener("click", function () {
      const selected = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = selected;
      try { localStorage.setItem(key, selected); } catch (_) {}
      render();
    });
    render();
  });
})();
