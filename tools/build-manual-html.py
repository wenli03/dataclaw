"""把 docs/07-角色操作手册.md 转成可发布的单文件 HTML（截图内嵌为 data URI）。

用法：python tools/build-manual-html.py
输出：docs/07-角色操作手册.html
"""
from __future__ import annotations

import base64
import html
import re
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
MD_PATH = DOCS / "07-角色操作手册.md"
IMG_DIR = DOCS / "screenshots-manual"
OPT_DIR = DOCS / "screenshots-manual-opt"
OUT_PATH = DOCS / "07-角色操作手册.html"

# ---------------------------------------------------------------- 图片

def build_images() -> dict[str, dict]:
    OPT_DIR.mkdir(exist_ok=True)
    out: dict[str, dict] = {}
    for png in sorted(IMG_DIR.glob("*.png")):
        jpg = OPT_DIR / (png.stem + ".jpg")
        if not jpg.exists() or jpg.stat().st_mtime < png.stat().st_mtime:
            im = Image.open(png).convert("RGB")
            w, h = im.size
            if w > 1600:
                im = im.resize((1600, round(h * 1600 / w)), Image.LANCZOS)
            im.save(jpg, "JPEG", quality=88, optimize=True, progressive=True)
        im = Image.open(jpg)
        w, h = im.size
        b64 = base64.b64encode(jpg.read_bytes()).decode()
        out[f"screenshots-manual/{png.name}"] = {
            "uri": f"data:image/jpeg;base64,{b64}",
            "w": w,
            "h": h,
        }
    return out


IMAGES = build_images()

# ---------------------------------------------------------------- 行内格式

PLACEHOLDER = "\x00{}\x00"


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def inline(text: str) -> str:
    tokens: list[str] = []

    def hold(fragment: str) -> str:
        tokens.append(fragment)
        return PLACEHOLDER.format(len(tokens) - 1)

    # 行内代码
    def code_repl(m: re.Match) -> str:
        return hold(f"<code>{html.escape(m.group(1))}</code>")

    text = re.sub(r"`([^`]+)`", code_repl, text)

    # 图片
    def img_repl(m: re.Match) -> str:
        alt, path = m.group(1), m.group(2).strip()
        meta = IMAGES.get(path)
        if not meta:
            return hold(f'<span class="repo-path">{html.escape(path)}</span>')
        return hold(
            f'<img src="{meta["uri"]}" alt="{html.escape(alt)}" width="{meta["w"]}" height="{meta["h"]}" loading="lazy" decoding="async">'
        )

    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", img_repl, text)

    # 链接
    def link_repl(m: re.Match) -> str:
        label, href = m.group(1), m.group(2).strip()
        label_html = inline_no_link(label)
        if href.startswith(("http://", "https://")):
            return hold(f'<a href="{html.escape(href)}" target="_blank" rel="noopener">{label_html}</a>')
        if href.startswith("#"):
            return hold(f'<a href="{html.escape(href)}">{label_html}</a>')
        return hold(f'<span class="repo-path">{label_html}</span>')

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link_repl, text)

    text = esc(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)

    # 还原占位符（可能嵌套，多轮还原）
    for _ in range(6):
        changed = False
        for i, frag in enumerate(tokens):
            key = PLACEHOLDER.format(i)
            if key in text:
                text = text.replace(key, frag)
                changed = True
        if not changed:
            break
    return text


def inline_no_link(text: str) -> str:
    # 链接文字里只处理 code 与 bold，避免递归链接
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = esc(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return text


# ---------------------------------------------------------------- 块级解析

def slug(index: int) -> str:
    return f"sec-{index}"


STATUS = {
    "✅": ("ok", "已实现"),
    "🟡": ("partial", "有边界"),
    "⛔": ("no", "V2"),
}


def status_cell(cell: str) -> str:
    for mark, (cls, label) in STATUS.items():
        if mark in cell:
            return f'<span class="status {cls}">{label}</span>'
    return inline(cell)


def parse_table(lines: list[str]) -> str:
    rows = []
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(cells)
    head = rows[0]
    body = rows[2:]
    out = ['<div class="table-wrap"><table>', "<thead><tr>"]
    for c in head:
        out.append(f"<th>{inline(c)}</th>")
    out.append("</tr></thead><tbody>")
    for row in body:
        out.append("<tr>")
        for c in row:
            out.append(f"<td>{status_cell(c)}</td>")
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def is_table_start(lines: list[str], i: int) -> bool:
    if i + 1 >= len(lines):
        return False
    return lines[i].lstrip().startswith("|") and re.match(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", lines[i + 1]) is not None


def is_block_start(lines: list[str], i: int) -> bool:
    line = lines[i]
    if not line.strip():
        return True
    if re.match(r"^\s*(#{1,4})\s+", line):
        return True
    if re.match(r"^\s*```", line):
        return True
    if re.match(r"^\s*>", line):
        return True
    if re.match(r"^\s*---+\s*$", line):
        return True
    if re.match(r"^\s*([-*]|\d+\.)\s+", line):
        return True
    if is_table_start(lines, i):
        return True
    return False


def convert(md: str) -> tuple[str, list[dict]]:
    # 跳过 H1 与开头元信息，从第一个 H2 开始
    md = md.split("\n## ", 1)[1]
    md = "## " + md
    # 去掉截图索引（截图已内嵌）
    md = re.split(r"\n### 10\.5 截图索引", md)[0]
    md = md.replace("**最后更新**：2026-10-24  \n**反馈**：发现问题请提 issue，或在 `docs/04-实现说明与验收.md` 的验收清单中补充证据。", "")

    lines = md.splitlines()
    out: list[str] = []
    toc: list[dict] = []
    i = 0
    h2_index = 0
    h3_index = 0
    current_sid = "sec-0"

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        # 代码块
        if re.match(r"^\s*```", line):
            lang = line.strip().strip("`").strip()
            i += 1
            buf = []
            while i < len(lines) and not re.match(r"^\s*```", lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1
            code = "\n".join(buf)
            out.append(
                f'<div class="code-wrap"><pre><code class="language-{html.escape(lang)}">{html.escape(code)}</code></pre></div>'
            )
            continue

        # 标题
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            if level == 2:
                h2_index += 1
                h3_index = 0
                mm = re.match(r"^(\d+)\.\s*(.*)$", text)
                num = mm.group(1) if mm else ""
                if mm:
                    text = mm.group(2)
                current_sid = f"sec-{num}" if num else f"sec-{h2_index}"
                sid = current_sid
                eyebrow = f'<span class="eyebrow">{html.escape(num)}</span>' if num else ""
                out.append(f'<h2 id="{sid}">{eyebrow}<span>{inline(text)}</span></h2>')
                toc.append({"id": sid, "text": text, "level": 2})
            elif level == 3:
                h3_index += 1
                sid = f"{current_sid}-{h3_index}"
                out.append(f'<h3 id="{sid}">{inline(text)}</h3>')
                toc.append({"id": sid, "text": text, "level": 3})
            elif level == 4:
                out.append(f"<h4>{inline(text)}</h4>")
            i += 1
            continue

        # 分隔线
        if re.match(r"^\s*---+\s*$", line):
            out.append("<hr>")
            i += 1
            continue

        # 引用
        if re.match(r"^\s*>", line):
            buf = []
            while i < len(lines) and re.match(r"^\s*>", lines[i]):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append(f'<blockquote>{inline(" ".join(buf))}</blockquote>')
            continue

        # 表格
        if is_table_start(lines, i):
            buf = [lines[i], lines[i + 1]]
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                buf.append(lines[i])
                i += 1
            out.append(parse_table(buf))
            continue

        # 列表
        m = re.match(r"^\s*([-*]|\d+\.)\s+(.*)$", line)
        if m:
            ordered = bool(re.match(r"^\s*\d+\.", line))
            items = []
            while i < len(lines) and re.match(r"^\s*([-*]|\d+\.)\s+", lines[i]):
                mm = re.match(r"^\s*([-*]|\d+\.)\s+(.*)$", lines[i])
                items.append(mm.group(2).strip())
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
            continue

        # 段落
        buf = [line.strip()]
        i += 1
        while i < len(lines) and not is_block_start(lines, i):
            buf.append(lines[i].strip())
            i += 1
        out.append(f"<p>{inline(' '.join(buf))}</p>")

    return "\n".join(out), toc


# ---------------------------------------------------------------- 模板

CSS = """
:root{
  --bg:#f5f3ee; --surface:#ffffff; --surface-2:#ece9e1; --surface-3:#e3dfd4;
  --fg:#171a21; --muted:#5f6673; --faint:#8b919c; --border:#dcd6ca;
  --accent:#0c6b63; --accent-2:#3d4cc4; --accent-soft:#e3f2ef;
  --warn:#a95d07; --danger:#b42318; --good:#15703a;
  --display:"Songti SC","Noto Serif CJK SC","Source Han Serif SC",SimSun,Georgia,serif;
  --body:"PingFang SC","Noto Sans CJK SC","Source Han Sans SC","Microsoft YaHei",system-ui,sans-serif;
  --mono:"SFMono-Regular",Consolas,"Liberation Mono",Menlo,monospace;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#101318; --surface:#171b22; --surface-2:#1f242d; --surface-3:#29303b;
    --fg:#eef0f4; --muted:#a3abb8; --faint:#7b8492; --border:#2b323d;
    --accent:#5fd0c4; --accent-2:#96a4ff; --accent-soft:#17302e;
    --warn:#f0b35f; --danger:#ff8d80; --good:#6fdc9d;
    color-scheme:dark;
  }
}
:root[data-theme="dark"]{
  --bg:#101318; --surface:#171b22; --surface-2:#1f242d; --surface-3:#29303b;
  --fg:#eef0f4; --muted:#a3abb8; --faint:#7b8492; --border:#2b323d;
  --accent:#5fd0c4; --accent-2:#96a4ff; --accent-soft:#17302e;
  --warn:#f0b35f; --danger:#ff8d80; --good:#6fdc9d;
  color-scheme:dark;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
html,body{background:var(--bg); color:var(--fg)}
body::before{
  content:""; position:fixed; inset:0 0 auto 0; height:env(safe-area-inset-top,0px);
  z-index:60; background:var(--bg); pointer-events:none;
}
.page{
  background:var(--bg); color:var(--fg); font-family:var(--body);
  min-height:100%; padding-left:max(16px,env(safe-area-inset-left,0px));
  padding-right:max(16px,env(safe-area-inset-right,0px));
  padding-bottom:48px; font-size:15px; line-height:1.75;
  -webkit-font-smoothing:antialiased;
}
.page::before{
  content:""; position:fixed; inset:env(safe-area-inset-top,0px) 0 auto 0; height:3px; z-index:50;
  background:linear-gradient(90deg,var(--accent),var(--accent-2));
}
a{color:var(--accent); text-decoration:none; border-bottom:1px solid color-mix(in srgb,var(--accent) 35%,transparent)}
a:hover{border-bottom-color:var(--accent)}
code{font-family:var(--mono); font-size:.88em; background:var(--surface-2); padding:.12em .35em; border-radius:4px}
.repo-path{font-family:var(--mono); font-size:.86em; color:var(--muted); background:var(--surface-2); padding:.1em .35em; border-radius:4px; word-break:break-all}
img{max-width:100%; height:auto; display:block}
hr{border:0; border-top:1px solid var(--border); margin:34px 0}

.topbar{
  position:sticky; top:env(safe-area-inset-top,0px); z-index:40;
  display:flex; align-items:center; gap:18px; flex-wrap:wrap;
  padding:14px 0 12px; background:color-mix(in srgb,var(--bg) 88%,transparent);
  backdrop-filter:blur(12px); border-bottom:1px solid var(--border);
}
.brand{display:flex; align-items:center; gap:10px; font-weight:700; letter-spacing:.01em}
.brand .mark{
  width:28px; height:28px; border-radius:9px; display:grid; place-items:center;
  background:linear-gradient(145deg,var(--accent),var(--accent-2)); color:#fff;
  font-family:var(--display); font-size:17px; line-height:1;
}
.brand small{display:block; font-weight:400; font-size:11px; color:var(--muted); letter-spacing:.08em; text-transform:uppercase}
.topnav{display:flex; gap:4px; flex-wrap:wrap; margin-left:auto}
.topnav a{font-size:12.5px; color:var(--muted); padding:5px 9px; border-radius:999px; border:1px solid transparent}
.topnav a:hover{color:var(--fg); background:var(--surface-2); border-bottom-color:transparent}
.theme-btn{
  border:1px solid var(--border); background:var(--surface); color:var(--muted);
  border-radius:999px; padding:5px 11px; font-size:12px; cursor:pointer; font-family:var(--body);
}
.theme-btn:hover{color:var(--fg); border-color:var(--accent)}

.layout{display:grid; grid-template-columns:250px minmax(0,1fr); gap:44px; max-width:1280px; margin:0 auto}
.toc-aside{padding-top:34px}
.toc-inner{position:sticky; top:76px; max-height:calc(100vh - 100px); overflow:auto; padding-right:6px}
.toc-title{font-size:11px; letter-spacing:.16em; text-transform:uppercase; color:var(--faint); margin:0 0 10px; font-weight:600}
.toc a{display:block; font-size:12.5px; color:var(--muted); padding:5px 10px; border-left:2px solid transparent; border-bottom:0; line-height:1.45}
.toc a.lv3{padding-left:22px; font-size:12px; color:var(--faint)}
.toc a:hover{color:var(--fg); background:var(--surface-2)}
.toc a.on{color:var(--accent); border-left-color:var(--accent); background:var(--accent-soft)}
main{min-width:0; padding-top:30px}

.hero{
  background:var(--surface); border:1px solid var(--border); border-radius:20px;
  padding:34px 36px 30px; position:relative; overflow:hidden;
}
.hero::after{
  content:""; position:absolute; right:-70px; top:-90px; width:280px; height:280px;
  border-radius:50%; background:radial-gradient(circle,color-mix(in srgb,var(--accent) 16%,transparent),transparent 68%);
  pointer-events:none;
}
.hero .kicker{font-size:11.5px; letter-spacing:.18em; text-transform:uppercase; color:var(--accent); font-weight:700; margin-bottom:14px}
.hero h1{
  font-family:var(--display); font-size:clamp(32px,4.4vw,52px); line-height:1.12;
  margin:0 0 14px; font-weight:700; letter-spacing:.01em; text-wrap:balance;
}
.hero .lead{max-width:720px; color:var(--muted); font-size:15.5px; line-height:1.8; margin:0}
.hero .meta{display:flex; flex-wrap:wrap; gap:8px; margin-top:22px}
.chip{
  display:inline-flex; align-items:center; gap:6px; font-size:12px; color:var(--muted);
  background:var(--surface-2); border:1px solid var(--border); border-radius:999px; padding:5px 11px;
}
.chip b{color:var(--fg); font-weight:600}
.role-grid{display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-top:26px}
.role-card{
  background:var(--surface); border:1px solid var(--border); border-radius:14px;
  padding:15px 15px 13px; display:flex; flex-direction:column; gap:6px; min-width:0;
  border-top:3px solid var(--role); color:var(--fg); border-bottom:1px solid var(--border);
}
.role-card:hover{border-color:var(--role); border-bottom-color:var(--role)}
.role-card .dot{width:8px; height:8px; border-radius:50%; background:var(--role)}
.role-card .name{font-weight:700; font-size:14.5px; display:flex; align-items:center; gap:7px}
.role-card .desc{font-size:12px; color:var(--muted); line-height:1.6; flex:1}
.role-card .go{font-size:12px; color:var(--role); font-weight:600; margin-top:4px}
.role-admin{--role:#0c6b63}
.role-analyst{--role:#3d4cc4}
.role-sales{--role:#a95d07}
.role-legal{--role:#a5325c}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]) .role-admin{--role:#5fd0c4}
  :root:not([data-theme="light"]) .role-analyst{--role:#96a4ff}
  :root:not([data-theme="light"]) .role-sales{--role:#f0b35f}
  :root:not([data-theme="light"]) .role-legal{--role:#ff9ab5}
}
:root[data-theme="dark"] .role-admin{--role:#5fd0c4}
:root[data-theme="dark"] .role-analyst{--role:#96a4ff}
:root[data-theme="dark"] .role-sales{--role:#f0b35f}
:root[data-theme="dark"] .role-legal{--role:#ff9ab5}

.section{scroll-margin-top:80px}
.content h2{
  scroll-margin-top:80px; font-family:var(--display); font-size:clamp(26px,3vw,34px);
  line-height:1.25; margin:54px 0 18px; font-weight:700; display:flex; align-items:baseline; gap:14px;
  padding-bottom:12px; border-bottom:1px solid var(--border); text-wrap:balance;
}
.content h2 .eyebrow{
  font-family:var(--mono); font-size:12px; color:var(--accent); letter-spacing:.08em;
  border:1px solid color-mix(in srgb,var(--accent) 35%,var(--border)); border-radius:999px;
  padding:2px 9px; flex:none; font-weight:600;
}
.content h3{
  scroll-margin-top:80px; font-size:19px; margin:34px 0 12px; font-weight:700;
  font-family:var(--display); letter-spacing:.01em;
}
.content h4{font-size:15px; margin:24px 0 8px; font-weight:700}
.content p{margin:0 0 14px; color:var(--fg); max-width:78ch}
.content ul,.content ol{margin:0 0 16px; padding-left:1.35em}
.content li{margin:5px 0}
.content li::marker{color:var(--accent)}
.content strong{font-weight:700}
.content blockquote{
  margin:16px 0; padding:13px 16px; background:var(--surface-2);
  border-left:3px solid var(--accent); border-radius:0 10px 10px 0; color:var(--muted); font-size:14px;
}
.content blockquote p{margin:0}
.content hr{display:none}

.table-wrap{overflow-x:auto; margin:16px 0 22px; border:1px solid var(--border); border-radius:12px; background:var(--surface)}
table{width:100%; border-collapse:collapse; font-size:13px; min-width:560px}
thead th{
  text-align:left; font-size:11px; letter-spacing:.08em; text-transform:uppercase;
  color:var(--faint); background:var(--surface-2); padding:10px 12px; border-bottom:1px solid var(--border);
  white-space:nowrap; font-weight:600;
}
tbody td{padding:10px 12px; border-bottom:1px solid var(--border); vertical-align:top; line-height:1.6}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover{background:color-mix(in srgb,var(--accent) 5%,transparent)}
tbody td:first-child{color:var(--fg)}

.status{display:inline-block; font-size:11px; font-weight:700; letter-spacing:.02em; padding:2px 8px; border-radius:999px; white-space:nowrap}
.status.ok{color:var(--good); background:color-mix(in srgb,var(--good) 12%,transparent); border:1px solid color-mix(in srgb,var(--good) 30%,transparent)}
.status.partial{color:var(--warn); background:color-mix(in srgb,var(--warn) 12%,transparent); border:1px solid color-mix(in srgb,var(--warn) 30%,transparent)}
.status.no{color:var(--danger); background:color-mix(in srgb,var(--danger) 12%,transparent); border:1px solid color-mix(in srgb,var(--danger) 30%,transparent)}

.content figure{margin:20px 0 26px}
.content figure img{
  border:1px solid var(--border); border-radius:14px; box-shadow:0 8px 28px rgba(20,24,32,.08);
  background:var(--surface);
}
.content figcaption{
  margin-top:9px; padding-left:10px; border-left:2px solid var(--accent);
  font-size:12px; color:var(--muted); line-height:1.55;
}
.code-wrap{position:relative; margin:14px 0 20px}
.code-wrap pre{
  margin:0; padding:16px 16px; background:#11151b; color:#e7ebf2; border-radius:12px;
  overflow-x:auto; font-family:var(--mono); font-size:12.5px; line-height:1.7; border:1px solid #262d38;
}
.code-wrap code{background:none; padding:0; color:inherit; font-size:inherit}
.copy-btn{
  position:absolute; right:9px; top:9px; font-size:11px; color:#aeb6c4;
  background:#1b212a; border:1px solid #303948; border-radius:7px; padding:3px 8px;
  cursor:pointer; font-family:var(--body);
}
.copy-btn:hover{color:#fff; border-color:#4a5668}

.toc-mobile{display:none; margin:22px 0 0; background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:12px 16px}
.toc-mobile summary{cursor:pointer; font-size:13px; font-weight:600; color:var(--fg)}
.toc-mobile .toc{padding-top:10px}
.toc-mobile a{display:block; font-size:12.5px; color:var(--muted); padding:4px 0; border-bottom:0}
.toc-mobile a.lv3{padding-left:18px; font-size:12px}

.to-top{
  position:fixed; right:max(16px,env(safe-area-inset-right,0px)); bottom:max(18px,env(safe-area-inset-bottom,0px));
  width:38px; height:38px; border-radius:50%; border:1px solid var(--border);
  background:var(--surface); color:var(--muted); cursor:pointer; display:none;
  font-size:16px; box-shadow:0 6px 18px rgba(0,0,0,.12); z-index:45;
}
.to-top.show{display:block}
.to-top:hover{color:var(--accent); border-color:var(--accent)}

.foot{
  max-width:1280px; margin:54px auto 0; padding-top:18px; border-top:1px solid var(--border);
  color:var(--faint); font-size:12px; display:flex; justify-content:space-between; gap:16px; flex-wrap:wrap;
}

@media (max-width:1080px){
  .layout{grid-template-columns:1fr; gap:0}
  .toc-aside{display:none}
  .toc-mobile{display:block}
  .role-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .topnav{display:none}
}
@media (max-width:640px){
  .page{font-size:14.5px}
  .hero{padding:24px 20px 22px; border-radius:16px}
  .hero h1{font-size:29px; word-break:keep-all; overflow-wrap:normal}
  .role-grid{grid-template-columns:1fr}
  .content h2{font-size:25px; gap:9px}
  .content h3{font-size:17.5px}
  table{min-width:520px}
  .foot{flex-direction:column}
}
@media (prefers-reduced-motion:reduce){
  html{scroll-behavior:auto}
  *{transition:none!important; animation:none!important}
}
"""


def build_html(body: str, toc: list[dict]) -> str:
    toc_html = "".join(
        f'<a class="lv{item["level"]}" href="#{item["id"]}">{html.escape(item["text"])}</a>'
        for item in toc
    )
    role_cards = """
      <div class="role-grid">
        <a class="role-card role-admin" href="#sec-2"><span class="dot"></span><span class="name">管理员</span><span class="desc">配人、配员工、配数据权限，看审计与运营总览。</span><span class="go">进入管理员任务线 →</span></a>
        <a class="role-card role-analyst" href="#sec-3"><span class="dot"></span><span class="name">数据分析师</span><span class="desc">一句话查工时，出 5 KPI 大屏与深度报告。</span><span class="go">进入分析师任务线 →</span></a>
        <a class="role-card role-sales" href="#sec-4"><span class="dot"></span><span class="name">销售</span><span class="desc">拜访前拿到客户 360、需求预判与话术。</span><span class="go">进入销售任务线 →</span></a>
        <a class="role-card role-legal" href="#sec-5"><span class="dot"></span><span class="name">法务</span><span class="desc">上传合同，风险分级、HITL 审批、修订版 docx。</span><span class="go">进入法务任务线 →</span></a>
      </div>
    """
    return f"""<title>DataClaw 角色手册</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>{CSS}</style>
<div class="page">
  <header class="topbar">
    <div class="brand"><span class="mark">D</span><span>DataClaw<small>角色操作手册</small></span></div>
    <nav class="topnav">
      <a href="#sec-1">上手</a>
      <a href="#sec-2">管理员</a>
      <a href="#sec-3">分析师</a>
      <a href="#sec-4">销售</a>
      <a href="#sec-5">法务</a>
      <a href="#sec-7">安全验收</a>
      <a href="#sec-9">能力对照</a>
    </nav>
    <button class="theme-btn" id="themeBtn" type="button" aria-label="切换深浅色">切换主题</button>
  </header>

  <div class="layout">
    <aside class="toc-aside"><div class="toc-inner">
      <p class="toc-title">目录</p>
      <nav class="toc">{toc_html}</nav>
    </div></aside>

    <main>
      <section class="hero">
        <div class="kicker">DataClaw V1.0 · 企业级数字员工平台</div>
        <h1>DataClaw 角色操作手册</h1>
        <p class="lead">30 分钟走完一次「登录 → 配置 → 对话 → 交付 → 审计」。同一条产品主线，四种角色的用法：管理员配好平台，分析师出大屏，销售拿拜访指南，法务审完合同。</p>
        <div class="meta">
          <span class="chip"><b>4</b> 个角色任务线</span>
          <span class="chip"><b>3</b> 条标杆场景</span>
          <span class="chip"><b>36</b> 张实拍截图</span>
          <span class="chip"><b>26/26</b> 黑盒验收通过</span>
          <span class="chip">离线可跑 · 无需 LLM Key</span>
        </div>
        {role_cards}
      </section>

      <details class="toc-mobile"><summary>目录</summary><nav class="toc">{toc_html}</nav></details>

      <div class="content">
        {body}
      </div>
    </main>
  </div>

  <footer class="foot">
    <span>DataClaw V1.0 · 2026-10 · 上海汉得信息技术股份有限公司</span>
    <span>截图来自真实浏览器操作；演示数据均为模拟数据。</span>
  </footer>
  <button class="to-top" id="toTop" type="button" aria-label="回到顶部">↑</button>
</div>

<script>
(function(){{
  var root=document.documentElement;
  try{{ var saved=localStorage.getItem('dc-theme'); if(saved) root.dataset.theme=saved; }}catch(e){{}}
  var btn=document.getElementById('themeBtn');
  function label(){{
    var dark = root.dataset.theme === 'dark' || (!root.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches);
    btn.textContent = dark ? '浅色' : '深色';
  }}
  label();
  btn.addEventListener('click',function(){{
    var dark = root.dataset.theme === 'dark' || (!root.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches);
    root.dataset.theme = dark ? 'light' : 'dark';
    try{{ localStorage.setItem('dc-theme', root.dataset.theme); }}catch(e){{}}
    label();
  }});

  // 代码块复制
  document.querySelectorAll('.code-wrap').forEach(function(wrap){{
    var pre=wrap.querySelector('pre'); if(!pre) return;
    var b=document.createElement('button'); b.className='copy-btn'; b.type='button'; b.textContent='复制';
    b.addEventListener('click',async function(){{
      var text=pre.innerText;
      try{{ await navigator.clipboard.writeText(text); b.textContent='已复制'; }}
      catch(e){{
        var r=document.createRange(); r.selectNodeContents(pre);
        var s=getSelection(); s.removeAllRanges(); s.addRange(r);
        b.textContent='请按 Ctrl+C';
      }}
      setTimeout(function(){{ b.textContent='复制'; }},1600);
    }});
    wrap.appendChild(b);
  }});

  // 返回顶部
  var top=document.getElementById('toTop');
  window.addEventListener('scroll',function(){{ top.classList.toggle('show', window.scrollY>700); }},{{passive:true}});
  top.addEventListener('click',function(){{ window.scrollTo({{top:0,behavior:'smooth'}}); }});

  // TOC 当前项
  var links=[].slice.call(document.querySelectorAll('.toc a'));
  var map={{}}; links.forEach(function(a){{ map[a.getAttribute('href').slice(1)]=a; }});
  if('IntersectionObserver' in window){{
    var obs=new IntersectionObserver(function(entries){{
      entries.forEach(function(en){{
        if(en.isIntersecting){{ links.forEach(function(a){{a.classList.remove('on');}}); var a=map[en.target.id]; if(a) a.classList.add('on'); }}
      }});
    }},{{rootMargin:'-15% 0px -75% 0px'}});
    document.querySelectorAll('h2[id],h3[id]').forEach(function(h){{ obs.observe(h); }});
  }}
}})();
</script>
"""


def main() -> None:
    md = MD_PATH.read_text(encoding="utf-8")
    body, toc = convert(md)
    # 给图片包一层 figure + figcaption（convert 里是裸 img）
    def fig(m: re.Match) -> str:
        img_tag, alt = m.group(1), m.group(2)
        return f'<figure>{img_tag}<figcaption>{html.escape(alt)}</figcaption></figure>'

    body = re.sub(r'(<img[^>]+alt="([^"]*)"[^>]*>)', fig, body)
    html_out = build_html(body, toc)
    OUT_PATH.write_text(html_out, encoding="utf-8")
    size = OUT_PATH.stat().st_size / 1024 / 1024
    print(f"wrote {OUT_PATH} ({size:.2f} MB), sections={len([t for t in toc if t['level']==2])}")


if __name__ == "__main__":
    main()
