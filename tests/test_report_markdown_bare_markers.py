from __future__ import annotations

import signal

import pytest

from foundry.report_documents import report_nodes_from_markdown


@pytest.fixture
def deadline():
    def _timeout(signum, frame):
        raise TimeoutError("report_nodes_from_markdown did not return")

    previous = signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(5)
    yield
    signal.alarm(0)
    signal.signal(signal.SIGALRM, previous)


@pytest.mark.parametrize("marker", ["#", "# ", "###### ", "-", "- ", "* ", "1. ", "2) "])
def test_a_line_with_only_a_block_marker_does_not_hang(deadline, marker):
    nodes = report_nodes_from_markdown(f"正文第一段\n\n{marker}\n\n正文第二段")

    texts = [
        part.get("text", "")
        for node in nodes
        for part in node.get("content", [])
        if isinstance(part, dict)
    ]
    assert "正文第一段" in texts and "正文第二段" in texts


def test_real_headings_and_lists_after_a_paragraph_still_split_it(deadline):
    nodes = report_nodes_from_markdown("第一段\n# 标题\n- 条目")

    assert [node["type"] for node in nodes] == ["paragraph", "heading", "bulletList"]
