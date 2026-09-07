(() => {
  const admin = document.currentScript.dataset.admin === "true";
  const originalTitle = document.title;
  let socket, attempts = 0, timer, previous = -1, refreshing = false;
  function badge(link, count) {
    if (!link) return;
    let element = link.querySelector(".live-notification-badge, .admin-support-rail__badge, [data-notification-count], span.absolute");
    if (!element && count) {
      element = document.createElement("span");
      element.className = "live-notification-badge";
      link.style.position = "relative";
      link.append(element);
    }
    if (element) {
      element.classList.add("live-notification-count");
      element.textContent = count > 99 ? "99+" : count;
      element.hidden = !count;
      element.setAttribute("aria-label", "ยังไม่อ่าน " + count + " รายการ");
    }
  }
  function connect() {
    socket = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/" + (admin ? "admin/" : "") + "events/");
    socket.onopen = () => { attempts = 0; };
    socket.onmessage = async ({data}) => {
      const event = JSON.parse(data);
      if (event.type !== "notifications") return;
      const count = admin ? event.admin_support_chat_count : event.seller_support_chat_count;
      badge(document.querySelector("[data-admin-support-link]"), count);
      document.querySelectorAll('a[href="/accounts/support/chat/"]').forEach(el => badge(el, count));
      document.querySelectorAll('[data-notification-bell], a[href="/accounts/notifications/"], a[href="/admin/accounts/notification/"]').forEach(el => badge(el, event.unread_notification_count));
      if (admin && count > previous && previous >= 0) {
        document.title = "(" + count + ") ข้อความใหม่จากผู้ขาย";
      }
      if (!count) document.title = originalTitle;
      previous = count;
      if (admin && document.querySelector(".support-inbox__threads") && !refreshing) {
        refreshing = true;
        try {
          const url = new URL(location.href); url.searchParams.delete("ticket");
          const response = await fetch(url, {credentials:"same-origin"});
          if (response.ok) {
            const html = new DOMParser().parseFromString(await response.text(), "text/html");
            const incoming = html.querySelector(".support-inbox__threads");
            if (incoming) {
              const selected = new URL(location.href).searchParams.get("ticket");
              incoming.querySelectorAll("a").forEach(link => {
                if (new URL(link.href, location.origin).searchParams.get("ticket") === selected) {
                  link.classList.add("is-selected"); link.setAttribute("aria-current", "page");
                }
              });
              document.querySelector(".support-inbox__threads").replaceWith(incoming);
            }
          }
        } catch (_) {} finally { refreshing = false; }
      }
    };
    socket.onclose = event => {
      if (event.code !== 4403) timer = setTimeout(connect, Math.min(30000, 1000 * 2 ** attempts++));
    };
  }
  window.addEventListener("pagehide", () => { clearTimeout(timer); socket.onclose = null; socket.close(); });
  window.addEventListener("pageshow", event => { if (event.persisted) connect(); });
  setInterval(() => { if (socket?.readyState === WebSocket.OPEN) socket.send('{"type":"ping"}'); }, 30000);
  connect();
})();
