// Opens Truv Bridge for the order and advances the borrower only when
// onEvent fires with type COMPLETED and source "order".
(function () {
  var card = document.getElementById("verify-card");
  var button = document.getElementById("open-bridge");
  var statusBox = document.getElementById("verify-status");
  var bridgeToken = card.dataset.bridgeToken;
  var eventUrl = card.dataset.eventUrl;
  var reviewUrl = card.dataset.reviewUrl;
  var completed = false;

  function showStatus(message, kind) {
    statusBox.textContent = message;
    statusBox.className = "alert alert-" + (kind || "info");
  }

  // Report Bridge events to the server so they appear in the timeline.
  // The server does not treat these as proof of verification.
  function report(type, source) {
    return fetch(eventUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: type, source: source || "" })
    }).catch(function () { /* timeline only, safe to ignore */ });
  }

  if (typeof window.TruvBridge === "undefined") {
    button.textContent = "Verification unavailable";
    showStatus("We could not load the secure verification window. Check your connection or disable content blockers, then refresh.", "error");
    return;
  }

  var bridge = window.TruvBridge.init({
    bridgeToken: bridgeToken,
    isOrder: true,
    // With isOrder, Bridge creates its iframe only when open() is called, so onLoad
    // fires after the borrower clicks. Do not gate the button on it.
    // LOAD also reaches onEvent below, which reports it to the timeline.
    onLoad: function () {},
    onEvent: function (type, payload, source) {
      report(type, source);
      if (type === "COMPLETED" && source === "order" && !completed) {
        completed = true;
        button.disabled = true;
        button.textContent = "Income verified";
        showStatus("Income verified. Taking you to review your application...", "success");
        report("ADVANCING", "app").then(function () {
          setTimeout(function () { window.location.href = reviewUrl; }, 1200);
        });
      }
    },
    onSuccess: function () {
      // Fires per connected employer. Not used to advance: the order may not be complete yet.
    },
    onClose: function () {
      if (!completed) {
        button.disabled = false;
        button.textContent = "Continue verification";
        showStatus("You closed the verification window before finishing. Select Continue verification to pick up where you left off.", "warning");
      }
    }
  });

  // bridge.js loaded and init succeeded, so the borrower can start.
  button.disabled = false;
  button.textContent = "Connect my employer";

  button.addEventListener("click", function () {
    statusBox.className = "alert hidden";
    bridge.open();
  });
})();
