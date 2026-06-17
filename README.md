# HarcOS — Humanoid Robot Control System

A modular control framework for Unitree robots built on the [Model Context Protocol](https://modelcontextprotocol.io), inspired by [DimOS](https://github.com/dimensionalOS/dimos). Each robot's capabilities are exposed as MCP tools, accessible to AI agents (via Ollama) or any Python script.

---

## Project Structure

```
HarcOS/
├── run.py                  ← CLI entry point
├── registry.py             ← Robot name → blueprint mapping
├── mcp_server.py           ← Shared FastMCP server factory
├── robots/
│   ├── base.py             ← RobotController abstract base class
│   ├── go2/
│   │   ├── controller.py   ← Go2 hardware (WebRTC)
│   │   ├── skills.py       ← Go2 MCP tools
│   │   └── blueprint.py    ← Go2 factory
│   └── g1/
│       ├── controller.py   ← G1 hardware (DDS / SDK2)
│       ├── skills.py       ← G1 MCP tools
│       └── blueprint.py    ← G1 factory
├── clients/
│   ├── __init__.py         ← exports RobotClientConfig, RobotClient, G1Client, Go2Client
│   ├── base.py             ← RobotClient — generic MCP client + Ollama agent loop
│   ├── g1.py               ← G1Client
│   └── go2.py              ← Go2Client
└── requirements.txt
```

---

## Running the MCP Server

### stdio (Claude Desktop / MCP Inspector)

```bash
python run.py g1                          # G1 — auto-detect DDS interface
python run.py g1 --interface eth0         # G1 — specify interface
python run.py go2 --ip 192.168.123.161   # Go2 — specific IP
```

### HTTP SSE server (Python client / agent loop)

```bash
python run.py g1  --transport sse --port 9991
python run.py go2 --transport sse --port 9990
```

The server listens on `http://localhost:<port>/sse`.  
`0.0.0.0` is the **bind address** — always use `localhost` (or the machine's IP) in client URLs.

---

## MCP Inspector

Browse and call tools interactively in a browser UI:

```bash
# stdio mode
npx @modelcontextprotocol/inspector python run.py g1
npx @modelcontextprotocol/inspector python run.py go2

# SSE mode (server must already be running)
npx @modelcontextprotocol/inspector
# → set Transport: SSE, URL: http://localhost:9991/sse
```

> **Tip:** In the inspector, always use `http://localhost:<port>/sse` — not `http://0.0.0.0:<port>`.

---

## Python Client

### Architecture (DimOS-inspired)

The client uses a `RobotClientConfig` dataclass to hold all settings (transport, model, system prompt, server URL). Both transports (`stdio` and `http`) share the same `mcp.ClientSession` interface — all methods work identically.

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
        await robot.move(0.2, 0.0, 0.0)
        await robot.stop()
        await robot.wave_hand()
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

### Ollama Agent Loop

Requires [Ollama](https://ollama.com) running locally with a tool-calling model (`llama3.2`, `llama3.1`, `mistral`, `qwen2.5`, etc.).

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

No history across calls. Useful for one-off commands.

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
# Go2 — list tools and attempt connect
python -m clients.go2 --ip 192.168.123.161

# Go2 — Ollama agent
python -m clients.go2 --agent "Connect and check the battery"

# Go2 — HTTP transport + agent
python -m clients.go2 --transport http --agent "go forward 1 meter"

# Use a different Ollama model
python -m clients.go2 --agent "What tools are available?" --model qwen2.5
```

---

## Skills Reference

### G1 (humanoid)

| Tool | Description |
|---|---|
| `connect` | Connect over DDS |
| `disconnect` | Disconnect cleanly |
| `get_battery` | Voltage proxy via motor state |
| `get_imu` | Roll, pitch, yaw (rad) + accelerations (m/s²) |
| `stand_up` | Stand up from sitting / lying |
| `stand_down` | Sit / lie down from standing |
| `balance_stand` | Enter stable balanced posture |
| `move` | Velocity command: `vx`, `vy`, `vyaw` |
| `stop` | Stop all movement |
| `damp` | Motors into compliant / low-power mode |
| `wave_hand` | Wave hand |

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
| `ROBOT_IP` | Go2 | Robot IP (default: `192.168.123.161`) |
| `G1_ROBOT_IP` | G1 | Optional identifier, not used by DDS |
| `G1_NETWORK_INTERFACE` | G1 | DDS interface (auto-detected if not set) |

---

## Technical Notes

### Go2 vs G1 transport

| | Go2 | G1 |
|---|---|---|
| Transport | WebRTC | DDS (CycloneDDS) |
| Addressing | IP address | Network interface |
| SDK | `unitree_webrtc_connect_leshy` | `unitree_sdk2py` (Linux only) |
| Motion client | `SportClient` | `LocoClient` |

### G1 battery

`unitree_hg.LowState_` (G1's IDL) has no BMS fields. `get_battery()` returns the average motor supply voltage (~51 V) as a proxy. The `soc_percent` value is a placeholder — full SOC would require a separate BMS topic subscription.

### G1 SDK on Windows

`unitree_sdk2py` requires native CycloneDDS which is Linux-only. On Windows, `connect()` will return `"unitree_sdk2py not installed"`. Use a Linux machine or WSL to run G1 in production.

---

## Adding a New Robot

1. Create `robots/<name>/controller.py` — subclass `RobotController` from `robots/base.py`
2. Create `robots/<name>/skills.py` — implement `register(mcp, controller)`
3. Create `robots/<name>/blueprint.py` — implement `build_<name>()` returning `(mcp, controller)`
4. Register in `registry.py`: `BLUEPRINTS["<name>"] = build_<name>`
5. Optionally add `clients/<name>.py` — subclass `RobotClient` with typed method wrappers

`python run.py <name>` works immediately after step 4.