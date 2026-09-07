"""Real kernel-isolation smoke check; no model calls or external network traffic."""
import asyncio
import os
import tempfile
from pathlib import Path

from codeweaver.process import execute


async def main():
    with tempfile.TemporaryDirectory(prefix="codeweaver-sandbox-check-") as directory:
        root = Path(directory)
        (root / ".env").write_text("TEST_SENTINEL_NOT_A_CREDENTIAL")
        (root / ".codeweaver").mkdir()
        namespace = os.readlink("/proc/self/ns/net")
        program = """
import os, sys
from pathlib import Path
assert os.readlink('/proc/self/ns/net') != sys.argv[1]
assert not Path('/home').exists()
assert Path('.env').read_text() == ''
Path('allowed.txt').write_text('ok')
Path('.codeweaver/hidden-write').write_text('isolated')
print('isolated command passed')
"""
        result = await execute(root, ["/usr/bin/python3", "-c", program, namespace], 10)
        assert result["exit_code"] == 0, result
        assert (root / "allowed.txt").read_text() == "ok"
        assert not (root / ".codeweaver/hidden-write").exists()
        assert (root / ".env").read_text() == "TEST_SENTINEL_NOT_A_CREDENTIAL"
        print("PASS: distinct network namespace, hidden credentials, isolated control writes, permitted workspace write")


if __name__ == "__main__":
    asyncio.run(main())
