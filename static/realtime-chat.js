(() => {
  const config = document.currentScript.dataset;
  const list = document.getElementById(config.list);
  if (!list) return;
  const form = list.parentElement.querySelector(config.form);
  const input = form?.querySelector('[name="body"]');
  const button = form?.querySelector('[type="submit"]');
  const root = list.parentElement;
  const viewportRoot = root.closest('.support-inbox--selected') || root;
  const pageChatRoot = root.closest(".support-chat-main");
  root.classList.add("has-live-chat");
  root.dataset.liveChatConnection = "connecting";
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
  const resizeInput = () => {
    if (!input) return;
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 132) + "px";
  };
  resizeInput();
  const visualViewport = window.visualViewport;
  let largestViewportHeight = visualViewport?.height || window.innerHeight;
  let viewportTimer;
  const fitKeyboardViewport = () => {
    const visibleHeight = visualViewport?.height || window.innerHeight;
    if (pageChatRoot) {
      const viewportOffset = visualViewport?.offsetTop || 0;
      const top = Math.max(0, pageChatRoot.getBoundingClientRect().top - viewportOffset);
      pageChatRoot.style.setProperty(
        "--support-chat-main-height",
        `${Math.max(260, Math.floor(visibleHeight - top))}px`,
      );
    }
    if (!input || !window.matchMedia("(max-width: 600px)").matches) {
      viewportRoot.classList.remove("is-keyboard-open");
      pageChatRoot?.classList.remove("is-keyboard-open");
      viewportRoot.style.removeProperty("--live-chat-available-height");
      return;
    }
    if (document.activeElement !== input) largestViewportHeight = Math.max(largestViewportHeight, visibleHeight);
    const keyboardOpen = document.activeElement === input && largestViewportHeight - visibleHeight > 100;
    if (pageChatRoot) {
      pageChatRoot.classList.toggle("is-keyboard-open", keyboardOpen);
    } else {
      const top = Math.max(0, viewportRoot.getBoundingClientRect().top);
      viewportRoot.style.setProperty("--live-chat-available-height", `${Math.max(250, Math.floor(visibleHeight - top))}px`);
      viewportRoot.classList.toggle("is-keyboard-open", keyboardOpen);
    }
    if (keyboardOpen) requestAnimationFrame(() => { list.scrollTop = list.scrollHeight; });
  };
  const scheduleKeyboardViewport = () => {
    clearTimeout(viewportTimer);
    viewportTimer = setTimeout(fitKeyboardViewport, 40);
  };
  visualViewport?.addEventListener("resize", scheduleKeyboardViewport);
  visualViewport?.addEventListener("scroll", scheduleKeyboardViewport);
  input?.addEventListener("focus", () => {
    scheduleKeyboardViewport();
    setTimeout(fitKeyboardViewport, 220);
  });
  input?.addEventListener("blur", () => {
    setTimeout(fitKeyboardViewport, 120);
  });
  window.addEventListener("resize", scheduleKeyboardViewport);
  fitKeyboardViewport();
  const send = (value) => {
    if (socket?.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify(value)); return true;
  };
  const newClientId = () => {
    if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
    const bytes = new Uint8Array(16);
    if (typeof crypto.getRandomValues === "function") crypto.getRandomValues(bytes);
    else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256);
    bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
    const hex = [...bytes].map(byte => byte.toString(16).padStart(2, "0")).join("");
    return [hex.slice(0,8), hex.slice(8,12), hex.slice(12,16), hex.slice(16,20), hex.slice(20)].join("-");
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
    root.dataset.liveChatConnection = "connecting";
    status.textContent = "กำลังเชื่อมต่อ…";
    const prefix = config.admin ? "admin/" : "";
    socket = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/" + prefix + "chat/" + config.kind + "/" + config.room + "/");
    socket.onopen = () => { retry = 0; };
    socket.onmessage = ({data}) => {
      const event = JSON.parse(data);
      if (event.type === "ready") {
        root.dataset.liveChatConnection = "connected";
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
          form?.classList.remove("is-sending");
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
        form?.classList.remove("is-sending");
        if (button) button.disabled = !allowed;
        info.classList.add("live-chat-error");
        info.textContent = event.message;
      }
    };
    socket.onclose = (event) => {
      root.dataset.liveChatConnection = "reconnecting";
      status.textContent = event.code === 4403 ? "กรุณาเข้าสู่ระบบใหม่" : "การเชื่อมต่อขาด กำลังเชื่อมต่อใหม่…";
      if (event.code !== 4403) timer = setTimeout(connect, Math.min(30000, 1000 * 2 ** retry++));
    };
  }
  form?.addEventListener("submit", event => {
    if (!input.value.trim() || pending) return;
    if (!allowed) {
      event.preventDefault();
      info.textContent = "ไม่สามารถส่งข้อความในบทสนทนานี้ได้";
      return;
    }
    // Mobile in-app browsers can take a moment to open WebSocket connections.
    // Submit the regular Django form while it is unavailable so the message is never trapped on screen.
    if (socket?.readyState !== WebSocket.OPEN) {
      info.textContent = "กำลังส่งข้อความ…";
      return;
    }
    event.preventDefault();
    info.classList.remove("live-chat-error");
    // Keep the same ID until acknowledged, including after a network interruption.
    pending = {type:"send", body:input.value.trim(), client_id:newClientId()};
    rememberPending();
    storeDraft();
    form.classList.add("is-sending");
    if (button) button.disabled = true;
    info.textContent = "กำลังส่ง…";
    send(pending);
  });
  input?.addEventListener("keydown", event => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    if (input.value.trim() && !pending && allowed) form.requestSubmit();
  });
  let lastTyping = 0;
  input?.addEventListener("input", () => {
    resizeInput();
    storeDraft();
    if (Date.now() - lastTyping > 1200) { send({type:"typing"}); lastTyping = Date.now(); }
  });
  older.addEventListener("click", () => send({type:"history", before:oldest()}));
  document.addEventListener("visibilitychange", read);
  let readTimer;
  list.addEventListener("scroll", () => { clearTimeout(readTimer); readTimer = setTimeout(read, 150); });
  window.addEventListener("pagehide", () => {
    clearTimeout(timer);
    clearTimeout(viewportTimer);
    visualViewport?.removeEventListener("resize", scheduleKeyboardViewport);
    visualViewport?.removeEventListener("scroll", scheduleKeyboardViewport);
    socket.onclose = null;
    socket.close();
  });
  window.addEventListener("pageshow", event => { if (event.persisted) connect(); });
  setInterval(() => send({type:"ping"}), 30000);
  connect();
})();
