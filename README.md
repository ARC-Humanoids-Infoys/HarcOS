# HarcOS — Humanoid Robot Control System

A modular, hardware-agnostic control framework for humanoid robots using the Model Context Protocol (MCP). HarcOS provides a unified interface to manage multiple robot platforms (Unitree Go2, Unitree G1, and more) through standardized skills and CLI commands.

## Project Architecture

HarcOS is built on clean separation of concerns:

```
HarcOS/
├── mcp_server.py           ← Shared FastMCP server factory
├── registry.py             ← Robot name → blueprint mapping
├── run.py                  ← CLI entry point
├── robots/
│   ├── base.py             ← RobotController abstract base class
│   ├── go2/
│   │   ├── controller.py   ← Go2 hardware integration layer
│   │   ├── skills.py       ← MCP tool registrations for Go2
│   │   └── blueprint.py    ← Go2 factory function
│   └── g1/
│       ├── controller.py   ← G1 hardware integration (SDK2 DDS)
│       ├── skills.py       ← MCP tool registrations for G1
│       └── blueprint.py    ← G1 factory function
└── requirements.txt
```

## Core Design Principles

**1. Shared MCP Infrastructure**
   - `mcp_server.py` centralizes FastMCP instance creation
   - All robot blueprints reuse the same server factory
   - Single source of truth prevents duplication

**2. Per-Robot Composition**
   - `robots/<robot>/blueprint.py` assembles controller + skills + MCP server
   - Returns (mcp, controller) tuple ready for execution
   - Enables easy robot swapping

**3. Per-Robot Skill Registration**
   - `robots/<robot>/skills.py` registers MCP @tool decorators
   - Each robot type has independent skill definitions
   - Extensible design for custom capabilities

**4. Minimal Core Skills**
   - `connect` / `disconnect` — establish/close robot connection
   - `get_battery` — battery status
   - `move` / `stop` — motion control
   - Robot-specific skills (Go2: sport commands; G1: stand_up/stand_down)

## Usage

### Go2 Robot

```bash
# Default connection (stdio mode for Claude Desktop)
python run.py go2

# Connect to specific IP address
python run.py go2 --ip 192.168.123.161

# HTTP server mode (port 9990)
python run.py go2 --transport sse --port 9990
```

### G1 Robot

```bash
# Default connection — DDS network interface is auto-detected
python run.py g1

# Override interface if auto-detection picks the wrong one
python run.py g1 --interface enp0s31f6

# HTTP server mode (port 9991)
python run.py g1 --transport sse --port 9991
```

> **Note:** The G1 communicates over DDS (not WebRTC like Go2). It requires a
> physical Ethernet interface connected to the robot's network. DDS is initialized
> with `ChannelFactoryInitialize(0, <interface>)` — this is process-global and
> cannot be re-initialized within the same process.

### MCP Inspector (Debugging & Testing)

Use the [MCP Inspector](https://github.com/modelcontextprotocol/inspector) to interactively explore and test all available tools:

```bash
# Inspect Go2 robot tools
npx @modelcontextprotocol/inspector python3 run.py go2

# Inspect G1 robot tools
npx @modelcontextprotocol/inspector python3 run.py g1
```

This launches a browser-based UI where you can browse all registered MCP tools, call them manually, and inspect inputs/outputs — useful for development and hardware debugging.

## Environment Variables

**Go2:**
- `ROBOT_IP` — Go2 IP address (defaults to 192.168.123.161)

**G1:**
- `G1_ROBOT_IP` — G1 identifier/IP (optional, not used by DDS transport)
- `G1_NETWORK_INTERFACE` — Network interface for DDS communication. **Auto-detected** if not set (tries `eth0` → `enp0s31f6` → `enp0s25` → `eno1` → first non-loopback). Override only if auto-detection picks the wrong interface.

## G1 Technical Notes

### DDS Transport vs WebRTC
| | Go2 | G1 |
|---|---|---|
| Transport | WebRTC (`unitree_webrtc_connect_leshy`) | DDS / CycloneDDS (`unitree_sdk2py`) |
| Addressing | IP address | Network interface name |
| Motion client | `SportClient` | `LocoClient` + `MotionSwitcherClient` |

### IDL Schema: `unitree_hg` vs `unitree_go`
Go2 uses the `unitree_go` IDL; G1 uses the **`unitree_hg` (humanoid)** IDL. These
are **structurally different**. The key consequence:

| Field | `unitree_go.LowState_` (Go2) | `unitree_hg.LowState_` (G1) |
|---|---|---|
| `bms_state` | ✅ Present | ❌ Not present |
| `power_v` / `power_a` | ✅ Present | ❌ Not present |
| `motor_state[i].vol` | ✅ Present | ✅ Present |
| `imu_state` | ✅ Present | ✅ Present |

### `get_battery` on G1
Because `unitree_hg.LowState_` has no BMS/power fields, `get_battery()` on G1
returns the **motor supply voltage** as a proxy and a **placeholder SOC** of 85%.
Full battery SOC would require subscribing to a separate BMS DDS topic (not yet
implemented). The `voltage_v` field (~51V) is real and reflects the power bus voltage.

---

## Adding a New Robot

HarcOS is designed for extensibility. To add H1, H2, or any other robot platform:

### 1. Create `robots/h1/controller.py`

```python
from robots.base import RobotController

class H1Controller(RobotController):
    def __init__(self, **kwargs):
        # Initialize your hardware connection
        pass
    
    def connect(self) -> str:
        # Establish connection to robot — return a human-readable status string
        return "Connected to H1"
    
    def disconnect(self):
        # Close connection gracefully
        pass
    
    def move(self, vx: float, vy: float, omega: float) -> dict:
        # Execute motion command
        pass
    
    def stop(self) -> dict:
        # Stop all motion
        return {"status": "stopped"}
    
    def get_battery(self) -> dict | str:
        # Return battery status dict, or error string on failure
        return {"soc_percent": 100, "voltage_v": 51.0, "current_a": 0.0}
    
    def get_pose(self) -> dict:
        # Return current pose/position
        return {"x": 0, "y": 0, "theta": 0}
```

### 2. Create `robots/h1/skills.py`

```python
from fastmcp import FastMCP
from robots.base import RobotController

def register(mcp: FastMCP, controller: RobotController):
    @mcp.tool()
    def connect() -> str:
        """Connect to H1 robot."""
        result = controller.connect()
        return f"Connected: {result}"
    
    @mcp.tool()
    def get_battery() -> str:
        """Get H1 battery status."""
        result = controller.get_battery()
        return f"Battery: {result['battery']}%"
    
    # Add more skills as needed
```

### 3. Create `robots/h1/blueprint.py`

```python
from robots.h1.controller import H1Controller
from robots.h1.skills import register
from mcp_server import create_server

def build_h1():
    """Factory function to assemble H1 robot with MCP server."""
    mcp = create_server("h1")
    controller = H1Controller()
    register(mcp, controller)
    return mcp, controller
```

### 4. Update `registry.py`

```python
from robots.h1.blueprint import build_h1

BLUEPRINTS = {
    "go2": build_go2,
    "g1": build_g1,
    "h1": build_h1,  # Add this line
}
```

**Done!** Now `python run.py h1` will work immediately.

## Design Philosophy

- **Minimal Core**: Only essential hardware abstraction
- **Modular Skills**: Each robot independently registers capabilities
- **Clean Interfaces**: `RobotController` base class enforces consistency
- **Extensible**: Add new robots without modifying existing code
- **MCP-First**: All skills exposed as standardized MCP tools for AI agents
# HarcOS
