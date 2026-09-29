"""Every file the shipped config names is where the engine looks for it.

A relative path in the config is read from the engine's project root, the repository root
(core/paths.project_root). `llm.abbreviationsPath` and `llm.domainContextPath` said
`config/abbreviations.txt` and `config/domain.txt` after the files had moved to engine/config/,
and a missing file reads as "none" without a word: the DOCX's Terms section was always the
placeholder, and no description prompt ever carried the domain brief (the task 3.14 anchor
against invented audio/video vocabulary).
"""
import json
import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ENGINE = os.path.join(_ROOT, "engine")
if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

pytestmark = pytest.mark.unit

with open(os.path.join(_ENGINE, "config", "config.defaults.json"), encoding="utf-8") as _f:
    DEFAULTS = json.load(_f)


def _relative_files(node, key=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _relative_files(v, f"{key}.{k}" if key else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _relative_files(v, f"{key}[{i}]")
    elif isinstance(node, str) and re.search(r"\.(txt|json|jsonc|csv)$", node) and not os.path.isabs(node):
        yield key, node


@pytest.mark.parametrize("key, path", list(_relative_files(DEFAULTS)))
def test_every_file_the_defaults_name_is_there(key, path):
    from core.paths import paths
    assert os.path.normcase(paths().project_root) == os.path.normcase(_ROOT)
    assert os.path.isfile(os.path.join(_ROOT, path)), f"{key}: {path} is not in the repository"


def test_the_description_prompts_get_the_domain_brief():
    import llm_enrichment as le
    brief = le.load_domain_context(_ROOT, DEFAULTS)
    assert "flash" in brief.lower()


def test_every_reader_gets_the_same_abbreviations():
    # The DOCX / SWE.4 exporters and unit headers read from the project root, the model step
    # read from engine/ and the description prompts from the analyzed C++ repository - so one
    # path could never serve them all. Now every reader starts from the analyzer's root.
    import llm_enrichment as le
    from docx_common import load_abbreviations
    from api.services.doc_render import _load_abbreviations
    assert os.path.normcase(le.analyzer_root()) == os.path.normcase(_ROOT)
    docx_view = load_abbreviations(_ROOT, DEFAULTS)
    assert docx_view
    assert le.load_abbreviations(le.analyzer_root(), DEFAULTS) == docx_view      # prompts
    assert _load_abbreviations(DEFAULTS) == docx_view                           # the web page
