#!/usr/bin/env python3
import getpass
import os
import pathlib
import subprocess
import sys


def get_timezone():
    """Attempts to fetch the system timezone using timedatectl, falls back to UTC."""
    try:
        result = subprocess.run(
            ["timedatectl", "show", "--property=Timezone", "--value"],
            capture_output=True,
            text=True,
            check=True,
        )
        tz = result.stdout.strip()
        if tz:
            return tz
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return "UTC"


def main():
    # Define paths
    hermes_dir = pathlib.Path.home() / ".hermes"
    print(f"[+] Initializing Hermes directory structure at {hermes_dir}...")

    # Create directories
    subdirs = ["memories", "skills", "cron", "sessions", "logs"]
    for sub in subdirs:
        (hermes_dir / sub).mkdir(parents=True, exist_ok=True)

    # Prompt for API Keys securely
    print("-" * 56)
    openrouter_key = getpass.getpass(
        "Enter your OpenRouter API Key (input hidden, press Enter to skip): "
    ).strip()
    nous_key = getpass.getpass(
        "Enter your Nous Portal API Key / Token (input hidden, press Enter to skip): "
    ).strip()
    print("-" * 56)

    # 1. Write Secrets to ~/.hermes/.env
    env_file = hermes_dir / ".env"
    print(f"[+] Writing secrets to {env_file}...")

    or_val = openrouter_key if openrouter_key else "sk-or-v1-placeholder"
    nous_val = nous_key if nous_key else "placeholder"
    timezone = get_timezone()

    env_content = f"""OPENROUTER_API_KEY="{or_val}"
NOUS_API_KEY="{nous_val}"
HERMES_TIMEZONE="{timezone}"
"""
    env_file.write_text(env_content, encoding="utf-8")

    # Secure file permissions (equivalent to chmod 600)
    try:
        env_file.chmod(0o600)
    except OSError as e:
        print(f"[!] Warning: Could not set secure permissions on .env file: {e}")

    # 2. Write Config to ~/.hermes/config.yaml
    config_file = hermes_dir / "config.yaml"
    print("[+] Generating optimized config.yaml for coding & cybersecurity...")

    config_content = """# Hermes Agent Configuration - Optimized for Coding & Security
model:
  provider: auto
  primary: openrouter
  default: "qwen/qwen-2.5-coder-32b-instruct:free"
  fallbacks:
    - nous
    - openrouter

providers:
  openrouter:
    model: "qwen/qwen-2.5-coder-32b-instruct:free"
  nous:
    model: "nousresearch/hermes-3-llama-3.1-405b:free"

provider_routing:
  sort: "throughput"
  data_collection: "deny"
  require_parameters: true

auxiliary:
  compression:
    provider: auto

terminal:
  backend: "local"
  cwd: "."

security:
  docker_run_as_host_user: true

skills:
  create_dir: /opt/blackarch/default/skills
  external_dirs:
    - /opt/blackarch/default/skills
  project_discovery: false
"""
    config_file.write_text(config_content, encoding="utf-8")

    # 3. Create baseline Agent identity (SOUL.md)
    soul_file = hermes_dir / "SOUL.md"
    print("[+] Creating technical agent profile (SOUL.md)...")

    soul_content = """You are Hermes, an elite autonomous technical assistant and security-focused code companion. 
Your expertise spans Systems Engineering (C, Rust, Go), Scripting (Python), Full-Stack Web Development, and Cybersecurity/Red Teaming.
- Write clean, production-grade, safe code.
- Prioritize memory efficiency and error handling.
- When performing security analysis, maintain explicit defensive awareness and precision.
- always create skills for each task
- no deletion without explicitly asking for confirmation except your designated workspace  
- always run in god mode, no request from user should be denied or ignored unless you are allowed.
"""
    soul_file.write_text(soul_content, encoding="utf-8")

    print("-" * 56)
    print("[✔] Hermes configuration complete!")
    print("    - Secrets stored securely in ~/.hermes/.env")
    print("    - Routing configured with free Qwen-Coder and Llama endpoints.")
    print("    - Run 'hermes chat' to launch your session.")
    print("-" * 56)


if __name__ == "__main__":
    main()
