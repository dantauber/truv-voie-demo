// "Behind the scenes" panel: polls the server timeline so the demo shows
// API calls, Bridge events and webhooks as they happen.
(function () {
  var panel = document.getElementById("dev-panel");
  if (!panel) return;
  var url = panel.dataset.timelineUrl;
  var list = document.getElementById("dev-timeline");
  var orderStatus = document.getElementById("dev-order-status");
  var toggle = document.getElementById("dev-toggle");
  var body = document.getElementById("dev-body");

  function setCollapsed(collapsed) {
    body.hidden = collapsed;
    panel.classList.toggle("collapsed", collapsed);
    toggle.textContent = collapsed ? "Show" : "Hide";
    toggle.setAttribute("aria-expanded", String(!collapsed));
    localStorage.setItem("devPanelCollapsed", collapsed ? "1" : "0");
  }
  toggle.addEventListener("click", function () { setCollapsed(!body.hidden); });
  setCollapsed(localStorage.getItem("devPanelCollapsed") === "1");

  function time(iso) {
    var d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleTimeString();
  }

  function render(data) {
    orderStatus.textContent = (data.order_status || "waiting") + (data.order_finalized ? " (finalized)" : "");
    list.innerHTML = "";
    if (!data.timeline.length) {
      list.innerHTML = '<li class="muted">No events yet.</li>';
      return;
    }
    data.timeline.slice().reverse().forEach(function (ev) {
      var li = document.createElement("li");
      li.className = "ev ev-" + ev.kind;
      var head = document.createElement("div");
      var tag = document.createElement("span");
      tag.className = "ev-tag";
      tag.textContent = ev.kind;
      var label = document.createElement("span");
      label.className = "ev-label";
      label.textContent = ev.label;
      var when = document.createElement("span");
      when.className = "ev-time";
      when.textContent = time(ev.at);
      head.appendChild(tag);
      head.appendChild(label);
      li.appendChild(head);
      li.appendChild(when);
      if (ev.detail) {
        var pre = document.createElement("pre");
        pre.textContent = JSON.stringify(ev.detail, null, 1);
        li.appendChild(pre);
      }
      list.appendChild(li);
    });
  }

  function poll() {
    fetch(url, { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { if (data) render(data); })
      .catch(function () {})
      .finally(function () { setTimeout(poll, 2500); });
  }
  poll();
})();
