#!/usr/bin/env python3
"""
Strava Agent - Answers questions about your Strava activities.

Uses Claude to understand queries, write code, and execute against SQLite.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

import anthropic

# Paths
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "db" / "activities.db"
CONTEXT_PATH = BASE_DIR / "context" / "system_prompt.md"
REGISTRY_PATH = BASE_DIR / "modules" / "registry.json"
MODULES_DIR = BASE_DIR / "modules"
CONFIG_PATH = BASE_DIR / "config.json"


def load_config():
    """Load configuration."""
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def get_system_prompt():
    """Build the full system prompt with context."""
    with open(CONTEXT_PATH, "r") as f:
        base_prompt = f.read()

    with open(REGISTRY_PATH, "r") as f:
        registry = json.load(f)

    # Add module information
    if registry["modules"]:
        modules_info = "\n\n## Available Reusable Modules\n\n"
        for mod in registry["modules"]:
            modules_info += f"### {mod['name']}\n"
            modules_info += f"File: `modules/{mod['file']}`\n"
            modules_info += f"{mod['description']}\n"
            modules_info += f"Functions: {', '.join(mod['functions'])}\n\n"
        base_prompt += modules_info
    else:
        base_prompt += "\n\n## Available Reusable Modules\n\nNo modules created yet.\n"

    # Add database stats
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("SELECT COUNT(*), MIN(start_date_local), MAX(start_date_local) FROM activities")
        count, min_date, max_date = cursor.fetchone()
        conn.close()

        if count:
            base_prompt += f"\n\n## Database Status\n\n"
            base_prompt += f"- Total activities: {count:,}\n"
            base_prompt += f"- Date range: {min_date[:10] if min_date else 'N/A'} to {max_date[:10] if max_date else 'N/A'}\n"
    except Exception:
        pass

    return base_prompt


# Tool definitions for Claude
TOOLS = [
    {
        "name": "execute_sql",
        "description": "Execute a SQL query against the Strava activities database. Use this for simple queries. Returns results as a list of dictionaries.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The SQL query to execute. Must be a SELECT query.",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "execute_python",
        "description": "Execute a Python script for complex analysis. The script has access to sqlite3, json, datetime, and the database at 'db/activities.db'. Print your results - the output will be captured and returned.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute. Use print() for output.",
                },
                "explanation": {
                    "type": "string",
                    "description": "Brief explanation of what this code does.",
                },
            },
            "required": ["code", "explanation"],
        },
    },
    {
        "name": "create_module",
        "description": "Create a reusable Python module for a query pattern worth saving. This will be committed to the repo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Module name (snake_case, e.g., 'weekly_mileage')",
                },
                "description": {
                    "type": "string",
                    "description": "What this module does",
                },
                "code": {
                    "type": "string",
                    "description": "Python module code with documented functions",
                },
                "functions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of function signatures exposed by this module",
                },
            },
            "required": ["name", "description", "code", "functions"],
        },
    },
    {
        "name": "list_modules",
        "description": "List all available reusable modules and their functions.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


def execute_sql(query: str) -> dict:
    """Execute a SQL query and return results."""
    if not query.strip().upper().startswith("SELECT"):
        return {"error": "Only SELECT queries are allowed"}

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query)
        rows = cursor.fetchall()
        conn.close()

        # Convert to list of dicts
        results = [dict(row) for row in rows]

        # Limit results for display
        if len(results) > 100:
            return {
                "results": results[:100],
                "total_count": len(results),
                "truncated": True,
                "message": f"Showing first 100 of {len(results)} results",
            }

        return {"results": results, "total_count": len(results)}

    except Exception as e:
        return {"error": str(e)}


def execute_python(code: str, explanation: str) -> dict:
    """Execute Python code and capture output."""
    # Create a temp file with the code
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        # Add imports and db path
        wrapper = f'''
import sys
import os
sys.path.insert(0, "{BASE_DIR}")
os.chdir("{BASE_DIR}")

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = "{DB_PATH}"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# User code below
{code}
'''
        f.write(wrapper)
        temp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, temp_path],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(BASE_DIR),
        )

        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]: {result.stderr}"

        return {
            "output": output.strip() if output.strip() else "(no output)",
            "return_code": result.returncode,
        }

    except subprocess.TimeoutExpired:
        return {"error": "Script timed out after 30 seconds"}
    except Exception as e:
        return {"error": str(e)}
    finally:
        os.unlink(temp_path)


def create_module(name: str, description: str, code: str, functions: list[str]) -> dict:
    """Create a new reusable module and prepare it for commit."""
    filename = f"{name}.py"
    filepath = MODULES_DIR / filename

    # Check if module already exists
    if filepath.exists():
        return {"error": f"Module {name} already exists. Use a different name or update manually."}

    try:
        # Write the module file
        with open(filepath, "w") as f:
            f.write(f'"""\n{description}\n"""\n\n')
            f.write(code)

        # Update registry
        with open(REGISTRY_PATH, "r") as f:
            registry = json.load(f)

        registry["modules"].append({
            "name": name,
            "file": filename,
            "description": description,
            "functions": functions,
        })

        with open(REGISTRY_PATH, "w") as f:
            json.dump(registry, f, indent=2)

        # Create a branch and commit
        branch_name = f"module/{name}"
        commit_msg = f"Add {name} module: {description}"

        try:
            # Create branch
            subprocess.run(["git", "checkout", "-b", branch_name], cwd=BASE_DIR, capture_output=True)
            # Add files
            subprocess.run(["git", "add", str(filepath), str(REGISTRY_PATH)], cwd=BASE_DIR, capture_output=True)
            # Commit
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=BASE_DIR, capture_output=True)
            # Create PR
            pr_result = subprocess.run(
                ["gh", "pr", "create", "--title", commit_msg, "--body", f"Auto-generated module.\n\n{description}\n\nFunctions: {', '.join(functions)}"],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
            )
            # Merge PR
            if pr_result.returncode == 0:
                subprocess.run(["gh", "pr", "merge", "--merge", "--delete-branch"], cwd=BASE_DIR, capture_output=True)
            # Return to main
            subprocess.run(["git", "checkout", "main"], cwd=BASE_DIR, capture_output=True)

            return {
                "success": True,
                "message": f"Module '{name}' created and merged via PR",
                "file": filename,
                "functions": functions,
            }
        except Exception as e:
            # If git fails, still report the module was created
            return {
                "success": True,
                "message": f"Module '{name}' created (git/PR failed: {e})",
                "file": filename,
                "functions": functions,
            }

    except Exception as e:
        return {"error": f"Failed to create module: {e}"}


def list_available_modules() -> dict:
    """List all available modules."""
    with open(REGISTRY_PATH, "r") as f:
        registry = json.load(f)

    return {"modules": registry["modules"]}


def handle_tool_call(tool_name: str, tool_input: dict) -> str:
    """Execute a tool and return the result as a string."""
    if tool_name == "execute_sql":
        result = execute_sql(tool_input["query"])
    elif tool_name == "execute_python":
        result = execute_python(tool_input["code"], tool_input.get("explanation", ""))
    elif tool_name == "create_module":
        result = create_module(
            tool_input["name"],
            tool_input["description"],
            tool_input["code"],
            tool_input["functions"],
        )
    elif tool_name == "list_modules":
        result = list_available_modules()
    else:
        result = {"error": f"Unknown tool: {tool_name}"}

    return json.dumps(result, indent=2, default=str)


# Pricing per million tokens (as of 2025)
PRICING = {
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
}


class StravaAgent:
    """Agent that answers questions about Strava activities."""

    def __init__(self):
        config = load_config()
        self.client = anthropic.Anthropic(api_key=config["anthropic"]["api_key"])
        self.model = "claude-sonnet-4-20250514"
        self.conversation_history = []
        self.last_usage = None  # Store usage from last ask()

    def ask(self, question: str, on_update=None) -> str:
        """
        Ask a question about Strava activities.

        Args:
            question: The user's question
            on_update: Optional callback for progress updates (for Slack)

        Returns:
            The agent's answer
        """
        # Add user message to history
        self.conversation_history.append({"role": "user", "content": question})

        system_prompt = get_system_prompt()
        messages = self.conversation_history.copy()

        # Track token usage across all API calls for this question
        total_input_tokens = 0
        total_output_tokens = 0

        while True:
            # Call Claude
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                tools=TOOLS,
                messages=messages,
            )

            # Accumulate token usage
            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

            # Check if we need to handle tool calls
            if response.stop_reason == "tool_use":
                # Process tool calls
                tool_results = []
                assistant_content = response.content

                for block in response.content:
                    if block.type == "tool_use":
                        if on_update:
                            on_update(f"Running {block.name}...")

                        result = handle_tool_call(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })

                # Add assistant response and tool results to messages
                messages.append({"role": "assistant", "content": assistant_content})
                messages.append({"role": "user", "content": tool_results})

            else:
                # Got final response
                final_text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        final_text += block.text

                # Store usage info
                self.last_usage = {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "cost": self._calculate_cost(total_input_tokens, total_output_tokens),
                }

                # Update conversation history with final exchange
                self.conversation_history.append({"role": "assistant", "content": final_text})

                return final_text

    def _calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD based on token usage."""
        pricing = PRICING.get(self.model, {"input": 3.00, "output": 15.00})
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    def get_cost_string(self) -> str | None:
        """Get a formatted cost string for the last query."""
        if not self.last_usage:
            return None
        u = self.last_usage
        return f"${u['cost']:.4f} ({u['input_tokens']:,} in / {u['output_tokens']:,} out)"

    def clear_history(self):
        """Clear conversation history."""
        self.conversation_history = []


def main():
    """Interactive CLI for testing."""
    print("Strava Agent CLI")
    print("Type 'quit' to exit, 'clear' to reset conversation\n")

    agent = StravaAgent()

    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not question:
            continue
        if question.lower() == "quit":
            break
        if question.lower() == "clear":
            agent.clear_history()
            print("Conversation cleared.\n")
            continue

        print("\nThinking...")
        try:
            answer = agent.ask(question, on_update=lambda msg: print(f"  [{msg}]"))
            cost_str = agent.get_cost_string()
            print(f"\nAgent: {answer}")
            if cost_str:
                print(f"  [{cost_str}]\n")
            else:
                print()
        except Exception as e:
            print(f"\nError: {e}\n")
            traceback.print_exc()


if __name__ == "__main__":
    main()
