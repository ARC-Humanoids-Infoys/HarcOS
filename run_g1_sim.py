"""
run_g1_sim.py
-------------
Launch the Unitree G1 simulation with Ollama (llama3.2) as the LLM agent.

Usage:
    source /home/arc09/.venv/bin/activate
    python run_g1_sim.py
"""

from dimos.agents.mcp.mcp_client import McpClient
from dimos.agents.mcp.mcp_server import McpServer
from dimos.agents.ollama_agent import ollama_installed
from dimos.core.coordination.module_coordinator import ModuleCoordinator
from dimos.agents.skills.navigation import NavigationSkillContainer
from dimos.agents.skills.speak_skill import SpeakSkill
from dimos.core.coordination.blueprints import autoconnect
from dimos.core.global_config import global_config
from dimos.robot.unitree.g1.blueprints.perceptive.unitree_g1_sim import unitree_g1_sim
from dimos.robot.unitree.g1.skill_container import UnitreeG1SkillContainer
from dimos.robot.unitree.g1.system_prompt import G1_SYSTEM_PROMPT

# Enable simulation mode
global_config.update(simulation=True)

# Build the agentic sim blueprint with Ollama
_agentic_skills_ollama = autoconnect(
    McpServer.blueprint(),
    McpClient.blueprint(system_prompt=G1_SYSTEM_PROMPT, model="ollama:llama3.2"),
    NavigationSkillContainer.blueprint(),
    SpeakSkill.blueprint(),
    UnitreeG1SkillContainer.blueprint(),
)

unitree_g1_agentic_sim_ollama = autoconnect(
    unitree_g1_sim,
    _agentic_skills_ollama,
).requirements(ollama_installed)

if __name__ == "__main__":
    print("Starting G1 simulation with Ollama (llama3.2)...")
    coordinator = ModuleCoordinator.build(unitree_g1_agentic_sim_ollama, {})
    coordinator.wait()
