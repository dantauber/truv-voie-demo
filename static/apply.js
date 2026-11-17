// Prevent double submits, which would create two Truv orders.
(function () {
  var form = document.getElementById("apply-form");
  var button = document.getElementById("apply-submit");
  form.addEventListener("submit", function () {
    button.disabled = true;
    button.textContent = "Starting secure verification...";
  });
})();
