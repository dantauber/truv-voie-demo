// While Truv finishes processing, refresh the review page every few seconds.
(function () {
  var processing = document.getElementById("processing");
  var key = "reviewReloads:" + window.location.pathname;
  if (!processing) { sessionStorage.removeItem(key); return; }
  var count = parseInt(sessionStorage.getItem(key) || "0", 10);
  if (count >= 20) {
    var note = document.createElement("p");
    note.className = "alert alert-warning";
    note.textContent = "This is taking longer than usual. Refresh the page in a minute, or contact us if it continues.";
    processing.appendChild(note);
    sessionStorage.removeItem(key);
    return;
  }
  setTimeout(function () {
    sessionStorage.setItem(key, String(count + 1));
    window.location.reload();
  }, 4000);
})();
