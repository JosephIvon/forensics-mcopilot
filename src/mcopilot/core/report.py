"""统一报告输出：Markdown 为主，HTML 为可归档/可转发的第二形态。

所有智能体共用，保证交付物长得一样、可以被同一套脚本批量生成。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .util import fmt, img_b64, md_to_html, write_text


@dataclass
class Report:
    title: str
    subtitle: str = ""
    sections: list[tuple[str, str]] = field(default_factory=list)
    images: list[Path] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def add(self, heading: str, body: str) -> None:
        self.sections.append((heading, body))

    # -- 渲染 ----------------------------------------------------------
    def to_markdown(self) -> str:
        parts = [f"# {self.title}"]
        if self.subtitle:
            parts.append(f"> {self.subtitle}")
        if self.meta:
            rows = [[k, fmt(v)] for k, v in self.meta.items()]
            from .util import md_table
            parts.append(md_table(["项", "值"], rows))
        for heading, body in self.sections:
            parts.append(f"\n## {heading}")
            if body:
                parts.append(body)
        for img in self.images:
            parts.append(f"\n![{img.stem}]({img.as_posix()})")
        return "\n".join(parts) + "\n"

    def write(self, out_dir: Path, stem: str, with_html: bool = True) -> dict[str, Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        md_path = write_text(out_dir / f"{stem}.md", self.to_markdown())
        result = {"markdown": md_path}
        if with_html:
            html = md_to_html(self.to_markdown(), self.title)
            # 图表内联为 base64，HTML 单文件可直接转发
            extra = []
            for img in self.images:
                if img.exists():
                    extra.append(f'<p><img src="data:image/png;base64,{img_b64(img)}"></p>')
            if extra:
                html = html.replace("</body>", "\n".join(extra) + "\n</body>")
            result["html"] = write_text(out_dir / f"{stem}.html", html)
        return result


def severity_badge(level: str) -> str:
    return {"高": "高", "中": "中", "低": "低"}.get(level, "低")


def kv_block(pairs: Sequence[tuple[str, Any]]) -> str:
    from .util import md_table
    return md_table(["项", "值"], [[k, fmt(v)] for k, v in pairs])


def callout(level: str, text: str) -> str:
    """GitHub 风格提示块，md 里转成 blockquote，HTML 里靠 > 样式。"""
    prefix = {"高": "🔴", "中": "🟠", "低": "🟢", "提示": "ℹ️"}.get(level, "ℹ️")
    return f"> **{prefix} {level}** {text}"
