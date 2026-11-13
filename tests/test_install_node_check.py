"""
deploy/install.sh decides whether to install Node.js with its node_ok()
function. Run that function, lifted verbatim from the script, against stub
`node` binaries reporting different versions.
"""
import re
import subprocess
from pathlib import Path

import pytest

INSTALL = Path(__file__).resolve().parent.parent / "deploy" / "install.sh"


def node_ok_source():
    match = re.search(r"^NODE_MIN_MAJOR=.*?^}\n", INSTALL.read_text(), re.S | re.M)
    assert match, "node_ok() not found in install.sh"
    return match.group(0)


@pytest.mark.parametrize("version, npm, expected", [
    ("18.19.0", True, "install"),     # Raspberry Pi OS Bookworm's apt package
    ("20.19.2", True, "ok"),
    ("24.22.0", True, "ok"),
    ("24.22.0", False, "install"),    # node without npm cannot build
    (None, False, "install"),         # Raspberry Pi OS Lite: no node at all
])
def test_node_ok(tmp_path, version, npm, expected):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    if version:
        node = bindir / "node"
        node.write_text(f'#!/bin/sh\n[ "$1" = "-p" ] && echo {version.split(".")[0]}\n')
        node.chmod(0o755)
    if npm:
        (bindir / "npm").write_text("#!/bin/sh\n")
        (bindir / "npm").chmod(0o755)
    script = tmp_path / "check.sh"
    script.write_text(node_ok_source() + "if node_ok; then echo ok; else echo install; fi\n")
    result = subprocess.run(["/bin/bash", str(script)], capture_output=True, text=True,
                            env={"PATH": str(bindir)})
    assert result.stdout.strip() == expected, result.stderr
