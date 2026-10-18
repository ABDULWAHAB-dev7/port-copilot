/* Customs Copilot: shared behaviour. Menu, scroll reveals, service status. */
(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* Mobile menu */
  var btn = document.getElementById("menu-btn");
  var nav = document.getElementById("main-nav");
  if (btn && nav) {
    var setOpen = function (on) {
      nav.classList.toggle("open", on);
      btn.setAttribute("aria-expanded", on ? "true" : "false");
    };
    btn.addEventListener("click", function () { setOpen(!nav.classList.contains("open")); });
    nav.addEventListener("click", function (e) { if (e.target.closest("a")) setOpen(false); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") setOpen(false); });
  }

  /* Reveal on scroll */
  var items = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && !reduceMotion) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("in");
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1, rootMargin: "0px 0px -5% 0px" });
    items.forEach(function (el) { io.observe(el); });
  } else {
    items.forEach(function (el) { el.classList.add("in"); });
  }


  /* Scroll-linked motion: progress bar, header, photo parallax, step rail */
  var bar = document.createElement("div");
  bar.className = "progress";
  bar.setAttribute("aria-hidden", "true");
  document.body.appendChild(bar);

  var header = document.querySelector(".site-header");
  var toTop = document.getElementById("to-top");
  var photos = Array.prototype.slice.call(document.querySelectorAll(".ph img"));
  var rail = document.querySelector(".steps");
  var ticking = false;

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  function frame() {
    ticking = false;
    var y = window.scrollY, vh = window.innerHeight;
    var max = document.documentElement.scrollHeight - vh;
    bar.style.transform = "scaleX(" + (max > 0 ? clamp(y / max, 0, 1) : 0).toFixed(4) + ")";
    if (header) header.classList.toggle("scrolled", y > 8);
    if (toTop) toTop.hidden = y < 900;
    if (reduceMotion) return;
    photos.forEach(function (img) {
      var box = img.parentElement.getBoundingClientRect();
      if (box.bottom < -80 || box.top > vh + 80) return;
      var lim = box.height * 0.065;
      var delta = (box.top + box.height / 2 - vh / 2) / vh;
      img.style.setProperty("--py", clamp(-delta * lim * 2, -lim, lim).toFixed(1) + "px");
    });
    if (rail) {
      var r = rail.getBoundingClientRect();
      rail.style.setProperty("--p", clamp((vh * 0.6 - r.top) / r.height, 0, 1).toFixed(3));
    }
  }
  function queue() { if (!ticking) { ticking = true; window.requestAnimationFrame(frame); } }
  window.addEventListener("scroll", queue, { passive: true });
  window.addEventListener("resize", queue);
  frame();

  /* Current section in the header */
  var links = document.querySelectorAll('.main-nav a[href^="#"]');
  if (links.length && "IntersectionObserver" in window) {
    var map = {};
    links.forEach(function (a) { map[a.getAttribute("href").slice(1)] = a; });
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        links.forEach(function (a) { a.removeAttribute("aria-current"); });
        var a = map[entry.target.id];
        if (a) a.setAttribute("aria-current", "true");
      });
    }, { rootMargin: "-40% 0px -55% 0px" });
    Object.keys(map).forEach(function (id) {
      var el = document.getElementById(id);
      if (el) spy.observe(el);
    });
  }

  /* Service status. Other scripts can wait on window.ccHealth. */
  function paint(text, ok) {
    document.querySelectorAll("[data-status]").forEach(function (el) {
      el.textContent = text;
      var dot = el.previousElementSibling;
      if (dot && dot.classList.contains("dot")) dot.style.background = ok ? "#6FB3A8" : "#D39B3A";
    });
  }
  window.ccHealth = fetch("/api/health").then(function (res) {
    if (!res.ok) throw new Error("status " + res.status);
    return res.json();
  }).then(function (h) {
    paint(h && h.llm_available ? "Service online, AI drafting on" : "Service online, offline mode", true);
    return h;
  }).catch(function () {
    paint("Service unavailable", false);
    return null;
  });
})();
