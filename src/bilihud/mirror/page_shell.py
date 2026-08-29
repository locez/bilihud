"""Render the static HTML and CSS shell of the Mirror browser page."""

from __future__ import annotations

from .state import MIRROR_ICON_ROUTE


def render_page_shell() -> str:
    """Return the document shell through the opening client script tag."""
    icon_link = f'  <link rel="icon" type="image/png" href="{MIRROR_ICON_ROUTE}">\n'
    return (
        """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
"""
        + icon_link
        + """  <style>
    html, body {
      margin: 0;
      padding: 0;
      width: 100%;
      height: 100%;
      background: transparent;
      overflow: hidden;
      font-family: var(--hud-font-family, 'Segoe UI', 'Microsoft YaHei', sans-serif);
    }
    body {
      position: relative;
      color: white;
      text-shadow: 0 1px 2px rgba(0, 0, 0, 0.85);
      --danmaku-x: 4%;
      --danmaku-y: 4%;
    }
    #panel {
      position: fixed;
      box-sizing: border-box;
      left: var(--danmaku-x);
      top: var(--danmaku-y);
      width: fit-content;
      max-width: calc(100vw - 16px);
      max-height: calc(100vh - var(--danmaku-y) - 20px);
      min-width: 240px;
      min-height: 96px;
      overflow: auto;
      scrollbar-width: none;
      -ms-overflow-style: none;
      resize: none;
      padding: 14px;
      background: rgba(0, 0, 0, 0.28);
      border-radius: 8px;
      color: white;
      cursor: move;
      touch-action: none;
      user-select: none;
      transition: left 180ms ease, top 180ms ease;
    }
    #panel::-webkit-scrollbar {
      width: 0;
      height: 0;
      display: none;
    }
    #panel.is-dragging {
      cursor: grabbing;
      transition: none;
    }
    #panel.is-resizing {
      cursor: nwse-resize;
      transition: none;
    }
    #effect-layer {
      position: fixed;
      inset: 0;
      z-index: 10;
      display: flex;
      align-items: center;
      justify-content: center;
      pointer-events: none;
      overflow: hidden;
    }
    .gift-effect {
      position: absolute;
      min-width: min(68vw, 720px);
      padding: 28px 44px;
      border: 2px solid rgba(255, 220, 116, 0.9);
      border-radius: 18px;
      background: rgba(35, 12, 42, 0.78);
      box-shadow: 0 0 0 12px rgba(255, 220, 116, 0.08), 0 0 70px rgba(255, 96, 208, 0.65);
      color: white;
      text-align: center;
      animation: gift-burst 1800ms cubic-bezier(0.16, 0.84, 0.32, 1) both;
    }
    .gift-effect::before, .gift-effect::after {
      content: "";
      position: absolute;
      inset: -28px;
      border: 1px solid rgba(255, 220, 116, 0.45);
      border-radius: 50%;
      animation: gift-ring 1800ms ease-out both;
    }
    .gift-effect::after {
      inset: -72px;
      border-color: rgba(255, 96, 208, 0.32);
      animation-delay: 120ms;
    }
    .gift-effect-content {
      position: relative;
      z-index: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 14px;
      font-size: 42px;
      font-weight: 800;
    }
    .gift-effect-meta {
      position: relative;
      z-index: 1;
      margin-top: 8px;
      color: rgba(255, 255, 255, 0.86);
      font-size: 20px;
    }
    .gift-effect img {
      width: 88px;
      height: 88px;
      object-fit: contain;
      filter: drop-shadow(0 0 16px rgba(255, 220, 116, 0.75));
    }
    .gift-effect-compositor {
      position: absolute;
      inset: 0;
      pointer-events: none;
      overflow: hidden;
    }
    .gift-effect-canvas {
      position: absolute;
      left: 50%;
      top: 50%;
      width: auto;
      height: auto;
      transform: translate(-50%, -50%);
      transform-origin: center center;
      animation: gift-video-in 240ms ease-out both;
    }
    .gift-effect-source {
      position: absolute;
      width: 1px;
      height: 1px;
      opacity: 0;
      pointer-events: none;
    }
    .gift-effect-gif {
      position: absolute;
      left: 50%;
      top: 50%;
      width: min(58vw, 720px);
      height: min(66vh, 720px);
      object-fit: contain;
      transform: translate(-50%, -50%);
      filter: drop-shadow(0 0 28px rgba(255, 220, 116, 0.82));
      animation: gift-video-in 240ms ease-out both;
    }
    @keyframes gift-video-in {
      0% { opacity: 0; transform: translate(-50%, -50%) scale(0.96); }
      100% { opacity: 1; transform: translate(-50%, -50%) scale(1); }
    }
    @keyframes gift-burst {
      0% { opacity: 0; transform: scale(0.72); }
      16% { opacity: 1; transform: scale(1.06); }
      30% { transform: scale(1); }
      78% { opacity: 1; transform: scale(1); }
      100% { opacity: 0; transform: scale(1.12); }
    }
    @keyframes gift-ring {
      0% { opacity: 0; transform: scale(0.55); }
      18% { opacity: 1; }
      100% { opacity: 0; transform: scale(1.18); }
    }
    .message {
      line-height: 1.32;
      margin: 0 0 6px;
      font-size: 18px;
      font-weight: 500;
    }
    .gift-user {
      color: #FFD700;
      font-size: 17px;
      font-weight: 700;
    }
    .gift-action, .gift-name, .gift-animation-quantity {
      color: #FF66CC;
      font-size: 17px;
    }
    .gift-name {
      font-weight: 700;
    }
    .gift-animation-row {
      display: flex;
      align-items: center;
      gap: 7px;
      min-height: 44px;
      line-height: 1.2;
    }
    .gift-animation-row .gift-user {
      min-width: 0;
      overflow-wrap: anywhere;
    }
    .gift-animation {
      display: block;
      flex: 0 0 44px;
      width: 44px;
      height: 44px;
      object-fit: contain;
    }
    .gift-animation-quantity {
      flex: 0 0 auto;
      font-weight: 700;
    }
    .gift-value {
      color: #FFD86E;
      font-size: 15px;
      font-weight: 700;
      margin-left: 5px;
      white-space: nowrap;
    }
    .gift-animation-row .gift-value {
      margin-left: 0;
    }
    .super-chat {
      box-sizing: border-box;
      margin: 0 0 8px;
      padding: 8px 10px 9px;
      border-left: 4px solid #2A2038;
      border-radius: 5px;
      background-color: #3C2A4D;
      color: white;
    }
    .super-chat-header {
      display: flex;
      align-items: baseline;
      gap: 8px;
      line-height: 1.2;
    }
    .super-chat-label {
      color: #FFD86E;
      font-size: 12px;
      font-weight: 900;
      letter-spacing: 1px;
    }
    .super-chat-user {
      color: white;
      font-size: 16px;
      font-weight: 800;
    }
    .super-chat-price {
      color: #FFD86E;
      font-size: 17px;
      font-weight: 900;
    }
    .super-chat-message {
      margin-top: 5px;
      color: white;
      font-size: 17px;
      font-weight: 500;
      line-height: 1.35;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .meta-badge {
      display: inline-block;
      margin-right: 4px;
      padding: 0 5px;
      border-radius: 4px;
      font-size: 13px;
      line-height: 18px;
      font-weight: 800;
      color: white;
      background: transparent;
      border: 1px solid currentColor;
      vertical-align: 1px;
      text-shadow: none;
    }
    .wealth-badge {
      color: #C9B6FF;
    }
    .privilege-badge {
      color: #F1D17A;
      min-width: 16px;
      text-align: center;
    }
    .user {
      font-size: 17px;
      font-weight: 700;
    }
    .colon {
      color: white;
      font-size: 17px;
    }
    .reply {
      color: #FF79C6;
      font-weight: 800;
    }
    .emoticon {
      vertical-align: middle;
      max-height: 44px;
      max-width: 180px;
    }
  </style>
</head>
<body>
  <div id="panel"></div>
  <div id="effect-layer"></div>
  <script>
"""
    )

__all__ = ("render_page_shell",)
