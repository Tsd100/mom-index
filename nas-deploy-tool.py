#!/usr/bin/env python3
"""
NAS 离线 Docker 部署工具 — 一键生成离线部署包。

用法：复制到任意 Python 项目根目录，执行：
    python nas-deploy-tool.py

会自动：
  1. 检测项目依赖（pyproject.toml / requirements.txt / uv.lock）
  2. 下载所有传递依赖的 Linux wheels（国内镜像加速）
  3. 下载 supercronic + uv 二进制
  4. 生成离线 Dockerfile + docker-compose.yml
  5. 输出到 nas-deploy/ 目录

然后把这个目录传到 NAS，执行：
    docker pull python:3.12-slim-bookworm   # 只需一次
    cd nas-deploy && docker compose up -d --build
"""

import os
import sys
import json
import shutil
import hashlib
import urllib.request
import subprocess
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# 配置（可按需修改）
# ============================================================

PYTHON_VERSION = "3.12"
TARGET_PLATFORM = "x86_64-unknown-linux-gnu"  # amd64 NAS
SUPERCRONIC_VERSION = "v0.2.39"
SUPERCRONIC_SHA1 = "c98bbf82c5f648aaac8708c182cc83046fe48423"
UV_PLATFORM = "x86_64-unknown-linux-gnu"

# 国内镜像（按优先级）
MIRRORS = [
    "https://pypi.tuna.tsinghua.edu.cn/packages",
    "https://mirrors.aliyun.com/pypi/packages",
]

# 对 Python 3.12 不兼容的包（只有 cp313+ wheel）— 可选加速器，缺失不影响
SKIP_INCOMPATIBLE = {"hf-xet", "hf_xet"}

# 平台专用包（自动跳过非 Linux 的）
SKIP_PLATFORM_SPECIFIC = {"pywin32"}


class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def log(msg, color=None):
    prefix = color or ""
    print(f"{prefix}{msg}{Colors.RESET}")


def step(n, total, desc):
    log(f"\n[{n}/{total}] {desc}...", Colors.CYAN + Colors.BOLD)


def run(cmd, capture=True):
    """Run a shell command."""
    result = subprocess.run(cmd, shell=True, capture_output=capture, text=True)
    return result.returncode == 0, result.stdout.strip() if capture else "", result.stderr.strip() if capture else ""


def detect_project(root: Path):
    """Detect project type and dependencies."""
    result = {"type": None, "deps": [], "lock_path": None}

    uv_lock = root / "uv.lock"
    pyroject = root / "pyproject.toml"
    requirements = root / "requirements.txt"

    if uv_lock.exists() and pyroject.exists():
        result["type"] = "uv"
        result["lock_path"] = uv_lock
        # Parse direct deps from pyproject.toml
        import tomllib
        with open(pyroject, "rb") as f:
            data = tomllib.load(f)
        result["deps"] = data.get("project", {}).get("dependencies", [])
    elif requirements.exists():
        result["type"] = "pip"
        result["lock_path"] = requirements
        with open(requirements) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    result["deps"].append(line)

    return result


def download_file(url, dest, max_retries=3):
    """Download a file with retries."""
    for i in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "NAS-Deploy-Tool/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            with open(dest, "wb") as f:
                f.write(data)
            return True, len(data)
        except Exception as e:
            if i == max_retries - 1:
                return False, str(e)
    return False, "unknown"


def download_wheels_from_lock(lock_path: Path, dest: Path):
    """Download all wheels for Linux from a uv.lock file."""
    import tomllib

    with open(lock_path, "rb") as f:
        lock = tomllib.load(f)

    packages = lock.get("package", [])
    log(f"  锁文件中共 {len(packages)} 个包")

    tasks = []
    for pkg in packages:
        name = pkg.get("name", "unknown")

        if name in SKIP_INCOMPATIBLE or name in SKIP_PLATFORM_SPECIFIC:
            continue

        wheels = pkg.get("wheels", [])
        sdist = pkg.get("sdist")

        # Priority: cp312 manylinux x86_64 > any manylinux x86_64 > any.whl > sdist
        chosen = None
        is_wheel = True

        for w in wheels:
            url = w["url"]
            if "manylinux" in url and "x86_64" in url and f"cp{PYTHON_VERSION.split('.')[1]}" in url:
                chosen = w
                break
        if not chosen:
            for w in wheels:
                if "manylinux" in url and "x86_64" in url:
                    chosen = w
                    break
        if not chosen:
            for w in wheels:
                if "-any.whl" in url or "py3-none-any" in url:
                    chosen = w
                    break
        if not chosen and sdist:
            chosen = sdist
            is_wheel = False
        if not chosen and wheels:
            # Last resort — but skip if it's platform-incompatible
            last = wheels[0]
            url_lower = last["url"].lower()
            if "win32" not in url_lower and "win_amd64" not in url_lower and "macosx" not in url_lower:
                chosen = last

        if chosen:
            path_part = chosen["url"].split("/packages/")[-1] if "/packages/" in chosen["url"] else None
            if path_part:
                filename = os.path.basename(chosen["url"])
                filepath = dest / filename
                if not filepath.exists():
                    tasks.append((name, path_part, filename))

    log(f"  需下载 {len(tasks)} 个包")

    def _download(name, path_part, filename):
        for mirror in MIRRORS:
            url = f"{mirror}/{path_part}"
            ok, result = download_file(url, dest / filename)
            if ok:
                return f"OK {name} ({result / 1024:.0f}KB)"
        # Fallback to PyPI
        url = f"https://files.pythonhosted.org/packages/{path_part}"
        ok, result = download_file(url, dest / filename)
        if ok:
            return f"OK {name} ({result / 1024:.0f}KB) [PyPI]"
        return f"FAIL {name}: {result}"

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_download, n, p, f): n for n, p, f in tasks}
        for future in as_completed(futures):
            result = future.result()
            if "FAIL" in result:
                log(f"  {result}", Colors.RED)
            elif int(len(tasks) * 0.1) == 0 or len(tasks) < 20:
                log(f"  {result}")

    return len(tasks)


def download_wheels_from_pip(deps, dest: Path):
    """Download wheels using pip download for non-uv projects."""
    req_file = dest.parent / "_tmp_requirements.txt"
    with open(req_file, "w") as f:
        for dep in deps:
            f.write(f"{dep}\n")

    log("  使用 pip download 下载（可能需要几分钟）...")
    cmd = (
        f'pip download --python-version {PYTHON_VERSION} '
        f'--platform manylinux2014_x86_64 --only-binary :all: '
        f'--dest "{dest}" -r "{req_file}"'
    )
    ok, stdout, stderr = run(cmd)
    req_file.unlink(missing_ok=True)

    if not ok:
        # Fallback: try without --only-binary for packages without wheels
        log("  部分包无 wheel，尝试下载 sdist...", Colors.YELLOW)
        cmd = (
            f'pip download --python-version {PYTHON_VERSION} '
            f'--platform manylinux2014_x86_64 '
            f'--dest "{dest}" -r "{req_file}"'
        )
        ok, stdout, stderr = run(cmd)

    return ok, stderr


def download_supercronic(dest: Path):
    """Download supercronic binary."""
    url = f"https://github.com/aptible/supercronic/releases/download/{SUPERCRONIC_VERSION}/supercronic-linux-amd64"
    filepath = dest / "supercronic-linux-amd64"
    ok, result = download_file(url, filepath)
    if ok:
        # Verify SHA1
        with open(filepath, "rb") as f:
            actual_sha1 = hashlib.sha1(f.read()).hexdigest()
        if actual_sha1 != SUPERCRONIC_SHA1:
            log(f"  SHA1 不匹配！期望 {SUPERCRONIC_SHA1}，实际 {actual_sha1}", Colors.RED)
            filepath.unlink()
            return False
        log(f"  supercronic {SUPERCRONIC_VERSION} ({result / 1024:.0f}KB, SHA1 OK)", Colors.GREEN)
        return True
    log(f"  supercronic 下载失败: {result}", Colors.RED)
    return False


def download_uv(dest: Path):
    """Download uv binary."""
    url = f"https://github.com/astral-sh/uv/releases/latest/download/uv-{UV_PLATFORM}.tar.gz"
    filepath = dest / f"uv-{UV_PLATFORM}.tar.gz"
    ok, result = download_file(url, filepath)
    if ok:
        log(f"  uv ({result / 1024 / 1024:.1f}MB)", Colors.GREEN)
        return True
    log(f"  uv 下载失败: {result}", Colors.RED)
    return False


def generate_dockerfile(project_info: dict, dest: Path):
    """Generate the offline Dockerfile."""
    deps_str = " \\\n    ".join(project_info["deps"])

    dockerfile = f'''FROM python:{PYTHON_VERSION}-slim-bookworm

WORKDIR /app

# ============================================================
# 离线构建 · 由 nas-deploy-tool.py 自动生成
# 构建前确保 NAS 已拉取基础镜像：
#   docker pull python:{PYTHON_VERSION}-slim-bookworm
# ============================================================

# supercronic 定时调度器
COPY offline-deps/supercronic-linux-amd64 /usr/local/bin/supercronic
RUN chmod +x /usr/local/bin/supercronic && supercronic -version

# uv 包管理器
COPY offline-deps/uv-{UV_PLATFORM}.tar.gz /tmp/
RUN tar xzf /tmp/uv-{UV_PLATFORM}.tar.gz -C /usr/local/bin/ --strip-components=1 \\
    && chmod +x /usr/local/bin/uv /usr/local/bin/uvx \\
    && rm /tmp/uv-{UV_PLATFORM}.tar.gz

# 安装依赖（纯离线，无依赖解析）
COPY offline-deps/wheels/ /tmp/wheels/
RUN uv venv /app/.venv && \\
    uv pip install --no-index --find-links /tmp/wheels/ setuptools wheel && \\
    uv pip install --no-index --no-deps /tmp/wheels/*.whl && \\
    for sdist in /tmp/wheels/*.tar.gz; do \\
        uv pip install --no-index --no-build-isolation "$sdist" 2>/dev/null || true; \\
    done && \\
    rm -rf /tmp/wheels

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app:$PYTHONPATH"

# 项目源码
COPY src/ ./src/
COPY pyproject.toml ./

# 入口
COPY docker/entrypoint.sh /entrypoint.sh
RUN sed -i 's/\\r$//' /entrypoint.sh && chmod +x /entrypoint.sh \\
    && mkdir -p /app/config /app/output

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/entrypoint.sh"]
'''
    with open(dest / "docker" / "Dockerfile", "w", encoding="utf-8") as f:
        f.write(dockerfile)


def generate_docker_compose(project_name: str, dest: Path, web_port: int = 8080):
    """Generate docker-compose.yml."""
    compose = f'''services:
  {project_name}:
    build:
      context: .
      dockerfile: docker/Dockerfile
    container_name: {project_name}
    restart: unless-stopped

    ports:
      - "{web_port}:{web_port}"

    volumes:
      - ./config:/app/config:ro
      - ./output:/app/output

    env_file:
      - .env

    environment:
      - TZ=Asia/Shanghai
      - WEBSERVER_PORT={web_port}
'''
    with open(dest / "docker-compose.yml", "w", encoding="utf-8") as f:
        f.write(compose)


def main():
    root = Path.cwd()
    project_name = root.name.lower().replace(" ", "-")

    log(f"\n{'='*60}", Colors.CYAN)
    log(f"  NAS 离线 Docker 部署工具", Colors.CYAN + Colors.BOLD)
    log(f"  项目: {root}", Colors.CYAN)
    log(f"{'='*60}", Colors.CYAN)

    # Step 1: Detect project
    step(1, 5, "检测项目依赖")
    info = detect_project(root)
    if not info["type"]:
        log("  未找到 pyproject.toml / requirements.txt，无法继续", Colors.RED)
        sys.exit(1)
    log(f"  类型: {info['type']}, 直接依赖: {len(info['deps'])} 个")

    # Step 2: Create directory structure
    step(2, 5, "创建 nas-deploy 目录结构")
    nas_dir = root / f"{project_name}-nas-deploy"
    offline_dir = nas_dir / "offline-deps"
    wheels_dir = offline_dir / "wheels"
    docker_dir = nas_dir / "docker"

    for d in [nas_dir, offline_dir, wheels_dir, docker_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # Step 3: Download Python wheels
    step(3, 5, "下载 Python 依赖")
    if info["type"] == "uv" and info["lock_path"]:
        count = download_wheels_from_lock(info["lock_path"], wheels_dir)
    else:
        ok, err = download_wheels_from_pip(info["deps"], wheels_dir)
        count = len(list(wheels_dir.glob("*")))

    # Also ensure setuptools + wheel are present (needed for building sdists)
    run(f'pip download --python-version {PYTHON_VERSION} --platform manylinux2014_x86_64 '
        f'--only-binary :all: --dest "{wheels_dir}" setuptools wheel')

    wheel_count = len(list(wheels_dir.glob("*.whl")))
    sdist_count = len(list(wheels_dir.glob("*.tar.gz")))
    log(f"  下载完成: {wheel_count} 个 wheel + {sdist_count} 个 sdist", Colors.GREEN)

    # Step 4: Download system dependencies
    step(4, 5, "下载系统依赖（supercronic + uv）")
    ok_super = download_supercronic(offline_dir)
    ok_uv = download_uv(offline_dir)
    if not ok_super or not ok_uv:
        log("部分系统依赖下载失败，请检查网络", Colors.RED)

    # Step 5: Generate config files
    step(5, 5, "生成 Docker 配置文件")
    generate_dockerfile(info, nas_dir)

    # Copy source code
    src_dir = nas_dir / "src"
    src_dir.mkdir(exist_ok=True)
    # Try to copy the main package
    for candidate in [root / "src", root / project_name, root / "app"]:
        if candidate.is_dir():
            shutil.copytree(candidate, src_dir, dirs_exist_ok=True)
            log(f"  已复制源码: {candidate.name}")

    # Copy pyproject.toml
    if (root / "pyproject.toml").exists():
        shutil.copy2(root / "pyproject.toml", nas_dir / "pyproject.toml")

    generate_docker_compose(project_name, nas_dir)

    # Create .dockerignore
    ignore_content = ".git\n__pycache__\n*.pyc\n.gitignore\noutput/\n"
    with open(nas_dir / ".dockerignore", "w") as f:
        f.write(ignore_content)

    # Create .env template if not exists
    env_path = nas_dir / ".env"
    if not env_path.exists():
        env_path.write_text("# 在此填写你的环境变量\n")

    # Summary
    total_size = sum(f.stat().st_size for f in nas_dir.rglob("*") if f.is_file())
    log(f"\n{'='*60}", Colors.CYAN)
    log(f"  完成！部署包位置: {nas_dir}", Colors.GREEN + Colors.BOLD)
    log(f"  总大小: {total_size / 1024 / 1024:.0f} MB", Colors.GREEN)
    log(f"", Colors.GREEN)
    log(f"  NAS 部署步骤:", Colors.CYAN)
    log(f"  1. 将 nas-deploy/ 复制到 NAS", Colors.CYAN)
    log(f"  2. docker pull python:{PYTHON_VERSION}-slim-bookworm", Colors.CYAN)
    log(f"  3. cd nas-deploy && docker compose up -d --build", Colors.CYAN)
    log(f"{'='*60}\n", Colors.CYAN)


if __name__ == "__main__":
    main()
