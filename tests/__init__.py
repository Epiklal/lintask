"""Keeps every test away from the real settings of whoever runs them: QSettings and
QStandardPaths read XDG_CONFIG_HOME, and importing this package comes before any test
module creates a Settings object."""
import atexit
import os
import tempfile

_config = tempfile.TemporaryDirectory(prefix="lintask-tests-")
atexit.register(_config.cleanup)
os.environ["XDG_CONFIG_HOME"] = _config.name
# The main window starts the history recorder, which must not write into the real one.
os.environ["XDG_STATE_HOME"] = os.path.join(_config.name, "state")
os.environ.pop("STATE_DIRECTORY", None)
