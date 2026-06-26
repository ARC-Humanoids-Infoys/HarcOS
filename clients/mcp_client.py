"""
clients/mcp_client.py

    Human text input
          │
          ▼
    HarcMcpClient._queue  (Queue[HumanMessage])
          │
          ▼
    HarcMcpClient._loop() ← background thread, always running
          │
          ▼
    LangGraph create_react_agent
      model = "ollama:llama3.2"  (or "gpt-4o", or a ChatModel instance)
      tools = [StructuredTool(...), ...]  ← fetched from MCP server
          │
          ▼ LLM decides which tool to call
    StructuredTool.func(**kwargs)
          │
          ▼
    HTTP POST to http://localhost:9991/mcp
      {"jsonrpc":"2.0","method":"tools/call","params":{"name":"move","arguments":{...}}}
          │
          ▼
    MCP server executes the skill → returns text result
          │
          ▼
    LLM sees result, decides next action or stops
          │
          ▼
    on_message callback / stdout print

Supported models (via LangChain init_chat_model):
    "ollama:llama3.2"           - Ollama locally (requires langchain-ollama)
    "ollama:qwen2.5"            - Ollama Qwen 2.5
    "ollama:mistral"            - Ollama Mistral
    "gpt-4o"                    - OpenAI (requires OPENAI_API_KEY + langchain-openai)
    "gpt-4o-mini"               - OpenAI mini
    ChatOllama(model="llama3.2") - pre-built LangChain ChatModel instance

Usage::

    # Start the MCP server first:
    #   python run.py g1 --transport streamable-http --port 9991

    # Ollama (default):
    client = HarcMcpClient(server_url="http://localhost:9991", model="ollama:llama3.2")
    client.start()
    client.send("stand up and wave your right hand")

    # OpenAI:
    client = HarcMcpClient(server_url="http://localhost:9991", model="gpt-4o")
    client.start()
    client.send_wait("walk forward 1 meter then stop")

    # Context manager (auto start/stop):
    with HarcMcpClient() as client:
        client.send_wait("connect and stand up")
"""

from __future__ import annotations

import time
import uuid
from queue import Empty, Queue
from threading import Event, RLock, Thread
from typing import Any, Callable, Optional

import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

# ---------------------------------------------------------------------------
# Default system prompt for G1
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = (
    "You are a controller for a Unitree G1 humanoid robot. "
    "Use the available tools to fulfil user requests precisely and safely. "
    "Always call connect() first if the robot is not already connected. "
    "Confirm each action's result before proceeding to the next step. "
    "If a tool returns an error, report it and stop safely."
)

# ---------------------------------------------------------------------------
# JSON Schema → Pydantic model helpers
# ---------------------------------------------------------------------------

_JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _json_type(prop_schema: dict) -> type:
    """Resolve a JSON Schema property type to a Python type."""
    # Handle anyOf (e.g. {"anyOf": [{"type": "number"}, {"type": "null"}]})
    if "anyOf" in prop_schema:
        for sub in prop_schema["anyOf"]:
            if sub.get("type") != "null":
                return _JSON_TYPE_MAP.get(sub.get("type", "string"), str)
    return _JSON_TYPE_MAP.get(prop_schema.get("type", "string"), str)


def _schema_to_pydantic(tool_name: str, schema: dict) -> type[BaseModel]:
    """Dynamically build a Pydantic BaseModel from a JSON Schema object."""
    properties: dict[str, dict] = schema.get("properties", {})
    required: set[str] = set(schema.get("required", []))

    fields: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        py_type = _json_type(prop_schema)
        desc = prop_schema.get("description", "")

        if prop_name in required:
            fields[prop_name] = (py_type, Field(..., description=desc))
        elif "default" in prop_schema:
            fields[prop_name] = (py_type, Field(prop_schema["default"], description=desc))
        else:
            fields[prop_name] = (Optional[py_type], Field(None, description=desc))

    # Unique class name per tool to avoid Pydantic model registry collisions
    return create_model(f"_{tool_name}_args", **fields)


# ---------------------------------------------------------------------------
# HarcMcpClient
# ---------------------------------------------------------------------------


class HarcMcpClient:
    """DimOS-style MCP agent client using LangChain/LangGraph.

    Connects to a running MCP server (streamable-http transport),
    discovers tools automatically, and runs a LangGraph ReAct agent loop
    in a background thread.

    Args:
        server_url:          Base URL of the MCP HTTP server
                             (default: ``http://localhost:9991``).
        model:               LangChain model string or ChatModel instance.
                             Examples: ``"ollama:llama3.2"``, ``"gpt-4o"``,
                             ``ChatOllama(model="llama3.2")``.
        system_prompt:       Agent system prompt.  Defaults to a G1-specific
                             safety prompt.
        tool_fetch_timeout:  Seconds to wait for the server to become ready.
        verbose:             Print tool calls and agent responses to stdout.
        on_message:          Optional callback called for every agent message
                             (``AIMessage``, ``ToolMessage``, etc.).
    """

    def __init__(
        self,
        server_url: str = "http://localhost:9991",
        model: str | Any = "ollama:llama3.2",
        system_prompt: str | None = None,
        tool_fetch_timeout: float = 30.0,
        verbose: bool = True,
        on_message: Callable[[BaseMessage], None] | None = None,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.model = model
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self.tool_fetch_timeout = tool_fetch_timeout
        self.verbose = verbose
        self.on_message = on_message

        self._http = httpx.Client(timeout=120.0)
        self._session_id: str | None = None
        self._queue: Queue[HumanMessage] = Queue()
        self._history: list[BaseMessage] = []
        self._lock = RLock()
        self._stop = Event()
        self._graph = None
        self._thread = Thread(target=self._loop, daemon=True, name="HarcMcpClient")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> "HarcMcpClient":
        """Fetch tools, build the LangGraph agent, and start the background thread.

        Returns self for use as a context manager or for chaining.
        """
        tools = self._fetch_tools()
        with self._lock:
            self._graph = self._build_agent(tools)
        self._thread.start()
        return self

    def stop(self) -> None:
        """Signal the background thread to stop and wait for it to finish."""
        self._stop.set()
        self._thread.join(timeout=5.0)
        self._http.close()

    def __enter__(self) -> "HarcMcpClient":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Sending commands
    # ------------------------------------------------------------------

    def send(self, text: str) -> None:
        """Queue a natural-language command (non-blocking).

        The agent processes queued commands sequentially in a background thread.
        Use :meth:`send_wait` to block until the response is complete.

        Args:
            text: Natural language instruction, e.g. "walk forward 1 meter".
        """
        self._queue.put(HumanMessage(content=text))

    def send_wait(self, text: str, timeout: float = 120.0) -> None:
        """Queue a command and block until the agent finishes processing it.

        Args:
            text:    Natural language instruction.
            timeout: Maximum seconds to wait (default: 120).
        """
        self.send(text)
        self._queue.join()  # blocks until _loop calls task_done()

    def clear_history(self) -> None:
        """Reset conversation history to start a fresh session."""
        with self._lock:
            self._history.clear()

    # ------------------------------------------------------------------
    # Agent construction
    # ------------------------------------------------------------------

    def _build_agent(self, tools: list[StructuredTool]):
        """Build a LangGraph ReAct agent with the fetched tools."""
        from langchain_core.messages import SystemMessage
        from langgraph.prebuilt import create_react_agent

        if isinstance(self.model, str):
            from langchain.chat_models import init_chat_model
            llm = init_chat_model(self.model)
        else:
            llm = self.model  # pre-built ChatOllama / ChatOpenAI instance

        return create_react_agent(
            model=llm,
            tools=tools,
            prompt=SystemMessage(content=self.system_prompt),
        )

    # ------------------------------------------------------------------
    # Background processing loop
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                msg = self._queue.get(timeout=0.5)
            except Empty:
                continue
            try:
                with self._lock:
                    self._process(msg)
            finally:
                self._queue.task_done()

    def _process(self, message: HumanMessage) -> None:
        """Run the ReAct agent on the current message, streaming updates."""
        self._history.append(message)
        for update in self._graph.stream(
            {"messages": self._history}, stream_mode="updates"
        ):
            for node_output in update.values():
                for msg in node_output.get("messages", []):
                    self._history.append(msg)
                    if self.verbose:
                        self._print_msg(msg)
                    if self.on_message:
                        self.on_message(msg)

    def _print_msg(self, msg: BaseMessage) -> None:
        if isinstance(msg, AIMessage):
            if msg.content:
                print(f"\n[Agent] {msg.content}")
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    print(f"[Tool call]  {tc['name']}({tc.get('args', {})})")
        elif isinstance(msg, ToolMessage):
            print(f"[Tool result] {msg.name} → {msg.content}")

    # ------------------------------------------------------------------
    # Tool discovery (HTTP JSON-RPC)
    # ------------------------------------------------------------------

    def _fetch_tools(self) -> list[StructuredTool]:
        """Wait for the MCP server, fetch tools/list, and return StructuredTools."""
        deadline = time.monotonic() + self.tool_fetch_timeout
        while True:
            try:
                result = self._mcp("tools/list")
                raw_tools: list[dict] = result.get("tools", [])
                break
            except httpx.ConnectError:
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        f"MCP server not reachable at {self.server_url}/mcp "
                        f"after {self.tool_fetch_timeout:.0f}s.\n"
                        "Start it first:\n"
                        "  python run.py g1 --transport streamable-http --port 9991"
                    )
                time.sleep(1.0)

        if self.verbose:
            names = [t["name"] for t in raw_tools]
            print(f"[HarcMcpClient] Discovered {len(names)} tools: {names}")

        return [self._make_tool(t) for t in raw_tools]

    def _make_tool(self, mcp_tool: dict) -> StructuredTool:
        """Wrap a single MCP tool spec as a LangChain StructuredTool."""
        name = mcp_tool["name"]
        description = mcp_tool.get("description", "")
        schema = mcp_tool.get("inputSchema", {"type": "object", "properties": {}})

        # Use a default-arg capture to avoid the late-binding closure bug
        def call(_name: str = name, **kwargs: Any) -> str:
            result = self._mcp("tools/call", {"name": _name, "arguments": kwargs})
            content = result.get("content", [])
            return "\n".join(
                c.get("text", "") for c in content if c.get("type") == "text"
            )

        args_model = _schema_to_pydantic(name, schema)

        return StructuredTool(
            name=name,
            description=description,
            func=call,
            args_schema=args_model,
        )

    # ------------------------------------------------------------------
    # Low-level HTTP JSON-RPC helper
    # ------------------------------------------------------------------

    _MCP_HEADERS = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    def _parse_mcp_response(self, resp: httpx.Response) -> dict[str, Any]:
        """Parse a MCP server response — handles both JSON and SSE formats."""
        import json as _json
        ct = resp.headers.get("content-type", "")
        if "text/event-stream" in ct:
            # SSE body: "event: message\r\ndata: {...}\r\n\r\n"
            for line in resp.text.splitlines():
                if line.startswith("data:"):
                    return _json.loads(line[len("data:"):].strip())
            return {}
        return resp.json()

    def _mcp_init(self) -> None:
        """Perform the MCP initialize handshake and store the session ID."""
        body: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "HarcMcpClient", "version": "1.0"},
            },
        }
        resp = self._http.post(
            f"{self.server_url}/mcp", json=body, headers=self._MCP_HEADERS
        )
        resp.raise_for_status()
        self._session_id = resp.headers.get("mcp-session-id")
        data = self._parse_mcp_response(resp)
        if "error" in data:
            raise RuntimeError(f"MCP initialize error: {data['error']}")

        # Send the required initialized notification
        notif: dict[str, Any] = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        notif_headers = dict(self._MCP_HEADERS)
        if self._session_id:
            notif_headers["mcp-session-id"] = self._session_id
        self._http.post(f"{self.server_url}/mcp", json=notif, headers=notif_headers)

    def _mcp(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a JSON-RPC 2.0 request to the MCP server and return the result.

        Automatically performs the MCP initialize handshake on first call.
        """
        if self._session_id is None:
            self._mcp_init()

        body: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
        }
        if params is not None:
            body["params"] = params

        headers: dict[str, str] = dict(self._MCP_HEADERS)
        if self._session_id:
            headers["mcp-session-id"] = self._session_id

        resp = self._http.post(f"{self.server_url}/mcp", json=body, headers=headers)
        resp.raise_for_status()
        data = self._parse_mcp_response(resp)
        if "error" in data:
            raise RuntimeError(f"MCP error [{method}]: {data['error']}")
        return data.get("result", {})
