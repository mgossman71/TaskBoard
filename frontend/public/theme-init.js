// Applies the persisted theme before first paint (avoids a flash of the wrong theme).
// Served as a same-origin file so the Content-Security-Policy can forbid inline scripts.
(function () {
  try {
    var t = localStorage.getItem("tb-theme");
    if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
  } catch (e) {}
})();
