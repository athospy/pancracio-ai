// Polls /dashboard/widgets every 60s and swaps the result into the page — this app's first
// client-side data-fetching logic. A failed poll (network error, or any non-2xx that isn't a
// 401) leaves the last-good widgets on screen rather than blanking the page; only a 401 (an
// expired session) forces a full navigation, since that needs a real re-login, not a re-render.
(function () {
  const container = document.getElementById("dashboard-widgets");
  if (!container) return;

  async function refresh() {
    let res;
    try {
      res = await fetch("/dashboard/widgets");
    } catch (err) {
      return;
    }
    if (res.status === 401) {
      window.location = "/login";
      return;
    }
    if (!res.ok) return;
    container.innerHTML = await res.text();
  }

  setInterval(refresh, 60000);
})();
