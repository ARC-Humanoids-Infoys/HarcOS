# HarcOS — Humanoid Robot Control System

A modular control framework for Unitree robots built on the [Model Context Protocol](https://modelcontextprotocol.io), inspired by [DimOS](https://github.com/dimensionalOS/dimos). Each robot's capabilities are exposed as MCP tools, accessible to AI agents (Ollama or OpenAI via LangChain) or any Python script.

---

## Project Structure

```
HarcOS/
├── run.py                  ← CLI entry point — start the MCP server
├── run_g1_nlp.py           ← Interactive natural-language shell for the G1
├── registry.py             ← Robot name → blueprint mapping
├── mcp_server.py           ← Shared FastMCP server factory
├── robots/
│   ├── base.py             ← RobotController abstract base class
│   ├── go2/
│   │   ├── controller.py   ← Go2 hardware (WebRTC)
│   │   ├── skills.py       ← Go2 MCP tools
│   │   └── blueprint.py    ← Go2 factory
│   └── g1/
│       ├── controller.py   ← G1 hardware (WebRTC)
│       ├── skills.py       ← G1 MCP tools
│       └── blueprint.py    ← G1 factory
├── clients/
│   ├── __init__.py         ← exports RobotClient, G1Client, Go2Client, HarcMcpClient
│   ├── base.py             ← RobotClient — MCP client + Ollama agent loop (async)
│   ├── g1.py               ← G1Client (typed wrappers around RobotClient)
│   ├── go2.py              ← Go2Client
│   └── mcp_client.py       ← HarcMcpClient — LangGraph ReAct agent (DimOS McpClient pattern)
└── requirements.txt
```

---

## Running the MCP Server

### stdio (Claude Desktop / MCP Inspector)

```bash
python run.py g1                         # G1 — connect to 192.168.123.161
python run.py g1 --ip 192.168.123.161   # G1 — explicit IP
python run.py go2 --ip 192.168.123.161  # Go2 — specific IP
```

### HTTP server (Python client / agent loop)

```bash
# SSE transport (async streaming)
python run.py g1  --transport sse --port 9991
python run.py go2 --transport sse --port 9990

# Streamable-HTTP transport (JSON-RPC 2.0 POST to /mcp) — required by HarcMcpClient
python run.py g1  --transport streamable-http --port 9991
python run.py go2 --transport streamable-http --port 9990
```

> `0.0.0.0` is the bind address — always use `localhost` (or the machine's LAN IP) in client URLs.

---

## Natural-Language Shell (LangGraph Agent)

`run_g1_nlp.py` is an interactive REPL that accepts plain English commands and sends them to a LangGraph ReAct agent. The agent automatically decides which MCP tools to call.

### Quick start

```bash
# Terminal 1 — start the MCP server
python run.py g1 --transport streamable-http --port 9991

# Terminal 2 — start Ollama
ollama serve
ollama pull llama3.2   # or qwen2.5, mistral-nemo (≥7B recommended)

# Terminal 3 — launch the shell
python run_g1_nlp.py
```

```
G1> connect
G1> stand up
G1> walk forward 0.5 meters for 3 seconds
G1> wave your right hand then stop
G1> show battery status
G1> sit down and disconnect
G1> quit
```

### Flags

```bash
python run_g1_nlp.py --model ollama:llama3.2        # default
python run_g1_nlp.py --model ollama:qwen2.5         # better tool-calling
python run_g1_nlp.py --model gpt-4o                 # OpenAI (needs OPENAI_API_KEY)
python run_g1_nlp.py --server http://localhost:9991  # default server
python run_g1_nlp.py --quiet                         # hide tool-call trace
python run_g1_nlp.py --cmd "stand up and wave"       # single command, non-interactive
```

---

## HarcMcpClient (LangGraph agent — DimOS McpClient pattern)

`clients/mcp_client.py` architecture:

```
Natural language text
      │
      ▼
HarcMcpClient._queue  (Queue[HumanMessage])
      │
      ▼
HarcMcpClient._loop() ← background thread, always running
      │
      ▼
LangGraph create_react_agent
  model = "ollama:llama3.2"   (or "gpt-4o", or a ChatModel instance)
  tools = [StructuredTool(...), ...]  ← fetched from MCP server on start()
      │
      ▼ LLM decides which tools to call
StructuredTool.func(**kwargs)
      │
      ▼
HTTP POST http://localhost:9991/mcp
  {"jsonrpc":"2.0","method":"tools/call","params":{"name":"move","arguments":{...}}}
      │
      ▼
MCP server executes the skill → text result
      │
      ▼
LLM sees result, calls next tool or stops → prints / calls on_message callback
```

### Usage

```python
from clients import HarcMcpClient

# Ollama (default)
client = HarcMcpClient(server_url="http://localhost:9991", model="ollama:llama3.2")
client.start()
client.send("stand up and wave your right hand")          # non-blocking
client.send_wait("walk forward 1 meter then stop")        # blocks until done
client.clear_history()                                    # fresh conversation
client.stop()

# Context manager
with HarcMcpClient(model="ollama:qwen2.5") as client:
    client.send_wait("connect and get battery status")
```

```python
# OpenAI (needs: pip install langchain-openai && export OPENAI_API_KEY=sk-...)
with HarcMcpClient(model="gpt-4o") as client:
    client.send_wait("stand up and clap three times")
```

```python
# Pre-built ChatOllama instance (full control)
from langchain_ollama import ChatOllama
model = ChatOllama(model="llama3.2", base_url="http://localhost:11434", temperature=0)
with HarcMcpClient(model=model) as client:
    client.send_wait("wave and say hello")
```

```python
# Custom on_message callback
from langchain_core.messages import AIMessage

def handle(msg):
    if isinstance(msg, AIMessage) and msg.content:
        print(f"Robot says: {msg.content}")

with HarcMcpClient(on_message=handle, verbose=False) as client:
    client.send_wait("check the IMU")
```

### Supported models

| Model string | Backend | Notes |
|---|---|---|
| `"ollama:llama3.2"` | Ollama | Good tool calling, fast |
| `"ollama:qwen2.5"` | Ollama | Better tool calling |
| `"ollama:mistral-nemo"` | Ollama | Solid tool calling |
| `"gpt-4o"` | OpenAI | Best reliability, needs API key |
| `"gpt-4o-mini"` | OpenAI | Cheaper, slightly less reliable |
| `ChatOllama(...)` | Ollama | Direct instance, full config |

> Avoid models smaller than 7B for reliable tool use.

---

## MCP Inspector

Browse and call tools interactively in a browser UI:

```bash
# Recommended — clears stale port locks automatically
./inspector.sh g1
./inspector.sh go2

# Manual (if ports 6277/6274 are already free)
npx @modelcontextprotocol/inspector python run.py g1
npx @modelcontextprotocol/inspector python run.py go2

# SSE mode (server must already be running)
npx @modelcontextprotocol/inspector
# → set Transport: SSE, URL: http://localhost:9991/sse

# streamable-http mode (JSON-RPC 2.0 POST)
npx @modelcontextprotocol/inspector
# → set Transport: Streamable HTTP, URL: http://localhost:9991/mcp
```

> **Tip:** If you see `PORT IS IN USE at port 6277`, run `lsof -ti:6277 -ti:6274 | xargs kill -9` then retry.
> In the inspector, always use `http://localhost:<port>/sse` — not `http://0.0.0.0:<port>`.

---

## Python Client (async, direct)

### Architecture (DimOS-inspired)

The `RobotClient` / `G1Client` path uses the MCP SDK's `ClientSession` directly with Python `asyncio`. Use this for scripted sequences where you control each step explicitly.

The `HarcMcpClient` path (above) uses LangChain/LangGraph and handles tool selection automatically from natural language.

```
RobotClientConfig          RobotClient
  robot, model,      →      _connect_stdio()  or  _connect_http()
  transport,                 ↓                      ↓
  server_url,           StdioServerParameters    sse_client(url)
  system_prompt,             ↓                      ↓
  verbose               ClientSession          ClientSession
                             ↓
                        list_tools() / call() / agent_send()
```

### Two transports

| | stdio | http |
|---|---|---|
| **How** | Spawns `run.py` subprocess | Connects to running SSE server |
| **Start** | automatic | `python run.py <robot> --transport sse` |
| **Best for** | Claude Desktop, one-off scripts | Agent loop, persistent sessions |
| **agent_send()** | ✓ | ✓ |

### Python API

```python
from clients import G1Client, Go2Client, RobotClient, RobotClientConfig
import asyncio

# --- Direct calls (stdio, default) ---
async def main():
    async with G1Client() as robot:
        print(await robot.connect())
        await robot.stand_up()
        await robot.move(0.2, 0.0, 0.0, duration=3.0)
        await robot.stop()
        await robot.execute_arm_command("high_wave")
        await robot.damp()

asyncio.run(main())
```

```python
# --- HTTP transport (server must be running) ---
async def main():
    async with G1Client(transport="http", server_url="http://localhost:9991") as robot:
        print(await robot.list_tools())
        print(await robot.call("connect"))

asyncio.run(main())
```

```python
# --- Generic client — any robot, any tool ---
async def main():
    async with RobotClient(RobotClientConfig("g1")) as robot:
        print(await robot.list_tools())
        print(await robot.call("get_imu"))

asyncio.run(main())
```

### Ollama Agent Loop (async, direct SDK)

Requires [Ollama](https://ollama.com) running locally with a tool-calling model.

#### `agent_send()` — persistent multi-turn (DimOS pattern)

History is preserved across calls. Both transports supported.

```python
from clients import G1Client
import asyncio

async def main():
    async with G1Client() as robot:
        reply = await robot.agent_send("connect and stand up")
        print(reply)
        reply = await robot.agent_send("now wave your hand")   # history kept
        print(reply)
        robot.clear_history()                                   # fresh session

asyncio.run(main())
```

#### `run_agent()` — single-shot (backward compat)

```python
async def main():
    async with G1Client() as robot:
        await robot.run_agent(
            "Connect to the robot, stand it up, then wave its hand",
            model="llama3.2",
            verbose=True,
        )

asyncio.run(main())
```

### CLI

```bash
# G1 — list tools and attempt connect
python -m clients.g1 --interface eth0

# G1 — Ollama agent
python -m clients.g1 --agent "connect and stand up"

# G1 — HTTP transport + agent
python -m clients.g1 --transport http --agent "stand up and wave"

# Use a different Ollama model
python -m clients.g1 --agent "What tools are available?" --model qwen2.5
```

---

## Skills Reference

### G1 (humanoid)

> **Network:** Connect Ethernet to the **main controller** at `192.168.123.161` (port 8081 for WebRTC).
> Set your laptop IP: `sudo ip addr add 192.168.123.100/24 dev enp2s0`
> `192.168.123.164` is the Jetson/PC4 SSH board — it does NOT run motion commands.

| Tool | Description |
|---|---|
| `connect` | Connect via WebRTC, switch to AI mode |
| `disconnect` | Disconnect cleanly |
| `get_battery` | Voltage, charge %, current |
| `get_imu` | Roll, pitch, yaw (rad) + accelerations (m/s²) |
| `stand_up` | Stand up from sitting / lying |
| `stand_down` | Sit down from standing |
| `balance_stand` | Enter stable balanced posture |
| `move` | Velocity command: `vx`, `vy`, `vyaw`, `duration` |
| `stop` | Stop all movement immediately |
| `damp` | Motors into compliant / low-power mode |
| `wave_hand` | High wave (gesture 26) |
| `shake_hand` | Handshake (gesture 27) |
| `clap` | Clap (gesture 17) |
| `high_five` | High five (gesture 18) |
| `hug` | Hug (gesture 19) |
| `hands_up` | Raise both hands (gesture 15) |
| `cancel_action` | Cancel arm gesture, return to default |
| `execute_arm_command` | Named gesture: `high_wave`, `shake_hand`, `clap`, etc. |
| `execute_mode_command` | Named FSM mode: `walk`, `run`, `damp`, `sit`, etc. |

### Go2 (quadruped)

| Tool | Description |
|---|---|
| `connect` | Connect over WebRTC |
| `disconnect` | Disconnect cleanly |
| `get_battery` | Charge %, voltage, current, cycle count |

---

## Environment Variables

| Variable | Robot | Description |
|---|---|---|
| `ROBOT_IP` | Go2, G1 | Robot main controller IP |
| `G1_ROBOT_IP` | G1 | G1 main controller IP (overrides `ROBOT_IP`) |
| `OPENAI_API_KEY` | — | OpenAI API key (required for `model="gpt-4o"` in `HarcMcpClient`) |

---

## Installation

```bash
pip install -r requirements.txt

# Ollama backend (free, local)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2    # recommended — good tool calling, fast
ollama pull qwen2.5     # alternative — better multi-step tool calling

# OpenAI backend (optional)
pip install langchain-openai
export OPENAI_API_KEY=sk-...
```

---

## Technical Notes

### Go2 vs G1 transport

| | Go2 | G1 |
|---|---|---|
| Transport | WebRTC | WebRTC |
| Addressing | IP address | IP address (192.168.123.161) |
| SDK | `unitree_webrtc_connect_leshy` | `unitree_webrtc_connect_leshy` |
| Motion API | `rt/wirelesscontroller` | `rt/wirelesscontroller` |
| Arm API | — | `rt/api/arm/request` (api_id 7106) |
| Posture API | — | `rt/api/sport/request` (api_id 7101/7102) |
| Mode switch | — | `rt/api/motion_switcher/request` (api_id 1002) |

### G1 battery and IMU

G1 telemetry comes from the `rt/lowstate` WebRTC topic (same as Go2). The `soc_percent` and `current_a` fields may be `null` depending on firmware — `voltage_v` is always available.

### AI mode required

The G1 boots in **Developer mode**. `connect()` automatically calls `SelectMode("ai")` via `rt/api/motion_switcher/request`. Without this, **all motion commands are silently ignored**. If motion stops working after a reboot, call `connect()` again.

---

## Adding a New Robot

1. Create `robots/<name>/controller.py` — subclass `RobotController` from `robots/base.py`
2. Create `robots/<name>/skills.py` — implement `register(mcp, controller)`
3. Create `robots/<name>/blueprint.py` — implement `build_<name>()` returning `(mcp, controller)`
4. Register in `registry.py`: `BLUEPRINTS["<name>"] = build_<name>`
5. Optionally add `clients/<name>.py` — subclass `RobotClient` with typed method wrappers

`python run.py <name>` works immediately after step 4.