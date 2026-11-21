/* Wybieracz miesiąca: przycisk z nazwą miesiąca otwiera siatkę 12 miesięcy ze strzałkami roku.
   Działa w każdej przeglądarce (natywne pole type="month" bywa zwykłym polem tekstowym, np. w Safari).
   Bez JavaScriptu zostaje zwykłe pole tekstowe RRRR-MM. Atrybuty: data-mp, data-marks="2027-01,2026-12" (miesiące z danymi),
   data-autosubmit (wyślij formularz po wyborze). */
(function () {
  var MONTHS = ["styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień"];
  var SHORT = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"];
  var RE = /^(\d{4})-(\d{2})$/;
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function key(y, m) { return y + "-" + pad(m + 1); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; }

  function init(root) {
    var input = root.querySelector("input");
    if (!input || root.dataset.ready) return;
    root.dataset.ready = "1";
    var marks = (root.dataset.marks || "").split(",").filter(Boolean);
    var now = new Date();
    var today = key(now.getFullYear(), now.getMonth());
    var nextDate = new Date(now.getFullYear(), now.getMonth() + 1, 1);
    var next = key(nextDate.getFullYear(), nextDate.getMonth());
    var sel = RE.test(input.value) ? input.value : "";
    var year = sel ? +sel.slice(0, 4) : now.getFullYear();
    input.type = "hidden";

    function label(v) { var p = RE.exec(v); return p ? MONTHS[+p[2] - 1] + " " + p[1] : "wybierz miesiąc"; }
    var btn = el("button", "mp-btn");
    btn.type = "button";
    function paint() {   // 📅 ikona, nazwa miesiąca, strzałka: osobne elementy, żeby dało się je ostylować
      btn.textContent = "";
      btn.appendChild(el("span", "mp-ico", "📅"));
      btn.appendChild(el("span", "mp-txt", label(sel)));
      btn.appendChild(el("span", "mp-caret", "▾"));
    }
    paint();
    btn.setAttribute("aria-haspopup", "true");
    var pop = el("div", "mp-pop"); pop.hidden = true;
    var head = el("div", "mp-head");
    var prev = el("button", "mp-nav", "◀"); prev.type = "button"; prev.setAttribute("aria-label", "poprzedni rok");
    var yearEl = el("strong", "mp-year");
    var nxt = el("button", "mp-nav", "▶"); nxt.type = "button"; nxt.setAttribute("aria-label", "następny rok");
    head.appendChild(prev); head.appendChild(yearEl); head.appendChild(nxt);
    var grid = el("div", "mp-grid");
    var foot = el("div", "mp-foot");
    var bThis = el("button", "mp-link", "Ten miesiąc"); bThis.type = "button";
    var bNext = el("button", "mp-link", "Następny"); bNext.type = "button";
    foot.appendChild(bThis); foot.appendChild(bNext);
    pop.appendChild(head); pop.appendChild(grid); pop.appendChild(foot);
    if (marks.length) pop.appendChild(el("div", "mp-note", "• miesiąc z danymi"));
    root.appendChild(btn); root.appendChild(pop);

    function choose(v) {
      sel = v; input.value = v; paint(); close();
      if (root.hasAttribute("data-autosubmit") && input.form) {
        if (input.form.requestSubmit) input.form.requestSubmit(); else input.form.submit();
      }
    }
    function render() {
      yearEl.textContent = year;
      grid.textContent = "";
      MONTHS.forEach(function (_, i) {
        var v = key(year, i), b = el("button", "mp-m", SHORT[i]);
        b.type = "button"; b.title = MONTHS[i] + " " + year;
        if (v === sel) b.classList.add("sel");
        if (v === today) b.classList.add("cur");
        if (marks.indexOf(v) >= 0) { b.classList.add("mark"); b.textContent = SHORT[i] + " •"; }
        b.addEventListener("click", function () { choose(v); });
        grid.appendChild(b);
      });
    }
    function open() { render(); pop.hidden = false; btn.setAttribute("aria-expanded", "true"); }
    function close() { pop.hidden = true; btn.setAttribute("aria-expanded", "false"); }
    btn.addEventListener("click", function (e) { e.stopPropagation(); pop.hidden ? open() : close(); });
    prev.addEventListener("click", function () { year--; render(); });
    nxt.addEventListener("click", function () { year++; render(); });
    bThis.addEventListener("click", function () { choose(today); });
    bNext.addEventListener("click", function () { choose(next); });
    pop.addEventListener("click", function (e) { e.stopPropagation(); });
    root._mpClose = close;
  }

  function boot() {
    document.documentElement.classList.add("js");
    Array.prototype.forEach.call(document.querySelectorAll("[data-mp]"), init);
  }
  document.addEventListener("click", function () {
    Array.prototype.forEach.call(document.querySelectorAll("[data-mp]"), function (r) { if (r._mpClose) r._mpClose(); });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") Array.prototype.forEach.call(document.querySelectorAll("[data-mp]"), function (r) { if (r._mpClose) r._mpClose(); });
  });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
