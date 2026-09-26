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
  const mediaUploadUrl = form?.dataset.mediaUploadUrl;
  const mediaPreview = form?.querySelector("[data-chat-media-preview]");
  const menuToggle = form?.querySelector("[data-chat-menu-toggle]");
  const mediaMenu = form?.querySelector("[data-chat-menu]");
  const cameraDialog = document.querySelector("[data-chat-camera-dialog]");
  const cameraPreview = cameraDialog?.querySelector("[data-chat-camera-preview]");
  const cameraOpen = form?.querySelector("[data-chat-camera-open]");
  const cameraClose = cameraDialog?.querySelector("[data-chat-camera-close]");
  const cameraCapture = cameraDialog?.querySelector("[data-chat-camera-capture]");
  const cameraRecord = cameraDialog?.querySelector("[data-chat-camera-record]");
  let mediaQueue = [];
  let mediaSending = false;
  let cameraStream = null;
  let mediaRecorder = null;
  let recordedChunks = [];

  const mediaError = value => {
    if (!info) return;
    info.classList.add("live-chat-error");
    info.textContent = value;
  };
  const refreshMediaPreview = () => {
    if (!mediaPreview) return;
    mediaPreview.replaceChildren();
    mediaPreview.hidden = mediaQueue.length === 0;
    mediaQueue.forEach((item, index) => {
      const card = document.createElement("div");
      card.className = "chat-composer__media-card";
      const preview = document.createElement(item.file.type.startsWith("video/") ? "video" : "img");
      preview.src = item.previewUrl;
      if (preview.tagName === "VIDEO") {
        preview.muted = true;
        preview.preload = "metadata";
      } else preview.alt = "ตัวอย่างรูปภาพที่เลือก";
      const remove = document.createElement("button");
      remove.type = "button";
      remove.title = "ยกเลิกไฟล์นี้";
      remove.setAttribute("aria-label", "ยกเลิกไฟล์นี้");
      remove.innerHTML = '<i data-lucide="x" aria-hidden="true"></i>';
      remove.addEventListener("click", () => {
        URL.revokeObjectURL(item.previewUrl);
        mediaQueue.splice(index, 1);
        refreshMediaPreview();
      });
      card.append(preview, remove);
      mediaPreview.append(card);
    });
    window.lucide?.createIcons({attrs: {"stroke-width": 2}});
  };
  const queueMedia = files => {
    const additions = Array.from(files || []).filter(file => {
      const supported = ["image/jpeg", "image/png", "image/webp", "video/mp4", "video/quicktime", "video/webm"].includes(file.type);
      if (!supported) mediaError("รองรับเฉพาะรูป JPG, PNG, WEBP และวิดีโอ MP4, MOV, WEBM");
      return supported;
    }).map(file => ({file, previewUrl: URL.createObjectURL(file)}));
    if (!additions.length) return;
    mediaQueue.push(...additions);
    if (info) { info.classList.remove("live-chat-error"); info.textContent = ""; }
    refreshMediaPreview();
  };
  form?.querySelectorAll("[data-chat-image-input], [data-chat-video-input]").forEach(fileInput => {
    fileInput.addEventListener("change", () => {
      queueMedia(fileInput.files);
      fileInput.value = "";
      mediaMenu?.setAttribute("hidden", "");
      menuToggle?.setAttribute("aria-expanded", "false");
    });
  });
  menuToggle?.addEventListener("click", () => {
    const open = mediaMenu?.hasAttribute("hidden");
    if (open) mediaMenu.removeAttribute("hidden");
    else mediaMenu?.setAttribute("hidden", "");
    menuToggle.setAttribute("aria-expanded", String(Boolean(open)));
  });
  document.addEventListener("pointerdown", event => {
    if (mediaMenu && !mediaMenu.hasAttribute("hidden") && !event.target.closest(".chat-composer__attachment")) {
      mediaMenu.setAttribute("hidden", "");
      menuToggle?.setAttribute("aria-expanded", "false");
    }
  });
  const stopCamera = () => {
    if (mediaRecorder?.state === "recording") mediaRecorder.stop();
    cameraStream?.getTracks().forEach(track => track.stop());
    cameraStream = null;
    if (cameraPreview) cameraPreview.srcObject = null;
    if (cameraRecord) {
      cameraRecord.dataset.recording = "false";
      cameraRecord.title = "เริ่มบันทึกวิดีโอ";
      cameraRecord.setAttribute("aria-label", "เริ่มบันทึกวิดีโอ");
    }
  };
  cameraOpen?.addEventListener("click", async () => {
    if (!cameraDialog?.showModal || !navigator.mediaDevices?.getUserMedia) {
      mediaError("เบราว์เซอร์นี้ไม่รองรับการเปิดกล้อง");
      return;
    }
    try {
      cameraStream = await navigator.mediaDevices.getUserMedia({video: {facingMode: {ideal: "environment"}}, audio: true});
      cameraPreview.srcObject = cameraStream;
      cameraDialog.showModal();
      await cameraPreview.play();
    } catch (_) {
      stopCamera();
      mediaError("ไม่สามารถเปิดกล้องได้ กรุณาอนุญาตสิทธิ์กล้องและไมโครโฟน");
    }
  });
  const closeCameraDialog = () => {
    stopCamera();
    if (cameraDialog?.open) cameraDialog.close();
  };
  cameraClose?.addEventListener("click", closeCameraDialog);
  cameraDialog?.addEventListener("cancel", event => { event.preventDefault(); closeCameraDialog(); });
  cameraCapture?.addEventListener("click", () => {
    if (!cameraPreview?.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = cameraPreview.videoWidth;
    canvas.height = cameraPreview.videoHeight;
    canvas.getContext("2d").drawImage(cameraPreview, 0, 0);
    canvas.toBlob(blob => {
      if (!blob) return;
      queueMedia([new File([blob], `camera-${Date.now()}.jpg`, {type: "image/jpeg"})]);
      closeCameraDialog();
    }, "image/jpeg", 0.9);
  });
  cameraRecord?.addEventListener("click", () => {
    if (!cameraStream || typeof MediaRecorder === "undefined") {
      mediaError("เบราว์เซอร์นี้ไม่รองรับการบันทึกวิดีโอจากกล้อง");
      return;
    }
    if (mediaRecorder?.state === "recording") {
      mediaRecorder.stop();
      return;
    }
    recordedChunks = [];
    try {
      mediaRecorder = new MediaRecorder(cameraStream, {mimeType: "video/webm"});
    } catch (_) {
      mediaRecorder = new MediaRecorder(cameraStream);
    }
    mediaRecorder.addEventListener("dataavailable", event => { if (event.data.size) recordedChunks.push(event.data); });
    mediaRecorder.addEventListener("stop", () => {
      if (!recordedChunks.length) return;
      const type = mediaRecorder.mimeType || "video/webm";
      queueMedia([new File([new Blob(recordedChunks, {type})], `camera-${Date.now()}.webm`, {type})]);
      closeCameraDialog();
    }, {once: true});
    mediaRecorder.start();
    cameraRecord.dataset.recording = "true";
    cameraRecord.title = "หยุดบันทึกวิดีโอ";
    cameraRecord.setAttribute("aria-label", "หยุดบันทึกวิดีโอ");
  });
  const uploadQueuedMedia = async () => {
    if (!mediaUploadUrl || mediaSending || !mediaQueue.length) return;
    mediaSending = true;
    const uploads = mediaQueue.splice(0);
    refreshMediaPreview();
    if (button) button.disabled = true;
    for (let index = 0; index < uploads.length; index += 1) {
      const payload = new FormData();
      payload.append("attachment", uploads[index].file);
      payload.append("body", index === 0 ? input.value.trim() : "");
      payload.append("client_id", newClientId());
      try {
        const response = await fetch(mediaUploadUrl, {
          method: "POST",
          headers: {"X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]")?.value || ""},
          body: payload,
          credentials: "same-origin",
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "ส่งไฟล์ไม่สำเร็จ");
        if (result.message) {
          messages.set(result.message.id, result.message);
          render(true);
        }
        URL.revokeObjectURL(uploads[index].previewUrl);
      } catch (error) {
        mediaQueue.unshift(...uploads.slice(index));
        refreshMediaPreview();
        mediaError(error.message || "ส่งไฟล์ไม่สำเร็จ");
        break;
      }
    }
    if (!mediaQueue.length) {
      input.value = "";
      resizeInput();
      storeDraft();
    }
    mediaSending = false;
    if (button) button.disabled = !allowed;
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
    const orderedMessages = [...messages.values()].sort((a,b) => a.id-b.id);
    const latestReadOwnId = Math.max(0, ...orderedMessages
      .filter(message => String(message.sender_id) === config.user && message.read_at)
      .map(message => message.id));
    const textWidth = (element, value) => {
      const style = getComputedStyle(element);
      const meter = document.createElement("span");
      meter.style.position = "fixed";
      meter.style.visibility = "hidden";
      meter.style.whiteSpace = "pre";
      meter.style.font = style.font;
      meter.style.letterSpacing = style.letterSpacing;
      meter.textContent = value;
      document.body.append(meter);
      const width = meter.getBoundingClientRect().width;
      meter.remove();
      return width;
    };
    const timeDividerLabel = (value) => {
      const date = new Date(value);
      const weekday = date.toLocaleDateString("th-TH", {weekday: "short"});
      const time = date.toLocaleTimeString("th-TH", {hour: "2-digit", minute: "2-digit", hour12: false});
      return `${weekday} ${time} น.`;
    };
    orderedMessages.forEach((message, index) => {
      const previousMessage = orderedMessages[index - 1];
      const messageDate = new Date(message.created_at);
      const previousDate = previousMessage ? new Date(previousMessage.created_at) : null;
      const isNewDay = previousDate && messageDate.toDateString() !== previousDate.toDateString();
      const isLongPause = previousDate && messageDate - previousDate >= 30 * 60 * 1000;
      if (!previousMessage || isNewDay || isLongPause) {
        const divider = document.createElement("p");
        divider.className = "live-chat-time-divider";
        divider.textContent = timeDividerLabel(message.created_at);
        list.append(divider);
      }
      const row = document.createElement("article");
      const isOwn = String(message.sender_id) === config.user;
      row.className = "live-chat-row" + (isOwn ? " is-own" : "");
      row.dataset.messageId = message.id;
      const bubble = document.createElement("div");
      bubble.className = "live-chat-bubble";
      let body = null;
      if (message.attachment_url) {
        const link = document.createElement("a");
        link.className = "live-chat-media-link";
        link.href = message.attachment_url;
        link.target = "_blank";
        link.rel = "noopener";
        link.setAttribute("aria-label", message.media_type === "video" ? "เปิดวิดีโอแบบเต็ม" : "เปิดรูปภาพแบบเต็ม");
        const media = document.createElement(message.media_type === "video" ? "video" : "img");
        media.className = "live-chat-media";
        media.src = message.attachment_url;
        if (message.media_type === "video") {
          media.controls = true;
          media.preload = "metadata";
          media.controlsList = "nodownload";
        } else {
          media.alt = "รูปภาพที่ส่งในแชท";
          media.loading = "lazy";
        }
        link.append(media);
        bubble.append(link);
      }
      if (message.body) {
        body = document.createElement("p");
        body.textContent = message.body;
        bubble.append(body);
      }
      const time = document.createElement("time");
      time.dateTime = message.created_at;
      time.textContent = new Date(message.created_at).toLocaleString("th-TH", {day:"numeric", month:"short", hour:"2-digit", minute:"2-digit"})
        + (row.classList.contains("is-own") ? (message.read_at ? " · อ่านแล้ว" : " · ส่งแล้ว") : "");
      bubble.append(time);
      const content = document.createElement("div");
      content.className = "live-chat-content";
      content.append(bubble);
      if (isOwn && message.id === latestReadOwnId) {
        const receipt = document.createElement("span");
        receipt.className = "live-chat-read-avatar";
        receipt.title = message.reader_name || "อ่านแล้ว";
        receipt.setAttribute("aria-label", message.reader_name || "อ่านแล้ว");
        if (message.reader_avatar_url) {
          const image = document.createElement("img");
          image.src = message.reader_avatar_url;
          image.alt = "";
          receipt.append(image);
        } else {
          receipt.textContent = (message.reader_name || "").trim().charAt(0).toUpperCase();
        }
        content.append(receipt);
      }
      if (!isOwn) {
        const avatar = document.createElement("span");
        const nextMessage = orderedMessages[index + 1];
        avatar.className = "live-chat-avatar" + (nextMessage && String(nextMessage.sender_id) === String(message.sender_id) ? " is-placeholder" : "");
        avatar.title = message.sender_name || "ผู้ใช้งาน";
        avatar.setAttribute("aria-label", message.sender_name || "ผู้ใช้งาน");
        if (message.sender_avatar_url) {
          const image = document.createElement("img");
          image.src = message.sender_avatar_url;
          image.alt = "";
          avatar.append(image);
        } else {
          avatar.textContent = (message.sender_name || "?").trim().charAt(0).toUpperCase() || "?";
        }
        row.append(avatar);
      }
      row.append(content); list.append(row);
      if (!message.attachment_url && body) {
        const longestLine = String(message.body).split("\n").reduce(
          (widest, line) => textWidth(body, line) > widest.width ? {width: textWidth(body, line), text: line} : widest,
          {width: 0, text: ""},
        );
        const contentWidth = Math.max(longestLine.width, textWidth(time, time.textContent));
        const bubbleStyle = getComputedStyle(bubble);
        const horizontalSpace = parseFloat(bubbleStyle.paddingLeft) + parseFloat(bubbleStyle.paddingRight)
          + parseFloat(bubbleStyle.borderLeftWidth) + parseFloat(bubbleStyle.borderRightWidth);
        const maximum = Math.min(window.innerWidth * (window.matchMedia("(max-width: 600px)").matches ? 0.88 : 0.78), 620);
        bubble.style.width = `${Math.max(76, Math.min(maximum, Math.ceil(contentWidth + horizontalSpace)))}px`;
      }
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
          if (m.id <= event.through && m.sender_id !== event.sender_id) {
            m.read_at = event.read_at || new Date().toISOString();
            m.reader_name = event.reader_name || null;
            m.reader_avatar_url = event.reader_avatar_url || null;
          }
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
    if (mediaQueue.length) {
      event.preventDefault();
      if (!allowed) {
        mediaError("ไม่สามารถส่งข้อความในบทสนทนานี้ได้");
        return;
      }
      uploadQueuedMedia();
      return;
    }
    if (!input.value.trim() || pending) {
      event.preventDefault();
      return;
    }
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
