"""Render the Mirror client-side state and gift-effect compositor."""

from __future__ import annotations

from .state import MIRROR_IMAGE_ROUTE, MIRROR_MEDIA_ROUTE


def render_page_script(events_route: str, settings_json: str) -> str:
    """Return the client script with runtime routes and settings embedded."""
    return f"""    const panel = document.getElementById("panel");
    const effectLayer = document.getElementById("effect-layer");
    const maxMessages = 200;
    const PANEL_LAYOUT_STORAGE_KEY = "bilihud-mirror-layout-v1";
    const PANEL_MIN_WIDTH = 240;
    const PANEL_MIN_HEIGHT = 96;
    const PANEL_RESIZE_HANDLE_SIZE = 24;
    let giftEffectsEnabled = false;
    let userAvatarsEnabled = false;
    let panelLayout = null;
    let interactionState = null;
    let panelInitialized = false;
    let activeEffectCleanup = null;

    function clamp(value, minimum, maximum) {{
      return Math.max(minimum, Math.min(maximum, value));
    }}

    function readPanelLayout() {{
      try {{
        const raw = window.localStorage.getItem(PANEL_LAYOUT_STORAGE_KEY);
        if (!raw) return null;
        const value = JSON.parse(raw);
        if (!value || typeof value !== "object") return null;
        const layout = {{
          x: Number(value.x),
          y: Number(value.y),
          width: Number(value.width),
          height: Number(value.height),
        }};
        if (![layout.x, layout.y, layout.width, layout.height].every(Number.isFinite)) return null;
        if (layout.x < 0 || layout.x > 100 || layout.y < 0 || layout.y > 100) return null;
        if (layout.width < 1 || layout.width > 100 || layout.height < 1 || layout.height > 100) return null;
        return layout;
      }} catch (_error) {{
        return null;
      }}
    }}

    function persistPanelLayout() {{
      const viewportWidth = Math.max(1, window.innerWidth);
      const viewportHeight = Math.max(1, window.innerHeight);
      const rect = panel.getBoundingClientRect();
      panelLayout = {{
        x: clamp((rect.left / viewportWidth) * 100, 0, 100),
        y: clamp((rect.top / viewportHeight) * 100, 0, 100),
        width: clamp((rect.width / viewportWidth) * 100, 1, 100),
        height: clamp((rect.height / viewportHeight) * 100, 1, 100),
      }};
      try {{
        window.localStorage.setItem(PANEL_LAYOUT_STORAGE_KEY, JSON.stringify(panelLayout));
      }} catch (_error) {{
        // Private browsing can disable storage; the live layout still works.
      }}
    }}

    function applySettings(settings) {{
      giftEffectsEnabled = settings.giftEffects === true;
      const nextUserAvatarsEnabled = settings.userAvatars === true;
      const avatarsChanged = nextUserAvatarsEnabled !== userAvatarsEnabled;
      userAvatarsEnabled = nextUserAvatarsEnabled;
      const fontFamily = typeof settings.fontFamily === "string"
        ? settings.fontFamily.trim()
        : "";
      const cssFontFamily = fontFamily.length > 0
        ? fontFamily
        : "'Segoe UI', 'Microsoft YaHei', sans-serif";
      document.body.style.setProperty("--hud-font-family", cssFontFamily);
      const danmakuX = Number(settings.danmakuX);
      const danmakuY = Number(settings.danmakuY);
      const nextX = Number.isFinite(danmakuX) ? clamp(danmakuX, 0, 100) : 4;
      const nextY = Number.isFinite(danmakuY) ? clamp(danmakuY, 0, 100) : 4;
      document.body.style.setProperty("--danmaku-x", nextX + "%");
      document.body.style.setProperty("--danmaku-y", nextY + "%");
      if (panelInitialized && panelLayout !== null) {{
        panelLayout.x = nextX;
        panelLayout.y = nextY;
        restorePanelLayout();
        persistPanelLayout();
      }}
      if (avatarsChanged) syncUserAvatars();
    }}

    applySettings({settings_json});

    function restorePanelLayout() {{
      if (panelLayout === null) return;
      panel.style.width = panelLayout.width + "vw";
      panel.style.height = panelLayout.height + "vh";
      setPanelPosition(
        (panelLayout.x / 100) * Math.max(1, window.innerWidth),
        (panelLayout.y / 100) * Math.max(1, window.innerHeight),
      );
    }}

    function setPanelPosition(leftPx, topPx) {{
      const maxLeft = Math.max(0, window.innerWidth - panel.offsetWidth);
      const maxTop = Math.max(0, window.innerHeight - panel.offsetHeight);
      const nextLeft = Math.max(0, Math.min(maxLeft, leftPx));
      const nextTop = Math.max(0, Math.min(maxTop, topPx));
      const leftPercent = window.innerWidth > 0 ? (nextLeft / window.innerWidth) * 100 : 0;
      const topPercent = window.innerHeight > 0 ? (nextTop / window.innerHeight) * 100 : 0;
      document.body.style.setProperty("--danmaku-x", leftPercent + "%");
      document.body.style.setProperty("--danmaku-y", topPercent + "%");
    }}

    function setPanelSize(widthPx, heightPx) {{
      const maxWidth = Math.max(PANEL_MIN_WIDTH, window.innerWidth - 16);
      const maxHeight = Math.max(PANEL_MIN_HEIGHT, window.innerHeight - 16);
      panel.style.width = clamp(widthPx, PANEL_MIN_WIDTH, maxWidth) + "px";
      panel.style.height = clamp(heightPx, PANEL_MIN_HEIGHT, maxHeight) + "px";
      const rect = panel.getBoundingClientRect();
      setPanelPosition(rect.left, rect.top);
    }}

    function isResizeHandle(event, rect) {{
      return event.clientX >= rect.right - PANEL_RESIZE_HANDLE_SIZE
        && event.clientY >= rect.bottom - PANEL_RESIZE_HANDLE_SIZE;
    }}

    panel.addEventListener("pointerdown", event => {{
      if (event.button !== 0) return;
      const rect = panel.getBoundingClientRect();
      const resizing = isResizeHandle(event, rect);
      interactionState = {{
        mode: resizing ? "resize" : "move",
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        offsetX: event.clientX - rect.left,
        offsetY: event.clientY - rect.top,
        startWidth: rect.width,
        startHeight: rect.height,
      }};
      panel.classList.toggle("is-dragging", !resizing);
      panel.classList.toggle("is-resizing", resizing);
      panel.setPointerCapture(event.pointerId);
      event.preventDefault();
    }});

    panel.addEventListener("pointermove", event => {{
      const state = interactionState;
      if (state === null) {{
        panel.style.cursor = isResizeHandle(event, panel.getBoundingClientRect())
          ? "nwse-resize"
          : "move";
        return;
      }}
      if (event.pointerId !== state.pointerId) return;
      if (state.mode === "resize") {{
        setPanelSize(
          state.startWidth + event.clientX - state.startX,
          state.startHeight + event.clientY - state.startY,
        );
      }} else {{
        setPanelPosition(event.clientX - state.offsetX, event.clientY - state.offsetY);
      }}
      event.preventDefault();
    }});

    function finishPanelInteraction(event) {{
      const state = interactionState;
      if (state === null || event.pointerId !== state.pointerId) return;
      if (panel.hasPointerCapture(event.pointerId)) panel.releasePointerCapture(event.pointerId);
      interactionState = null;
      panel.classList.remove("is-dragging");
      panel.classList.remove("is-resizing");
      panel.style.cursor = "move";
      persistPanelLayout();
    }}

    panel.addEventListener("pointerup", finishPanelInteraction);
    panel.addEventListener("pointercancel", finishPanelInteraction);

    panelLayout = readPanelLayout();
    restorePanelLayout();
    panelInitialized = true;
    window.addEventListener("resize", () => restorePanelLayout());

    function appendText(parent, text) {{
      parent.appendChild(document.createTextNode(text));
    }}

    function appendUserAvatar(parent, entry) {{
      const avatarUrl = typeof entry.userAvatarUrl === "string" ? entry.userAvatarUrl.trim() : "";
      if (!avatarUrl) return;
      const slot = document.createElement("span");
      slot.className = "user-avatar-slot";
      slot.dataset.avatarUrl = avatarUrl;
      slot.dataset.avatarAlt = entry.user ? entry.user + "的头像" : "用户头像";
      parent.appendChild(slot);
      syncUserAvatar(slot);
    }}

    function syncUserAvatar(slot) {{
      if (!userAvatarsEnabled) {{
        slot.replaceChildren();
        return;
      }}
      if (slot.firstElementChild !== null) return;
      const avatarUrl = slot.dataset.avatarUrl || "";
      if (!avatarUrl) return;
      const avatar = document.createElement("img");
      avatar.className = "user-avatar";
      avatar.width = 28;
      avatar.height = 28;
      avatar.alt = slot.dataset.avatarAlt || "用户头像";
      avatar.addEventListener("error", () => avatar.remove(), {{ once: true }});
      slot.appendChild(avatar);
      avatar.src = proxyImageUrl(avatarUrl);
    }}

    function syncUserAvatars() {{
      for (const slot of document.querySelectorAll(".user-avatar-slot")) {{
        syncUserAvatar(slot);
      }}
    }}

    function proxyImageUrl(url) {{
      return "{MIRROR_IMAGE_ROUTE}?url=" + encodeURIComponent(url || "");
    }}

    function proxyMediaUrl(url) {{
      return "{MIRROR_MEDIA_ROUTE}?url=" + encodeURIComponent(url || "");
    }}

    function scaleImageSize(width, height) {{
      const sourceWidth = Number(width) || 44;
      const sourceHeight = Number(height) || 44;
      if (sourceWidth <= 0 || sourceHeight <= 0) {{
        return {{ width: 44, height: 44 }};
      }}
      let scale = 44 / sourceHeight;
      let nextWidth = Math.max(1, Math.round(sourceWidth * scale));
      let nextHeight = 44;
      if (nextWidth > 180) {{
        scale = 180 / sourceWidth;
        nextWidth = 180;
        nextHeight = Math.max(1, Math.round(sourceHeight * scale));
      }}
      return {{ width: nextWidth, height: nextHeight }};
    }}

    function giftQuantityText(entry) {{
      const quantity = Number(entry.giftQuantity);
      return Number.isFinite(quantity) ? String(quantity) : "0";
    }}

    function appendGiftValue(parent, entry) {{
      const value = typeof entry.giftValue === "string" ? entry.giftValue.trim() : "";
      if (!value) return;
      const price = document.createElement("span");
      price.className = "gift-value";
      price.textContent = value;
      parent.appendChild(price);
    }}

    function renderGiftText(row, entry) {{
      row.className = "message gift";
      row.replaceChildren();
      appendUserAvatar(row, entry);

      const user = document.createElement("span");
      user.className = "gift-user";
      user.textContent = entry.user || "";
      row.appendChild(user);

      const action = document.createElement("span");
      action.className = "gift-action";
      action.textContent = " " + (entry.giftAction || "") + " ";
      row.appendChild(action);

      const gift = document.createElement("span");
      gift.className = "gift-name";
      gift.textContent = (entry.giftName || "礼物") + " x" + giftQuantityText(entry);
      row.appendChild(gift);
      appendGiftValue(row, entry);
    }}

    function renderGiftAnimation(row, entry) {{
      row.className = "message gift gift-animation-row";
      row.replaceChildren();
      appendUserAvatar(row, entry);

      const user = document.createElement("span");
      user.className = "gift-user";
      user.textContent = entry.user || "";
      row.appendChild(user);

      const image = document.createElement("img");
      image.className = "gift-animation";
      image.width = 44;
      image.height = 44;
      image.src = proxyImageUrl(entry.giftAnimationUrl);
      image.alt = entry.giftName || "礼物";
      image.addEventListener("error", () => renderGiftText(row, entry), {{ once: true }});
      row.appendChild(image);

      const quantity = document.createElement("span");
      quantity.className = "gift-animation-quantity";
      quantity.textContent = " x" + giftQuantityText(entry);
      row.appendChild(quantity);
      appendGiftValue(row, entry);
    }}

    function renderGiftEntry(entry, playEffect = false) {{
      const row = document.createElement("div");
      row.dataset.seq = String(entry.seq);
      if (entry.giftAnimationUrl) {{
        renderGiftAnimation(row, entry);
      }} else {{
        renderGiftText(row, entry);
      }}
      panel.appendChild(row);
      while (panel.children.length > maxMessages) {{
        panel.removeChild(panel.firstElementChild);
      }}
      panel.scrollTop = panel.scrollHeight;
      if (playEffect && giftEffectsEnabled) playGiftEffect(entry);
    }}

    function trimEffectLayer() {{
      while (effectLayer.children.length > 3) {{
        effectLayer.removeChild(effectLayer.firstElementChild);
      }}
    }}

    function clearActiveGiftEffect() {{
      const cleanup = activeEffectCleanup;
      activeEffectCleanup = null;
      if (cleanup) cleanup();
      effectLayer.replaceChildren();
    }}

    function playFallbackGiftEffect(entry) {{
      clearActiveGiftEffect();
      const effect = document.createElement("div");
      effect.className = "gift-effect";

      const content = document.createElement("div");
      content.className = "gift-effect-content";
      const imageUrl = entry.giftImageUrl || "";
      if (imageUrl) {{
        const image = document.createElement("img");
        image.src = proxyImageUrl(imageUrl);
        image.alt = entry.giftName || "礼物";
        content.appendChild(image);
      }}
      const title = document.createElement("span");
      title.textContent = (entry.giftName || "礼物") + " x" + String(entry.giftQuantity || 0);
      content.appendChild(title);
      effect.appendChild(content);

      const meta = document.createElement("div");
      meta.className = "gift-effect-meta";
      meta.textContent = (entry.user || "观众") + " 送出了礼物";
      effect.appendChild(meta);

      effectLayer.appendChild(effect);
      trimEffectLayer();
      effect.addEventListener("animationend", () => effect.remove());
    }}

    function playGiftFallback(entry) {{
      clearActiveGiftEffect();
      if (entry.giftAnimationUrl) {{
        const image = document.createElement("img");
        image.className = "gift-effect-gif";
        image.src = proxyImageUrl(entry.giftAnimationUrl);
        image.alt = entry.giftName || "礼物";
        effectLayer.appendChild(image);
        trimEffectLayer();
        window.setTimeout(() => image.remove(), 3000);
        return;
      }}
      playFallbackGiftEffect(entry);
    }}

    function isPackedFrame(frame) {{
      return frame && [frame.x, frame.y, frame.width, frame.height].every(Number.isFinite)
        && frame.x >= 0 && frame.y >= 0 && frame.width > 0 && frame.height > 0;
    }}

    function centerGiftCanvas(canvas, width, height) {{
      const viewportWidth = Math.max(1, window.innerWidth);
      const viewportHeight = Math.max(1, window.innerHeight);
      const scale = Math.min(viewportWidth / width, viewportHeight / height);
      canvas.style.width = Math.max(1, Math.round(width * scale)) + "px";
      canvas.style.height = Math.max(1, Math.round(height * scale)) + "px";
    }}

    function playMaskedGiftEffect(entry) {{
      const layout = entry.giftEffectLayout || {{}};
      const rgbFrame = layout.rgbFrame;
      const alphaFrame = layout.alphaFrame;
      if (!isPackedFrame(rgbFrame) || !isPackedFrame(alphaFrame)) return false;
      clearActiveGiftEffect();

      const compositor = document.createElement("div");
      compositor.className = "gift-effect-compositor";
      const canvas = document.createElement("canvas");
      canvas.className = "gift-effect-canvas";
      const video = document.createElement("video");
      video.className = "gift-effect-source";
      video.autoplay = true;
      video.muted = true;
      video.playsInline = true;
      video.preload = "auto";
      video.crossOrigin = "anonymous";
      compositor.appendChild(canvas);
      compositor.appendChild(video);

      canvas.width = rgbFrame.width;
      canvas.height = rgbFrame.height;
      centerGiftCanvas(canvas, rgbFrame.width, rgbFrame.height);
      const colorContext = canvas.getContext("2d", {{ willReadFrequently: true }});
      const maskCanvas = document.createElement("canvas");
      const maskContext = maskCanvas.getContext("2d", {{ willReadFrequently: true }});
      if (!colorContext || !maskContext) return false;

      maskCanvas.width = rgbFrame.width;
      maskCanvas.height = rgbFrame.height;
      let stopped = false;
      let frameRequest = 0;
      const handleResize = () => centerGiftCanvas(canvas, rgbFrame.width, rgbFrame.height);
      window.addEventListener("resize", handleResize);

      const cleanup = () => {{
        if (stopped) return;
        stopped = true;
        window.cancelAnimationFrame(frameRequest);
        window.removeEventListener("resize", handleResize);
        video.pause();
        video.removeAttribute("src");
        video.load();
        if (activeEffectCleanup === cleanup) activeEffectCleanup = null;
        if (compositor.isConnected) compositor.remove();
      }};
      activeEffectCleanup = cleanup;
      const renderFrame = () => {{
        if (stopped) return;
        try {{
          if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {{
            colorContext.clearRect(0, 0, rgbFrame.width, rgbFrame.height);
            colorContext.drawImage(
              video,
              rgbFrame.x,
              rgbFrame.y,
              rgbFrame.width,
              rgbFrame.height,
              0,
              0,
              rgbFrame.width,
              rgbFrame.height,
            );
            maskContext.clearRect(0, 0, rgbFrame.width, rgbFrame.height);
            maskContext.drawImage(
              video,
              alphaFrame.x,
              alphaFrame.y,
              alphaFrame.width,
              alphaFrame.height,
              0,
              0,
              rgbFrame.width,
              rgbFrame.height,
            );
            const color = colorContext.getImageData(0, 0, rgbFrame.width, rgbFrame.height);
            const mask = maskContext.getImageData(0, 0, rgbFrame.width, rgbFrame.height);
            for (let index = 0; index < color.data.length; index += 4) {{
              color.data[index + 3] = mask.data[index];
            }}
            colorContext.putImageData(color, 0, 0);
          }}
        }} catch (_error) {{
          cleanup();
          playGiftFallback(entry);
          return;
        }}
        frameRequest = window.requestAnimationFrame(renderFrame);
      }};
      const fail = () => {{
        if (stopped) return;
        cleanup();
        playGiftFallback(entry);
      }};
      video.addEventListener("ended", cleanup, {{ once: true }});
      video.addEventListener("error", fail, {{ once: true }});
      effectLayer.appendChild(compositor);
      trimEffectLayer();
      video.src = proxyMediaUrl(entry.giftEffectUrl);
      const playPromise = video.play();
      if (playPromise) playPromise.catch(fail);
      frameRequest = window.requestAnimationFrame(renderFrame);
      window.setTimeout(cleanup, 15000);
      return true;
    }}

    function playGiftEffect(entry) {{
      const officialEffectUrl = entry.giftEffectUrl || "";
      if (officialEffectUrl && entry.giftEffectLayout && playMaskedGiftEffect(entry)) return;
      playGiftFallback(entry);
    }}

    function safeScColor(value, fallback) {{
      return typeof value === "string" && /^#[0-9a-f]{{6}}$/i.test(value)
        ? value
        : fallback;
    }}

    function renderSuperChatEntry(entry) {{
      const row = document.createElement("div");
      row.className = "message super-chat";
      row.dataset.seq = String(entry.seq);
      row.style.backgroundColor = safeScColor(entry.scBackgroundColor, "#3C2A4D");
      row.style.borderLeftColor = safeScColor(entry.scBackgroundBottomColor, "#2A2038");

      const header = document.createElement("div");
      header.className = "super-chat-header";
      const label = document.createElement("span");
      label.className = "super-chat-label";
      label.textContent = "SC";
      header.appendChild(label);
      appendUserAvatar(header, entry);
      const user = document.createElement("span");
      user.className = "super-chat-user";
      user.textContent = entry.user || "";
      header.appendChild(user);
      const price = document.createElement("span");
      price.className = "super-chat-price";
      price.style.color = safeScColor(entry.scBackgroundPriceColor, "#FFD86E");
      price.textContent = "¥" + String(Number(entry.scPrice) || 0);
      header.appendChild(price);
      row.appendChild(header);

      const content = document.createElement("div");
      content.className = "super-chat-message";
      for (const segment of entry.segments || []) appendText(content, segment.text || "");
      row.appendChild(content);

      panel.appendChild(row);
      while (panel.children.length > maxMessages) {{
        panel.removeChild(panel.firstElementChild);
      }}
      panel.scrollTop = panel.scrollHeight;
    }}

    function renderEntry(entry, playEffect = false) {{
      if (entry.kind === "gift") {{
        renderGiftEntry(entry, playEffect);
        return;
      }}
      if (entry.kind === "super_chat") {{
        renderSuperChatEntry(entry);
        return;
      }}
      const row = document.createElement("div");
      row.className = "message";
      row.dataset.seq = String(entry.seq);
      appendUserAvatar(row, entry);

      for (const badgeData of entry.badges || []) {{
        const badge = document.createElement("span");
        const badgeType = String(badgeData.type || "generic").replace(/[^a-z0-9_-]/gi, "") || "generic";
        const badgeClass = badgeType + "-badge";
        badge.className = "meta-badge " + badgeClass;
        badge.textContent = badgeData.text || "";
        badge.title = badgeData.title || "";
        if (badgeData.color) {{
          badge.style.color = badgeData.color;
          badge.style.borderColor = badgeData.color;
        }}
        row.appendChild(badge);
      }}

      const user = document.createElement("span");
      user.className = "user";
      user.style.color = entry.userColor || "#66CCFF";
      user.textContent = entry.user || "";
      row.appendChild(user);

      const colon = document.createElement("span");
      colon.className = "colon";
      colon.textContent = " : ";
      row.appendChild(colon);

      for (const segment of entry.segments || []) {{
        if (segment.type === "image") {{
          const img = document.createElement("img");
          img.className = "emoticon";
          img.src = proxyImageUrl(segment.url);
          img.alt = segment.text || "";
          const imageSize = scaleImageSize(segment.width, segment.height);
          img.width = imageSize.width;
          img.height = imageSize.height;
          row.appendChild(img);
        }} else if (segment.type === "reply") {{
          const reply = document.createElement("span");
          reply.className = "reply";
          reply.textContent = segment.text || "";
          row.appendChild(reply);
        }} else {{
          appendText(row, segment.text || "");
        }}
      }}

      panel.appendChild(row);
      while (panel.children.length > maxMessages) {{
        panel.removeChild(panel.firstElementChild);
      }}
      panel.scrollTop = panel.scrollHeight;
      if (playEffect && giftEffectsEnabled && entry.kind === "gift") {{
        playGiftEffect(entry);
      }}
    }}

    function renderSnapshot(entries) {{
      panel.replaceChildren();
      for (const entry of entries || []) {{
        renderEntry(entry);
      }}
    }}

    const events = new EventSource("{events_route}");
    events.addEventListener("snapshot", event => renderSnapshot(JSON.parse(event.data)));
    events.addEventListener("append", event => renderEntry(JSON.parse(event.data), true));
    events.addEventListener("settings", event => applySettings(JSON.parse(event.data)));
  </script>
</body>
</html>"""


__all__ = ("render_page_script",)
