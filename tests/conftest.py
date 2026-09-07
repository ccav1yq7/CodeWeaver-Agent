import pytest

from codeweaver.authorization import Authority
from codeweaver.capabilities import Toolbox
from codeweaver.configuration import Settings
from codeweaver.filesystem import Workspace
from codeweaver.records import Journal


@pytest.fixture
def setup_tools(tmp_path):
    journal = Journal(tmp_path)
    tools = Toolbox(Workspace(tmp_path), Authority(Settings(provider="demo", mode="workspace")), journal)
    yield tools, journal
    journal.close()
