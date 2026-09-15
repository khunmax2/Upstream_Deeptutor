"""The upload ceiling the go-live nginx script puts in `location /deepwitya`.

Found 2026-09-15: production answered 413 to every DeepWitya upload over 1 MB,
because the cutover swapped the block's port and never carried the ceiling
the preview had. These pin the edit itself (deploy/nginx_upload_ceiling.py)
and that --cutover keeps making it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"


def _load():
    # deploy/ is not a package; load the file by path. It must be registered
    # before it runs: @dataclass looks its module up in sys.modules.
    spec = importlib.util.spec_from_file_location(
        "nginx_upload_ceiling", DEPLOY / "nginx_upload_ceiling.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ceiling = _load()

# The shape of the host's :443 server (sites-available/sansarnnews-ssl) as the
# host reported it on 2026-09-15: another team's upload location with its own
# ceiling, the /deepwitya block with none, the studio include after it.
HOST = """\
server {
    listen 443 ssl;
    server_name 203.185.144.41;

    location ^~ /sansarn-research-helper/api/upload {
        client_max_body_size 10m;
        proxy_pass http://127.0.0.1:9100;
    }

    location /deepwitya {
        proxy_pass http://127.0.0.1:10320;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_buffering off;
        proxy_read_timeout 3600s;
    }

    # DeepWitya Course Studio — see deploy/apply-nginx-golive.sh
    include /etc/nginx/snippets/deepwitya-studio.conf;
}
"""


def test_the_host_block_has_no_ceiling_today():
    assert ceiling.ceilings(HOST) == []


def test_apply_adds_two_lines_inside_the_block_and_nothing_else():
    new, what = ceiling.apply(HOST)
    assert "200m" in what
    added = [line for line in new.splitlines() if line not in HOST.splitlines()]
    assert added == [f"        {ceiling.MARK}", "        client_max_body_size 200m;"]
    assert ceiling.ceilings(new) == ["200m"]
    # the other team's location keeps its own ceiling
    assert "        client_max_body_size 10m;" in new
    # inside the block, right after its opening line
    block = new[new.index("location /deepwitya {") :]
    assert block.splitlines()[2] == "        client_max_body_size 200m;"


def test_apply_twice_changes_nothing_the_second_time():
    once, _ = ceiling.apply(HOST)
    twice, what = ceiling.apply(once)
    assert twice == once
    assert "อยู่แล้ว" in what


def test_apply_raises_a_ceiling_set_by_hand_instead_of_adding_a_second():
    by_hand = HOST.replace(
        "        proxy_pass http://127.0.0.1:10320;\n",
        "        proxy_pass http://127.0.0.1:10320;\n        client_max_body_size 50m;\n",
    )
    new, what = ceiling.apply(by_hand)
    assert ceiling.ceilings(new) == ["200m"]
    assert "50m → 200m" in what
    assert ceiling.MARK not in new


def test_remove_takes_out_exactly_what_apply_added():
    applied, _ = ceiling.apply(HOST)
    removed, changed = ceiling.remove(applied)
    assert changed
    assert removed == HOST
    assert ceiling.remove(HOST) == (HOST, False)


def test_the_studio_and_old_blocks_are_not_the_deepwitya_block():
    only_others = """\
server {
    location /deepwitya/studio {
        proxy_pass http://127.0.0.1:10330;
    }
    location /deepwitya2 {
        proxy_pass http://127.0.0.1:10320;
    }
}
"""
    with pytest.raises(ceiling.Refused):
        ceiling.apply(only_others)


def test_refuses_what_it_cannot_edit_safely():
    with pytest.raises(ceiling.Refused):
        ceiling.apply(HOST + HOST)  # two /deepwitya blocks
    with pytest.raises(ceiling.Refused):
        ceiling.apply(HOST, "200 MB")
    with pytest.raises(ceiling.Refused):
        ceiling.apply("server {\n    location /deepwitya {\n        proxy_pass x;\n")


def test_the_command_line_checks_applies_and_removes(tmp_path, capsys):
    conf = tmp_path / "sansarnnews-ssl"
    conf.write_text(HOST, encoding="utf-8")
    assert ceiling.main([str(conf), "--check"]) == 0
    assert "1m" in capsys.readouterr().out
    assert ceiling.main([str(conf), "--apply", "200m"]) == 0
    assert ceiling.ceilings(conf.read_text(encoding="utf-8")) == ["200m"]
    assert ceiling.main([str(conf), "--remove"]) == 0
    assert conf.read_text(encoding="utf-8") == HOST
    assert ceiling.main([str(tmp_path / "missing-mode")]) == 1


def _case(script: str, mode: str) -> str:
    start = script.index(f"  {mode})")
    return script[start : script.index(";;", start)]


def test_cutover_carries_the_ceiling_and_revert_takes_it_back():
    script = (DEPLOY / "apply-nginx-golive.sh").read_text(encoding="utf-8")
    assert "upload_ceiling --apply" in _case(script, "--cutover")
    assert "upload_ceiling --remove" in _case(script, "--revert")
    assert "upload_ceiling --apply" in _case(script, "--upload-ceiling")
