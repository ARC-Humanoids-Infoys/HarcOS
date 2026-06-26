"""
clients/base.py
---------------
HarcOS robot client — DimOS-inspired architecture.

Two transport modes
-------------------
  stdio  — spawns run.py as a subprocess (Claude Desktop / local dev).
  http   — connects to a running HTTP MCP server (agent loop, production).
           Start the server first: python run.py <robot> --transport sse

Both transports share the same mcp.ClientSession interface, so all API
methods work identically regardless of transport.

Key DimOS patterns adopted
---------------------------
  - RobotClientConfig  — injectable config (model, transport, url, system_prompt)
  - _fetch_tools()     — discover + cache MCP tools on connect
  - _tool_registry     — name → tool spec, used to build Ollama tool descriptors
  - _history           — persistent conversation across agent_send() calls
  - agent_send()       — async, persistent history, returns final LLM response
  - clear_history()    — reset conversation state
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from threading import RLock
from typing import Any

ROBOTS = ("go2", "g1")

DEFAULT_SYSTEM_PROMPT = (
    "You are a robot controller for a Unitree robot. "
    "Use the available tools to fulfil user requests precisely and safely. "
    "Always call connect() first if the robot is not already connected. "
    "Confirm each action's result before proceeding to the next."
)


@dataclass
class RobotClientConfig:
    """Configuration for a HarcOS robot client (mirrors DimOS McpClientConfig).

    Args:
        robot:              Robot name — "go2" or "g1".
        model:              Ollama model name for the agent loop.
        system_prompt:      System prompt injected at the start of every session.
        transport:          "stdio" (subprocess) or "http" (HTTP MCP server).
        server_url:         Base URL of the HTTP MCP server (transport="http").
        ip:                 Go2 robot IP address.
        interface:          G1 DDS network interface name.
        verbose:            Print tool calls and results to stdout.
        tool_fetch_timeout: Seconds to wait for the HTTP server to become ready.
    """

    robot: str
    model: str = "llama3.2"
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    transport: str = "stdio"
    server_url: str = "http://localhost:9990"
    ip: str | None = None
    interface: str | None = None
    verbose: bool = True
    tool_fetch_timeout: float = 60.0


class RobotClient:
    """HarcOS robot MCP client — DimOS-inspired.

    Supports two transports:
      - stdio: spawns ``run.py <robot>`` as a subprocess (Claude Desktop / local).
      - http:  connects to a running MCP HTTP server via httpx (agent loop).

    The HTTP transport enables a persistent Ollama agent loop that runs in a
    background thread with full conversation history, matching DimOS's
    McpClient pattern exactly.

    Example — direct calls (stdio)::

        async with RobotClient(RobotClientConfig("g1")) as client:
            await client.call("connect")
            await client.call("move", {"vx": 0.2, "vy": 0.0, "vyaw": 0.0})

    Example — persistent agent loop (HTTP)::

        async with RobotClient(
            RobotClientConfig("g1", transport="http", model="llama3.2")
        ) as client:
            reply = await client.agent_send("stand up and wave your hand")
            print(reply)

    Example — single-shot agent (stdio, backward compat)::

        async with RobotClient(RobotClientConfig("g1")) as client:
            await client.run_agent("connect and stand up")
    """

    def __init__(self, config: RobotClientConfig) -> None:
        if config.robot not in ROBOTS:
            raise ValueError(
                f"Unknown robot '{config.robot}'. Choose from: {', '.join(ROBOTS)}"
            )
        self.config = config

        # Tool registry: name → raw MCP tool spec dict (DimOS _tool_registry)
        self._tool_registry: dict[str, dict[str, Any]] = {}

        # Persistent conversation history across agent_send() calls
        self._history: list[dict[str, Any]] = []
        self._lock = RLock()

        # MCP session (shared by both transports)
        self._exit_stack: AsyncExitStack | None = None
        self.session = None  # mcp.ClientSession

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "RobotClient":
        if self.config.transport == "http":
            await self._connect_http()
        else:
            await self._connect_stdio()
        await self._fetch_tools()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._exit_stack is not None:
            await self._exit_stack.aclose()

    # ------------------------------------------------------------------
    # Transport: stdio
    # ------------------------------------------------------------------

    async def _connect_stdio(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        args = ["run.py", self.config.robot]
        if self.config.ip:
            args += ["--ip", self.config.ip]
        if self.config.interface:
            args += ["--interface", self.config.interface]

        self._exit_stack = AsyncExitStack()
        params = StdioServerParameters(command=sys.executable, args=args)
        read, write = await self._exit_stack.enter_async_context(stdio_client(params))
        self.session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await self.session.initialize()

    # ------------------------------------------------------------------
    # Transport: HTTP (MCP streamable-http via mcp SDK)
    # ------------------------------------------------------------------

    async def _connect_http(self) -> None:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        url = f"{self.config.server_url}/mcp"
        self._exit_stack = AsyncExitStack()

        # Retry until the server is ready (DimOS _try_fetch_tools pattern)
        deadline = asyncio.get_event_loop().time() + self.config.tool_fetch_timeout
        last_exc: Exception | None = None
        while True:
            try:
                read, write, _ = await self._exit_stack.enter_async_context(
                    streamablehttp_client(url)
                )
                self.session = await self._exit_stack.enter_async_context(
                    ClientSession(read, write)
                )
                await self.session.initialize()
                return
            except Exception as exc:
                last_exc = exc
                if asyncio.get_event_loop().time() >= deadline:
                    raise RuntimeError(
                        f"MCP streamable-http server not reachable at {url} "
                        f"after {self.config.tool_fetch_timeout:.0f}s. "
                        f"Start it first: python run.py {self.config.robot} --transport streamable-http. "
                        f"Last error: {exc}"
                    ) from last_exc
                await asyncio.sleep(1.0)

    # ------------------------------------------------------------------
    # Tool discovery (DimOS _fetch_tools pattern)
    # ------------------------------------------------------------------

    def _tools_as_ollama(self) -> list[dict[str, Any]]:
        """Return the tool registry in Ollama tool-call format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": spec.get("description", ""),
                    "parameters": spec.get(
                        "inputSchema", {"type": "object", "properties": {}}
                    ),
                },
            }
            for name, spec in self._tool_registry.items()
        ]

    async def _fetch_tools(self) -> None:
        """Fetch tools/list via the session and populate the tool registry."""
        resp = await self.session.list_tools()
        self._tool_registry = {
            t.name: {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": t.inputSchema,
            }
            for t in resp.tools
        }
        if self.config.verbose:
            names = list(self._tool_registry)
            print(f"[HarcOS] Discovered {len(names)} tools: {names}")

    # ------------------------------------------------------------------
    # Direct tool calls
    # ------------------------------------------------------------------

    async def list_tools(self) -> list[str]:
        """Return names of all tools available on the server."""
        resp = await self.session.list_tools()
        return [t.name for t in resp.tools]

    async def call(self, tool: str, args: dict[str, Any] | None = None) -> str:
        """Call any MCP tool by name and return its text result.

        Args:
            tool: Tool name (e.g. "connect", "move").
            args: Tool arguments dict (e.g. {"vx": 0.2, "vy": 0.0, "vyaw": 0.0}).
        """
        result = await self.session.call_tool(tool, args or {})
        if result.content:
            return "\n".join(
                c.text if hasattr(c, "text") else str(c) for c in result.content
            )
        return str(result)

    # ------------------------------------------------------------------
    # Agent loop — persistent history (DimOS agent_send pattern)
    # ------------------------------------------------------------------

    async def agent_send(self, prompt: str) -> str:
        """Send a natural-language command and return the agent's final response.

        Runs a full Ollama tool-calling loop using the current MCP session.
        Conversation history is preserved across calls — multi-turn by default.

        Args:
            prompt: Natural language instruction, e.g. "walk forward 1 meter".
        """
        try:
            from ollama import AsyncClient as OllamaAsync
        except ImportError:
            raise RuntimeError("ollama not installed. Run: pip install ollama")

        ollama_tools = self._tools_as_ollama()
        client = OllamaAsync()

        with self._lock:
            if not self._history:
                self._history.append(
                    {"role": "system", "content": self.config.system_prompt}
                )
            self._history.append({"role": "user", "content": prompt})
            messages = list(self._history)

        while True:
            response = await client.chat(
                model=self.config.model,
                messages=messages,
                tools=ollama_tools or None,
            )
            msg = response.message

            if not msg.tool_calls:
                final = msg.content or ""
                if self.config.verbose and final:
                    print(f"\n[{self.config.model}] {final}")
                messages.append({"role": "assistant", "content": final})
                with self._lock:
                    self._history = messages
                return final

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
                name = tc.function.name
                input_args = tc.function.arguments or {}

                if self.config.verbose:
                    print(f"[Tool call]   {name}({input_args})")

                try:
                    tool_result = await self.call(name, input_args)
                except Exception as exc:
                    tool_result = f"Tool error: {exc}"

                if self.config.verbose:
                    print(f"[Tool result] {name} → {tool_result}")

                messages.append({"role": "tool", "content": tool_result})

            with self._lock:
                self._history = messages

    def clear_history(self) -> None:
        """Reset conversation history (start a fresh agent session)."""
        with self._lock:
            self._history.clear()

    # ------------------------------------------------------------------
    # run_agent — single-shot agent (no persistent history; backward compat)
    # ------------------------------------------------------------------

    async def run_agent(
        self,
        prompt: str,
        model: str | None = None,
        verbose: bool | None = None,
    ) -> str:
        """Single-shot Ollama agent — does not persist history across calls.

        Works with both stdio and http transports. For persistent multi-turn
        sessions use agent_send().

        Args:
            prompt:  Natural language instruction.
            model:   Ollama model override (defaults to config.model).
            verbose: Override config.verbose for this call only.
        """
        use_model = model or self.config.model
        use_verbose = verbose if verbose is not None else self.config.verbose

        try:
            from ollama import AsyncClient as OllamaAsync
        except ImportError:
            raise RuntimeError("ollama not installed. Run: pip install ollama")

        ollama_tools = self._tools_as_ollama()
        client = OllamaAsync()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.config.system_prompt},
            {"role": "user", "content": prompt},
        ]

        while True:
            response = await client.chat(
                model=use_model,
                messages=messages,
                tools=ollama_tools or None,
            )
            msg = response.message

            if not msg.tool_calls:
                if use_verbose and msg.content:
                    print(f"[{use_model}] {msg.content}")
                return msg.content or ""

            messages.append(msg)

            for tc in msg.tool_calls:
                name = tc.function.name
                input_args = tc.function.arguments or {}

                if use_verbose:
                    print(f"[Tool call]   {name}({input_args})")

                result = await self.call(name, input_args)

                if use_verbose:
                    print(f"[Tool result] {name} → {result}")

                messages.append({"role": "tool", "content": result})
