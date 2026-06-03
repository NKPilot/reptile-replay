#!/usr/bin/env python3
"""
视频下载脚本 —— 基于 yt-dlp 自动批量下载爬宠公开视频。

用法:
    # 从 URL 列表文件下载
    python download_videos.py --urls urls.txt

    # 下载单个视频
    python download_videos.py --url "https://www.youtube.com/watch?v=xxxx"

    # 指定输出目录
    python download_videos.py --urls urls.txt --outdir data/raw

    # 限制分辨率
    python download_videos.py --urls urls.txt --max-height 720

    # 从本机浏览器读取 cookies（推荐，需先在浏览器登录 YouTube）
    python download_videos.py --urls urls.txt --cookies-from-browser chrome

    # WSL 环境：指定 Windows 侧 Chrome 配置目录路径
    python download_videos.py --urls urls.txt \\
        --cookies-from-browser chrome \\
        --browser-profile "/mnt/c/Users/xxx/.../Google/Chrome/User Data/Default"

    # 使用 Edge 浏览器 cookies（WSL 中 Windows Edge 可访问）
    python download_videos.py --urls urls.txt \\
        --cookies-from-browser edge \\
        --browser-profile "/mnt/c/Users/xxx/.../Microsoft/Edge/User Data/Default"

    # 使用已登录 YouTube 账号导出的 cookies 文件
    python download_videos.py --urls urls.txt --cookies cookies.txt

    # 使用 Android client 绕过 bot 检测（通常不可靠）
    python download_videos.py --urls urls.txt --client android

    # 使用代理
    python download_videos.py --urls urls.txt --proxy socks5://127.0.0.1:1080

输出:
    data/raw/{video_id}/
        {video_id}.mp4          # 视频文件
        {video_id}.info.json    # yt-dlp 元数据
        {video_id}.jpg          # 缩略图
    data/downloads/download_log.csv  # 下载记录

常见问题:
    1. "Sign in to confirm you're not a bot"
       → 最可靠方案：导出 cookies 文件
         a) Chrome 安装扩展 "Get cookies.txt LOCALLY"
         b) 访问 YouTube，点扩展图标 → Export
         c) 保存到项目根目录 cookies.txt
         d) 运行: python download_videos.py --urls urls.txt
       → 或：先关闭 Windows Chrome，再运行
         python download_videos.py --urls urls.txt \\
           --cookies-from-browser chrome \\
           --browser-profile "/mnt/c/Users/xxx/.../Chrome/User Data/Default"

    2. "no such table: meta"
       → 更新 yt-dlp: uv pip install -U yt-dlp
       → 或使用 nightly: uv pip install \\
           "yt-dlp @ https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/latest/download/yt-dlp.tar.gz"

    3. "Permission denied" 读取浏览器 cookies
       → Chrome/Edge 运行时锁定 cookies 数据库
       → 关闭浏览器后再运行，或导出 cookies.txt

    4. 下载速度慢
       → 使用 --proxy socks5://127.0.0.1:1080
"""

import argparse
import csv
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTDIR = PROJECT_ROOT / "data" / "raw"
DOWNLOAD_ARCHIVE = PROJECT_ROOT / "data" / "downloads" / "downloaded.txt"
DOWNLOAD_LOG = PROJECT_ROOT / "data" / "downloads" / "download_log.csv"

# 常见 bot 检测错误特征
BOT_DETECTION_PATTERNS = [
    r"Sign in to confirm you.{0,20}re not a bot",
    r"confirm you.{0,20}re not a bot",
    r"bot.*detected",
    r"HTTP Error 429",
    r"rate.?limit",
]

# 在 WSL 中可检测的 Windows 浏览器配置
_WSL_WINDOWS_CHROME_PATHS = [
    "/mnt/c/Users/{user}/AppData/Local/Google/Chrome/User Data",
    "/mnt/c/Users/{user}/AppData/Local/Google/Chrome SxS/User Data",
]
_WSL_WINDOWS_EDGE_PATHS = [
    "/mnt/c/Users/{user}/AppData/Local/Microsoft/Edge/User Data",
]


def is_wsl() -> bool:
    """检测是否在 WSL 中运行"""
    return "microsoft" in platform.release().lower() or "wsl" in platform.release().lower()


def get_wsl_windows_user() -> Optional[str]:
    """获取 WSL 中映射的 Windows 用户名（优先扫描文件系统）"""
    # 方法1: 扫描 /mnt/c/Users/ 找到有浏览器 cookies 的用户
    users_dir = Path("/mnt/c/Users")
    if users_dir.exists():
        cookie_indicators = [
            "AppData/Local/Google/Chrome/User Data/Default/Network/Cookies",
            "AppData/Local/Google/Chrome/User Data/Default/Cookies",
            "AppData/Local/Microsoft/Edge/User Data/Default/Network/Cookies",
        ]
        for d in sorted(users_dir.iterdir()):
            if d.is_dir() and d.name not in ("Public", "Default", "defaultuser0", "All Users"):
                for indicator in cookie_indicators:
                    cookie_path = d / indicator
                    if cookie_path.exists() and cookie_path.stat().st_size > 0:
                        return d.name

    # 方法2: cmd.exe 询问
    try:
        result = subprocess.run(
            ["cmd.exe", "/c", "echo", "%USERNAME%"],
            capture_output=True, text=True, timeout=5,
        )
        username = result.stdout.strip()
        if username:
            return username
    except Exception:
        pass

    return None


def detect_available_browsers() -> list[tuple[str, str]]:
    """
    检测环境中可用的浏览器（仅返回 cookies 数据库非空的）。
    返回 [(browser_name, profile_path), ...]
    """
    results = []
    wsl = is_wsl()

    # WSL: 检查 Windows 侧浏览器
    if wsl:
        user = get_wsl_windows_user()
        if user:
            # Edge first (Windows 10/11 默认安装，且通常不被锁定)
            for pattern in _WSL_WINDOWS_EDGE_PATHS:
                path = Path(pattern.format(user=user))
                if _cookie_db_nonempty(path / "Default" / "Network" / "Cookies") or \
                   _cookie_db_nonempty(path / "Default" / "Cookies"):
                    results.append(("edge", str(path / "Default")))
                    break

            # Chrome
            for pattern in _WSL_WINDOWS_CHROME_PATHS:
                path = Path(pattern.format(user=user))
                if _cookie_db_nonempty(path / "Default" / "Network" / "Cookies") or \
                   _cookie_db_nonempty(path / "Default" / "Cookies"):
                    results.append(("chrome", str(path / "Default")))
                    break

    # Linux 原生浏览器
    config_home = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    # Chromium (WSL 中最可能安装的 Linux 浏览器)
    for browser_key, config_dir in [
        ("chromium", "chromium"),
        ("chrome", "google-chrome"),
        ("brave", "BraveSoftware/Brave-Browser"),
    ]:
        path = Path(config_home) / config_dir
        if _cookie_db_nonempty(path / "Default" / "Network" / "Cookies") or \
           _cookie_db_nonempty(path / "Default" / "Cookies"):
            results.append((browser_key, str(path / "Default")))

    return results


def _cookie_db_nonempty(db_path: Path) -> bool:
    """检查 cookies 数据库文件是否非空"""
    try:
        return db_path.exists() and db_path.stat().st_size > 0
    except (OSError, PermissionError):
        return False


def _detect_js_runtime(preferred: str = "node") -> Optional[str]:
    """检测可用的 JS 运行时（yt-dlp 需要它来解 n challenge）"""
    runtimes = ["node", "deno", "bun", "quickjs"]
    if preferred != "node":
        runtimes.insert(0, preferred)

    for rt in runtimes:
        if rt == "quickjs":
            exe = "qjs"
        else:
            exe = rt
        if shutil.which(exe):
            return rt
    return None


def _find_cookies_file(root: Path) -> Optional[Path]:
    """在项目根目录下自动查找 cookies 文件"""
    patterns = [
        "cookies.txt",
        "www.youtube.com_cookies.txt",
        "youtube_cookies.txt",
        "*cookies*.txt",
    ]
    for pattern in patterns:
        if "*" in pattern:
            for f in sorted(root.glob(pattern)):
                if f.is_file() and f.stat().st_size > 0:
                    return f
        else:
            candidate = root / pattern
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
    return None


def ensure_dirs():
    DEFAULT_OUTDIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_LOG.parent.mkdir(parents=True, exist_ok=True)
    if not DOWNLOAD_LOG.exists():
        with open(DOWNLOAD_LOG, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "video_id", "url", "title", "duration", "platform",
                "animal_type", "behavior_candidate", "downloaded_at",
                "status", "file_path", "notes"
            ])


def check_yt_dlp() -> Optional[str]:
    """检查 yt-dlp 是否可用，返回版本号"""
    try:
        result = subprocess.run(
            ["yt-dlp", "--version"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def is_bot_detection_error(stderr: str) -> bool:
    """检测是否为 bot 检测导致的失败"""
    for pattern in BOT_DETECTION_PATTERNS:
        if re.search(pattern, stderr, re.IGNORECASE):
            return True
    return False


def is_permission_error(stderr: str) -> bool:
    """检测是否为权限/文件锁错误"""
    return bool(re.search(r"Permission( denied)?|Errno 13", stderr, re.IGNORECASE))


def is_cookie_db_error(stderr: str) -> bool:
    """检测 cookies 数据库读取错误（如 no such table: meta）"""
    return bool(re.search(r"no such table|cannot open database|malformed", stderr, re.IGNORECASE))


def get_auth_help(browser: str = "chrome", is_wsl_env: bool = False) -> str:
    """返回认证帮助信息（带具体可执行的命令）"""
    lines = ["YouTube 要求验证身份。请选择以下任一方案：", ""]

    if is_wsl_env:
        user = get_wsl_windows_user() or "YOUR_USERNAME"
        edge_profile = f"/mnt/c/Users/{user}/AppData/Local/Microsoft/Edge/User Data/Default"
        chrome_profile = f"/mnt/c/Users/{user}/AppData/Local/Google/Chrome/User Data/Default"

        lines.append("  ★ 方案 A（推荐）: 导出 cookies.txt")
        lines.append("    1) 在 Windows 浏览器安装扩展 \"Get cookies.txt LOCALLY\"")
        lines.append("    2) 打开 YouTube（确保已登录），点击扩展 → Export")
        lines.append(f"    3) 保存到: {PROJECT_ROOT}/cookies.txt")
        lines.append("    4) 运行: python scripts/download_videos.py --urls urls.txt")
        lines.append("")
        lines.append("  ★ 方案 B: 关闭浏览器后读取 Windows cookies")
        lines.append("    1) 完全关闭 Windows 浏览器（Chrome/Edge）")
        lines.append("    2) 运行以下命令：")
        if Path(edge_profile).exists():
            lines.append(f"       python scripts/download_videos.py --urls urls.txt \\")
            lines.append(f"         --cookies-from-browser edge \\")
            lines.append(f'         --browser-profile "{edge_profile}"')
        else:
            lines.append(f"       python scripts/download_videos.py --urls urls.txt \\")
            lines.append(f"         --cookies-from-browser chrome \\")
            lines.append(f'         --browser-profile "{chrome_profile}"')
    else:
        lines.append(f"  --cookies-from-browser {browser}")
        lines.append("  或导出 cookies.txt 到项目根目录")
        lines.append("  或 --client android（不可靠）")

    return "\n".join(lines)


def build_yt_dlp_cmd(
    url: str,
    outdir: Path,
    max_height: int = 720,
    cookies: Optional[Path] = None,
    cookies_from_browser: str = "",
    browser_profile: str = "",
    proxy: str = "",
    client: str = "web",
    extra_args: str = "",
    js_runtime: str = "node",
) -> list:
    """构建 yt-dlp 命令"""
    cmd = [
        "yt-dlp",
        "--write-info-json",
        "--write-thumbnail",
        "--restrict-filenames",
        "--download-archive", str(DOWNLOAD_ARCHIVE),
        "-o", str(outdir / "%(id)s" / "%(id)s.%(ext)s"),
        "--no-playlist",
        "--no-overwrites",
        "--retries", "5",
        "--fragment-retries", "5",
        "--limit-rate", "5M",
        "--sleep-requests", "3",
        "--sleep-interval", "5",
        "--max-sleep-interval", "10",
    ]

    # JS 运行时 + EJS challenge solver（解决 n challenge）
    if js_runtime and _detect_js_runtime(js_runtime):
        cmd.extend([
            "--js-runtimes", js_runtime,
            "--remote-components", "ejs:github",
        ])

    # --- 格式选择 ---
    # 使用 yt-dlp 内置的格式选择器，更健壮
    cmd.extend([
        "-f", f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best",
        # 合并为单个文件（mp4 容器兼容性最好）
        "--merge-output-format", "mp4",
    ])

    # --- 认证方式 ---
    if cookies_from_browser:
        if browser_profile:
            # yt-dlp 支持 BROWSER:PROFILE 格式（2026 年新语法）
            # 较新版本用 + 分隔 keyring，但我们传完整路径作为 profile
            cmd.extend(["--cookies-from-browser", f"{cookies_from_browser}:{browser_profile}"])
        else:
            cmd.extend(["--cookies-from-browser", cookies_from_browser])
    else:
        # 自动检测项目根目录下的 cookies 文件
        cookies_file = cookies or _find_cookies_file(PROJECT_ROOT)
        if cookies_file and cookies_file.exists():
            cmd.extend(["--cookies", str(cookies_file)])
        elif cookies:
            raise FileNotFoundError(f"cookies 文件不存在: {cookies}")

    # --- Extractor 参数 ---
    if client == "android":
        cmd.extend([
            "--extractor-args",
            "youtube:player_client=android,android_vr;player_skip=webpage",
        ])
    elif client == "ios":
        cmd.extend([
            "--extractor-args",
            "youtube:player_client=ios;player_skip=webpage",
        ])

    # --- 代理 ---
    if proxy:
        cmd.extend(["--proxy", proxy])

    # --- 用户自定义额外参数 ---
    if extra_args:
        cmd.extend(extra_args.split())

    cmd.append(url)
    return cmd


def download_single(
    url: str,
    outdir: Path,
    max_height: int = 720,
    cookies: Optional[Path] = None,
    cookies_from_browser: str = "",
    browser_profile: str = "",
    proxy: str = "",
    client: str = "web",
    extra_args: str = "",
    js_runtime: str = "node",
) -> dict:
    """下载单个视频，返回结果字典"""
    cmd = build_yt_dlp_cmd(
        url, outdir, max_height, cookies,
        cookies_from_browser, browser_profile, proxy, client, extra_args,
        js_runtime,
    )
    print(f"[下载] {url}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        combined_output = result.stdout + result.stderr

        if result.returncode != 0:
            if "has already been recorded in the archive" in combined_output:
                print(f"  ⏭ 已下载过，跳过")
                return {"status": "skipped", "reason": "already_downloaded"}

            if is_bot_detection_error(combined_output):
                print(f"  ⚠ YouTube bot 检测触发!")
                return {
                    "status": "failed",
                    "error": "bot_detected",
                    "detail": result.stderr[-500:],
                }

            if is_permission_error(combined_output):
                print(f"  ⚠ 浏览器 cookies 读取被拒绝（浏览器可能正在运行）")
                return {
                    "status": "failed",
                    "error": "permission_denied",
                    "detail": result.stderr[-500:],
                }

            if is_cookie_db_error(combined_output):
                print(f"  ⚠ Cookies 数据库格式不兼容（需更新 yt-dlp 或改用 cookies.txt）")
                return {
                    "status": "failed",
                    "error": "cookie_db_error",
                    "detail": result.stderr[-500:],
                }

            error_tail = result.stderr[-300:].strip()
            print(f"  ✗ 下载失败: {error_tail}")
            return {"status": "failed", "error": result.stderr[-500:]}

        return _extract_metadata(outdir)

    except subprocess.TimeoutExpired:
        print(f"  ✗ 下载超时 (>10分钟)")
        return {"status": "failed", "error": "timeout"}


def _extract_metadata(outdir: Path) -> dict:
    """从 info.json 提取元数据"""
    info_files = sorted(
        outdir.glob("*/*.info.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not info_files:
        return {
            "status": "success",
            "video_id": "unknown", "title": "", "duration": 0,
            "platform": "", "file_path": "",
        }

    latest_info = info_files[0]
    with open(latest_info) as f:
        info = json.load(f)

    video_id = info.get("id", "unknown")
    video_dir = latest_info.parent

    video_files = (
        list(video_dir.glob("*.mp4"))
        + list(video_dir.glob("*.mkv"))
        + list(video_dir.glob("*.webm"))
    )
    file_path = str(video_files[0]) if video_files else ""

    return {
        "status": "success",
        "video_id": video_id,
        "title": info.get("title", ""),
        "duration": info.get("duration", 0),
        "platform": info.get("extractor", ""),
        "file_path": file_path,
    }


def download_with_fallback(
    url: str,
    outdir: Path,
    max_height: int = 720,
    cookies: Optional[Path] = None,
    cookies_from_browser: str = "",
    browser_profile: str = "",
    proxy: str = "",
    client: str = "web",
    extra_args: str = "",
    js_runtime: str = "node",
) -> dict:
    """
    带回落策略的下载。
    注意：android/ios client 不支持 cookies，回落时会自动去掉 cookies。
    """
    has_auth = bool(
        cookies_from_browser
        or (cookies and cookies.exists())
        or (not cookies and _find_cookies_file(PROJECT_ROOT) is not None)
    )

    # web client 是首选（支持 cookies）
    if has_auth and client == "web":
        result = download_single(
            url, outdir, max_height, cookies,
            cookies_from_browser, browser_profile, proxy, "web", extra_args,
            js_runtime,
        )
        if result["status"] in ("success", "skipped"):
            return result
        # 非 bot 检测错误（如格式不支持），不回落直接返回
        if result.get("error") != "bot_detected":
            return result
        # Bot 检测：提示但继续用 cookies 重试 web
        print(f"  ↪ 重试...")
        time.sleep(5)
        result = download_single(
            url, outdir, max_height, cookies,
            cookies_from_browser, browser_profile, proxy, "web", extra_args,
            js_runtime,
        )
        if result["status"] in ("success", "skipped"):
            return result
        return result

    # 无认证或指定了 android/ios：直接使用
    actual_client = client
    # 如果指定了 android/ios 但有 cookies，去掉 cookies（不兼容）
    final_cookies = None
    final_browser = ""
    if actual_client in ("android", "ios"):
        final_cookies = None
        final_browser = ""
    else:
        final_cookies = cookies
        final_browser = cookies_from_browser

    return download_single(
        url, outdir, max_height, final_cookies,
        final_browser, browser_profile, proxy, actual_client, extra_args,
        js_runtime,
    )


def log_download(result: dict, url: str, animal_type: str = "", behavior: str = ""):
    """记录下载到 CSV"""
    with open(DOWNLOAD_LOG, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            result.get("video_id", ""),
            url,
            result.get("title", ""),
            result.get("duration", 0),
            result.get("platform", ""),
            animal_type,
            behavior,
            datetime.now().isoformat(),
            result.get("status", "unknown"),
            result.get("file_path", ""),
            result.get("error", "") or result.get("reason", ""),
        ])


def print_env_info():
    """打印环境诊断信息"""
    print("环境诊断:")
    print(f"  WSL: {is_wsl()}")
    if is_wsl():
        user = get_wsl_windows_user()
        print(f"  Windows 用户: {user or '未检测到'}")
    print(f"  yt-dlp: {check_yt_dlp() or '未安装'}")

    browsers = detect_available_browsers()
    if browsers:
        print(f"  可用浏览器: {', '.join(b for b, _ in browsers)}")
    else:
        print(f"  可用浏览器: 无")

    found = _find_cookies_file(PROJECT_ROOT)
    print(f"  cookies 文件: {found.name if found else '未找到'}")

    # 检查是否有数据源
    urls_txt = PROJECT_ROOT / "urls.txt"
    if urls_txt.exists():
        with open(urls_txt) as f:
            urls = [l.strip() for l in f if l.strip() and not l.startswith("#")]
        print(f"  视频 URL: {len(urls)} 个")


def main():
    parser = argparse.ArgumentParser(
        description="爬宠视频批量下载（增强版 yt-dlp 封装）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 查看环境诊断
  python download_videos.py --env

  # 基本使用（需要 cookies.txt 或浏览器 cookies）
  python download_videos.py --urls urls.txt

  # WSL 环境使用 Edge cookies（需先关闭 Edge）
  python download_videos.py --urls urls.txt \\
      --cookies-from-browser edge \\
      --browser-profile "/mnt/c/Users/.../Microsoft/Edge/User Data/Default"

  # 使用 cookies 文件
  python download_videos.py --urls urls.txt --cookies cookies.txt

  # 使用代理
  python download_videos.py --urls urls.txt \\
      --cookies-from-browser chrome --proxy socks5://127.0.0.1:1080
        """,
    )
    parser.add_argument("--urls", type=str, help="URL 列表文件（每行一个 URL）")
    parser.add_argument("--url", type=str, help="下载单个 URL")
    parser.add_argument("--outdir", type=str, default=str(DEFAULT_OUTDIR), help="输出目录")
    parser.add_argument("--max-height", type=int, default=720, help="最大分辨率高度")
    parser.add_argument("--animal", type=str, default="", help="动物类型标注")
    parser.add_argument("--behavior", type=str, default="", help="预期行为标注")
    parser.add_argument("--env", action="store_true", help="打印环境诊断信息")

    # 认证相关
    auth_group = parser.add_argument_group("认证方式")
    auth_group.add_argument("--cookies", type=str, help="Netscape cookies.txt 文件路径")
    auth_group.add_argument(
        "--cookies-from-browser", type=str, default="",
        help="从浏览器读取 cookies（chrome/chromium/firefox/edge/brave/opera）",
    )
    auth_group.add_argument(
        "--browser-profile", type=str, default="",
        help="浏览器配置目录的完整路径（WSL 中指向 Windows 浏览器的 cookies 路径）",
    )
    auth_group.add_argument(
        "--client", type=str, default="web",
        choices=["web", "android", "ios"],
        help="YouTube 客户端类型（默认: web）",
    )

    # 其他
    parser.add_argument("--proxy", type=str, default="", help="代理地址")
    parser.add_argument("--extra-args", type=str, default="", help="传递给 yt-dlp 的额外参数")
    parser.add_argument("--js-runtime", type=str, default="", help="JS 运行时用于解 n challenge（node/deno/bun，默认自动检测）")
    parser.add_argument("--update", action="store_true", help="更新 yt-dlp 到最新版本")
    args = parser.parse_args()

    # 环境诊断
    if args.env:
        print_env_info()
        if not args.url and not args.urls:
            return

    # 更新 yt-dlp
    if args.update:
        print("正在更新 yt-dlp 到最新 nightly 版本...")
        subprocess.run(
            ["uv", "pip", "install", "-U",
             "yt-dlp @ https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/latest/download/yt-dlp.tar.gz"],
            check=False,
        )
        version = check_yt_dlp()
        print(f"yt-dlp 版本: {version}")
        if not args.url and not args.urls:
            return

    version = check_yt_dlp()
    if not version:
        print("错误: yt-dlp 未安装。请运行: uv pip install yt-dlp")
        sys.exit(1)
    print(f"yt-dlp 版本: {version}")

    ensure_dirs()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    cookies = Path(args.cookies) if args.cookies else None

    # 收集 URL 列表
    urls = []
    if args.url:
        urls = [args.url]
    elif args.urls:
        urls_path = Path(args.urls)
        if not urls_path.exists():
            print(f"错误: URL 文件不存在: {args.urls}")
            sys.exit(1)
        with open(urls_path) as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    else:
        print("请指定 --url 或 --urls，或用 --env 查看环境诊断")
        sys.exit(1)

    # 检查认证状态
    has_cookies_file = bool(
        (cookies and cookies.exists())
        or (not cookies and _find_cookies_file(PROJECT_ROOT) is not None)
    )
    has_browser_auth = bool(args.cookies_from_browser)
    has_auth = has_cookies_file or has_browser_auth
    is_wsl_env = is_wsl()

    # 无认证时的智能处理
    if not has_auth:
        if not has_browser_auth and args.client == "web":
            print("=" * 60)
            print("  ⚠  未配置认证方式！YouTube 要求验证身份。")
            print("=" * 60)
            print()
            print(get_auth_help("edge" if is_wsl_env else "chrome", is_wsl_env))
            print()
            print("尝试无认证方式下载（通常不会成功）...")
            print()

    # JS 运行时检测
    js_runtime = args.js_runtime if args.js_runtime else (_detect_js_runtime() or "")
    if js_runtime:
        print(f"JS 运行时: {js_runtime}")
    elif not args.js_runtime:
        print("⚠ 未检测到 JS 运行时（node/deno），n challenge 可能失败")

    print(f"\n共 {len(urls)} 个视频待下载")
    print(f"输出目录: {outdir}")

    stats = {"success": 0, "skipped": 0, "failed": 0}
    fail_reasons: dict[str, int] = {}
    start_time = time.time()

    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}] ", end="")
        try:
            result = download_with_fallback(
                url, outdir, args.max_height, cookies,
                args.cookies_from_browser, args.browser_profile,
                args.proxy, args.client, args.extra_args,
                js_runtime,
            )
        except FileNotFoundError as exc:
            print(f"错误: {exc}")
            sys.exit(1)

        log_download(result, url, args.animal, args.behavior)

        if result["status"] == "success":
            stats["success"] += 1
            title = result.get("title", "")[:60]
            duration = result.get("duration", 0)
            print(f"  ✓ {title} ({duration}s)")
        elif result["status"] == "skipped":
            stats["skipped"] += 1
        else:
            stats["failed"] += 1
            reason = result.get("error", "unknown")
            fail_reasons[reason] = fail_reasons.get(reason, 0) + 1

        if i < len(urls):
            time.sleep(3)

    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"  下载完成 ({elapsed:.0f}s)")
    print(f"{'='*60}")
    print(f"成功: {stats['success']}  跳过: {stats['skipped']}  失败: {stats['failed']}")
    print(f"日志: {DOWNLOAD_LOG}")

    # 针对失败原因给出建议
    if stats["failed"] > 0:
        print(f"\n失败原因分布:")
        for reason, count in fail_reasons.items():
            print(f"  - {reason}: {count} 个")

        if "bot_detected" in fail_reasons:
            print(f"\n{'='*60}")
            print(f"  解决方案")
            print(f"{'='*60}")
            print(get_auth_help("edge" if is_wsl_env else "chrome", is_wsl_env))

        if "permission_denied" in fail_reasons:
            print(f"\n  提示: 浏览器正在运行导致 cookies 被锁定")
            print(f"  请关闭浏览器后再试，或使用浏览器扩展导出 cookies.txt")

        if "cookie_db_error" in fail_reasons:
            print(f"\n  提示: yt-dlp 版本与浏览器 cookies 格式不兼容")
            print(f"  请更新 yt-dlp: uv pip install -U yt-dlp")
            print(f"  或使用 cookies.txt 文件替代")


if __name__ == "__main__":
    main()
