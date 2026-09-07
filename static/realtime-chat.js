(() => {
  const config = document.currentScript.dataset;
  const list = document.getElementById(config.list);
  if (!list) return;
  const form = list.parentElement.querySelector(config.form);
  const input = form?.querySelector('[name="body"]');
  const button = form?.querySelector('[type="submit"]');
  const root = list.parentElement;
  root.classList.add("has-live-chat");
  const bar = document.createElement("div");
  bar.className = "live-chat-bar";
  const status = document.createElement("span");
  status.setAttribute("role", "status");
  const older = document.createElement("button");
  older.type = "button";
  older.textContent = "ข้อความก่อนหน้า";
  older.className = "live-chat-history";
  older.hidden = true;
  bar.append(status, older);
  root.insertBefore(bar, list);
  const info = document.createElement("div");
  info.className = "live-chat-info";
  info.setAttribute("aria-live", "polite");
  list.after(info);
  list.classList.add("live-chat-list");
  const draftKey = ["chat-draft", config.user, config.kind, config.room].join(":");
  const pendingKey = draftKey + ":pending";
  let socket, retry = 0, timer, typingTimer, first = true, pending = null, allowed = true;
  let messages = new Map();
  try {
    const saved = JSON.parse(sessionStorage.getItem(pendingKey));
    if (saved?.type === "send" && typeof saved.body === "string" && typeof saved.client_id === "string") pending = saved;
  } catch (_) {}
  const rememberPending = () => {
    try {
      if (pending) sessionStorage.setItem(pendingKey, JSON.stringify(pending));
      else sessionStorage.removeItem(pendingKey);
    } catch (_) {}
  };
  const storeDraft = () => { try { sessionStorage.setItem(draftKey, input?.value || ""); } catch (_) {} };
  try { if (input && !input.value) input.value = sessionStorage.getItem(draftKey) || ""; } catch (_) {}
  const send = (value) => {
    if (socket?.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify(value)); return true;
  };
  const latest = () => Math.max(0, ...messages.keys());
  const oldest = () => Math.min(...messages.keys());
  const read = () => {
    if (!document.hidden && latest() && list.scrollHeight - list.scrollTop - list.clientHeight < 90)
      send({type:"read", through:latest()});
  };
  function render(scroll = false, prepend = false) {
    const height = list.scrollHeight, top = list.scrollTop;
    const atBottom = height - top - list.clientHeight < 90;
    list.replaceChildren();
    [...messages.values()].sort((a,b) => a.id-b.id).forEach((message) => {
      const row = document.createElement("article");
      row.className = "live-chat-row" + (String(message.sender_id) === config.user ? " is-own" : "");
      row.dataset.messageId = message.id;
      const bubble = document.createElement("div");
      bubble.className = "live-chat-bubble";
      const body = document.createElement("p");
      body.textContent = message.body;
      const time = document.createElement("time");
      time.dateTime = message.created_at;
      time.textContent = new Date(message.created_at).toLocaleString("th-TH", {day:"numeric", month:"short", hour:"2-digit", minute:"2-digit"})
        + (row.classList.contains("is-own") ? (message.read_at ? " · อ่านแล้ว" : " · ส่งแล้ว") : "");
      bubble.append(body,time); row.append(bubble); list.append(row);
    });
    if (scroll || atBottom) list.scrollTop = list.scrollHeight;
    else list.scrollTop = top + (prepend ? list.scrollHeight - height : 0);
  }
  function connect() {
    status.textContent = "กำลังเชื่อมต่อ…";
    const prefix = config.admin ? "admin/" : "";
    socket = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/" + prefix + "chat/" + config.kind + "/" + config.room + "/");
    socket.onopen = () => { retry = 0; };
    socket.onmessage = ({data}) => {
      const event = JSON.parse(data);
      if (event.type === "ready") {
        status.textContent = "เชื่อมต่อแล้ว";
        send({type:"history", after:latest()});
        if (pending) send(pending);
      } else if (event.type === "history") {
        allowed = event.can_send;
        if (button) button.disabled = !allowed || Boolean(pending);
        event.messages.forEach(m => messages.set(m.id, m));
        if (!event.after) older.hidden = !event.more;
        render(first, Boolean(event.before)); first = false; read();
        if (event.after && event.more) send({type:"history", after:latest()});
      } else if (event.type === "message" || event.type === "ack") {
        const m = event.message;
        if (String(m.sender_id) !== config.user) {
          clearTimeout(typingTimer);
          if (!pending) info.textContent = "";
        }
        messages.set(m.id, {...messages.get(m.id), ...m});
        if (pending && pending.client_id === m.client_id) {
          if (input.value.trim() === pending.body) input.value = "";
          pending = null; rememberPending(); storeDraft();
          if (button) button.disabled = !allowed;
          info.textContent = "";
        }
        render(String(m.sender_id) === config.user); read();
      } else if (event.type === "room") {
        allowed = event.can_send;
        if (button) button.disabled = !allowed || Boolean(pending);
        document.querySelectorAll(".support-inbox__status, [data-live-chat-status]").forEach(badge => {
          badge.textContent = event.label;
          badge.dataset.status = event.status;
          if (badge.classList.contains("support-inbox__status")) {
            badge.className = "support-inbox__status support-inbox__status--" + event.status;
          }
        });
      } else if (event.type === "read") {
        messages.forEach(m => {
          if (m.id <= event.through && m.sender_id !== event.sender_id) m.read_at = true;
        });
        render();
      } else if (event.type === "typing" && String(event.sender_id) !== config.user) {
        info.textContent = "กำลังพิมพ์…";
        clearTimeout(typingTimer);
        typingTimer = setTimeout(() => { info.textContent = ""; }, 2500);
      } else if (event.type === "error") {
        pending = null;
        rememberPending();
        if (button) button.disabled = !allowed;
        info.classList.add("live-chat-error");
        info.textContent = event.message;
      }
    };
    socket.onclose = (event) => {
      status.textContent = event.code === 4403 ? "กรุณาเข้าสู่ระบบใหม่" : "การเชื่อมต่อขาด กำลังเชื่อมต่อใหม่…";
      if (event.code !== 4403) timer = setTimeout(connect, Math.min(30000, 1000 * 2 ** retry++));
    };
  }
  form?.addEventListener("submit", event => {
    event.preventDefault();
    if (!input.value.trim() || pending) return;
    if (!allowed) { info.textContent = "ไม่สามารถส่งข้อความในบทสนทนานี้ได้"; return; }
    info.classList.remove("live-chat-error");
    // Keep the same ID until acknowledged, including after a network interruption.
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
    const hex = [...bytes].map(b => b.toString(16).padStart(2,"0")).join("");
    pending = {type:"send", body:input.value.trim(), client_id:[hex.slice(0,8),hex.slice(8,12),hex.slice(12,16),hex.slice(16,20),hex.slice(20)].join("-")};
    rememberPending();
    storeDraft();
    if (button) button.disabled = true;
    info.textContent = "กำลังส่ง…";
    send(pending);
  });
  let lastTyping = 0;
  input?.addEventListener("input", () => {
    storeDraft();
    if (Date.now() - lastTyping > 1200) { send({type:"typing"}); lastTyping = Date.now(); }
  });
  older.addEventListener("click", () => send({type:"history", before:oldest()}));
  document.addEventListener("visibilitychange", read);
  let readTimer;
  list.addEventListener("scroll", () => { clearTimeout(readTimer); readTimer = setTimeout(read, 150); });
  window.addEventListener("pagehide", () => { clearTimeout(timer); socket.onclose = null; socket.close(); });
  window.addEventListener("pageshow", event => { if (event.persisted) connect(); });
  setInterval(() => send({type:"ping"}), 30000);
  connect();
})();
