def __getattr__(name):
    if name == "RobotClientConfig":
        from clients.base import RobotClientConfig
        return RobotClientConfig
    if name == "RobotClient":
        from clients.base import RobotClient
        return RobotClient
    if name == "G1Client":
        from clients.g1 import G1Client
        return G1Client
    if name == "Go2Client":
        from clients.go2 import Go2Client
        return Go2Client
    if name == "HarcMcpClient":
        from clients.mcp_client import HarcMcpClient
        return HarcMcpClient
    raise AttributeError(f"module 'clients' has no attribute {name!r}")

__all__ = ["RobotClientConfig", "RobotClient", "G1Client", "Go2Client", "HarcMcpClient"]
