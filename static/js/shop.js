(function () {
  "use strict";

  var DATA = JSON.parse(document.getElementById("shop-data").textContent);

  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  var money = function (n) { return (DATA.shop.currency || "₹") + Number(n || 0).toLocaleString("en-IN"); };

  function illustration(colors) {
    var main = (colors && colors[0]) || "#C2185B", trim = (colors && colors[1]) || "#E8A317";
    return '<svg viewBox="0 0 200 250" role="img" aria-label="Saree illustration" style="width:100%;height:100%;background:' + main + '1f">' +
      '<path d="M84 28 Q100 22 116 28 L118 58 Q100 62 82 58 Z" fill="' + trim + '" fill-opacity=".8"/>' +
      '<path d="M82 58 Q100 62 118 58 L150 228 Q100 238 50 228 Z" fill="' + main + '"/>' +
      '<path d="M60 140 L66 228 M76 140 L80 230 M92 140 L94 232" stroke="' + trim + '" stroke-opacity=".45" stroke-width="2" fill="none"/>' +
      '<path d="M54 212 Q100 222 146 212 L150 228 Q100 238 50 228 Z" fill="' + trim + '"/>' +
      '<path d="M118 30 Q84 60 70 140 L90 146 Q104 80 124 44 Z" fill="' + main + '" fill-opacity=".92"/>' +
      '<path d="M120 34 Q150 50 160 120 L144 126 Q138 78 118 50 Z" fill="' + main + '"/>' +
      '<path d="M160 120 L144 126 L140 112 L157 105 Z" fill="' + trim + '"/></svg>';
  }

  var occasion = "All", query = "", sortBy = "new", detailId = null;
  var HEART = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20.5s-7.5-4.6-7.5-10.2A4.3 4.3 0 0 1 12 7.6a4.3 4.3 0 0 1 7.5 2.7c0 5.6-7.5 10.2-7.5 10.2z"/></svg>';

  /* Saved sarees and "new since your last visit" are remembered on this device only. */
  function readStore(key, fallback) {
    try { var v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch (err) { return fallback; }
  }
  function writeStore(key, val) { try { localStorage.setItem(key, JSON.stringify(val)); } catch (err) {} }

  var saved = readStore("dobara-saved", []);
  if (!Array.isArray(saved)) saved = [];
  var newIds = (function () {
    var ids = DATA.sarees.map(function (x) { return x.id; }), out = [], sess = null;
    try { sess = sessionStorage.getItem("dobara-new"); } catch (err) {}
    if (sess) { try { out = JSON.parse(sess); } catch (err) { out = []; } }
    else {
      var seen = readStore("dobara-seen", null);
      if (Array.isArray(seen)) out = ids.filter(function (id) { return seen.indexOf(id) < 0; });
      try { sessionStorage.setItem("dobara-new", JSON.stringify(out)); } catch (err) {}
      writeStore("dobara-seen", ids);
    }
    return Array.isArray(out) ? out : [];
  })();

  function isAvailable(l) { return l.status === "available"; }
  function isNew(l) { return isAvailable(l) && newIds.indexOf(l.id) >= 0; }
  function isSaved(l) { return saved.indexOf(l.id) >= 0; }
  function pctOff(l) {
    var p = Number(l.price), o = Number(l.original);
    return o > p && o > 0 ? Math.round((1 - p / o) * 100) : 0;
  }
  function byId(id) {
    for (var i = 0; i < DATA.sarees.length; i++) if (String(DATA.sarees[i].id) === String(id)) return DATA.sarees[i];
    return null;
  }
  function orderButton(l) {
    if (l.status === "sold") return '<button class="btn ghost" disabled>Sold</button>';
    if (l.status === "reserved") return '<button class="btn ghost" disabled>On hold</button>';
    return DATA.shop.hasWhatsapp
      ? '<a class="btn" href="/go/order/' + encodeURIComponent(l.id) + '" target="_blank" rel="noopener">Order on WhatsApp</a>'
      : '<button class="btn" disabled>Order on WhatsApp</button>';
  }

  function unique(arr) {
    var out = [];
    arr.forEach(function (x) { if (x && out.indexOf(x) < 0) out.push(x); });
    return out;
  }

  function renderShop() {
    var newCount = DATA.sarees.filter(isNew).length, savedCount = DATA.sarees.filter(isSaved).length;
    var chips = [{ k: "All", t: "All" }];
    if (newCount) chips.push({ k: "__new", t: "New (" + newCount + ")" });
    chips.push({ k: "__saved", t: HEART + "Saved" + (savedCount ? " (" + savedCount + ")" : ""), raw: true });
    unique(DATA.sarees.map(function (x) { return x.occasion; })).forEach(function (o) { chips.push({ k: o, t: o }); });
    if (!chips.some(function (c) { return c.k === occasion; })) occasion = "All";
    $("chips").innerHTML = chips.map(function (c) {
      return '<button class="chip" type="button" aria-pressed="' + (c.k === occasion) + '" data-o="' + esc(c.k) + '">' + (c.raw ? c.t : esc(c.t)) + "</button>";
    }).join("");

    var note = $("newNote");
    if (newCount && occasion !== "__new") {
      note.innerHTML = "<b>" + newCount + (newCount === 1 ? " new saree" : " new sarees") + " since your last visit.</b> " +
        '<button class="linkbtn" type="button" data-o="__new">Show ' + (newCount === 1 ? "it" : "them") + "</button>";
      note.hidden = false;
    } else note.hidden = true;

    var sel = $("fabric"), cur = sel.value;
    var fabrics = unique(DATA.sarees.map(function (x) { return x.fabric; }));
    sel.innerHTML = '<option value="">All fabrics</option>' + fabrics.map(function (f) { return "<option>" + esc(f) + "</option>"; }).join("");
    if (fabrics.indexOf(cur) >= 0) sel.value = cur;

    renderGrid();
  }

  function card(l) {
    var off = pctOff(l);
    var orig = off ? "<s>" + money(l.original) + '</s><span class="off">' + off + "% off</span>" : "";
    return '<article class="item ' + (isAvailable(l) ? "" : "sold") + '" data-id="' + esc(l.id) + '">' +
      '<div class="pic"><button class="pic-open" type="button" data-open aria-label="See details of ' + esc(l.name) + '">' +
      (l.photo ? '<img src="' + esc(l.photo) + '" alt="' + esc(l.name) + '" loading="lazy">' : illustration(l.colors)) + "</button>" +
      (isNew(l) ? '<span class="tag-new">New</span>' : "") +
      '<button class="heart" type="button" data-save aria-pressed="' + isSaved(l) + '" aria-label="Save ' + esc(l.name) + '">' + HEART + "</button></div>" +
      '<div class="info"><h3><button class="name-open" type="button" data-open>' + esc(l.name) + "</button></h3>" +
      '<div class="meta">' + esc([l.fabric, l.occasion, l.condition].filter(Boolean).join(" · ")) + "</div>" +
      (l.blouse ? '<div class="meta">Blouse: ' + esc(l.blouse) + "</div>" : "") +
      '<div class="price"><strong>' + money(l.price) + "</strong>" + orig + "</div>" + orderButton(l) + "</div></article>";
  }

  function renderGrid() {
    var fabric = $("fabric").value;
    var words = query.toLowerCase().split(/\s+/).filter(Boolean);
    var list = DATA.sarees.filter(function (l) {
      if (occasion === "__new" ? !isNew(l) : occasion === "__saved" ? !isSaved(l) : (occasion !== "All" && l.occasion !== occasion)) return false;
      if (fabric && l.fabric !== fabric) return false;
      var text = [l.name, l.fabric, l.occasion, l.condition, l.blouse, l.description].join(" ").toLowerCase();
      return words.every(function (w) { return text.indexOf(w) >= 0; });
    });
    if (sortBy === "low") list.sort(function (a, b) { return Number(a.price) - Number(b.price); });
    else if (sortBy === "high") list.sort(function (a, b) { return Number(b.price) - Number(a.price); });
    else if (sortBy === "save") list.sort(function (a, b) { return pctOff(b) - pctOff(a); });
    list = list.filter(isAvailable).concat(list.filter(function (l) { return !isAvailable(l); }));

    var total = DATA.sarees.length, narrowed = occasion !== "All" || fabric || words.length;
    $("count").textContent = narrowed
      ? list.length + " of " + total + (total === 1 ? " saree" : " sarees")
      : total + (total === 1 ? " saree" : " sarees");

    var grid = $("grid");
    if (!list.length) {
      grid.innerHTML = '<div class="empty">' + (occasion === "__saved" && !fabric && !words.length
        ? "Nothing saved yet. Tap the heart on a saree to keep it here."
        : "No sarees match right now. Message us and we'll tell you when one comes in.") +
        (total ? '<br><button class="linkbtn" type="button" data-reset>Show all sarees</button>' : "") + "</div>";
      return;
    }
    grid.innerHTML = list.map(card).join("");
  }

  function toggleSaved(id) {
    var l = byId(id); if (!l) return;
    var i = saved.indexOf(l.id);
    if (i >= 0) saved.splice(i, 1); else saved.push(l.id);
    writeStore("dobara-saved", saved);
    renderShop();
    if ($("detail").open) renderDetail();
  }

  function renderDetail() {
    var l = byId(detailId); if (!l) { if ($("detail").open) $("detail").close(); return; }
    var off = pctOff(l), on = isSaved(l);
    var facts = [["Fabric", l.fabric], ["Occasion", l.occasion], ["Condition", l.condition], ["Blouse", l.blouse]]
      .filter(function (f) { return f[1]; })
      .map(function (f) { return "<dt>" + f[0] + "</dt><dd>" + esc(f[1]) + "</dd>"; }).join("");
    $("detailBody").innerHTML =
      '<div class="dt-pic"><button class="btn ghost small dt-close" type="button" data-close>Close</button>' +
      (l.photo ? '<img src="' + esc(l.photo) + '" alt="' + esc(l.name) + '">' : illustration(l.colors)) + "</div>" +
      '<div class="dt-info"><h2 id="dtName">' + esc(l.name) + "</h2>" +
      '<div class="price"><strong>' + money(l.price) + "</strong>" + (off ? "<s>" + money(l.original) + "</s>" : "") + "</div>" +
      (off ? '<p class="dt-save-note">You save ' + money(Number(l.original) - Number(l.price)) + " (" + off + "% off the original price)</p>" : "") +
      (l.description ? '<p class="dt-desc">' + esc(l.description) + "</p>" : "") +
      (facts ? '<dl class="facts">' + facts + "</dl>" : "") +
      '<div class="dt-actions">' + orderButton(l) +
      '<button class="btn ghost" type="button" data-save aria-pressed="' + on + '">' + (on ? "Saved. Tap to remove" : "Save for later") + "</button></div></div>";
  }

  function openDetail(id) {
    if (!byId(id)) return;
    detailId = id;
    renderDetail();
    if (!$("detail").open) $("detail").showModal();
    $("detail").scrollTop = 0;
  }

  function pickChip(e) {
    var b = e.target.closest("button[data-o]");
    if (!b) return;
    occasion = b.getAttribute("data-o");
    renderShop();
  }
  $("chips").addEventListener("click", pickChip);
  $("newNote").addEventListener("click", pickChip);
  $("fabric").addEventListener("change", renderGrid);
  $("sort").addEventListener("change", function () { sortBy = $("sort").value; renderGrid(); });
  $("q").addEventListener("input", function () { query = $("q").value; renderGrid(); });
  $("grid").addEventListener("click", function (e) {
    if (e.target.closest("[data-reset]")) {
      occasion = "All"; query = ""; $("q").value = ""; $("fabric").value = "";
      renderShop(); return;
    }
    var item = e.target.closest("[data-id]"); if (!item) return;
    var id = item.getAttribute("data-id");
    if (e.target.closest("[data-save]")) toggleSaved(id);
    else if (e.target.closest("[data-open]")) openDetail(id);
  });
  $("detail").addEventListener("click", function (e) {
    if (e.target === $("detail") || e.target.closest("[data-close]")) $("detail").close();
    else if (e.target.closest("[data-save]")) toggleSaved(detailId);
  });

  renderShop();
})();
