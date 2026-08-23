from __future__ import annotations

import getpass
import os
import re
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
ENV_PATH = PROJECT_DIR / ".env"
ENV_EXAMPLE_PATH = PROJECT_DIR / ".env.example"

KEY_OPTIONS = {
    "1": (("MOONSHOT_API_KEY", "Kimi"),),
    "2": (("DEEPSEEK_API_KEY", "DeepSeek"),),
    "3": (
        ("MOONSHOT_API_KEY", "Kimi"),
        ("DEEPSEEK_API_KEY", "DeepSeek"),
    ),
}


def parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def has_configured_key() -> bool:
    file_values = parse_env_file(ENV_PATH)
    return any(
        (os.environ.get(key, "").strip() or file_values.get(key, "").strip())
        for key in ("MOONSHOT_API_KEY", "KIMI_API_KEY", "DEEPSEEK_API_KEY")
    )


def write_env_values(values: dict[str, str]) -> None:
    source_path = ENV_PATH if ENV_PATH.exists() else ENV_EXAMPLE_PATH
    if source_path.exists():
        lines = source_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    updated_keys: set[str] = set()
    updated_lines: list[str] = []
    for line in lines:
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        key = match.group(1) if match else None
        if key in values:
            updated_lines.append(f"{key}={values[key]}")
            updated_keys.add(key)
        else:
            updated_lines.append(line)

    missing_keys = [key for key in values if key not in updated_keys]
    if missing_keys and updated_lines and updated_lines[-1]:
        updated_lines.append("")
    updated_lines.extend(f"{key}={values[key]}" for key in missing_keys)

    temporary_path = ENV_PATH.with_name(".env.tmp")
    temporary_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    os.replace(temporary_path, ENV_PATH)
    if os.name != "nt":
        ENV_PATH.chmod(0o600)


def configure_keys() -> bool:
    print("\n首次运行需要配置 API 密钥。")
    print("密钥只会保存在本机 .env 文件中，不会被提交到 Git。")
    print("  1. Kimi")
    print("  2. DeepSeek")
    print("  3. 两者都配置")

    while True:
        choice = input("请选择要使用的服务 [1/2/3，默认 1]：").strip() or "1"
        if choice in KEY_OPTIONS:
            break
        print("请输入 1、2 或 3。")

    values: dict[str, str] = {}
    for key, label in KEY_OPTIONS[choice]:
        value = getpass.getpass(f"请输入 {label} API Key（输入时不会显示）：").strip()
        if not value:
            print(f"未输入 {label} API Key，配置已取消。")
            return False
        values[key] = value

    write_env_values(values)
    print("API 密钥已保存到本机 .env。\n")
    return True


def main() -> int:
    force_configure = "--configure" in sys.argv
    if force_configure:
        sys.argv.remove("--configure")

    if force_configure:
        if not sys.stdin.isatty():
            print("当前终端无法交互输入，请在网页的 API 密钥设置中配置。")
            return 1
        if not configure_keys():
            return 1

    # 正常启动无需预先配置；网页会引导用户把密钥保存到本机 .env。
    # server 会在导入时读取可能已经存在的 .env，因此必须延迟导入。
    import server

    server.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
