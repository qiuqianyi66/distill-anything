#!/usr/bin/env python3
"""gate 回归：产物格式四态 + 证据库四态（成立 / 失效 / 已变 / 缺库）。

用法：python tests/run_gate_tests.py
退出码 0 = 全部符合预期；1 = 有偏差（改判据后必须重跑）
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FILE_CASES = {
    "good": "PASS",
    "bad": "FAIL",
    "incomplete": "INCOMPLETE",
    "missing-ref": "FAIL",
    # perspective 结构判据：只对思维型触发，5 模型+张力 应过，8 模型应红（该删没删），
    # 缺张力应 INCOMPLETE（没蒸出来）。来源：蒸馏 nuwa-skill examples，2026-11-08。
    "persp-ok": "PASS",
    "persp-models-8": "FAIL",
    "persp-no-tension": "INCOMPLETE",
    # frontmatter 被 markdown 格式化器改写（*** 代替 ---、键间插空行）必须判红，
    # 否则会被当成「本来没有 frontmatter 的 report」放行。来源：nuwa 产物落盘后实测，2026-11-08。
    "fm-mangled": "FAIL",
    # 外来文件：带第三方技能键且无 source 必须 SKIP，不是 INCOMPLETE。
    "foreign-file": "SKIP",
    # 2026-11-09 反例审计补的三例：这三条判据此前从来没有被任何 fixture 打红过。
    # 先由 runtime/.tmp/gate_teeth_audit.py 扫出「只出现 True、从无 False」的判据，再逐条补反例。
    "banned-word": "FAIL",        # banned-words：裸用「优秀/毫无疑问」不加标记必须 VIOLATION
    "unknown-thin": "INCOMPLETE",  # unknown-depth：未知台账第三条写成占位必须 GAP
    "fm-partial": "INCOMPLETE",    # frontmatter：只有 name 没有 description 必须 GAP
}

DIR_CASES = {
    "evidence-ok": "PASS",
    "evidence-dead": "FAIL",
}


def run_gate(gate: Path, target: Path, extra=None):
    proc = subprocess.run(
        [sys.executable, str(gate), str(target), "--json"] + (extra or []),
        capture_output=True, text=True, encoding="utf-8",
    )
    try:
        data = json.loads(proc.stdout)
        return data["status"], proc.returncode
    except (json.JSONDecodeError, KeyError):
        return None, proc.returncode


def run_gate_full(gate: Path, target: Path, extra=None):
    proc = subprocess.run(
        [sys.executable, str(gate), str(target), "--json"] + (extra or []),
        capture_output=True, text=True, encoding="utf-8",
    )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}


def report(name, expect, got, code):
    ok = got == expect
    print(f"{'ok  ' if ok else 'FAIL'} {name:<16} expect={expect:<10} got={str(got):<10} exit={code}")
    return 0 if ok else 1


def main() -> int:
    root = Path(__file__).resolve().parent
    gate = root.parent / "scripts" / "gate.py"
    if not gate.exists():
        print(f"FAIL gate.py 不存在：{gate}")
        return 1

    failures = 0
    total = 0

    for name, expect in FILE_CASES.items():
        total += 1
        got, code = run_gate(gate, root / "fixtures" / f"{name}.md")
        failures += report(name, expect, got, code)

    for name, expect in DIR_CASES.items():
        total += 1
        got, code = run_gate(gate, root / "fixtures" / name / "report.md")
        failures += report(name, expect, got, code)

    # 降级路径是观察期判据：缺这一节不许改变三态（good.md 无兜底词，仍必须 PASS），
    # 且 checks 里必须能看见它、ok 必须是 None（升成硬判就会变成惩罚历史）。
    total += 1
    detail = run_gate_full(gate, root / "fixtures" / "good.md")
    fb = next((c for c in detail.get("checks", []) if c.get("name") == "section:降级路径"), {})
    ok = detail.get("status") == "PASS" and fb and fb.get("ok") is None
    print(f"{'ok  ' if ok else 'FAIL'} {'fallback-soft':<16} expect=PASS+ok:None got={detail.get('status')}/{fb.get('ok')}")
    failures += 0 if ok else 1

    # 证据已变：复制 evidence-ok 后篡改被引用的行段，必须从 PASS 降到 INCOMPLETE
    total += 1
    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "evidence-changed"
        shutil.copytree(root / "fixtures" / "evidence-ok", dst)
        lib = dst / "src" / "lib.ts"
        lib.write_text(lib.read_text(encoding="utf-8").replace("LINE_2", "LINE_2_MUTATED"), encoding="utf-8")
        got, code = run_gate(gate, dst / "report.md")
        failures += report("changed", "INCOMPLETE", got, code)

    # 无证据库：引用 E id 但同级没有 evidence.jsonl，必须 INCOMPLETE 而非 PASS
    total += 1
    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "evidence-missing"
        shutil.copytree(root / "fixtures" / "evidence-ok", dst, ignore=shutil.ignore_patterns("evidence.jsonl"))
        got, code = run_gate(gate, dst / "report.md")
        failures += report("no-library", "INCOMPLETE", got, code)

    # 路径锚点与 E id 等价：同一处证据写成 src/lib.ts:1-3，index 后该条 supports 应含 report.md
    total += 1
    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "distill-anchor"
        shutil.copytree(root / "fixtures" / "evidence-ok", dst)
        rp = dst / "report.md"
        rp.write_text(rp.read_text(encoding="utf-8").replace("E-aaaa0001", "src/lib.ts:1-3"),
                      encoding="utf-8")
        distill = gate.parent / "distill.py"
        idx = subprocess.run([sys.executable, str(distill), "index", "--root", str(dst)],
                             capture_output=True, text=True, encoding="utf-8")
        rows = [json.loads(l) for l in (dst / "evidence.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        e1 = next((r for r in rows if r.get("id") == "E-aaaa0001"), {})
        ok = idx.returncode == 0 and "report.md" in e1.get("supports", [])
        print(f"{'ok  ' if ok else 'FAIL'} {'path-anchor':<16} expect=exit0+supports[report.md] got=exit{idx.returncode}/{e1.get('supports', [])}")
        failures += 0 if ok else 1

    # 证据老化：超 30 天只提醒不拦。index 退出 2，gate 仍 PASS
    total += 1
    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "distill-aging"
        shutil.copytree(root / "fixtures" / "evidence-ok", dst)
        ev = dst / "evidence.jsonl"
        rows = [json.loads(l) for l in ev.read_text(encoding="utf-8").splitlines() if l.strip()]
        rows[0]["observed_at"] = "2025-01-01"
        ev.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        distill = gate.parent / "distill.py"
        idx = subprocess.run([sys.executable, str(distill), "index", "--root", str(dst)],
                             capture_output=True, text=True, encoding="utf-8")
        gate_got, _ = run_gate(gate, dst / "report.md")
        ok = idx.returncode == 2 and gate_got == "PASS"
        print(f"{'ok  ' if ok else 'FAIL'} {'aging':<16} expect=idx2/PASS got=idx{idx.returncode}/{gate_got}")
        failures += 0 if ok else 1

    # 严格锚点：证据库够 5 条时，正文全用路径锚点应 INCOMPLETE；换回 E id 应 PASS
    total += 2
    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "distill-strict"
        shutil.copytree(root / "fixtures" / "evidence-ok", dst)
        distill = gate.parent / "distill.py"
        for p, l, st in (("src/lib.ts", "2-4", "紧邻已收录行段的第二段"), ("src/lib.ts", "7-8", "紧邻已收录行段的第三段")):
            subprocess.run([sys.executable, str(distill), "evidence", "add", "--dir", str(dst),
                            "--path", p, "--lines", l, "--level", "O", "--statement", st,
                            "--source", "commit:test"], capture_output=True, text=True, encoding="utf-8")
        rp = dst / "report.md"
        orig = rp.read_text(encoding="utf-8")
        pathy = orig
        for eid, anchor in (("E-aaaa0001", "src/lib.ts:1-3"),
                            ("E-aaaa0002", "src/lib.ts:5-6"),
                            ("E-aaaa0003", "src/lib.ts:9-10")):
            pathy = pathy.replace(eid, anchor)
        rp.write_text(pathy, encoding="utf-8")
        got, code = run_gate(gate, rp, ["--strict-anchor"])
        failures += report("strict-gap", "INCOMPLETE", got, code)
        # 收口脚本把路径锚点换成 E id 后，同一份产物应转 PASS（顺带验证 anchorize 本身）
        anchorize = gate.parent / "anchorize.py"
        subprocess.run([sys.executable, str(anchorize), "--dir", str(dst),
                        "--date", "2026-11-08", "--source", "commit:test"],
                       capture_output=True, text=True, encoding="utf-8")
        got, code = run_gate(gate, rp, ["--strict-anchor"])
        failures += report("strict-ok", "PASS", got, code)

    # 重复锚点不凑数：同一处写 8 遍仍只算 1 个不同锚点，应报锚点不足
    total += 1
    with tempfile.TemporaryDirectory() as td:
        md = Path(td) / "dedup.md"
        md.write_text(
            "---\nname: dedup\ndescription: 同一锚点重复\n---\n\n# dedup\n\n"
            "## 1 证据台账\n| 断言 | 层级 | 锚点 |\n|---|---|---|\n| 同一处证据 | O | E-aaaa0001 |\n\n"
            "## 2 未知台账\n| 未知 | 为什么解不了 | 需要什么才能解 |\n|---|---|---|\n"
            "| 是否成立 | 未复核 | 重读原文 |\n\n## 3 诚实边界\n- 只有一条证据\n\n"
            + "\n".join(f"- 第 {i} 条结论指向同一处证据 [O] E-aaaa0001" for i in range(1, 9)) + "\n",
            encoding="utf-8",
        )
        data = run_gate_full(gate, md)
        anchors_check = next((c for c in data.get("checks", []) if c.get("name") == "anchors"), {})
        ok = anchors_check.get("ok") is False
        print(f"{'ok  ' if ok else 'FAIL'} {'anchor-dedup':<16} expect=anchors(False) got={anchors_check}")
        failures += 0 if ok else 1

    # 锚点越界：`../` 与绝对路径必须判不可解析，否则门禁会拿产品目录外的任意文件充证据
    total += 1
    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "distill-escape"
        (dst / "raw").mkdir(parents=True)
        (dst / "raw" / "ok.md").write_text("第 1 行\n第 2 行\n", encoding="utf-8")
        outside = Path(td) / "outside.md"
        outside.write_text("外部文件第 1 行\n", encoding="utf-8")
        md = dst / "report.md"
        md.write_text(
            "---\nname: escape\ndescription: 越界锚点\n---\n\n# escape\n\n"
            "## 1 证据台账\n| 断言 | 层级 | 锚点 |\n|---|---|---|\n"
            "| 越界读外部 | O | [O] ../outside.md:1 |\n"
            "| 绝对路径 | O | [O] " + str(outside).replace("\\", "/") + ":1 |\n\n"
            "## 2 未知台账\n| 未知 | 为什么解不了 | 需要什么才能解 |\n|---|---|---|\n"
            "| 无 | 无 | 无 |\n\n## 3 诚实边界\n- 测试越界\n",
            encoding="utf-8",
        )
        got, code = run_gate(gate, md)
        failures += report("anchor-escape", "FAIL", got, code)

    # 链接完整性：相对链接目标不存在、或 #锚点在目标里找不到标题，都必须 FAIL
    total += 2
    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "distill-links"
        (dst / "raw").mkdir(parents=True)
        (dst / "raw" / "ok.md").write_text("# 第一节\n\n内容一。\n\n## 第二节\n\n内容二。\n\n内容三。\n\n内容四。\n\n内容五。\n", encoding="utf-8")
        base = (
            "---\nname: links\ndescription: 链接检查\n---\n\n# links\n\n"
            "## 1 证据台账\n| 断言 | 层级 | 锚点 |\n|---|---|---|\n"
            "| 有文件有标题 | O | [O] raw/ok.md:1 |\n"
            "| 第二处 | O | [O] raw/ok.md:3 |\n"
            "| 第三处 | O | [O] raw/ok.md:5 |\n"
            "| 第四处 | O | [O] raw/ok.md:7 |\n"
            "| 第五处 | O | [O] raw/ok.md:9 |\n\n"
            "## 2 未知台账\n| 未知 | 为什么解不了 | 需要什么才能解 |\n|---|---|---|\n"
            "| 无 | 无 | 无 |\n\n## 3 诚实边界\n"
            "- 补充结论一，指向同一处证据 [O] raw/ok.md:1\n"
            "- 补充结论二，指向同一处证据 [O] raw/ok.md:1\n"
            "- 补充结论三，指向同一处证据 [O] raw/ok.md:1\n"
        )
        md = dst / "report.md"
        md.write_text(base + "- 见 [第一节](raw/ok.md#第一节)\n", encoding="utf-8")
        got, code = run_gate(gate, md)
        failures += report("links-ok", "PASS", got, code)
        md.write_text(base + "- 见 [坏链](raw/none.md#任意) 与 [坏锚](raw/ok.md#没有这节)\n", encoding="utf-8")
        got, code = run_gate(gate, md)
        failures += report("links-404", "FAIL", got, code)

    # init 的 --type 必须真的换骨架：声明了三种产物型却不是三种骨架，等于参数只做了校验
    total += 3
    with tempfile.TemporaryDirectory() as td:
        dpy = gate.parent.parent / "scripts" / "distill.py"
        must = {"mechanism": "结构地图", "perspective": "心智模型", "rules": "判据表"}
        for ty, marker in must.items():
            slug = f"probe-{ty}"
            subprocess.run(
                [sys.executable, str(dpy), "init", slug, "--type", ty, "--root", td],
                capture_output=True, text=True, encoding="utf-8",
            )
            body = (Path(td) / f"distill-{slug}" / "report.md").read_text(encoding="utf-8")
            got = "PASS" if marker in body else "FAIL"
            failures += report(f"init-skeleton-{ty}", "PASS", got, 0)

    # --json 的 stdout 必须能被 json.loads 解析：混入 summary 或 SKIP 行会让下游解析失败
    total += 1
    dpy = gate.parent.parent / "scripts" / "distill.py"
    fixture = Path(__file__).resolve().parent / "fixtures" / "good.md"
    r = subprocess.run(
        [sys.executable, str(dpy), "gate", str(fixture), "--json"],
        capture_output=True, text=True, encoding="utf-8",
    )
    try:
        json.loads(r.stdout)
        got = "PASS"
    except Exception:
        got = "FAIL"
    failures += report("json-gate-stdout", "PASS", got, r.returncode)

    # 带外来键但有 source 的我方产物不许被误 SKIP：source 是收口条件，缺了它才会放行
    total += 1
    data = run_gate_full(gate, root / "fixtures" / "foreign-with-source.md")
    ok = data.get("status") in ("PASS", "INCOMPLETE", "FAIL")
    print(f"{'ok  ' if ok else 'FAIL'} {'foreign-with-source':<16} expect=非SKIP got={data.get('status')}")
    failures += 0 if ok else 1

    # 写入完整性：stamp 建立基线后 gate 应 PASS；篡改产物后 write-integrity 必须报 GAP
    total += 2
    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "distill-stamp"
        shutil.copytree(root / "fixtures" / "evidence-ok", dst)
        distill = gate.parent / "distill.py"
        rp = dst / "report.md"
        stamp = subprocess.run([sys.executable, str(distill), "stamp", str(rp)],
                               capture_output=True, text=True, encoding="utf-8")
        data = run_gate_full(gate, rp)
        wi = next((c for c in data.get("checks", []) if c.get("name") == "write-integrity"), {})
        ok = stamp.returncode == 0 and wi.get("ok") is True
        print(f"{'ok  ' if ok else 'FAIL'} {'stamp-ok':<16} expect=write-integrity(True) got={wi}")
        failures += 0 if ok else 1
        rp.write_text(rp.read_text(encoding="utf-8").replace("fallback", "fallback_x"),
                      encoding="utf-8")
        got, code = run_gate(gate, rp)
        failures += report("stamp-mangled", "INCOMPLETE", got, code)

    # 分桶布局：产物被搬到 out/<bucket>/distill-* 后，--recursive 仍必须找到它。
    # 原先只 glob 顶层，DSH 2026-11-09 按域隔离后门禁会静默「0 份通过」，比报错更危险。
    total += 1
    with tempfile.TemporaryDirectory() as td:
        bucket = Path(td) / "bucket" / "distill-nested"
        bucket.mkdir(parents=True)
        shutil.copy(root / "fixtures" / "good.md", bucket / "report.md")
        # 素材里的仓库副本不该被当容器：放一份在 raw/ 下，期望仍只找到 1 份
        snap = bucket / "raw" / "skills" / "distill-copy"
        snap.mkdir(parents=True)
        shutil.copy(root / "fixtures" / "bad.md", snap / "report.md")
        distill = gate.parent / "distill.py"
        proc = subprocess.run([sys.executable, str(distill), "gate", td, "--recursive", "--json"],
                              capture_output=True, text=True, encoding="utf-8")
        try:
            rs = json.loads(proc.stdout)
        except json.JSONDecodeError:
            rs = []
        # 只验「发现」这一件事：命中 1 份，且是 bucket 里那份而不是 raw/ 快照副本。
        # 判什么状态不属本用例（fixture 换目录后其锚点指向的 src/ 不在原地）。
        hit_nested = len(rs) == 1 and "distill-nested" in rs[0]["target"]
        where = rs[0]["target"] if rs else "—"
        print(f"{'ok  ' if hit_nested else 'FAIL'} {'nested-container':<16} expect=命中嵌套1份  got={len(rs)} 份 {where[-40:]}")
        failures += 0 if hit_nested else 1

    # 变异夹具（2026-11-09 行为化门禁）：每条夹具只种一处缺陷，
    # 断言「被判红的 check 集合恰好等于预期集合」（既不少红，也不许被别的判据顺带拦下）。
    # 反向验证在同一用例里做：把对应判据临时放宽/关掉，该夹具必须转 PASS，否则说明它红在别的理由上。
    sys.path.insert(0, str(gate.parent))
    import gate as gate_mod

    MUTATIONS = {
        "mut-anchor-range": ("FAIL", {"anchor-liveness"}, ("resolve_anchor", lambda t, a: (True, "ok"))),
        "mut-anchor-outside": ("FAIL", {"anchor-liveness"}, ("resolve_anchor", lambda t, a: (True, "ok"))),
        "mut-marker-count": ("INCOMPLETE", {"markers"}, ("MARK_MIN", 0)),
        "mut-anchor-count": ("INCOMPLETE", {"anchors"}, ("ANCHOR_MIN", 0)),
    }
    for name, (expect_status, expect_fired, patch) in MUTATIONS.items():
        total += 1
        data = run_gate_full(gate, root / "fixtures" / f"{name}.md")
        fired = {c["name"] for c in data.get("checks", []) if c.get("ok") is False}
        ok_forward = data.get("status") == expect_status and fired == expect_fired
        attr, val = patch
        orig = getattr(gate_mod, attr)
        setattr(gate_mod, attr, val)
        try:
            back = gate_mod.check(root / "fixtures" / f"{name}.md")
        finally:
            setattr(gate_mod, attr, orig)
        ok_back = back["status"] == "PASS"
        ok = ok_forward and ok_back
        print(f"{'ok  ' if ok else 'FAIL'} {name:<16} expect={expect_status}/{sorted(expect_fired)} "
              f"got={data.get('status')}/{sorted(fired)} 反例={back['status']}")
        failures += 0 if ok else 1

    print(f"\n{total - failures}/{total} 通过")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
