#!/usr/bin/env python3
"""HarcOS web client interface.

Starts a local web app that lets you connect to an MCP server, list tools,
and call tools from a browser.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse


# Env vars shown in the inspector sidebar (key, description, is_secret)
_ROBOT_ENV_VARS: list[tuple[str, str, bool]] = [
    ("G1_ROBOT_IP",          "G1 controller IP (default: 192.168.123.161)",      False),
    ("ROBOT_IP",              "Fallback robot IP for any robot type",             False),
    ("G1_NETWORK_INTERFACE", "Network interface for G1 DDS (e.g. eth0)",        False),
    ("OPENAI_API_KEY",       "OpenAI API key — required for model=gpt-4o",      True),
]

HTML_PAGE = """\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>HarcOS</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --c-bg: #f9fafb;
      --c-surf: #ffffff;
      --c-border: #e5e7eb;
      --c-border2: #d1d5db;
      --c-ink: #111827;
      --c-ink2: #374151;
      --c-mute: #6b7280;
      --c-mute2: #9ca3af;
      --c-brand: #7c3aed;
      --c-brand-bg: #f5f3ff;
      --c-brand-bg2: #ede9fe;
      --c-green: #16a34a;
      --c-red: #dc2626;
      --c-yellow: #d97706;
      --c-blue: #2563eb;
      --mono: "IBM Plex Mono","Fira Code",Consolas,monospace;
      --sans: "Inter","Segoe UI",system-ui,sans-serif;
      --r: 6px;
    }
    html, body { height: 100%; overflow: hidden; }
    body { font-family: var(--sans); font-size: 14px; color: var(--c-ink);
           background: var(--c-bg); display: flex; flex-direction: column; }

    /* ======= Scrollbars ======= */
    ::-webkit-scrollbar { width: 5px; height: 5px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 4px; }

    /* ======= Shared ======= */
    .divider { border: none; border-top: 1px solid var(--c-border); margin: 0; }

    .btn { display: inline-flex; align-items: center; justify-content: center;
           gap: 6px; border: 1px solid var(--c-border); border-radius: var(--r);
           padding: 6px 12px; font: 600 13px/1 var(--sans); color: var(--c-ink2);
           background: var(--c-surf); cursor: pointer; transition: background 100ms; }
    .btn:hover { background: var(--c-bg); }
    .btn:disabled { opacity: 0.38; cursor: not-allowed; }
    .btn-primary { background: var(--c-ink); color: #fff; border-color: var(--c-ink); }
    .btn-primary:hover { background: #1f2937; border-color: #1f2937; }
    .btn-danger { background: var(--c-red); color: #fff; border-color: var(--c-red); }
    .btn-danger:hover { background: #b91c1c; }
    .btn-sm { padding: 4px 10px; font-size: 12px; }
    .btn-icon { padding: 5px; border: none; background: transparent; cursor: pointer;
                color: var(--c-mute); border-radius: 4px; }
    .btn-icon:hover { background: var(--c-bg); color: var(--c-ink); }

    label { font-size: 12px; font-weight: 600; color: var(--c-mute); display: block;
            margin-bottom: 4px; letter-spacing: 0.3px; }
    input, select, textarea {
      width: 100%; border: 1px solid var(--c-border); border-radius: var(--r);
      padding: 7px 10px; font: 13px/1 var(--sans); color: var(--c-ink);
      background: var(--c-surf); }
    input:focus, select:focus, textarea:focus {
      outline: none; border-color: var(--c-brand); box-shadow: 0 0 0 2px var(--c-brand-bg2); }
    textarea { resize: vertical; font-family: var(--mono); font-size: 12px; line-height: 1.5; }
    select { cursor: pointer; }

    /* ======= Workspace ======= */
    .workspace { display: flex; flex: 1; min-height: 0; overflow: hidden; }

    /* ======= LEFT SIDEBAR ======= */
    .sidebar { width: 220px; flex-shrink: 0; background: var(--c-surf);
               border-right: 1px solid var(--c-border);
               display: flex; flex-direction: column; overflow: hidden; }

    .sb-logo { display: flex; align-items: center; gap: 9px; padding: 14px 14px 12px;
               border-bottom: 1px solid var(--c-border); }
    .sb-logo-mark { width: 28px; height: 28px;
                    background: linear-gradient(135deg, #7c3aed, #a78bfa);
                    border-radius: 7px; display: flex; align-items: center;
                    justify-content: center; font: 700 14px var(--sans); color: #fff; }
    .sb-logo-text { font-weight: 700; font-size: 15px; }
    .sb-logo-ver { font-size: 11px; color: var(--c-mute); margin-top: 1px; }

    .sb-body { flex: 1; overflow-y: auto; padding: 12px; display: flex;
               flex-direction: column; gap: 12px; }

    .sb-field { display: flex; flex-direction: column; gap: 4px; }

    /* Robot chips */
    .robot-row { display: flex; gap: 6px; }
    .robot-chip { flex: 1; display: flex; flex-direction: column; align-items: center;
                  gap: 2px; padding: 8px 4px; border-radius: var(--r);
                  border: 1px solid var(--c-border); cursor: pointer;
                  background: var(--c-surf); transition: all 100ms; }
    .robot-chip:hover { background: var(--c-bg); }
    .robot-chip.active { background: var(--c-brand-bg); border-color: var(--c-brand);
                         color: var(--c-brand); }
    .rc-name { font-size: 13px; font-weight: 700; }
    .rc-port { font-size: 11px; color: inherit; opacity: 0.6; font-family: var(--mono); }
    .robot-chip.active .rc-port { opacity: 0.8; }

    /* Accordion */
    .accordion { border: 1px solid var(--c-border); border-radius: var(--r); overflow: hidden; }
    .acc-head { display: flex; align-items: center; gap: 6px; padding: 8px 10px;
                cursor: pointer; user-select: none; background: var(--c-surf); }
    .acc-head:hover { background: var(--c-bg); }
    .acc-icon { font-size: 10px; color: var(--c-mute); transition: transform 200ms; margin-left: auto; }
    .accordion.open .acc-icon { transform: rotate(180deg); }
    .acc-label { font-size: 12px; font-weight: 600; color: var(--c-mute); }
    .acc-body { display: none; border-top: 1px solid var(--c-border); padding: 10px; }
    .accordion.open .acc-body { display: block; }

    /* Env var rows */
    .env-row { padding: 5px 0; border-bottom: 1px solid var(--c-border); }
    .env-row:last-child { border-bottom: none; }
    .env-kv { display: flex; justify-content: space-between; align-items: baseline; gap: 4px; }
    .env-key { font: 600 11px var(--mono); color: var(--c-blue); word-break: break-all; }
    .env-val { font: 11px var(--mono); text-align: right; }
    .env-val.set { color: var(--c-green); }
    .env-val.unset { color: var(--c-mute2); }
    .env-val.vv { color: var(--c-ink2); max-width: 90px; overflow: hidden;
                   text-overflow: ellipsis; white-space: nowrap; }
    .env-desc { font-size: 11px; color: var(--c-mute); margin-top: 2px; line-height: 1.4; }

    .sb-foot { border-top: 1px solid var(--c-border); padding: 12px; display: flex;
               flex-direction: column; gap: 8px; }
    .sb-btn-row { display: flex; gap: 6px; }
    .sb-btn-row .btn { flex: 1; font-size: 12px; padding: 6px 8px; }

    /* Status indicator */
    .status-row { display: flex; align-items: center; gap: 7px; font-size: 12px; }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #d1d5db; flex-shrink: 0; }
    .status-row[data-mode="ok"] .status-dot { background: var(--c-green);
                                               box-shadow: 0 0 5px var(--c-green); }
    .status-row[data-mode="ok"] .status-text { color: var(--c-green); font-weight: 600; }
    .status-row[data-mode="bad"] .status-dot { background: var(--c-red); }
    .status-row[data-mode="bad"] .status-text { color: var(--c-red); }
    .status-row[data-mode="connecting"] .status-dot { background: var(--c-yellow);
      animation: pulse 1s infinite; }
    @keyframes pulse { 50% { opacity: 0.4; } }

    .server-info { font-size: 11px; color: var(--c-mute); line-height: 1.5; }
    .server-info strong { color: var(--c-ink2); font-weight: 600; }

    /* ======= MAIN area ======= */
    .main { flex: 1; display: flex; flex-direction: column; min-width: 0; overflow: hidden; }

    /* Top nav tabs */
    .top-nav { display: flex; align-items: center; border-bottom: 1px solid var(--c-border);
               background: var(--c-surf); padding: 0 16px; height: 42px; flex-shrink: 0; gap: 2px; }
    .nav-tab { padding: 0 14px; height: 42px; display: flex; align-items: center;
               font: 600 13px/1 var(--sans); color: var(--c-mute); cursor: pointer;
               border-bottom: 2px solid transparent; margin-bottom: -1px;
               transition: color 100ms; white-space: nowrap; }
    .nav-tab:hover { color: var(--c-ink); }
    .nav-tab.active { color: var(--c-brand); border-bottom-color: var(--c-brand); }

    /* ======= TOOLS VIEW ======= */
    #toolsView { display: flex; flex: 1; min-height: 0; overflow: hidden; }

    /* Tool list column */
    .tool-col { width: 300px; flex-shrink: 0; border-right: 1px solid var(--c-border);
                display: flex; flex-direction: column; overflow: hidden; }
    .col-head { padding: 10px 12px; border-bottom: 1px solid var(--c-border);
                display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
    .col-head-title { font-weight: 700; font-size: 15px; flex: 1; }
    .search-box { position: relative; margin: 8px 12px; flex-shrink: 0; }
    .search-box input { padding-left: 30px; }
    .search-icon { position: absolute; left: 9px; top: 50%; transform: translateY(-50%);
                   color: var(--c-mute); font-size: 13px; pointer-events: none; }

    .tool-items { flex: 1; overflow-y: auto; }
    .tool-row { display: flex; align-items: flex-start; gap: 0; padding: 10px 14px;
                cursor: pointer; border-bottom: 1px solid var(--c-border);
                transition: background 80ms; }
    .tool-row:last-child { border-bottom: none; }
    .tool-row:hover { background: var(--c-bg); }
    .tool-row.active { background: var(--c-brand-bg); }
    .tool-row-body { flex: 1; min-width: 0; }
    .tool-row-name { font-weight: 600; font-size: 13px; color: var(--c-ink);
                     white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .tool-row.active .tool-row-name { color: var(--c-brand); }
    .tool-row-desc { font-size: 12px; color: var(--c-mute); margin-top: 2px;
                     overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .tool-row-arrow { color: var(--c-mute2); font-size: 11px; margin-left: 6px;
                      margin-top: 3px; flex-shrink: 0; }
    .tool-row.active .tool-row-arrow { color: var(--c-brand); }
    .tool-empty { padding: 24px 14px; color: var(--c-mute); font-size: 13px;
                  text-align: center; }

    /* Tool detail column */
    .detail-col { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-width: 0; }
    .detail-empty { display: flex; flex-direction: column; align-items: center;
                    justify-content: center; flex: 1; gap: 10px; padding: 40px;
                    color: var(--c-mute); text-align: center; }
    .detail-empty-icon { font-size: 36px; opacity: 0.3; }
    .detail-empty-title { font-size: 15px; font-weight: 600; color: var(--c-ink2); }
    .detail-empty-sub { font-size: 13px; max-width: 26ch; line-height: 1.5; }

    /* Detail header */
    .detail-head { padding: 14px 18px; border-bottom: 1px solid var(--c-border);
                   background: var(--c-surf); flex-shrink: 0; }
    .detail-tool-name { font-weight: 700; font-size: 16px; }
    .detail-tool-desc { font-size: 13px; color: var(--c-mute); margin-top: 4px; line-height: 1.5; }
    .detail-badges { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
    .badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 4px;
             border: 1px solid currentColor; display: inline-flex; align-items: center; gap: 4px; }
    .badge-ok { color: var(--c-green); background: #f0fdf4; border-color: #bbf7d0; }
    .badge-no { color: var(--c-mute); background: var(--c-bg); border-color: var(--c-border); }

    /* Detail tabs */
    .detail-tabs { display: flex; border-bottom: 1px solid var(--c-border); padding: 0 18px;
                   background: var(--c-surf); flex-shrink: 0; }
    .dtab { padding: 8px 12px; font-size: 13px; font-weight: 600; color: var(--c-mute);
            cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; }
    .dtab:hover { color: var(--c-ink); }
    .dtab.active { color: var(--c-brand); border-bottom-color: var(--c-brand); }
    .dtab-panel { display: none; }
    .dtab-panel.active { display: flex; flex-direction: column; }

    /* Detail body */
    .detail-body { flex: 1; overflow-y: auto; }
    .detail-section { padding: 14px 18px; border-bottom: 1px solid var(--c-border); }
    .detail-section:last-child { border-bottom: none; }
    .section-title { font-size: 12px; font-weight: 700; color: var(--c-mute);
                     text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 10px; }

    /* Form fields */
    .field-grid { display: grid; gap: 14px; }
    .field { display: grid; gap: 5px; }
    .field-label-row { display: flex; align-items: center; gap: 6px; }
    .field-label-row label { margin: 0; font-size: 13px; color: var(--c-ink2); font-weight: 600; }
    .ftype { font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 3px;
             text-transform: uppercase; letter-spacing: 0.3px; }
    .ft-str { background: #dbeafe; color: #1d4ed8; }
    .ft-num { background: #fef9c3; color: #854d0e; }
    .ft-bool { background: #dcfce7; color: #166534; }
    .ft-obj { background: #ede9fe; color: #5b21b6; }
    .ft-arr { background: #fce7f3; color: #9d174d; }
    .freq { font-size: 10px; color: var(--c-red); font-weight: 700; }
    .field-desc { font-size: 12px; color: var(--c-mute); line-height: 1.4; }
    .field input[type="text"], .field input[type="number"],
    .field textarea, .field select { font-size: 13px; }
    .field textarea { min-height: 80px; }
    .field-check { display: flex; align-items: center; gap: 8px; }
    .field-check input[type="checkbox"] { width: 15px; height: 15px; accent-color: var(--c-brand); }

    /* Code block */
    .code-wrap { position: relative; }
    .code-block { background: #1e1e2e; border-radius: var(--r); padding: 12px 14px;
                  font: 12px/1.6 var(--mono); color: #cdd6f4; overflow: auto;
                  white-space: pre; max-height: 300px; }
    .jk { color: #89b4fa; } .js { color: #a6e3a1; }
    .jn { color: #fab387; } .jb { color: #cba6f7; } .jnl { color: #6c7086; }
    .copy-btn { position: absolute; top: 6px; right: 6px; background: #313244;
                border: 1px solid #45475a; border-radius: 4px; color: #cdd6f4;
                padding: 3px 8px; font: 11px var(--sans); cursor: pointer; }
    .copy-btn:hover { background: #45475a; }

    /* Run bar */
    .run-bar { display: flex; align-items: center; gap: 10px; padding: 12px 18px;
               border-top: 1px solid var(--c-border); background: var(--c-surf);
               flex-shrink: 0; }
    .run-bar .btn-primary { min-width: 80px; }

    /* Response */
    .resp-head { display: flex; align-items: center; gap: 8px; }
    .resp-badge { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 4px; }
    .resp-ok { background: #f0fdf4; color: var(--c-green); border: 1px solid #bbf7d0; }
    .resp-err { background: #fef2f2; color: var(--c-red); border: 1px solid #fecaca; }

    /* ======= LOG PANEL ======= */
    .log-panel { border-top: 1px solid var(--c-border); background: var(--c-surf);
                 flex-shrink: 0; display: flex; flex-direction: column; }
    .log-panel-head { display: flex; align-items: center; gap: 8px; padding: 6px 14px;
                      cursor: pointer; user-select: none; border-bottom: 1px solid transparent; }
    .log-panel.open .log-panel-head { border-bottom-color: var(--c-border); }
    .log-panel-head:hover { background: var(--c-bg); }
    .log-title { font-size: 12px; font-weight: 700; color: var(--c-mute);
                 text-transform: uppercase; letter-spacing: 0.6px; flex: 1; }
    .log-chevron { font-size: 10px; color: var(--c-mute); transition: transform 200ms; }
    .log-panel.open .log-chevron { transform: rotate(180deg); }
    .log-body { display: none; max-height: 160px; overflow-y: auto; }
    .log-panel.open .log-body { display: block; }
    .log-item { display: flex; align-items: baseline; gap: 10px; padding: 5px 14px;
                border-bottom: 1px solid var(--c-border); font-size: 12px; }
    .log-item:last-child { border-bottom: none; }
    .log-num { color: var(--c-mute2); font-family: var(--mono); min-width: 20px;
               text-align: right; flex-shrink: 0; }
    .log-method { font: 600 12px var(--mono); color: var(--c-brand); }
    .log-status { font-size: 11px; font-weight: 700; }
    .log-ok { color: var(--c-green); }
    .log-err { color: var(--c-red); }

    /* ======= AGENT VIEW ======= */
    #agentView { display: none; flex-direction: column; flex: 1; min-height: 0; overflow: hidden; }
    .agent-bar { display: flex; align-items: center; gap: 10px; padding: 10px 16px;
                 background: var(--c-surf); border-bottom: 1px solid var(--c-border);
                 flex-shrink: 0; }
    .agent-bar label { margin: 0; white-space: nowrap; }
    .agent-bar select { max-width: 200px; }
    .agent-bar-spacer { flex: 1; }

    .chat-msgs { flex: 1; overflow-y: auto; padding: 16px; display: flex;
                 flex-direction: column; gap: 12px; }
    .chat-empty { display: flex; flex-direction: column; align-items: center;
                  justify-content: center; flex: 1; gap: 10px; color: var(--c-mute);
                  text-align: center; padding: 40px; }
    .chat-empty-icon { font-size: 36px; opacity: 0.25; }
    .chat-empty-title { font-size: 15px; font-weight: 600; color: var(--c-ink2); }

    .msg { max-width: 760px; }
    .msg-user { align-self: flex-end; }
    .msg-agent { align-self: flex-start; }
    .msg-lbl { font-size: 11px; font-weight: 700; text-transform: uppercase;
               letter-spacing: 0.5px; color: var(--c-mute); margin-bottom: 4px; }
    .msg-user .msg-lbl { text-align: right; }
    .msg-bubble { border-radius: 10px; padding: 10px 14px; font-size: 13px;
                  line-height: 1.55; word-break: break-word; }
    .msg-user .msg-bubble { background: var(--c-brand); color: #fff;
                             border-bottom-right-radius: 3px; }
    .msg-agent .msg-bubble { background: var(--c-surf); border: 1px solid var(--c-border);
                              color: var(--c-ink); border-bottom-left-radius: 3px; }

    .tc-card { background: var(--c-surf); border: 1px solid var(--c-border);
               border-radius: 8px; overflow: hidden; font-size: 13px; margin-bottom: 6px; }
    .tc-head { display: flex; align-items: center; gap: 8px; padding: 7px 12px;
               cursor: pointer; user-select: none; background: var(--c-bg); }
    .tc-head:hover { background: #f3f4f6; }
    .tc-tag { font: 700 10px var(--mono); padding: 1px 6px; border-radius: 3px;
              background: var(--c-brand-bg2); color: var(--c-brand); }
    .tc-nm { font: 600 13px var(--mono); }
    .tc-chevron { color: var(--c-mute2); font-size: 10px; margin-left: auto; }
    .tc-body { display: none; padding: 10px 12px; border-top: 1px solid var(--c-border);
               display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .tc-slabel { font-size: 11px; font-weight: 700; text-transform: uppercase;
                 letter-spacing: 0.5px; color: var(--c-mute); margin-bottom: 5px; }
    .tc-code { background: #1e1e2e; border-radius: 5px; padding: 8px 10px;
               font: 11px/1.5 var(--mono); color: #cdd6f4; white-space: pre-wrap;
               word-break: break-word; max-height: 140px; overflow-y: auto; }

    .thinking { display: none; align-items: center; gap: 10px; padding: 10px 16px;
                color: var(--c-mute); font-size: 13px; }
    .thinking.active { display: flex; }
    .spinner { width: 14px; height: 14px; border: 2px solid var(--c-border);
               border-top-color: var(--c-brand); border-radius: 50%;
               animation: spin 0.7s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }

    .chat-input-bar { display: flex; align-items: flex-end; gap: 10px; padding: 12px 16px;
                      background: var(--c-surf); border-top: 1px solid var(--c-border);
                      flex-shrink: 0; }
    #agentPrompt { flex: 1; border: 1px solid var(--c-border); border-radius: 8px;
                   padding: 9px 12px; font: 13px/1.5 var(--sans); color: var(--c-ink);
                   background: var(--c-surf); resize: none; min-height: 40px;
                   max-height: 120px; overflow-y: auto; }
    #agentPrompt:focus { outline: none; border-color: var(--c-brand);
                         box-shadow: 0 0 0 2px var(--c-brand-bg2); }
  </style>
</head>
<body>
  <div class="workspace">
    <!-- LEFT SIDEBAR -->
    <aside class="sidebar">
      <div class="sb-logo">
        <div class="sb-logo-mark">H</div>
        <div>
          <div class="sb-logo-text">HarcOS</div>
          <div class="sb-logo-ver">MCP Client</div>
        </div>
      </div>

      <div class="sb-body">
        <!-- Robot selector -->
        <div class="sb-field">
          <label>Robot</label>
          <div class="robot-row">
            <button class="robot-chip active" data-robot="g1" data-port="9991">
              <span class="rc-name">G1</span>
              <span class="rc-port">:9991</span>
            </button>
            <button class="robot-chip" data-robot="go2" data-port="9990">
              <span class="rc-name">Go2</span>
              <span class="rc-port">:9990</span>
            </button>
          </div>
        </div>

        <!-- Transport -->
        <div class="sb-field">
          <label>Transport Type</label>
          <select id="transportType">
            <option value="streamable-http">Streamable HTTP</option>
            <option value="sse">SSE</option>
          </select>
        </div>

        <!-- Server URL -->
        <div class="sb-field">
          <label>Server URL</label>
          <input id="serverUrl" placeholder="http://localhost:9991" />
        </div>

        <!-- Environment Variables accordion -->
        <div class="accordion open" id="envAccordion">
          <div class="acc-head" id="envToggle">
            <span class="acc-label">Environment Variables</span>
            <span class="acc-icon">&#9660;</span>
          </div>
          <div class="acc-body" id="envBody">
            <div style="color:var(--c-mute2);font-size:12px;padding:4px 0;">Loading...</div>
          </div>
        </div>
      </div>

      <!-- Footer: connect + status -->
      <div class="sb-foot">
        <div class="sb-btn-row">
          <button id="connectBtn" class="btn btn-primary">Connect</button>
          <button id="disconnectBtn" class="btn btn-danger btn-sm" disabled>Disconnect</button>
        </div>
        <div class="status-row" id="statusRow" data-mode="bad">
          <span class="status-dot"></span>
          <span class="status-text" id="statusText">Disconnected</span>
        </div>
        <div class="server-info" id="serverInfo" style="display:none;">
          <strong id="serverName"></strong>&nbsp;<span id="serverVersion" style="color:var(--c-mute);"></span>
        </div>
      </div>
    </aside>

    <!-- MAIN -->
    <div class="main">
      <!-- Top nav -->
      <nav class="top-nav">
        <div class="nav-tab active" data-mode="tools">Tools</div>
        <div class="nav-tab" data-mode="agent">&#129302; Agent</div>
      </nav>

      <!-- TOOLS VIEW -->
      <div id="toolsView" style="flex:1;min-height:0;overflow:hidden;">
        <!-- Tool list column -->
        <div class="tool-col">
          <div class="col-head">
            <span class="col-head-title">Tools</span>
            <button id="listToolsBtn" class="btn btn-sm" disabled>List Tools</button>
          </div>
          <div class="search-box">
            <span class="search-icon">&#128269;</span>
            <input id="toolSearch" placeholder="Search tools..." />
          </div>
          <div id="toolItems" class="tool-items">
            <div class="tool-empty">Connect to a server to see tools.</div>
          </div>
        </div>

        <!-- Tool detail column -->
        <div class="detail-col" id="detailCol">
          <div class="detail-empty" id="detailEmpty">
            <div class="detail-empty-icon">&#128270;</div>
            <div class="detail-empty-title">No tool selected</div>
            <div class="detail-empty-sub">Select a tool from the list to inspect and run it.</div>
          </div>

          <div id="detailPanel" style="display:none;flex-direction:column;flex:1;min-height:0;overflow:hidden;">
            <div class="detail-head">
              <div class="detail-tool-name" id="detailName"></div>
              <div class="detail-tool-desc" id="detailDesc"></div>
              <div class="detail-badges" id="detailBadges"></div>
            </div>

            <div class="detail-tabs">
              <div class="dtab active" data-dtab="form">Form</div>
              <div class="dtab" data-dtab="json">JSON</div>
              <div class="dtab" data-dtab="schema">Output Schema</div>
            </div>

            <div class="detail-body">
              <div id="dtab-form" class="dtab-panel active">
                <div class="detail-section">
                  <div id="formFields" class="field-grid"></div>
                  <div id="noParams" style="display:none;color:var(--c-mute);font-size:13px;">This tool takes no parameters.</div>
                </div>
              </div>
              <div id="dtab-json" class="dtab-panel">
                <div class="detail-section">
                  <div class="section-title">Arguments</div>
                  <textarea id="rawArgs" style="min-height:120px;">{}</textarea>
                </div>
              </div>
              <div id="dtab-schema" class="dtab-panel">
                <div class="detail-section">
                  <div class="section-title">Output Schema</div>
                  <div class="code-wrap">
                    <div id="schemaCode" class="code-block"></div>
                    <button class="copy-btn" data-target="schemaCode">Copy</button>
                  </div>
                </div>
              </div>
            </div>

            <div class="run-bar">
              <button id="runBtn" class="btn btn-primary" disabled>&#9654; Run</button>
              <div id="runResult" style="flex:1;font-size:12px;color:var(--c-mute);">
                Click Run to execute the tool.
              </div>
            </div>

            <div id="responseSection" style="display:none;" class="detail-section" >
              <div class="resp-head">
                <div class="section-title" style="margin:0;">Response</div>
                <span id="respBadge" class="resp-badge"></span>
              </div>
              <div style="margin-top:10px;" class="code-wrap">
                <div id="responseCode" class="code-block"></div>
                <button class="copy-btn" data-target="responseCode">Copy</button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- AGENT VIEW -->
      <div id="agentView">
        <div class="agent-bar">
          <label for="agentModel">Model</label>
          <select id="agentModel">
            <option value="llama3.2">llama3.2</option>
            <option value="qwen2.5">qwen2.5</option>
            <option value="mistral">mistral</option>
            <option value="llama3.1">llama3.1</option>
            <option value="gpt-4o">gpt-4o (OpenAI)</option>
            <option value="gpt-4o-mini">gpt-4o-mini (OpenAI)</option>
          </select>
          <div class="agent-bar-spacer"></div>
          <button id="clearChatBtn" class="btn btn-sm">Clear History</button>
        </div>

        <div id="chatMsgs" class="chat-msgs">
          <div class="chat-empty" id="chatEmpty">
            <div class="chat-empty-icon">&#129302;</div>
            <div class="chat-empty-title">Agent ready</div>
            <div style="font-size:13px;color:var(--c-mute);max-width:28ch;line-height:1.5;">
              Connect to a server, then type a command in plain English.
            </div>
          </div>
        </div>

        <div class="thinking" id="thinking">
          <div class="spinner"></div>
          <span>Agent is thinking...</span>
        </div>

        <div class="chat-input-bar">
          <textarea id="agentPrompt" rows="1" placeholder="Type a command in plain English..."></textarea>
          <button id="agentSendBtn" class="btn btn-primary" disabled>Send</button>
        </div>
      </div>

      <!-- HISTORY LOG (bottom) -->
      <div class="log-panel" id="logPanel">
        <div class="log-panel-head" id="logToggle">
          <span class="log-title">History</span>
          <button id="clearLogBtn" class="btn-icon btn-sm" style="font-size:11px;padding:2px 6px;" title="Clear">&#215;</button>
          <span class="log-chevron">&#9660;</span>
        </div>
        <div class="log-body" id="logBody"></div>
      </div>
    </div>
  </div>

  <script>
    window.DEFAULT_MCP_SERVER = __DEFAULT_MCP_SERVER_JSON__;

    const clientId = (() => {
      const k = "harcos_inspector_id";
      const v = localStorage.getItem(k) || (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
      localStorage.setItem(k, v);
      return v;
    })();

    let connected = false, allTools = [], activeTool = null, logCount = 0;
    const $ = id => document.getElementById(id);

    const serverEl     = $("serverUrl"),    connectBtn  = $("connectBtn"),
          disconnectBtn= $("disconnectBtn"), statusRow   = $("statusRow"),
          statusText   = $("statusText"),    serverInfo  = $("serverInfo"),
          serverName   = $("serverName"),    serverVer   = $("serverVersion"),
          listToolsBtn = $("listToolsBtn"),  toolItems   = $("toolItems"),
          toolSearchEl = $("toolSearch"),    detailEmpty = $("detailEmpty"),
          detailPanel  = $("detailPanel"),   detailNameEl= $("detailName"),
          detailDescEl = $("detailDesc"),    detailBadges= $("detailBadges"),
          runBtn       = $("runBtn"),        formFieldsEl= $("formFields"),
          noParamsEl   = $("noParams"),      rawArgsEl   = $("rawArgs"),
          schemaCodeEl = $("schemaCode"),    responseSection= $("responseSection"),
          responseCodeEl=$("responseCode"),  respBadge   = $("respBadge"),
          logBody      = $("logBody"),
          agentSendBtn = $("agentSendBtn"),  agentPromptEl=$("agentPrompt"),
          chatMsgsEl   = $("chatMsgs"),      thinkingEl  = $("thinking"),
          chatEmptyEl  = $("chatEmpty");

    serverEl.value = window.DEFAULT_MCP_SERVER || "http://localhost:9991";

    /* ---- Robot switcher ---- */
    document.querySelectorAll(".robot-chip").forEach(chip => {
      chip.addEventListener("click", () => {
        document.querySelectorAll(".robot-chip").forEach(c => c.classList.remove("active"));
        chip.classList.add("active");
        try {
          const u = new URL(serverEl.value.trim());
          u.port = chip.dataset.port;
          serverEl.value = u.origin;
        } catch {
          serverEl.value = "http://localhost:" + chip.dataset.port;
        }
      });
    });

    /* ---- Mode nav ---- */
    document.querySelectorAll(".nav-tab").forEach(tab => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".nav-tab").forEach(t => t.classList.remove("active"));
        tab.classList.add("active");
        const m = tab.dataset.mode;
        $("toolsView").style.display = m === "tools" ? "flex" : "none";
        $("agentView").style.display = m === "agent" ? "flex" : "none";
      });
    });

    /* ---- Log panel ---- */
    $("logToggle").addEventListener("click", e => {
      if (e.target === $("clearLogBtn")) return;
      $("logPanel").classList.toggle("open");
    });
    $("clearLogBtn").addEventListener("click", () => { logBody.innerHTML = ""; logCount = 0; });

    function addLog(method, status, mode) {
      logCount++;
      const item = document.createElement("div"); item.className = "log-item";
      item.innerHTML = '<span class="log-num">' + logCount + '.</span>'
                     + '<span class="log-method">' + escH(method) + '</span>'
                     + '<span class="log-status log-' + mode + '">' + escH(status) + '</span>';
      logBody.prepend(item);
    }

    /* ---- Env vars accordion ---- */
    $("envToggle").addEventListener("click", () => $("envAccordion").classList.toggle("open"));
    async function loadEnvVars() {
      try {
        const r = await fetch("/api/envvars");
        const d = await r.json();
        renderEnv(d.vars || []);
      } catch {
        $("envBody").innerHTML = '<div style="color:var(--c-mute2);font-size:12px;">Could not load.</div>';
      }
    }
    function renderEnv(vars) {
      const body = $("envBody"); body.innerHTML = "";
      if (!vars.length) { body.innerHTML = '<div style="color:var(--c-mute2);font-size:12px;">No vars found.</div>'; return; }
      for (const v of vars) {
        const row = document.createElement("div"); row.className = "env-row";
        const valHtml = v.secret
          ? (v.value ? '<span class="env-val set">&#9679; Set</span>' : '<span class="env-val unset">&#9675; Not set</span>')
          : (v.value ? '<span class="env-val vv" title="' + escH(v.value) + '">' + escH(v.value) + '</span>'
                     : '<span class="env-val unset">&#8212;</span>');
        row.innerHTML = '<div class="env-kv"><span class="env-key">' + escH(v.key) + '</span>' + valHtml + '</div>'
                      + '<div class="env-desc">' + escH(v.desc) + '</div>';
        body.appendChild(row);
      }
    }

    /* ---- Status ---- */
    function setStatus(text, mode) {
      statusText.textContent = text; statusRow.dataset.mode = mode;
    }
    function setConnected(flag, info) {
      connected = flag;
      listToolsBtn.disabled = !flag; runBtn.disabled = !flag; agentSendBtn.disabled = !flag;
      disconnectBtn.disabled = !flag; connectBtn.disabled = flag;
      if (flag) {
        setStatus("Connected", "ok");
        if (info) {
          serverName.textContent = info.name || ""; serverVer.textContent = info.version ? "v" + info.version : "";
          serverInfo.style.display = "block";
        }
        addLog("initialize", "connected", "ok");
      } else {
        setStatus("Disconnected", "bad");
        serverInfo.style.display = "none";
        allTools = []; renderList([]);
        if (activeTool) showDetailEmpty();
      }
    }

    /* ---- API ---- */
    async function post(path, body) {
      const r = await fetch(path, { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.error || "HTTP " + r.status);
      return d;
    }

    /* ---- Connect / Disconnect ---- */
    connectBtn.addEventListener("click", async () => {
      const url = serverEl.value.trim(); if (!url) return;
      connectBtn.disabled = true; setStatus("Connecting...", "connecting");
      try {
        const out = await post("/api/initialize", { client_id: clientId, server_url: url });
        setConnected(true, out.server_info);
        await loadAllTools();
      } catch (e) {
        setConnected(false);
        setStatus(e.message.slice(0, 50), "bad");
        addLog("initialize", "failed", "err");
      } finally {
        if (!connected) connectBtn.disabled = false;
      }
    });
    disconnectBtn.addEventListener("click", () => { setConnected(false); });
    listToolsBtn.addEventListener("click", loadAllTools);

    /* ---- Tool list ---- */
    function escH(s) {
      return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
    }
    function renderList(tools) {
      toolItems.innerHTML = "";
      if (!tools.length) {
        const d = document.createElement("div"); d.className = "tool-empty";
        d.textContent = connected ? "No tools found." : "Connect to a server to see tools.";
        toolItems.appendChild(d); return;
      }
      tools.forEach(t => {
        const row = document.createElement("div"); row.className = "tool-row"; row.dataset.name = t.name;
        row.innerHTML = '<div class="tool-row-body">'
          + '<div class="tool-row-name">' + escH(t.name) + '</div>'
          + '<div class="tool-row-desc">' + escH(t.description || "") + '</div>'
          + '</div><span class="tool-row-arrow">&#9654;</span>';
        row.addEventListener("click", () => selectTool(t));
        toolItems.appendChild(row);
      });
    }
    toolSearchEl.addEventListener("input", () => {
      const q = toolSearchEl.value.toLowerCase();
      renderList(allTools.filter(t => t.name.toLowerCase().indexOf(q) !== -1));
      if (activeTool) {
        const el = toolItems.querySelector('[data-name="' + activeTool.name + '"]');
        if (el) el.classList.add("active");
      }
    });
    async function loadAllTools() {
      try {
        const out = await post("/api/tools/list", { client_id: clientId });
        allTools = out.tools || []; renderList(allTools);
        addLog("tools/list", allTools.length + " tools", "ok");
      } catch (e) { allTools = []; renderList([]); addLog("tools/list", "failed", "err"); }
    }

    /* ---- Tool selection ---- */
    function showDetailEmpty() {
      detailEmpty.style.display = "flex"; detailPanel.style.display = "none"; activeTool = null;
      document.querySelectorAll(".tool-row").forEach(r => r.classList.remove("active"));
    }
    function selectTool(tool) {
      activeTool = tool;
      document.querySelectorAll(".tool-row").forEach(r => r.classList.remove("active"));
      const row = toolItems.querySelector('[data-name="' + tool.name + '"]');
      if (row) row.classList.add("active");
      detailEmpty.style.display = "none"; detailPanel.style.display = "flex";
      detailNameEl.textContent = tool.name;
      detailDescEl.textContent = tool.description || "No description provided.";
      detailBadges.innerHTML = "";
      runBtn.disabled = !connected;
      buildForm(tool.inputSchema || {});
      schemaCodeEl.innerHTML = hl(tool.outputSchema || tool.inputSchema || {});
      rawArgsEl.value = "{}";
      responseSection.style.display = "none";
      document.querySelectorAll(".dtab").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".dtab-panel").forEach(p => p.classList.remove("active"));
      document.querySelector(".dtab[data-dtab='form']").classList.add("active");
      $("dtab-form").classList.add("active");
      // Switch to tools mode
      document.querySelectorAll(".nav-tab").forEach(t => t.classList.remove("active"));
      document.querySelector(".nav-tab[data-mode='tools']").classList.add("active");
      $("toolsView").style.display = "flex"; $("agentView").style.display = "none";
    }

    /* ---- Detail tabs ---- */
    document.querySelectorAll(".dtab").forEach(tab => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".dtab").forEach(t => t.classList.remove("active"));
        document.querySelectorAll(".dtab-panel").forEach(p => p.classList.remove("active"));
        tab.classList.add("active");
        $("dtab-" + tab.dataset.dtab).classList.add("active");
        if (tab.dataset.dtab === "json") rawArgsEl.value = JSON.stringify(collectArgs(), null, 2);
      });
    });

    /* ---- Copy buttons ---- */
    document.querySelectorAll(".copy-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        navigator.clipboard.writeText($(btn.dataset.target).innerText).then(() => {
          btn.textContent = "Copied!";
          setTimeout(() => { btn.textContent = "Copy"; }, 1500);
        });
      });
    });

    /* ---- JSON highlighter ---- */
    function hl(obj) {
      const raw = JSON.stringify(obj, null, 2);
      let out = "", i = 0;
      const esc = s => s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
      while (i < raw.length) {
        if (raw[i] === '"') {
          let j = i + 1;
          while (j < raw.length) {
            if (raw.charCodeAt(j) === 92) { j += 2; continue; }
            if (raw[j] === '"') { j++; break; }
            j++;
          }
          const tok = esc(raw.slice(i, j));
          let k = j;
          while (k < raw.length && raw[k] === ' ') k++;
          out += raw[k] === ':' ? '<span class="jk">' + tok + '</span>' : '<span class="js">' + tok + '</span>';
          i = j;
        } else if (raw.slice(i, i+4) === 'true')  { out += '<span class="jb">true</span>';  i += 4; }
        else if  (raw.slice(i, i+5) === 'false') { out += '<span class="jb">false</span>'; i += 5; }
        else if  (raw.slice(i, i+4) === 'null')  { out += '<span class="jnl">null</span>'; i += 4; }
        else if (raw[i] === '-' || (raw[i] >= '0' && raw[i] <= '9')) {
          let j = i;
          while (j < raw.length && '0123456789.-+eE'.indexOf(raw[j]) !== -1) j++;
          out += '<span class="jn">' + raw.slice(i, j) + '</span>';
          i = j;
        } else {
          const c = raw[i++];
          out += c === '&' ? '&amp;' : c === '<' ? '&lt;' : c === '>' ? '&gt;' : c;
        }
      }
      return out;
    }

    /* ---- Form builder ---- */
    function resolveType(p) {
      if (p.anyOf) for (const s of p.anyOf) if (s.type && s.type !== "null") return s.type;
      return p.type || "string";
    }
    const typeClass = { string:"ft-str", number:"ft-num", integer:"ft-num",
                        boolean:"ft-bool", object:"ft-obj", array:"ft-arr" };
    function buildForm(schema) {
      formFieldsEl.innerHTML = "";
      const props = schema.properties || {}, req = new Set(schema.required || []);
      const keys = Object.keys(props);
      noParamsEl.style.display = keys.length ? "none" : "block";
      keys.forEach(key => {
        const prop = props[key], type = resolveType(prop), isReq = req.has(key);
        const wrap = document.createElement("div"); wrap.className = "field";
        wrap.innerHTML = '<div class="field-label-row">'
          + '<label>' + escH(key) + '</label>'
          + '<span class="ftype ' + (typeClass[type] || "ft-str") + '">' + escH(type) + '</span>'
          + (isReq ? '<span class="freq">*</span>' : '') + '</div>'
          + (prop.description ? '<div class="field-desc">' + escH(prop.description) + '</div>' : '');
        if (type === "boolean") {
          const cw = document.createElement("div"); cw.className = "field-check";
          const inp = document.createElement("input"); inp.type = "checkbox";
          inp.dataset.fieldKey = key; inp.dataset.fieldType = type;
          const lbl = document.createElement("label"); lbl.textContent = "true"; lbl.style.cssText = "font-size:13px;margin:0;font-weight:400;color:var(--c-ink2);";
          cw.appendChild(inp); cw.appendChild(lbl); wrap.appendChild(cw);
        } else if (type === "array" || type === "object") {
          const inp = document.createElement("textarea");
          inp.dataset.fieldKey = key; inp.dataset.fieldType = type;
          inp.placeholder = type === "array" ? "[]" : "{}"; wrap.appendChild(inp);
        } else {
          const inp = document.createElement("input");
          inp.type = (type === "number" || type === "integer") ? "number" : "text";
          inp.dataset.fieldKey = key; inp.dataset.fieldType = type; wrap.appendChild(inp);
        }
        formFieldsEl.appendChild(wrap);
      });
    }
    function collectArgs() {
      const args = {};
      formFieldsEl.querySelectorAll("[data-field-key]").forEach(el => {
        const key = el.dataset.fieldKey, type = el.dataset.fieldType;
        if (el.type === "checkbox") { args[key] = el.checked; }
        else if (type === "number" || type === "integer") { const v = el.value.trim(); if (v !== "") args[key] = Number(v); }
        else if (type === "array" || type === "object") { const v = el.value.trim(); if (v) { try { args[key] = JSON.parse(v); } catch { args[key] = v; } } }
        else { if (el.value !== "") args[key] = el.value; }
      });
      return args;
    }

    /* ---- Run tool ---- */
    runBtn.addEventListener("click", async () => {
      if (!activeTool || !connected) return;
      let args = {};
      const tab = document.querySelector(".dtab.active") && document.querySelector(".dtab.active").dataset.dtab;
      if (tab === "json") {
        try { args = JSON.parse(rawArgsEl.value || "{}"); }
        catch (e) { showResp({ error: "Invalid JSON: " + e.message }, false); return; }
      } else { args = collectArgs(); }
      runBtn.disabled = true; runBtn.textContent = "Running...";
      addLog("tools/call " + activeTool.name, "running...", "ok");
      try {
        const out = await post("/api/tools/call", { client_id: clientId, name: activeTool.name, arguments: args });
        showResp(out.result, true);
        addLog("tools/call " + activeTool.name, "success", "ok");
      } catch (e) {
        showResp({ error: e.message }, false);
        addLog("tools/call " + activeTool.name, "failed", "err");
      } finally {
        runBtn.disabled = false; runBtn.innerHTML = "&#9654; Run";
      }
    });
    function showResp(data, ok) {
      responseSection.style.display = "block";
      respBadge.className = "resp-badge " + (ok ? "resp-ok" : "resp-err");
      respBadge.textContent = ok ? "Success" : "Error";
      responseCodeEl.innerHTML = hl(data);
      responseSection.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    /* ---- Agent ---- */
    function appendUserMsg(text) {
      const p = chatMsgsEl.querySelector(".chat-empty"); if (p) p.remove();
      const w = document.createElement("div"); w.className = "msg msg-user";
      w.innerHTML = '<div class="msg-lbl">You</div><div class="msg-bubble">' + escH(text) + '</div>';
      chatMsgsEl.appendChild(w); chatMsgsEl.scrollTop = chatMsgsEl.scrollHeight;
    }
    function appendAgentMsg(response, toolCalls) {
      const w = document.createElement("div"); w.className = "msg msg-agent";
      let html = '<div class="msg-lbl">Agent</div>';
      for (const tc of (toolCalls || [])) {
        const argsStr = JSON.stringify(tc.args, null, 2);
        const resStr = typeof tc.result === "string" ? tc.result : JSON.stringify(tc.result, null, 2);
        html += '<div class="tc-card"><div class="tc-head">'
              + '<span class="tc-tag">tool</span>'
              + '<span class="tc-nm">' + escH(tc.name) + '</span>'
              + '<span class="tc-chevron">&#9654;</span></div>'
              + '<div class="tc-body" style="display:none;">'
              + '<div><div class="tc-slabel">Arguments</div><div class="tc-code">' + escH(argsStr) + '</div></div>'
              + '<div><div class="tc-slabel">Result</div><div class="tc-code">' + escH(resStr) + '</div></div>'
              + '</div></div>';
      }
      if (response) html += '<div class="msg-bubble">' + escH(response).split(String.fromCharCode(10)).join('<br>') + '</div>';
      w.innerHTML = html;
      w.querySelectorAll(".tc-head").forEach(h => {
        h.addEventListener("click", () => {
          const b = h.nextElementSibling, ch = h.querySelector(".tc-chevron");
          if (b.style.display === "grid") { b.style.display = "none"; ch.innerHTML = "&#9654;"; }
          else { b.style.display = "grid"; ch.innerHTML = "&#9660;"; }
        });
      });
      chatMsgsEl.appendChild(w); chatMsgsEl.scrollTop = chatMsgsEl.scrollHeight;
    }
    function appendErrMsg(text) {
      const w = document.createElement("div"); w.className = "msg msg-agent";
      w.innerHTML = '<div class="msg-lbl" style="color:var(--c-red);">Error</div>'
        + '<div class="msg-bubble" style="background:#fef2f2;border-color:#fecaca;color:var(--c-red);">' + escH(text) + '</div>';
      chatMsgsEl.appendChild(w); chatMsgsEl.scrollTop = chatMsgsEl.scrollHeight;
    }
    async function sendAgent() {
      const prompt = agentPromptEl.value.trim(); if (!prompt || !connected) return;
      agentPromptEl.value = ""; agentPromptEl.style.height = "auto";
      appendUserMsg(prompt);
      agentSendBtn.disabled = true; thinkingEl.classList.add("active");
      try {
        const out = await post("/api/agent/send", { client_id: clientId, prompt, model: $("agentModel").value });
        thinkingEl.classList.remove("active");
        appendAgentMsg(out.response, out.tool_calls);
        addLog("agent/send", "done", "ok");
      } catch (e) {
        thinkingEl.classList.remove("active");
        appendErrMsg(e.message);
        addLog("agent/send", "failed", "err");
      } finally { agentSendBtn.disabled = !connected; }
    }
    agentSendBtn.addEventListener("click", sendAgent);
    agentPromptEl.addEventListener("keydown", e => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendAgent(); }
    });
    agentPromptEl.addEventListener("input", () => {
      agentPromptEl.style.height = "auto";
      agentPromptEl.style.height = Math.min(agentPromptEl.scrollHeight, 120) + "px";
    });
    $("clearChatBtn").addEventListener("click", async () => {
      chatMsgsEl.innerHTML = "";
      chatMsgsEl.appendChild(chatEmptyEl);
      try { await post("/api/agent/send", { client_id: clientId, prompt: "", clear_history: true }); } catch {}
    });

    /* ---- Init ---- */
    loadEnvVars();
    $("logPanel").classList.add("open");
  </script>
</body>
</html>
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _parse_mcp_response(content_type: str, body_bytes: bytes) -> dict[str, Any]:
    text = body_bytes.decode("utf-8", errors="replace").strip()
    if not text:
        return {}  # 202 Accepted or empty notification response
    if "text/event-stream" in (content_type or ""):
        for line in text.splitlines():
            if line.startswith("data:"):
                payload = line[len("data:") :].strip()
                if payload:
                    return json.loads(payload)
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


class WebState:
    def __init__(self, default_mcp: str) -> None:
        self.default_mcp = default_mcp
        self.sessions: dict[str, dict[str, str]] = {}
        self.agent_histories: dict[str, list] = {}
        self.lock = threading.RLock()


class HarcWebHandler(BaseHTTPRequestHandler):
    server_version = "HarcOSWebClient/1.0"

    def _state(self) -> WebState:
        return self.server.state  # type: ignore[attr-defined]

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json(
            status,
            {
                "ok": False,
                "error": message,
                "timestamp": _now_iso(),
            },
        )

    def _read_json_body(self) -> dict[str, Any]:
        length_raw = self.headers.get("Content-Length", "0")
        try:
            length = int(length_raw)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length") from exc

        if length <= 0:
            return {}

        body = self.rfile.read(length)
        try:
            data = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON body: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _mcp_request(
        self,
        server_url: str,
        method: str,
        params: dict[str, Any] | None = None,
        session_id: str | None = None,
        expect_result: bool = True,
        notification: bool = False,
    ) -> dict[str, Any]:
        endpoint = server_url.rstrip("/") + "/mcp"
        # JSON-RPC notifications must NOT have an "id" field.
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not notification:
            body["id"] = str(uuid.uuid4())
        if params is not None:
            body["params"] = params

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if session_id:
            headers["mcp-session-id"] = session_id

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers=headers,
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                content_type = resp.headers.get("Content-Type", "")
                response_data = _parse_mcp_response(content_type, resp.read())
                response_headers = resp.headers
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"MCP HTTP error {exc.code}: {details}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach MCP server: {exc.reason}") from exc

        # Skip error/result checks for fire-and-forget notifications.
        if notification:
            return {"result": {}, "session_id": session_id}

        if "error" in response_data:
            raise RuntimeError(f"MCP error in {method}: {response_data['error']}")

        result = response_data.get("result", {})
        return {
            "result": result,
            "session_id": response_headers.get("mcp-session-id") or session_id,
        }

    def _mcp_initialize(self, server_url: str) -> tuple[str, dict]:
        initialize_payload = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "HarcOSWebClient",
                "version": "1.0",
            },
        }
        init_out = self._mcp_request(server_url, "initialize", initialize_payload)
        session_id = init_out.get("session_id")
        if not session_id:
            raise RuntimeError("MCP server did not return mcp-session-id")

        server_info = init_out.get("result", {}).get("serverInfo", {})

        # Required notification — no id field, no result expected.
        self._mcp_request(
            server_url,
            "notifications/initialized",
            params=None,
            session_id=session_id,
            notification=True,
        )
        return session_id, server_info

    def _resolve_session(self, client_id: str) -> dict[str, str]:
        with self._state().lock:
            session = self._state().sessions.get(client_id)
        if not session:
            raise ValueError("Unknown client_id. Connect first.")
        return session

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            html = HTML_PAGE.replace(
                "__DEFAULT_MCP_SERVER_JSON__",
                json.dumps(self._state().default_mcp),
            )
            raw = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return

        if self.path == "/api/health":
            self._send_json(200, {"ok": True, "timestamp": _now_iso()})
            return

        if self.path == "/api/envvars":
            vars_out = []
            for key, desc, secret in _ROBOT_ENV_VARS:
                raw_val = os.environ.get(key, "")
                vars_out.append({
                    "key": key,
                    "value": bool(raw_val) if secret else raw_val,
                    "desc": desc,
                    "secret": secret,
                })
            self._send_json(200, {"ok": True, "vars": vars_out})
            return

        self._send_error_json(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        try:
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_error_json(400, str(exc))
            return

        if self.path == "/api/initialize":
            self._handle_initialize(payload)
            return

        if self.path == "/api/tools/list":
            self._handle_tools_list(payload)
            return

        if self.path == "/api/tools/call":
            self._handle_tools_call(payload)
            return

        if self.path == "/api/agent/send":
            self._handle_agent_send(payload)
            return

        self._send_error_json(404, "Not found")

    def _handle_initialize(self, payload: dict[str, Any]) -> None:
        client_id = str(payload.get("client_id") or "").strip()
        server_url = str(payload.get("server_url") or self._state().default_mcp).strip()

        if not client_id:
            self._send_error_json(400, "client_id is required")
            return
        if not _looks_like_url(server_url):
            self._send_error_json(400, "server_url must be a valid http/https URL")
            return

        try:
            session_id, server_info = self._mcp_initialize(server_url)
        except Exception as exc:
            self._send_error_json(502, f"Initialize failed: {exc}")
            return

        with self._state().lock:
            self._state().sessions[client_id] = {
                "server_url": server_url,
                "session_id": session_id,
            }

        self._send_json(
            200,
            {
                "ok": True,
                "client_id": client_id,
                "server_url": server_url,
                "session_id": session_id,
                "server_info": server_info,
            },
        )

    def _handle_tools_list(self, payload: dict[str, Any]) -> None:
        client_id = str(payload.get("client_id") or "").strip()
        if not client_id:
            self._send_error_json(400, "client_id is required")
            return

        try:
            sess = self._resolve_session(client_id)
            out = self._mcp_request(
                sess["server_url"],
                "tools/list",
                session_id=sess["session_id"],
            )
        except ValueError as exc:
            self._send_error_json(400, str(exc))
            return
        except Exception as exc:
            self._send_error_json(502, f"tools/list failed: {exc}")
            return

        self._send_json(200, {"ok": True, "tools": out["result"].get("tools", [])})

    def _handle_tools_call(self, payload: dict[str, Any]) -> None:
        client_id = str(payload.get("client_id") or "").strip()
        name = str(payload.get("name") or "").strip()
        arguments = payload.get("arguments", {})

        if not client_id:
            self._send_error_json(400, "client_id is required")
            return
        if not name:
            self._send_error_json(400, "name is required")
            return
        if not isinstance(arguments, dict):
            self._send_error_json(400, "arguments must be a JSON object")
            return

        try:
            sess = self._resolve_session(client_id)
            out = self._mcp_request(
                sess["server_url"],
                "tools/call",
                params={"name": name, "arguments": arguments},
                session_id=sess["session_id"],
            )
        except ValueError as exc:
            self._send_error_json(400, str(exc))
            return
        except Exception as exc:
            self._send_error_json(502, f"tools/call failed: {exc}")
            return

        self._send_json(200, {"ok": True, "result": out["result"]})


    def _handle_agent_send(self, payload: dict[str, Any]) -> None:
        client_id = str(payload.get("client_id") or "").strip()
        prompt    = str(payload.get("prompt")    or "").strip()
        model     = str(payload.get("model")     or "llama3.2").strip()
        clear     = bool(payload.get("clear_history", False))

        if not client_id:
            self._send_error_json(400, "client_id is required")
            return
        if clear:
            with self._state().lock:
                self._state().agent_histories.pop(client_id, None)
            self._send_json(200, {"ok": True, "response": "", "tool_calls": []})
            return
        if not prompt:
            self._send_error_json(400, "prompt is required")
            return

        try:
            sess = self._resolve_session(client_id)
        except ValueError as exc:
            self._send_error_json(400, str(exc))
            return

        with self._state().lock:
            history = list(self._state().agent_histories.get(client_id, []))

        try:
            result = asyncio.run(self._run_agent(sess, history, prompt, model))
        except RuntimeError as exc:
            self._send_error_json(502, f"Agent error: {exc}")
            return
        except Exception as exc:
            self._send_error_json(502, f"Agent error: {exc}")
            return

        with self._state().lock:
            self._state().agent_histories[client_id] = result["history"]

        self._send_json(200, {
            "ok": True,
            "response": result["response"],
            "tool_calls": result["tool_calls"],
        })

    async def _run_agent(
        self,
        sess: dict[str, str],
        history: list,
        prompt: str,
        model: str,
    ) -> dict[str, Any]:
        """One turn of the Ollama tool-calling loop over the existing MCP session."""
        try:
            from ollama import AsyncClient as OllamaAsync
        except ImportError as exc:
            raise RuntimeError("ollama not installed. Run: pip install ollama") from exc

        tools_resp = self._mcp_request(
            sess["server_url"], "tools/list", session_id=sess["session_id"]
        )
        raw_tools = tools_resp["result"].get("tools", [])

        ollama_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
                },
            }
            for t in raw_tools
        ]

        if not history:
            history = [
                {
                    "role": "system",
                    "content": (
                        "You are a controller for a Unitree robot. "
                        "Use the available tools to fulfil user requests precisely and safely. "
                        "Always call connect() first if the robot is not already connected. "
                        "Confirm each action's result before proceeding to the next step."
                    ),
                }
            ]

        history.append({"role": "user", "content": prompt})
        messages = list(history)
        client = OllamaAsync()
        tool_calls_log: list[dict[str, Any]] = []

        while True:
            resp = await client.chat(
                model=model,
                messages=messages,
                tools=ollama_tools or None,
            )
            msg = resp.message

            if not msg.tool_calls:
                final = msg.content or ""
                messages.append({"role": "assistant", "content": final})
                return {"response": final, "tool_calls": tool_calls_log, "history": messages}

            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments or {},
                            }
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )

            for tc in msg.tool_calls:
                name      = tc.function.name
                call_args = tc.function.arguments or {}
                try:
                    res = self._mcp_request(
                        sess["server_url"],
                        "tools/call",
                        params={"name": name, "arguments": call_args},
                        session_id=sess["session_id"],
                    )
                    tool_result = "\n".join(
                        c.get("text", "")
                        for c in res["result"].get("content", [])
                        if c.get("type") == "text"
                    ) or str(res["result"])
                except Exception as exc:
                    tool_result = f"Error: {exc}"

                tool_calls_log.append({"name": name, "args": call_args, "result": tool_result})
                messages.append({"role": "tool", "content": tool_result})

    def log_message(self, fmt: str, *args: object) -> None:
        # Keep server output concise while still showing access logs.
        super().log_message(fmt, *args)


def main() -> None:
    parser = argparse.ArgumentParser(description="HarcOS web client UI")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8088, help="Bind port (default: 8088)")
    parser.add_argument(
        "--default-mcp",
        default="http://localhost:9991",
        help="Default MCP base URL shown in the UI",
    )
    args = parser.parse_args()

    if not _looks_like_url(args.default_mcp):
        raise SystemExit("--default-mcp must be a valid http/https URL")

    httpd = ThreadingHTTPServer((args.host, args.port), HarcWebHandler)
    httpd.state = WebState(default_mcp=args.default_mcp)  # type: ignore[attr-defined]

    ui_url = f"http://{args.host}:{args.port}/"
    print("[HarcOS Web] Browser client started")
    print(f"[HarcOS Web] UI URL: {ui_url}")
    print("[HarcOS Web] Example MCP server: python run.py g1 --transport streamable-http --port 9991")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        print("\n[HarcOS Web] Stopped")


if __name__ == "__main__":
    main()
