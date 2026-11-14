"""材料体检：进 S3 之前先判「这些 raw 能不能读、要不要转」。

只读，不改文件。识别五类：
  1) 空文件（多半是下载失败）        —— 必须重取或换源
  2) 文本但非 UTF-8                 —— 先转码，不许按乱码读
  3) 二进制（PDF/Office/图片/音视频/压缩包）—— 需提取文本层，按格式给路线
  4) 未知后缀                       —— 先识别格式，再决定
  5) 超大文本（>8MB）               —— 切片/抽样，产物里声明抽样范围

用法：
  python material_audit.py <root> [--json] [--strict]
   python material_audit.py --selftest
"""
import json, os, sys, tempfile, pathlib

TEXT_SUFFIX = {
    ".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".csv", ".tsv", ".html", ".htm",
    ".xml", ".py", ".js", ".ts", ".mjs", ".cjs", ".go", ".rs", ".java", ".kt", ".c",
    ".h", ".cpp", ".sh", ".ps1", ".bat", ".toml", ".ini", ".cfg", ".log", ".sql",
    ".css", ".rst", ".tex", ".lock", ".gitignore",
}
BINARY_ROUTE = {
    ".pdf": "先取文本层（pdftotext / PyMuPDF）；无文本层按扫描件走 OCR，并标注 OCR 误差",
    ".docx": "解压取 word/document.xml；有修订要同时读 w:ins / w:del，别只读终稿",
    ".doc": "旧二进制格式，先转 docx 或 LibreOffice 提取，转完核对段落数",
    ".xlsx": "逐 sheet 读单元格与公式值（openpyxl）；注意合并单元格、隐藏列、多表关系",
    ".xls": "旧格式先转 xlsx；转换后抽查 3 个单元格与合计行",
    ".pptx": "逐页取文本框与备注；图上的字要另做 OCR",
    ".png": "OCR / 视觉读图；图表要读数轴、单位、图例，不许只写趋势",
    ".jpg": "OCR / 视觉读图；照片类只写可见事实，不推断动机",
    ".jpeg": "OCR / 视觉读图；照片类只写可见事实，不推断动机",
    ".gif": "抽首帧与关键帧再 OCR；动图不看全容易误读",
    ".bmp": "OCR / 视觉读图",
    ".webp": "OCR / 视觉读图",
    ".zip": "先列目录，再按内部类型逐项处理；不许整包当一份材料",
    ".tar": "先列目录，再按内部类型逐项处理",
    ".gz": "先确认真实格式（可能是 .tar.gz），再列目录",
    ".7z": "先列目录，再按内部类型逐项处理",
    ".mp3": "转写为逐字稿，保留时间戳；关键结论回听原片段",
    ".wav": "转写为逐字稿，保留时间戳",
    ".m4a": "转写为逐字稿，保留时间戳",
    ".mp4": "抽关键帧 + 转写；画面上的字另外 OCR",
    ".mov": "抽关键帧 + 转写；画面上的字另外 OCR",
    ".mkv": "抽关键帧 + 转写；画面上的字另外 OCR",
    ".ipynb": "按 cell 读，源码与输出分开；只信重跑过的输出",
    ".ttf": "字体文件，不读内容，只登记名称与用途",
    ".otf": "字体文件，不读内容，只登记名称与用途",
    ".woff": "字体文件，不读内容，只登记名称与用途",
    ".woff2": "字体文件，不读内容，只登记名称与用途",
    ".ico": "图标文件，不读内容；要判断含义时转 PNG 后视觉读图",
    ".bin": "不做内容蒸馏，只登记哈希、大小与来源",
    ".exe": "不做内容蒸馏，只登记哈希、大小与来源",
    ".dll": "不做内容蒸馏，只登记哈希、大小与来源",
    ".so": "不做内容蒸馏，只登记哈希、大小与来源",
}
MAX_TEXT = 8 * 1024 * 1024
SKIP_DIRS = {".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv", ".idea"}
DOTFILES = {".gitignore", ".gitattributes", ".editorconfig", ".npmrc", ".nvmrc",
            ".prettierrc", ".env", ".dockerignore", ".claude", ".foreign"}


def kind_of(p, data):
    suffix = p.suffix.lower()
    if p.stat().st_size == 0:
        return "empty"
    if suffix in BINARY_ROUTE:
        return "binary"
    if suffix in TEXT_SUFFIX or p.name.lower() in DOTFILES:
        return "large" if len(data) > MAX_TEXT else "text"
    if not suffix:
        return "large" if len(data) > MAX_TEXT else "text"
    if b"\x00" in data[:4096]:
        return "binary-unknown"
    # 后缀不认识、但内容是合法 UTF-8 的（.pem/.key/.env.example/各种配置与源码方言），
    # 按文本处理；「未知」只留给既不是文本、也没有 NUL 的可疑文件。
    if len(data) <= MAX_TEXT and looks_utf8(data):
        return "text"
    return "unknown"


def looks_utf8(data):
    try:
        data.decode("utf-8", errors="strict")
        return True
    except UnicodeDecodeError:
        return False


def scan_file(p):
    data = p.read_bytes()
    kind = kind_of(p, data)
    if kind == "empty":
        return kind, "空文件（0 字节）：多半是下载失败或占位，必须重取或换源"
    if kind == "binary":
        return kind, BINARY_ROUTE[p.suffix.lower()]
    if kind == "large":
        return kind, "文本超过 8MB：切片读或抽样，产物里声明抽样范围与未读部分"
    if kind == "binary-unknown":
        return kind, "未知二进制：先识别真实格式（file/魔数），再决定提取路线"
    if kind == "unknown":
        return kind, "未知后缀：先识别格式；识别不出就登记为不可读，不许猜内容"
    if not looks_utf8(data):
        return "encoding", "文本但非 UTF-8：先转 GB18030/UTF-8 再读，禁止按乱码摘句"
    return "ok", ""


def containers(root):
    out = sorted(p for p in root.rglob("distill-*")
                 if p.is_dir() and not any(part in ("raw", "notes") for part in p.parts))
    return out or [root]


def audit(root):
    rows, agg = [], {}
    for c in containers(root):
        raw = c / "raw"
        if not raw.exists():
            continue
        problems, files = [], 0
        for p in sorted(raw.rglob("*")):
            if not p.is_file() or p.name == ".gitkeep":
                continue
            if any(part in SKIP_DIRS for part in p.relative_to(raw).parts[:-1]):
                continue
            files += 1
            kind, detail = scan_file(p)
            if kind != "ok":
                problems.append({"path": p.relative_to(c).as_posix(), "kind": kind, "detail": detail})
                agg[kind] = agg.get(kind, 0) + 1
        rows.append({"container": c.name, "files": files, "problems": problems})
    return {"containers": rows, "by_kind": agg,
            "summary": {"containers": len(rows), "files": sum(r["files"] for r in rows),
                        "problems": sum(len(r["problems"]) for r in rows)}}


def selftest():
    fails = 0
    with tempfile.TemporaryDirectory() as td:
        c = pathlib.Path(td) / "distill-x"
        raw = c / "raw"
        raw.mkdir(parents=True)
        (raw / "ok.md").write_text("# hi", encoding="utf-8")
        (raw / "gbk.txt").write_bytes("中文".encode("gb18030"))
        (raw / "empty.md").write_bytes(b"")
        (raw / "doc.pdf").write_bytes(b"%PDF-1.4")
        (raw / "blob.bin").write_bytes(b"\x00\x01")
        (raw / "weird.xyz").write_bytes(b"\xff\xfe\xfa")
        (raw / "ca.pem").write_text("-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----", encoding="utf-8")
        rows = audit(pathlib.Path(td))["containers"][0]["problems"]
        got = {r["path"]: r["kind"] for r in rows}
        checks = [
            ("ok.md 不进问题", "raw/ok.md" not in got),
            ("GBK 判 encoding", got.get("raw/gbk.txt") == "encoding"),
            ("空文件判 empty", got.get("raw/empty.md") == "empty"),
            ("PDF 判 binary", got.get("raw/doc.pdf") == "binary"),
            ("bin 判 binary", got.get("raw/blob.bin") == "binary"),
            ("未知后缀判 unknown", got.get("raw/weird.xyz") == "unknown"),
            ("pem 按文本、不进问题", "raw/ca.pem" not in got),
        ]
        for name, ok in checks:
            print(f"{name:<22} {'ok' if ok else 'FAIL'}")
            fails += 0 if ok else 1
        print(f"总结 {len(checks) - fails}/{len(checks)}")
    return 1 if fails else 0


def main():
    if "--selftest" in sys.argv:
        return selftest()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    root = pathlib.Path(args[0])
    if not root.exists():
        print(f"路径不存在：{root}", file=sys.stderr)
        return 4
    res = audit(root)
    if "--json" in sys.argv:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        s = res["summary"]
        print(f"材料体检：{s['containers']} 个容器 / {s['files']} 个文件 / {s['problems']} 处需处理")
        if res["by_kind"]:
            print("  分类：" + "  ".join(f"{k}={v}" for k, v in sorted(res["by_kind"].items())))
        for r in res["containers"]:
            if not r["problems"]:
                continue
            print(f"[{r['container']}]")
            for p in r["problems"][:5]:
                print(f"  {p['path']} [{p['kind']}] {p['detail']}")
    return 1 if ("--strict" in sys.argv and res["summary"]["problems"]) else 0


if __name__ == "__main__":
    sys.exit(main())
