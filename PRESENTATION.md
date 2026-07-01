# HarcOS — Robot Navigation Using DimOS MCP & AI Agent
## Project Presentation

---

## 1. Project Overview

**HarcOS** (Humanoid and Robot Control OS) is a modular AI-powered control framework for **Unitree robots** — specifically the **G1 humanoid** and **Go2 quadruped**. The core idea is to expose every robot capability as a **Model Context Protocol (MCP) tool** so that any AI agent (or human-written script) can control the robot using natural language or structured API calls.

**Core innovation:** We designed and built an independent MCP server from scratch — inspired by the open-source DimOS framework — that handles robot navigation, posture control, sensor telemetry, and arm gestures, all over a standard JSON-RPC 2.0 protocol.

---

## 2. What Problem Are We Solving?

Controlling a physical robot traditionally requires:
- Low-level hardware SDK knowledge (WebRTC, DDS topics, raw API IDs)
- Writing repetitive boilerplate for every motion command
- No standard interface for AI agents to interact with hardware

**Our solution:** A clean MCP server that wraps all of this complexity so that:
- An AI agent (LLM) can call `move(vx=0.5, duration=3)` or `wave_hand()` just like calling any function
- A human can type *"walk forward 0.5 meters for 3 seconds"* in plain English and the robot executes it
- Any tool — Claude Desktop, Ollama, OpenAI GPT-4o, or a Python script — can control the robot through a single unified interface

---

## 3. Technologies Used

| Layer | Technology | Purpose |
|---|---|---|
| Robot SDK | `unitree_webrtc_connect_leshy` | WebRTC communication with G1 / Go2 hardware |
| MCP Framework | `FastMCP` (Python `mcp>=1.27.1`) | Expose robot skills as MCP tools |
| AI Agent (local) | **Ollama** + `llama3.2 / qwen2.5` | Free, on-device LLM for natural language control |
| AI Agent (cloud) | **OpenAI GPT-4o** | Cloud LLM option for higher reliability |
| Agent Orchestration | **LangChain + LangGraph** (ReAct agent) | Decides which tools to call based on natural language |
| Async Runtime | Python `asyncio` | Async hardware communication and agent loop |
| Transport | stdio / SSE / Streamable-HTTP | Flexible deployment — desktop app or HTTP server |
| Simulation | DimOS `unitree_g1_sim` | Test agent logic without physical hardware |
| Inspection | `@modelcontextprotocol/inspector` | Browser UI to browse and call MCP tools manually |

---

## 4. System Architecture

```
                    ┌──────────────────────────────┐
                    │   Natural Language Input       │
                    │  "walk forward 0.5 meters"    │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │     HarcMcpClient             │
                    │  (LangGraph ReAct Agent)      │
                    │  LLM: Ollama / GPT-4o         │
                    │  Decides: which tool to call  │
                    └──────────────┬───────────────┘
                                   │ HTTP POST /mcp
                                   │ JSON-RPC 2.0
                    ┌──────────────▼───────────────┐
                    │       HarcOS MCP Server       │
                    │       (FastMCP — run.py)      │
                    │  ┌────────────────────────┐  │
                    │  │  Robot Skills (tools)  │  │
                    │  │  connect / disconnect  │  │
                    │  │  stand_up / stand_down │  │
                    │  │  move / stop           │  │
                    │  │  wave_hand / clap      │  │
                    │  │  get_battery / get_imu │  │
                    │  └────────────────────────┘  │
                    └──────────────┬───────────────┘
                                   │ WebRTC
                    ┌──────────────▼───────────────┐
                    │     Unitree Robot Hardware    │
                    │   G1 Humanoid / Go2 Quadruped │
                    └──────────────────────────────┘
```

---

## 5. What We Built — Component by Component

### 5.1 The Independent MCP Server (`mcp_server.py`, `run.py`)

We created a **standalone MCP server** that any client (Claude Desktop, Python script, or AI agent) can connect to.

- Uses **FastMCP** to register tools declaratively
- Supports **3 transport modes**:
  - `stdio` — for Claude Desktop (no network needed)
  - `SSE` — HTTP streaming for persistent agent loops
  - `Streamable-HTTP` — JSON-RPC 2.0 POST, required for LangGraph agents
- A single CLI entry point: `python run.py g1 --transport streamable-http --port 9991`

```
python run.py g1                                   # stdio mode (Claude Desktop)
python run.py g1 --transport streamable-http       # HTTP mode (AI agent loop)
python run.py go2 --transport sse --port 9990      # Go2 SSE mode
```

### 5.2 Robot Controllers (`robots/g1/controller.py`, `robots/go2/controller.py`)

Each robot has a dedicated **controller class** that wraps the Unitree WebRTC SDK:

- Manages the WebRTC connection lifecycle
- Sends motion commands to the correct ROS2 topics (`rt/wirelesscontroller`, `rt/api/sport/request`)
- Reads telemetry from `rt/lowstate` (battery voltage, IMU roll/pitch/yaw)
- Handles the G1-specific requirement of switching to **AI mode** (`SelectMode("ai")`) before any motion is accepted

### 5.3 Robot Skills / MCP Tools (`robots/g1/skills.py`, `robots/go2/skills.py`)

Skills are the **MCP tool definitions** — each function decorated with `@mcp.tool()` becomes callable by any AI agent.

**G1 Humanoid tools (21 tools):**

| Tool | What It Does |
|---|---|
| `connect` | Connect via WebRTC and enter AI mode |
| `disconnect` | Clean disconnect |
| `get_battery` | Returns voltage, SoC %, current |
| `get_imu` | Returns roll, pitch, yaw + accelerations |
| `stand_up` | Stand up from sitting/lying |
| `stand_down` | Sit down from standing |
| `balance_stand` | Enter stable balanced posture |
| `move` | Velocity command (vx, vy, vyaw, duration) |
| `stop` | Stop all movement immediately |
| `damp` | Low-power / compliant motor mode |
| `wave_hand` | Wave gesture |
| `shake_hand` | Handshake gesture |
| `clap` | Clap gesture |
| `high_five` | High five gesture |
| `hug` | Hug gesture |
| `hands_up` | Raise both hands |
| `cancel_action` | Cancel current arm gesture |
| `execute_arm_command` | Named gesture by string ("high_wave", "clap", etc.) |
| `execute_mode_command` | Named FSM mode ("walk", "run", "damp", "sit") |

**Go2 Quadruped tools:**
- `connect`, `disconnect`, `get_battery`

### 5.4 Blueprint Pattern (`robots/g1/blueprint.py`, `registry.py`)

Inspired directly by DimOS's blueprint system:
- `build_g1()` and `build_go2()` are **factory functions** — they create the MCP server, instantiate the controller, register all skills, and return `(mcp, controller)` ready to run
- `registry.py` maps CLI names to blueprint functions — adding a new robot requires only 4 steps

### 5.5 AI Agent Clients (`clients/`)

We built two paths for AI-driven robot control:

#### Path A — `RobotClient` / `G1Client` (Direct async SDK, DimOS pattern)
- Uses `mcp.ClientSession` directly with Python `asyncio`
- Supports `stdio` and `http` transports transparently
- Has a built-in **Ollama agent loop** (`agent_send()`) with **persistent conversation history**
- Typed wrappers: `G1Client` provides `await robot.stand_up()`, `await robot.move(0.2, 0, 0, 3)`

```python
async with G1Client() as robot:
    await robot.connect()
    await robot.stand_up()
    await robot.move(vx=0.2, vy=0.0, vyaw=0.0, duration=3.0)
    await robot.wave_hand()
    await robot.damp()
```

#### Path B — `HarcMcpClient` (LangGraph ReAct agent, DimOS McpClient pattern)
- Uses **LangChain + LangGraph** `create_react_agent`
- Fetches available tools from the MCP server dynamically on startup
- Runs a **background thread** with a message queue for non-blocking operation
- Supports Ollama (local, free) and OpenAI (cloud)
- `send_wait("walk forward 1 meter then stop")` — blocks until the agent is done
- `send("wave your hand")` — non-blocking, agent processes in background

```python
with HarcMcpClient(model="ollama:llama3.2") as client:
    client.send_wait("connect, stand up, and wave your right hand")
    client.send_wait("walk forward 0.5 meters for 3 seconds then stop")
    client.send_wait("check battery status")
```

### 5.6 Natural Language Shell (`run_g1_nlp.py`)

An **interactive REPL** for controlling the G1 in plain English:

```
G1> connect
G1> stand up
G1> walk forward 0.5 meters for 3 seconds
G1> wave your right hand then stop
G1> show battery status
G1> sit down and disconnect
```

- Under the hood: every typed command goes through `HarcMcpClient` → LangGraph → MCP tools → robot hardware
- Supports `--model ollama:qwen2.5`, `--model gpt-4o`, `--quiet`, `--cmd` (single command mode)

### 5.7 DimOS Simulation Integration (`run_g1_sim.py`)

We integrated with **DimOS's simulation stack** to test agent logic without physical hardware:

- Uses `dimos.robot.unitree.g1.blueprints.perceptive.unitree_g1_sim`
- Plugs in `NavigationSkillContainer`, `SpeakSkill`, and `UnitreeG1SkillContainer`
- Runs the same `McpServer` + `McpClient` with `ollama:llama3.2` as the LLM

### 5.8 MCP Inspector Integration (`inspector.sh`)

A browser-based tool to **inspect and manually call MCP tools** — useful for testing:

```bash
./inspector.sh g1      # launches browser UI for G1
./inspector.sh go2     # launches browser UI for Go2
./inspector.sh --http  # connect to already-running HTTP server
```

---

## 6. How Navigation Works — End to End

**User says:** *"walk forward 0.5 meters for 3 seconds"*

1. `run_g1_nlp.py` receives the text and passes it to `HarcMcpClient`
2. `HarcMcpClient` places a `HumanMessage` on the queue
3. The LangGraph **ReAct agent** receives the message and asks the LLM: *"which tools do I need?"*
4. The LLM sees the available tools (`move`, `stop`, `connect`, etc.) and decides: call `move(vx=0.5, vy=0.0, vyaw=0.0, duration=3.0)`
5. LangGraph calls `StructuredTool.func(vx=0.5, vy=0.0, vyaw=0.0, duration=3.0)`
6. This fires an HTTP POST to `http://localhost:9991/mcp`:
   ```json
   {"jsonrpc":"2.0","method":"tools/call","params":{"name":"move","arguments":{"vx":0.5,"vy":0.0,"vyaw":0.0,"duration":3.0}}}
   ```
7. The MCP server routes this to `skills.py` → `controller.py` → `rt/wirelesscontroller` WebRTC topic
8. The robot's motion controller receives the velocity command and walks forward
9. After 3 seconds the controller stops publishing, and the robot halts
10. The MCP server returns `"OK"` → LangGraph → LLM confirms → prints result to user

---

## 7. Key Design Decisions & DimOS Inspiration

| Pattern | DimOS Original | Our Implementation |
|---|---|---|
| Blueprint factory | `Module.blueprint()` + `autoconnect()` | `build_g1()` / `build_go2()` in `blueprint.py` |
| MCP server | `McpServer` module | `create_server()` in `mcp_server.py` using FastMCP |
| MCP client | `McpClient` class | `HarcMcpClient` in `clients/mcp_client.py` |
| Tool registry | `_tool_registry` dict | Same pattern in `RobotClient._tool_registry` |
| HTTP retry loop | `_try_fetch_tools()` | `_connect_http()` with deadline retry |
| Persistent history | `_history` list | `RobotClient._history` + `clear_history()` |
| Agent loop | Ollama direct API | Both Ollama SDK (direct) and LangGraph (HarcMcpClient) |
| Registry | `all_blueprints.py` | `registry.py` BLUEPRINTS dict |

**Key departure from DimOS:** DimOS is a full robotics operating system with navigation stacks, perception, and a complex module graph. HarcOS deliberately strips this down to the minimal MCP layer — small, focused, easy to extend. Any robot can be added in 4 steps.

---

## 8. Project Structure Summary

```
HarcOS/
├── run.py                ← CLI — start the MCP server for any robot
├── run_g1_nlp.py         ← Interactive NL shell (LangGraph + Ollama/OpenAI)
├── run_g1_sim.py         ← DimOS simulation with Ollama agent
├── mcp_server.py         ← FastMCP factory (shared by all robots)
├── registry.py           ← Robot name → blueprint mapping
├── inspector.sh          ← Browser tool inspection UI
├── requirements.txt
│
├── robots/
│   ├── base.py           ← Abstract RobotController base class
│   ├── g1/
│   │   ├── controller.py ← G1 WebRTC hardware interface
│   │   ├── skills.py     ← G1 MCP tool definitions (21 tools)
│   │   └── blueprint.py  ← G1 factory: build_g1()
│   └── go2/
│       ├── controller.py ← Go2 WebRTC hardware interface
│       ├── skills.py     ← Go2 MCP tool definitions
│       └── blueprint.py  ← Go2 factory: build_go2()
│
└── clients/
    ├── base.py           ← RobotClient (async, MCP SDK + Ollama loop)
    ├── g1.py             ← G1Client (typed wrappers)
    ├── go2.py            ← Go2Client (typed wrappers)
    └── mcp_client.py     ← HarcMcpClient (LangGraph ReAct agent)
```

---

## 9. Results & Capabilities Demonstrated

- **Natural language → robot motion:** Type English, the G1 walks, waves, sits, stands
- **Multi-step task execution:** *"connect, stand up, walk forward, wave, sit down"* — executed as a sequence automatically by the agent
- **Multi-model support:** Tested with Ollama `llama3.2`, `qwen2.5`, and OpenAI `gpt-4o`
- **Two robot platforms:** G1 humanoid (21 motion tools) and Go2 quadruped
- **Three deployment modes:** Claude Desktop (stdio), HTTP SSE, Streamable-HTTP
- **Simulation tested:** Full agent loop verified in DimOS simulation before hardware
- **Extensible:** Adding a new robot requires ~4 files and no changes to the core framework

---

## 10. How to Run the Project

### Full demo — G1 natural language control:

```bash
# Terminal 1: start the MCP server
python run.py g1 --transport streamable-http --port 9991

# Terminal 2: start Ollama
ollama serve
ollama pull llama3.2

# Terminal 3: launch the NL shell
python run_g1_nlp.py

# Then type:
G1> connect
G1> stand up
G1> walk forward 0.5 meters for 3 seconds
G1> wave your right hand then stop
G1> show battery status
G1> sit down and disconnect
```

### Python script control:

```python
from clients import G1Client
import asyncio

async def main():
    async with G1Client() as robot:
        await robot.connect()
        await robot.stand_up()
        await robot.move(vx=0.2, vy=0.0, vyaw=0.0, duration=3.0)
        await robot.stop()
        await robot.wave_hand()
        await robot.damp()

asyncio.run(main())
```

### AI agent (OpenAI):

```python
from clients import HarcMcpClient

with HarcMcpClient(model="gpt-4o") as client:
    client.send_wait("connect, stand up, walk forward 1 meter, then wave and sit down")
```

---

## 11. Future Work

- **Go2 full motion skills** — extend quadruped with `move`, `stand`, `sit`, `flip` tools
- **Perception integration** — add camera/LiDAR MCP tools for vision-based navigation
- **Multi-robot coordination** — connect two MCP servers and orchestrate G1 + Go2 together
- **Voice control** — pipe Whisper STT into `run_g1_nlp.py` for hands-free operation
- **Cloud deployment** — run the MCP server on a remote machine and control over LAN/WAN

---

*HarcOS — Built on Model Context Protocol · Inspired by DimOS · Powered by Ollama & LangGraph*
