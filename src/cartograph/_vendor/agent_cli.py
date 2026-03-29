"""
Agent CLI - a declarative CLI framework for LLM/agent-driven tools.

Design principles:
  - All output is JSON (structured, parseable by agents)
  - No interactive prompts (agents can't answer y/n)
  - Grouped help text (readable by humans and agents)
  - Commands are plain functions that receive parsed args
  - Declarative: define commands as dicts, get argparse wiring for free

Usage:

    from agent_cli import AgentCLI, out, err

    def cmd_greet(args):
        return {"message": f"hello {args.name}"}

    cli = AgentCLI(
        prog="mytool",
        description="My agent-friendly tool",
        version="1.0.0",
    )
    cli.add_commands("Basics", [
        {
            "name": "greet",
            "help": "Say hello",
            "handler": cmd_greet,
            "args": [
                {"name": "name", "help": "Who to greet"},
            ],
        },
    ])
    cli.run()
"""

import argparse
import json
import sys


def out(result: dict) -> None:
    """Write a JSON result to stdout."""
    sys.stdout.write(json.dumps(result, indent=2) + "\n")


def err(result: dict, code: int = 1) -> None:
    """Write a JSON error to stdout and exit."""
    out(result)
    sys.exit(code)


def ok(message: str = "success", **extra) -> dict:
    """Build a success result dict."""
    return {"status": "ok", "message": message, **extra}


def fail(message: str, **extra) -> dict:
    """Build an error result dict."""
    return {"status": "error", "message": message, **extra}


class AgentCLI:
    """Declarative CLI builder that produces agent-friendly JSON output."""

    def __init__(self, prog: str, description: str = "", version: str = ""):
        self.prog = prog
        self.description = description
        self.version = version
        self._groups: list[tuple[str, list[dict]]] = []

    def add_commands(self, group_name: str, commands: list[dict]) -> None:
        """Register a group of commands.

        Each command dict has:
            name:     str           - subcommand name (use "parent child" for nested)
            help:     str           - one-line description
            handler:  callable      - function(args) -> dict or None
            args:     list[dict]    - argument specs (see _add_arg)
        """
        self._groups.append((group_name, commands))

    def build_parser(self) -> argparse.ArgumentParser:
        """Build the argparse parser from declared command groups."""
        parser = argparse.ArgumentParser(
            prog=self.prog,
            description=self.description,
            usage=argparse.SUPPRESS,
            add_help=False,
        )
        parser.add_argument("-h", "--help", action="store_true", default=False)
        if self.version:
            parser.add_argument(
                "-v", "--version", action="version",
                version=f"{self.prog} {self.version}",
            )

        sub = parser.add_subparsers(dest="command", metavar="<command>")
        self._nested_parsers = {}

        for _group_name, commands in self._groups:
            for cmd in commands:
                name = cmd["name"]
                parts = name.split()
                handler = cmd.get("handler")

                if len(parts) == 2:
                    parent, child = parts
                    if parent not in self._nested_parsers:
                        parent_parser = sub.add_parser(parent, help=f"{parent} operations")
                        parent_sub = parent_parser.add_subparsers(dest=f"{parent}_command")
                        self._nested_parsers[parent] = (parent_parser, parent_sub)
                    _, parent_sub = self._nested_parsers[parent]
                    p = parent_sub.add_parser(child, help=cmd.get("help", ""))
                else:
                    p = sub.add_parser(name, help=cmd.get("help", ""))

                for arg_spec in cmd.get("args", []):
                    self._add_arg(p, arg_spec)

                if handler:
                    p.set_defaults(func=handler)

        for parent, (parent_parser, _) in self._nested_parsers.items():
            parent_parser.set_defaults(func=lambda args, pp=parent_parser: pp.print_help())

        return parser

    def grouped_help(self) -> str:
        """Render grouped help text with optional color."""
        use_color = sys.stdout.isatty()
        if use_color:
            g, r = "\033[32m", "\033[0m"
        else:
            g, r = "", ""

        lines = ["", f"usage: {self.prog} <command> [options]", ""]
        for group_name, commands in self._groups:
            lines.append(f"  {group_name}:")
            for cmd in commands:
                name = cmd["name"]
                desc = cmd.get("help", "")
                lines.append(f"    {g}{name:<16s}{r} {desc}")
            lines.append("")
        lines.append(f"  Run '{g}{self.prog} <command> -h{r}' for command-specific help.")
        lines.append("")
        return "\n".join(lines)

    def run(self, argv: list[str] = None) -> None:
        """Parse args and dispatch to the handler.

        If the handler returns a dict, it is printed as JSON.
        Handlers can also call out()/err() directly for more control.
        """
        parser = self.build_parser()
        args = parser.parse_args(argv)

        if args.help or not args.command:
            sys.stdout.write(self.grouped_help())
            sys.exit(0)

        handler = getattr(args, "func", None)
        if not handler:
            sys.stdout.write(self.grouped_help())
            sys.exit(0)

        result = handler(args)
        if isinstance(result, dict):
            out(result)

    @staticmethod
    def _add_arg(parser: argparse.ArgumentParser, spec: dict) -> None:
        """Add an argument to a parser from a spec dict.

        Spec keys:
            name:       str   - positional arg name or --flag name
            help:       str   - help text
            required:   bool  - for optional args
            default:    any   - default value
            type:       type  - int, float, str, etc.
            choices:    list  - valid values
            action:     str   - "store_true", "store_false", etc.
            nargs:      str   - "?", "*", "+", etc.
            dest:       str   - attribute name on the parsed args
        """
        name = spec["name"]
        kwargs = {}
        for key in ("help", "required", "default", "type", "choices", "action", "nargs", "dest"):
            if key in spec:
                kwargs[key] = spec[key]

        if name.startswith("-"):
            parser.add_argument(name, **kwargs)
        else:
            kwargs.pop("required", None)
            parser.add_argument(name, **kwargs)
