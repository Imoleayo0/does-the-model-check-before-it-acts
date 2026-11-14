"""Run an Inspect eval against DeepSeek via the vault surrogate.

The DeepSeek API key lives in the Secure Vault. This script fetches the
surrogate (hsurr:...) from authd — NOT the real key — and passes it as
OPENAI_API_KEY with OPENAI_BASE_URL pointed at DeepSeek. The egress proxy
swaps the surrogate for the real key in transit.

Also fixes the httpx proxy-env parsing issue: the default NO_PROXY contains
IPv6 bracketed addresses ([::1]) that httpx cannot parse, so we override it
with a simple localhost-only value.

Usage:
  python run_deepseek_eval.py <task_file> <model> [--limit N] [--epochs N]
    [--two-turn true|false] [--log-dir DIR] [extra inspect args...]

Example:
  python run_deepseek_eval.py task_v2.py deepseek-chat --limit 4
"""
import os
import subprocess
import sys

sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    task_file = sys.argv[1]
    model = sys.argv[2]
    rest = sys.argv[3:]

    entry = dynamic_credential_entry("custom.deepseek")
    surrogate = entry["surrogate"]
    assert surrogate.startswith("hsurr:"), "expected a surrogate, not a raw key"

    env = dict(os.environ)
    env["OPENAI_API_KEY"] = surrogate
    env["OPENAI_BASE_URL"] = "https://api.deepseek.com/v1"
    # httpx cannot parse the default NO_PROXY (contains [::1]); use simple value
    env["NO_PROXY"] = "localhost,127.0.0.1"
    env["no_proxy"] = "localhost,127.0.0.1"

    # Inspect OpenAI provider: model name is "openai/<deepseek model>"
    cmd = [
        sys.executable, "-m", "inspect_ai", "eval",
        task_file,
        "--model", f"openai/{model}",
        "-M", "responses_api=false",
    ] + rest
    print("running:", " ".join(cmd))
    proc = subprocess.run(cmd, env=env)
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
