"""
run_g1_nlp.py
-------------
Interactive natural-language shell for the Unitree G1 humanoid robot.

Uses HarcMcpClient (LangChain/LangGraph ReAct agent) to translate natural
language into robot actions via the MCP server.  Supports both Ollama and
OpenAI as the LLM backend.

Prerequisites
-------------
1. Start the G1 MCP server in a separate terminal::

       python run.py g1 --transport streamable-http --port 9991

2a. For Ollama (default)::

       ollama serve
       ollama pull llama3.2      # or qwen2.5, mistral-nemo, etc.

2b. For OpenAI::

       export OPENAI_API_KEY=sk-...

Usage
-----
::

    # Ollama llama3.2 (default)
    python run_g1_nlp.py

    # Different Ollama model
    python run_g1_nlp.py --model ollama:qwen2.5

    # OpenAI GPT-4o
    python run_g1_nlp.py --model gpt-4o

    # Different server port
    python run_g1_nlp.py --server http://localhost:9991

Example commands
----------------
::

    G1> connect
    G1> stand up
    G1> walk forward 0.5 meters for 3 seconds
    G1> wave your right hand
    G1> clap twice
    G1> sit down and disconnect
"""

import argparse
import sys
import time

from clients.mcp_client import HarcMcpClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_g1_nlp.py",
        description="HarcOS G1 — natural language command shell",
    )
    parser.add_argument(
        "--model",
        default="ollama:llama3.2",
        metavar="MODEL",
        help=(
            'LangChain model string (default: "ollama:llama3.2"). '
            'Ollama: "ollama:qwen2.5", "ollama:mistral". '
            'OpenAI: "gpt-4o", "gpt-4o-mini" (needs OPENAI_API_KEY).'
        ),
    )
    parser.add_argument(
        "--server",
        default="http://localhost:9991",
        metavar="URL",
        help="MCP server base URL (default: http://localhost:9991)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        metavar="SECS",
        help="Seconds to wait for MCP server to become ready (default: 60)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress tool-call / tool-result trace output",
    )
    parser.add_argument(
        "--cmd",
        metavar="COMMAND",
        default=None,
        help="Run a single command and exit (non-interactive mode)",
    )
    return parser.parse_args()


def _banner(model: str, server: str) -> None:
    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║          HarcOS G1 Natural Language Shell            ║")
    print("╚══════════════════════════════════════════════════════╝")
    print(f"  Server : {server}")
    print(f"  Model  : {model}")
    print()
    print("  Type a command in plain English, or 'quit' to exit.")
    print("  Examples:")
    print("    connect")
    print("    stand up")
    print("    walk forward 0.5 meters for 3 seconds")
    print("    wave your right hand then stop")
    print("    show battery status")
    print()


def main() -> None:
    args = parse_args()

    print(f"[HarcOS] Connecting to MCP server at {args.server} …")
    print(f"[HarcOS] Loading model: {args.model}")

    try:
        client = HarcMcpClient(
            server_url=args.server,
            model=args.model,
            tool_fetch_timeout=args.timeout,
            verbose=not args.quiet,
        )
        client.start()
    except RuntimeError as exc:
        print(f"\n[HarcOS] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"\n[HarcOS] Failed to initialise agent: {exc}", file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Single-command (non-interactive) mode
    # ------------------------------------------------------------------
    if args.cmd:
        try:
            client.send_wait(args.cmd)
        finally:
            client.stop()
        return

    # ------------------------------------------------------------------
    # Interactive REPL
    # ------------------------------------------------------------------
    _banner(args.model, args.server)

    try:
        while True:
            try:
                text = input("G1> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not text:
                continue
            if text.lower() in ("quit", "exit", "q", ":q"):
                break
            if text.lower() in ("clear", "reset"):
                client.clear_history()
                print("[HarcOS] Conversation history cleared.")
                continue
            if text.lower() in ("help", "?"):
                print(
                    "Commands: any natural language instruction, or:\n"
                    "  clear / reset — wipe conversation history\n"
                    "  quit / exit   — exit the shell\n"
                )
                continue

            try:
                # send_wait blocks until the agent finishes processing
                client.send_wait(text)
            except KeyboardInterrupt:
                print("\n[HarcOS] Interrupted — use 'quit' to exit.")
            except Exception as exc:
                print(f"[HarcOS] Agent error: {exc}", file=sys.stderr)

    finally:
        print("[HarcOS] Shutting down agent …")
        client.stop()
        print("[HarcOS] Done.")


if __name__ == "__main__":
    main()
