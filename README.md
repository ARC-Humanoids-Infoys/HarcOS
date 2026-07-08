# HarcOS — Humanoid Robot Control System

A modular control framework for Unitree robots built on the [Model Context Protocol](https://modelcontextprotocol.io). Each robot's capabilities are exposed as MCP tools, accessible to AI agents (Ollama / OpenAI via LangChain) or any Python script.

---

## Project Structure

```
HarcOS/
├── run.py                  ← Start the MCP server
├── run_g1_nlp.py           ← Interactive natural-language shell (G1)
├── registry.py             ← Robot name → blueprint mapping
├── mcp_server.py           ← FastMCP server factory
├── robots/
│   ├── base.py             ← RobotController abstract base
│   ├── rubojudo_adapter.py ← RoboJuDo policy pipeline integration
│   ├── go2/                ← Go2 controller, skills, blueprint
│   └── g1/                 ← G1 controller, skills, blueprint
└── clients/
    ├── base.py             ← RobotClient (MCP + Ollama agent, async)
    ├── g1.py / go2.py      ← Typed client wrappers
    └── mcp_client.py       ← HarcMcpClient (LangGraph ReAct agent)
```

---

## Installation

```bash
pip install -r requirements.txt

# Ollama (local, free)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2    # good tool-calling, fast
ollama pull qwen2.5     # better multi-step tool-calling

# OpenAI (optional)
pip install langchain-openai
export OPENAI_API_KEY=sk-...
```

---

## Starting the MCP Server

**Always start the server first**, then connect a client.

```bash
# stdio — Claude Desktop / MCP Inspector (direct mode)
python run.py g1
python run.py go2 --ip 192.168.123.161

# SSE — Inspector (server-running mode) / async clients
python run.py g1  --transport sse --port 9991

# Streamable-HTTP — HarcMcpClient / NLP shell (recommended)
python run.py g1  --transport streamable-http --port 9991
python run.py go2 --transport streamable-http --port 9990
```

**Verify the server is up:**
```bash
ss -tlnp | grep 9991   # shows LISTEN when running
```

**Endpoints:**
- Streamable-HTTP: `http://localhost:9991/mcp` (POST only — not for browsers)
- SSE: `http://localhost:9991/sse`

---

## Natural-Language Shell

```bash
# Terminal 1
python run.py g1 --transport streamable-http --port 9991

# Terminal 2
ollama serve

# Terminal 3
python run_g1_nlp.py
```

```
G1> connect
G1> stand up and wave
G1> walk forward 0.5 meters for 3 seconds
G1> show battery status
G1> what robojudo configs are available?
G1> start robojudo with g1 config
G1> quit
```

**Flags:**
```bash
python run_g1_nlp.py --model ollama:qwen2.5          # better tool-calling
python run_g1_nlp.py --model gpt-4o                  # OpenAI
python run_g1_nlp.py --quiet                          # hide tool traces
python run_g1_nlp.py --cmd "stand up and wave"        # single command
```

---

## HarcMcpClient (Python API)

```python
from clients import HarcMcpClient

with HarcMcpClient(server_url="http://localhost:9991", model="ollama:llama3.2") as client:
    client.send("stand up and wave")               # non-blocking
    client.send_wait("walk forward 1 meter")       # blocks until done
    client.clear_history()                         # fresh conversation
```

**Supported models:**

| Model | Backend | Notes |
|---|---|---|
| `"ollama:llama3.2"` | Ollama | Fast, good tool-calling |
| `"ollama:qwen2.5"` | Ollama | Better multi-step tool-calling |
| `"gpt-4o"` | OpenAI | Most reliable, needs API key |
| `ChatOllama(...)` | Ollama | Direct instance, full config |

> Avoid models smaller than 7B for reliable tool use.

---

## MCP Inspector

```bash
./inspector.sh g1     # recommended — clears stale port locks automatically
./inspector.sh go2
```

Manual Inspector settings:
- **Streamable-HTTP** → Transport: `Streamable HTTP`, URL: `http://localhost:9991/mcp`
- **SSE** → Transport: `SSE`, URL: `http://localhost:9991/sse`

> If you see `PORT IS IN USE`: `lsof -ti:6277 -ti:6274 | xargs kill -9`

---

## Web Client (Browser UI)

A built-in browser interface for inspecting tools and running the NLP agent without the command line.

### Quick start

```bash
# Terminal 1 — MCP server
python run.py g1 --transport streamable-http --port 9991

# Terminal 2 — Web UI
python web_client.py --host 127.0.0.1 --port 8088 --default-mcp http://localhost:9991
```

Then open **http://127.0.0.1:8088/** in any browser.

### Switching robots

```bash
# G1 (default port 9991)
python run.py g1 --transport streamable-http --port 9991
python web_client.py --default-mcp http://localhost:9991

# Go2 (default port 9990)
python run.py go2 --transport streamable-http --port 9990
python web_client.py --default-mcp http://localhost:9990
```

Use the **G1 / Go2** chips in the sidebar to switch robots and auto-update the server URL.

### Inspector tab

| Feature | Description |
|---|---|
| Tool list | All MCP tools discovered from the server |
| Form | Auto-generated typed input fields from the tool's JSON schema |
| JSON | Raw JSON arguments editor |
| Schema | Full input schema viewer with copy button |
| Response | Syntax-highlighted JSON result after running a tool |

### Agent tab

Type natural-language commands directly — the agent uses Ollama (or OpenAI) to decide which tools to call.

```
connect and stand up
walk forward 0.5 meters then stop
show battery status
wave your right hand
```

Select the model in the Agent tab before sending:
- `llama3.2` — fast, good tool-calling (default)
- `qwen2.5` — better multi-step reasoning
- `gpt-4o` — most reliable (requires `OPENAI_API_KEY`)

### CLI options

```bash
python web_client.py --help

Options:
  --host HOST           Bind host (default: 127.0.0.1)
  --port PORT           Bind port (default: 8088)
  --default-mcp URL     Default MCP server URL shown in the UI
```

---

## RoboJuDo Integration

[RoboJuDo](https://github.com/HansZ8/RoboJuDo) is a plug-and-play RL policy deployment framework for Unitree robots. HarcOS exposes it as MCP tools so the AI agent can launch and control policies directly.

### Install (one-time)

```bash
git clone https://github.com/HansZ8/RoboJuDo.git ~/RoboJuDo
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU build
cd ~/RoboJuDo && pip install -e .

# Verify
python -c "import robojudo; print(robojudo.__version__)"   # → 1.5.0
```

### RoboJuDo MCP tools

| Tool | Description |
|---|---|
| `list_policies()` | List all available policies |
| `start_policy(config)` | Start a policy (`g1_harcos`, `g1_harcos_real`, `g1_beyondmimic`, …) |
| `stop_policy()` | Stop the running policy |
| `policy_status()` | Check if a policy is running and which one |
| `walk(forward, sideways, turn)` | Walk via the active policy |
| `policy_command(command)` | High-level command (`emergency_stop`, `start_motion`, …) |

**Common configs:** `g1_harcos` (sim), `g1_harcos_real` (real robot), `g1_harcos_mimic`, `g1_beyondmimic`, `g1_asap`

---

## Python Client (async, direct)

```python
from clients import G1Client
import asyncio

async def main():
    async with G1Client() as robot:          # stdio (spawns run.py automatically)
        await robot.connect()
        await robot.stand_up()
        await robot.move(0.2, 0.0, 0.0, duration=3.0)
        await robot.execute_arm_command("high_wave")
        await robot.damp()

asyncio.run(main())
```

```python
# HTTP transport (server must be running)
async with G1Client(transport="http", server_url="http://localhost:9991") as robot:
    await robot.agent_send("stand up and wave")   # LLM picks the tools
```

**CLI:**
```bash
python -m clients.g1 --agent "connect and stand up"
python -m clients.g1 --transport http --agent "wave your hand"
```

---

## Skills Reference

### G1 (humanoid)

> **Network:** Ethernet to `192.168.123.161` (WebRTC port 8081).
> Set laptop IP: `sudo ip addr add 192.168.123.100/24 dev enp2s0`
> `192.168.123.164` is the Jetson SSH board — motion commands do **not** run there.

| Tool | Description |
|---|---|
| `connect` / `disconnect` | WebRTC connect; activates AI mode automatically |
| `get_battery` | Voltage, charge %, current |
| `get_imu` | Roll, pitch, yaw (rad) + acceleration (m/s²) |
| `stand_up` / `stand_down` | Posture transitions |
| `balance_stand` | Stable balanced posture |
| `move(vx, vy, vyaw, duration)` | Velocity command |
| `stop` | Stop all movement immediately |
| `damp` | Motors into compliant / low-power mode |
| `wave_hand` / `shake_hand` / `clap` / `high_five` / `hug` / `hands_up` | Arm gestures |
| `execute_arm_command(name)` | Named gesture (e.g. `high_wave`, `x_ray`, `arm_heart`) |
| `execute_mode_command(name)` | Named FSM mode (e.g. `walk`, `run`, `sit`, `damp`) |
| `start_policy` / `stop_policy` / `policy_status` / `list_policies` | RoboJuDo management |
| `walk(forward, sideways, turn)` | Walk via RL policy |
| `policy_command(name)` | High-level policy command (emergency_stop, start_motion, …) |

### Go2 (quadruped)

| Tool | Description |
|---|---|
| `connect` / `disconnect` | WebRTC connect |
| `get_battery` | Charge %, voltage, current, cycle count |

---

## Environment Variables

| Variable | Description |
|---|---|
| `G1_ROBOT_IP` | G1 controller IP (default: `192.168.123.161`) |
| `ROBOT_IP` | Fallback IP for any robot |
| `OPENAI_API_KEY` | Required for `model="gpt-4o"` |

---

## Architecture

### System overview

```
User / AI Agent  (natural language)
        │
        ▼
run_g1_nlp.py  ──  LangGraph ReAct Agent
        │
        ▼
MCP Server  (run.py g1 --transport streamable-http)
        │
        ▼
G1 Skills  (robots/g1/skills.py)  ←── 25 MCP tools
        │
        ├─── Direct WebRTC path ──────────────────────────────────┐
        │    stand_up, wave, move, get_battery, get_imu …         │
        │    G1Controller → WebRTC → 192.168.123.161              │
        │                                                          ▼
        └─── RoboJuDo path ──────────────────────────────────► G1 Robot
             start_policy / stop_policy / walk / policy_command   (real or sim)
             RoboJuDoAdapter → HarcOSCtrl (velocity queue)
                             → RlPipeline (50 Hz)
                             → RL Policy (BeyondMimic / ASAP / …)
```

### Two control paths

| | Direct WebRTC | RoboJuDo |
|---|---|---|
| **Controls** | Gestures, posture, raw velocity | RL locomotion policies |
| **Rate** | On demand | 50 Hz continuous |
| **Best for** | wave, clap, stand up, battery, IMU | walking, running, expressive motion |
| **Config** | none | `g1_harcos` / `g1_harcos_real` |

### File map

```
HarcOS/
├── run.py                      ← MCP server entry point
├── run_g1_nlp.py               ← NLP shell (LangGraph agent)
├── robots/
│   ├── rubojudo_adapter.py     ← bridge between HarcOS and RoboJuDo
│   └── g1/
│       └── skills.py           ← 25 MCP tools (6 are RoboJuDo tools)
│
~/RoboJuDo/
├── robojudo/
│   ├── controller/
│   │   └── harcos_ctrl.py      ← velocity-queue controller (HarcOS-driven)
│   ├── config/g1/
│   │   └── g1_cfg.py           ← g1_harcos / g1_harcos_real / g1_harcos_mimic
│   └── pipeline/
│       └── rl_pipeline.py      ← runs policy at 50 Hz
```

### RoboJuDo MCP tools

| Tool | Description |
|---|---|
| `start_policy(config)` | Launch a locomotion or motion policy in a background thread |
| `stop_policy()` | Shut it down |
| `policy_status()` | Check if a policy is running and which one |
| `list_policies()` | List all available configs |
| `walk(forward, sideways, turn)` | Send velocity into the running policy in real time |
| `policy_command(command)` | Send a high-level command (`emergency_stop`, `start_motion`, …) |

---

## Testing

### No robot needed — test with the MCP Inspector

You can test and verify every tool **without a physical G1 connected**. The server starts fine; tools that need the robot will return a clear error, and RoboJuDo sim tools work fully offline.

**Step 1 — Start the MCP server**
```bash
conda activate go2_agent
cd ~/HarcOS
python run.py g1 --transport streamable-http --port 9991
```
Wait for:
```
INFO:     Uvicorn running on http://0.0.0.0:9991
```

**Step 2 — Open the Inspector**
```bash
# new terminal
./inspector.sh g1
```
In the Inspector UI set:
- Transport: `Streamable HTTP`
- URL: `http://localhost:9991/mcp`

Click **Connect**, then open the **Tools** tab. You will see all 25 tools.

---

### Test checklist (no robot)

**Basic server health**
```bash
ss -tlnp | grep 9991   # must show LISTEN
```

**Tool discovery — confirm all 25 tools load**

In the Inspector, click **Tools** and verify you see:
```
connect, disconnect, get_battery, stand_up, stand_down, move, stop,
balance_stand, damp, wave_hand, shake_hand, clap, high_five, hug,
hands_up, cancel_action, execute_arm_command, execute_mode_command,
get_imu, start_policy, stop_policy, policy_status,
list_policies, walk, policy_command
```

**RoboJuDo — list configs (no robot needed)**

In Inspector, call `list_policies` with no arguments.
Expected result:
```
Available configs: g1, g1_asap, g1_beyondmimic, g1_harcos,
g1_harcos_mimic, g1_harcos_real, g1_real, …
```

**RoboJuDo — start sim pipeline (no robot needed)**

Call `start_policy` with `config_name = "g1_harcos"`.
This starts a MuJoCo simulation — no physical robot required.
Expected result:
```
RoboJuDo pipeline 'g1_harcos' started (dt=0.02s).
```

Then call `policy_status`.
Expected:
```
robojudo_available: True, pipeline_running: True, current_config: g1_harcos
```

**RoboJuDo — send velocity into sim**

Call `walk` with `forward_speed=0.3, sideways_speed=0.0, turn_speed=0.0`.
Expected:
```
Velocity set: vx=0.3, vy=0.0, vyaw=0.0
```

Call `walk` with `forward_speed=0.0, sideways_speed=0.0, turn_speed=0.0` to stop.

**RoboJuDo — stop pipeline**

Call `stop_policy`.
Expected:
```
RoboJuDo pipeline 'g1_harcos' stopped.
```

**Robot tools — expected failure without hardware**

Call `connect`. Expected (no robot connected):
```
Connection timeout to G1 at 192.168.123.161. Check: Ethernet cable connected …
```
This is the correct behaviour — the tool reached the hardware layer.

---

### Test with NLP shell (no robot needed)

```bash
# Terminal 1 — server
python run.py g1 --transport streamable-http --port 9991

# Terminal 2 — Ollama
ollama serve

# Terminal 3 — NLP shell
python run_g1_nlp.py
```

```
G1> what locomotion policies are available?
G1> start the walking policy in sim
G1> check policy status
G1> walk forward at 0.3 meters per second
G1> stop moving
G1> stop the policy
G1> quit
```

---

### Test with real robot

Once physically connected (Ethernet to `192.168.123.161`, IP set on your interface):

```
G1> connect
G1> get battery status
G1> stand up
G1> start the walking policy for real robot
G1> walk forward at 0.2 meters per second
G1> stop moving
G1> stop the policy
G1> sit down
G1> disconnect
```

> **Safety:** Always have someone near the emergency stop. Call `damp` or send
> `policy_command("emergency_stop")` to cut power to all motors immediately.

---

## Adding a New Robot

1. `robots/<name>/controller.py` — subclass `RobotController`
2. `robots/<name>/skills.py` — implement `register(mcp, controller)`
3. `robots/<name>/blueprint.py` — implement `build_<name>()`
4. `registry.py` — add `BLUEPRINTS["<name>"] = build_<name>`
5. _(Optional)_ `clients/<name>.py` — typed `RobotClient` subclass

`python run.py <name>` works immediately after step 4.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `curl` returns empty | Server not running | Start with `python run.py g1 --transport streamable-http --port 9991` |
| `406 Not Acceptable` on `GET /mcp` | Browser / wrong transport | Use Inspector in Streamable HTTP mode, not a browser |
| `Missing session ID` | Raw curl without MCP handshake | This is normal — use Inspector or Python client |
| Motion commands silently ignored | G1 not in AI mode | Call `connect()` — it switches mode automatically |
| `PORT IS IN USE at port 6277` | Stale Inspector lock | `lsof -ti:6277 -ti:6274 \| xargs kill -9` |
