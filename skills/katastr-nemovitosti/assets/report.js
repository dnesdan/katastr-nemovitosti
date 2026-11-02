"use strict";
(() => {
  const cards = Array.from(document.querySelectorAll(".finding-card"));
  const filters = Array.from(document.querySelectorAll("[data-status-filter]"));
  const search = document.getElementById("finding-search");
  const topic = document.getElementById("topic-filter");
  const count = document.getElementById("finding-count");
  const empty = document.getElementById("no-filter-results");
  let status = "all";
  const normalize = (s) => String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("cs");
  const applyFilters = () => {
    const query = normalize(search ? search.value : "");
    const selectedTopic = topic ? topic.value : "all";
    let visible = 0;
    cards.forEach((card) => {
      const show = (status === "all" || card.dataset.status === status) &&
        (selectedTopic === "all" || card.dataset.topic === selectedTopic) &&
        normalize(card.dataset.search).includes(query);
      card.hidden = !show;
      if (show) visible++;
    });
    if (count) count.textContent = "Zobrazeno " + visible + " z " + cards.length + " nálezů";
    if (empty) empty.hidden = visible > 0 || cards.length === 0;
  };
  filters.forEach((button) => button.addEventListener("click", () => {
    status = button.dataset.statusFilter;
    filters.forEach((b) => {
      const active = b === button;
      b.classList.toggle("active", active);
      b.setAttribute("aria-pressed", String(active));
    });
    applyFilters();
  }));
  if (search) search.addEventListener("input", applyFilters);
  if (topic) topic.addEventListener("change", applyFilters);
  const revealFinding = (hash) => {
    if (!hash || !hash.startsWith("#")) return;
    let target;
    try { target = document.getElementById(decodeURIComponent(hash.slice(1))); }
    catch (_) { return; }
    if (!target?.classList.contains("finding-card") || !target.hidden) return;
    status = "all";
    if (search) search.value = "";
    if (topic) topic.value = "all";
    filters.forEach((b) => {
      const active = b.dataset.statusFilter === "all";
      b.classList.toggle("active",active);
      b.setAttribute("aria-pressed",String(active));
    });
    applyFilters();
  };
  document.addEventListener("click", (event) => {
    const link = event.target.closest?.("a[href^='#']");
    if (link) revealFinding(link.getAttribute("href"));
  });
  window.addEventListener("hashchange", () => revealFinding(window.location.hash));

  const map = document.getElementById("property-map");
  const objects = Array.from(document.querySelectorAll(".map-object"));
  const keys = Array.from(document.querySelectorAll("[data-select-object]"));
  const selectedTitle = document.getElementById("map-selected-title");
  const selectedDetail = document.getElementById("map-selected-detail");
  const selectObject = (id) => {
    let selected;
    objects.forEach((o) => {
      const active = o.dataset.object === id;
      o.classList.toggle("selected", active);
      o.setAttribute("aria-pressed", String(active));
      if (active) selected = o;
    });
    keys.forEach((key) => {
      const active = key.dataset.selectObject === id;
      key.classList.toggle("selected", active);
      key.setAttribute("aria-pressed", String(active));
    });
    if (selected && selectedTitle) selectedTitle.textContent = selected.dataset.label;
    if (selected && selectedDetail) selectedDetail.textContent = selected.dataset.detail;
  };
  objects.forEach((o) => {
    o.addEventListener("click", () => selectObject(o.dataset.object));
    o.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectObject(o.dataset.object);
      }
    });
  });
  keys.forEach((key) => key.addEventListener("click", () => selectObject(key.dataset.selectObject)));
  if (map) {
    let view = {x: 0, y: 0, w: 900, h: 540};
    let drag = null;
    const scaleNote = document.querySelector(".map-scale");
    const updateView = () => {
      map.setAttribute("viewBox", [view.x, view.y, view.w, view.h].join(" "));
      if (scaleNote) {
        if (Math.abs(view.w - 900) > 0.01) scaleNote.setAttribute("hidden", "");
        else scaleNote.removeAttribute("hidden");
      }
    };
    document.querySelectorAll("[data-map-action]").forEach((button) => button.addEventListener("click", () => {
      const action = button.dataset.mapAction;
      if (action === "reset") view = {x: 0, y: 0, w: 900, h: 540};
      else {
        const factor = action === "in" ? 0.8 : 1.25;
        const newWidth = Math.min(1800, Math.max(90, view.w * factor));
        const newHeight = newWidth * 0.6;
        view = {x: view.x + (view.w-newWidth)/2, y: view.y + (view.h-newHeight)/2, w: newWidth, h: newHeight};
      }
      updateView();
    }));
    map.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || event.target.closest(".map-object")) return;
      drag = {pointerId:event.pointerId, x:event.clientX, y:event.clientY, startX:view.x, startY:view.y};
      map.setPointerCapture(event.pointerId);
      map.classList.add("dragging");
    });
    map.addEventListener("pointermove", (event) => {
      if (!drag || drag.pointerId !== event.pointerId) return;
      const rect = map.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      view.x = drag.startX - (event.clientX-drag.x)*view.w/rect.width;
      view.y = drag.startY - (event.clientY-drag.y)*view.h/rect.height;
      updateView();
    });
    const endDrag = () => {drag = null; map.classList.remove("dragging");};
    map.addEventListener("pointerup", endDrag);
    map.addEventListener("pointercancel", endDrag);
    map.addEventListener("lostpointercapture", endDrag);
    map.addEventListener("keydown", (event) => {
      const moves = {ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
      if (!moves[event.key]) return;
      event.preventDefault();
      view.x += moves[event.key][0]*view.w*0.1;
      view.y += moves[event.key][1]*view.h*0.1;
      updateView();
    });
  }

  let printState = null;
  const beforePrint = () => {
    if (printState) return;
    printState = {
      details:Array.from(document.querySelectorAll("details")).map((d) => [d,d.open]),
      cards:cards.map((card) => [card,card.hidden]),
      mapView:map ? map.getAttribute("viewBox") : null,
      count:count ? count.textContent : null,
      scaleHidden:document.querySelector(".map-scale")?.hasAttribute("hidden") || false,
    };
    printState.details.forEach(([d]) => {d.open=true;});
    cards.forEach((card) => {card.hidden=false;});
    if (count) count.textContent = cards.length + " nálezů v přehledu";
    if (map) map.setAttribute("viewBox","0 0 900 540");
    document.querySelector(".map-scale")?.removeAttribute("hidden");
  };
  const afterPrint = () => {
    if (!printState) return;
    printState.details.forEach(([d,open]) => {d.open=open;});
    printState.cards.forEach(([card,hidden]) => {card.hidden=hidden;});
    if (map && printState.mapView) map.setAttribute("viewBox",printState.mapView);
    if (printState.scaleHidden) document.querySelector(".map-scale")?.setAttribute("hidden", "");
    if (count && printState.count !== null) count.textContent=printState.count;
    printState=null;
  };
  window.addEventListener("beforeprint",beforePrint);
  window.addEventListener("afterprint",afterPrint);
  const printButton = document.getElementById("print-report");
  if (printButton) printButton.addEventListener("click", () => window.print());
})();
