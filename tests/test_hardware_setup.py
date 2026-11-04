"""The sudo setup and the root helper it allows. Nothing here needs or uses real sudo:
the generated script runs against a stub `sudo` that only records its arguments.
"""
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import hardware_setup
from app.hardware_setup import (
    HELPER_TARGET, LEGACY_HELPER, LEGACY_RAPL_UDEV, LEGACY_SUDOERS, PACKAGED_HELPERS,
    RAPL_UDEV_TARGET, SUDOERS_TARGET,
)
from app.i18n import language_override

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / "scripts" / "lintask-smartctl"
FAKE_SUDO = """#!/bin/sh
echo "$*" >> "$LOG_DIR/sudo.log"
if [ "$1" = visudo ]; then
    cp "$3" "$LOG_DIR/rule"
    exit "${VISUDO_RC:-0}"
fi
"""


def write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def block_device() -> str | None:
    for name in sorted(os.listdir("/sys/class/block")) if os.path.isdir("/sys/class/block") else []:
        if os.path.exists(f"/dev/{name}") and stat.S_ISBLK(os.stat(f"/dev/{name}").st_mode):
            return name
    return None


class TestSudoRule(unittest.TestCase):
    def script(self, helper=HELPER_TARGET, source="/src/helper", user="alice", group="alice"):
        with mock.patch.object(hardware_setup, "_setup_helper", return_value=helper):
            return hardware_setup.setup_script(source, user, group)

    def test_rule_allows_only_the_helper(self):
        for helper in (*PACKAGED_HELPERS, HELPER_TARGET):
            with self.subTest(helper=helper):
                rule = f"alice ALL=(root) NOPASSWD: {helper} *"
                self.assertIn(shlex.quote(rule), self.script(helper))
                self.assertNotIn("NOPASSWD: ALL", self.script(helper))

    def test_rule_is_checked_before_it_is_installed(self):
        script = self.script()
        install = f'sudo install -m 0440 -o root -g root "$tmp" {SUDOERS_TARGET}'
        self.assertIn(f'sudo visudo -cf "$tmp" && {install}', script)

    def test_packaged_helper_is_not_overwritten(self):
        self.assertNotIn("-m 0755", self.script(PACKAGED_HELPERS[0]))
        self.assertIn(f"-m 0755 /src/helper {HELPER_TARGET}", self.script(HELPER_TARGET))

    def test_helper_gets_the_interpreter_of_a_system_without_bin_bash(self):
        bash = "/run/current-system/sw/bin/bash"
        with mock.patch.object(hardware_setup, "_system_binary", return_value=bash):
            script = self.script()
        expression = f"1s|.*|#!{bash} -p|"
        self.assertIn(f"[ -x /bin/bash ] || sudo sed -i {shlex.quote(expression)} {HELPER_TARGET}",
                      script)
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "helper"
            copy.write_text(HELPER.read_text())
            subprocess.run(["sed", "-i", expression, str(copy)], check=True)
            before, after = HELPER.read_text().split("\n", 1), copy.read_text().split("\n", 1)
        self.assertEqual(after[0], f"#!{bash} -p")
        self.assertEqual(after[1], before[1])

    def test_packaged_helper_keeps_its_interpreter(self):
        self.assertNotIn("sudo sed -i", self.script(PACKAGED_HELPERS[0]))

    def test_paths_and_names_are_shell_quoted(self):
        source = "/home/a b/$(touch pwned)/helper"
        group = "a b;touch pwned"
        script = self.script(source=source, group=group)
        self.assertIn(shlex.quote(source), script)
        self.assertIn(f"sudo chgrp {shlex.quote(group)} ", script)

    def test_generated_script_parses(self):
        subprocess.run(["bash", "-n"], input=self.script(), text=True, check=True)


class TestSetupScriptRun(unittest.TestCase):
    def run_script(self, visudo_rc=0, language="en"):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        write_executable(root / "sudo", FAKE_SUDO)
        with (mock.patch.object(hardware_setup, "_setup_helper", return_value=HELPER_TARGET),
              language_override(language)):
            script = hardware_setup.setup_script(str(HELPER), "alice", "alice")
        result = subprocess.run(
            ["bash", "-c", script], stdin=subprocess.DEVNULL, capture_output=True, text=True,
            env={"PATH": f"{root}:/usr/bin:/bin", "LOG_DIR": str(root),
                 "VISUDO_RC": str(visudo_rc), "HOME": str(root)})
        return result, (root / "sudo.log").read_text().splitlines(), root

    def test_valid_rule_gets_installed(self):
        result, sudo_calls, root = self.run_script()
        self.assertIn("SMART and memory data can now be read", result.stdout)
        self.assertTrue(any(SUDOERS_TARGET in call for call in sudo_calls))
        self.assertEqual((root / "rule").read_text(),
                         f"alice ALL=(root) NOPASSWD: {HELPER_TARGET} *\n")

    def test_messages_follow_the_language(self):
        result, _, _ = self.run_script(language="de")
        self.assertIn("SMART- und RAM-Daten können jetzt gelesen werden", result.stdout)
        result, _, _ = self.run_script(visudo_rc=1, language="de")
        self.assertIn("es wurde keine sudo-Regel installiert", result.stdout)

    def test_rule_rejected_by_visudo_is_not_installed(self):
        result, sudo_calls, _ = self.run_script(visudo_rc=1)
        self.assertIn("no sudo rule was installed", result.stdout)
        self.assertFalse(any(SUDOERS_TARGET in call for call in sudo_calls))

    def test_setup_replaces_the_rule_from_before_the_rename(self):
        _, sudo_calls, _ = self.run_script()
        self.assertIn(f"rm -f {LEGACY_SUDOERS} {LEGACY_HELPER}", sudo_calls)

    def test_rejected_rule_keeps_the_one_from_before_the_rename(self):
        _, sudo_calls, _ = self.run_script(visudo_rc=1)
        self.assertFalse(any(LEGACY_SUDOERS in call for call in sudo_calls))


# What sudo prints for a user with a full sudo rule and the rule from before the rename.
LEGACY_LISTING = f"""Passende Defaults-Einträge für alice auf host:
    env_reset, mail_badpass, secure_path=/usr/sbin\\:/usr/bin

Der Benutzer alice darf die folgenden Befehle auf host ausführen:
    (ALL : ALL) ALL
    (root) NOPASSWD: {LEGACY_HELPER} *
"""


class TestPasswordlessCommands(unittest.TestCase):
    def test_rule_that_asks_for_the_password_does_not_count(self):
        self.assertEqual(hardware_setup._passwordless_commands("    (ALL : ALL) ALL\n"), set())

    def test_command_without_its_arguments(self):
        self.assertEqual(hardware_setup._passwordless_commands(LEGACY_LISTING), {LEGACY_HELPER})

    def test_tag_holds_for_all_commands_of_the_line(self):
        listing = "    (root) NOPASSWD: /a *, /b\n"
        self.assertEqual(hardware_setup._passwordless_commands(listing), {"/a", "/b"})

    def test_other_tags_are_skipped(self):
        for line in ("(root) SETENV: NOPASSWD: /a", "(root) NOPASSWD: SETENV: /a"):
            with self.subTest(line=line):
                self.assertEqual(hardware_setup._passwordless_commands(line), {"/a"})

    def test_passwd_tag_ends_it(self):
        listing = "    (root) NOPASSWD: /a, PASSWD: /b, /c\n"
        self.assertEqual(hardware_setup._passwordless_commands(listing), {"/a"})

    def test_all_commands(self):
        self.assertEqual(hardware_setup._passwordless_commands("(ALL) NOPASSWD: ALL"), {"ALL"})


class TestHelperChoice(unittest.TestCase):
    def helpers(self, listing, *executables):
        """(sudo_helper, smart_helper) with these files installed and this sudo listing."""
        with (mock.patch.object(hardware_setup.os, "access",
                                side_effect=lambda path, _mode: path in executables),
              mock.patch.object(hardware_setup, "_sudo_listing", return_value=listing)):
            return hardware_setup.sudo_helper(), hardware_setup.smart_helper()

    def test_packaged_helper_without_its_rule_is_not_run(self):
        self.assertEqual(self.helpers("    (ALL : ALL) ALL\n", PACKAGED_HELPERS[0]), (None, None))

    def test_rule_from_before_the_rename_reads_only_smart_data(self):
        self.assertEqual(self.helpers(LEGACY_LISTING, PACKAGED_HELPERS[0], LEGACY_HELPER),
                         (None, LEGACY_HELPER))

    def test_rule_of_a_removed_helper_is_not_used(self):
        self.assertEqual(self.helpers(LEGACY_LISTING, PACKAGED_HELPERS[0]), (None, None))

    def test_packaged_helper_comes_first(self):
        listing = f"(root) NOPASSWD: {PACKAGED_HELPERS[0]} *\n(root) NOPASSWD: {LEGACY_HELPER} *"
        self.assertEqual(self.helpers(listing, PACKAGED_HELPERS[0], LEGACY_HELPER),
                         (PACKAGED_HELPERS[0], PACKAGED_HELPERS[0]))

    def test_new_helper_comes_before_the_old_one(self):
        listing = f"(root) NOPASSWD: {HELPER_TARGET} *\n(root) NOPASSWD: {LEGACY_HELPER} *"
        self.assertEqual(self.helpers(listing, HELPER_TARGET, LEGACY_HELPER),
                         (HELPER_TARGET, HELPER_TARGET))

    def test_rule_for_all_commands_is_enough(self):
        self.assertEqual(self.helpers("(ALL) NOPASSWD: ALL", PACKAGED_HELPERS[0]),
                         (PACKAGED_HELPERS[0], PACKAGED_HELPERS[0]))

    def test_setup_never_writes_a_rule_for_the_old_helper(self):
        with mock.patch.object(hardware_setup.os, "access",
                               side_effect=lambda path, _mode: path == LEGACY_HELPER):
            script = hardware_setup.setup_script("/src/helper", "alice", "alice")
        self.assertIn(f"NOPASSWD: {HELPER_TARGET} *", script)
        self.assertNotIn(f"NOPASSWD: {LEGACY_HELPER}", script)


class TestSudoListing(unittest.TestCase):
    def setUp(self):
        self.modified = 1
        self.now = 1000.0
        self.result = subprocess.CompletedProcess([], 0, stdout=LEGACY_LISTING)
        patches = [
            mock.patch.object(hardware_setup, "_sudo_listing_cache", None),
            mock.patch.object(hardware_setup, "_modified", side_effect=lambda _path: self.modified),
            mock.patch.object(hardware_setup.time, "monotonic", side_effect=lambda: self.now),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        run = mock.patch.object(hardware_setup.subprocess, "run",
                                side_effect=lambda *_args, **_kwargs: self.result)
        self.run_mock = run.start()
        self.addCleanup(run.stop)

    def test_sudo_is_asked_once(self):
        self.assertEqual(hardware_setup._sudo_listing(), LEGACY_LISTING)
        self.assertEqual(hardware_setup._sudo_listing(), LEGACY_LISTING)
        self.assertEqual(self.run_mock.call_count, 1)
        self.assertEqual(self.run_mock.call_args.args[0], ["sudo", "-n", "-l"])

    def test_changed_rules_are_read_again(self):
        hardware_setup._sudo_listing()
        self.modified = 2
        hardware_setup._sudo_listing()
        self.assertEqual(self.run_mock.call_count, 2)

    def test_old_listing_is_read_again(self):
        hardware_setup._sudo_listing()
        self.now += hardware_setup._SUDO_LISTING_MAX_AGE
        hardware_setup._sudo_listing()
        self.assertEqual(self.run_mock.call_count, 2)

    def test_refused_listing_is_empty_and_not_retried_at_once(self):
        self.result = subprocess.CompletedProcess([], 1, stdout="")
        self.assertEqual(hardware_setup._sudo_listing(), "")
        hardware_setup._sudo_listing()
        self.assertEqual(self.run_mock.call_count, 1)

    def test_failing_sudo_gives_an_empty_listing(self):
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("sudo", 3)):
            with self.subTest(error=error):
                hardware_setup._sudo_listing_cache = None
                self.run_mock.side_effect = error
                self.assertEqual(hardware_setup._sudo_listing(), "")


class TestRaplRule(unittest.TestCase):
    def test_rule_uses_absolute_paths_and_read_only_access(self):
        rule = hardware_setup.rapl_udev_rule("alice")
        self.assertRegex(rule, r'RUN\+="/\S*chgrp alice ')
        self.assertRegex(rule, r'RUN\+="/\S*chmod g\+r ')
        self.assertNotIn("g+w", rule)
        self.assertNotIn("a+", rule)

    def test_rule_target_is_a_udev_rule(self):
        self.assertTrue(RAPL_UDEV_TARGET.startswith("/etc/udev/rules.d/"))

    def test_old_rule_goes_only_after_the_new_one_is_installed(self):
        steps = hardware_setup._rapl_steps("alice")
        install = next(i for i, step in enumerate(steps) if f"{RAPL_UDEV_TARGET}; then" in step)
        self.assertEqual(steps[install + 1].strip(), f"sudo rm -f {LEGACY_RAPL_UDEV}")

    def test_side_channel_is_named_once_the_counters_are_open(self):
        script = "\n".join(hardware_setup._rapl_steps("alice"))
        self.assertLess(script.index("sudo chmod g+r"), script.index("CVE-2020-8694"))
        self.assertLess(script.index("CVE-2020-8694"), script.index("/etc/NIXOS"))


class TestHelperScript(unittest.TestCase):
    """The only program the sudo rule allows, so every argument is hostile until checked."""

    def run_helper(self, *args, script=HELPER):
        return subprocess.run(["bash", str(script), *args], capture_output=True, text=True)

    def stubbed_helper(self):
        """The helper with its tools replaced, so a test can never reach the real ones."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for tool in ("dmidecode", "smartctl"):
            write_executable(root / tool, f'#!/bin/sh\necho {tool} "$@"\n')
        text = (HELPER.read_text()
                .replace("/usr/sbin/dmidecode /usr/bin/dmidecode", f"{root}/dmidecode")
                .replace("/usr/sbin/smartctl /usr/bin/smartctl", f"{root}/smartctl"))
        self.assertNotIn("/usr/sbin/dmidecode", text)
        self.assertNotIn("/usr/sbin/smartctl", text)
        script = root / "helper"
        script.write_text(text)
        return script

    def test_invalid_device_names_are_rejected(self):
        script = self.stubbed_helper()
        for device in ("", ".", "..", "../sda", "../../etc/passwd", "/dev/sda", "sda/", "sda;id",
                       "sda id", "$(id)", "`id`", "sda\nsda", "*", "--help", "--scan", "-a",
                       "does-not-exist", "null", "zero"):
            with self.subTest(device=device):
                result = self.run_helper(device, script=script)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("Invalid block device", result.stderr)

    def test_no_argument_is_rejected(self):
        self.assertEqual(self.run_helper(script=self.stubbed_helper()).returncode, 2)

    def test_memory_only_reads_the_memory_table(self):
        result = self.run_helper("memory", "--dump-bin", "/tmp/x", script=self.stubbed_helper())
        self.assertEqual(result.stdout.split(), ["dmidecode", "-t", "memory"])

    def test_block_device_gets_fixed_smartctl_arguments(self):
        device = block_device()
        if device is None:
            self.skipTest("no block device available")
        result = self.run_helper(device, "--scan", "-s", "on", script=self.stubbed_helper())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.split(), ["smartctl", "--all", "--json=o", f"/dev/{device}"])

    def run_pageout(self, *pids, sudo_uid=None):
        env = {key: value for key, value in os.environ.items() if key != "SUDO_UID"}
        if sudo_uid is not None:
            env["SUDO_UID"] = str(sudo_uid)
        return subprocess.run(["bash", str(HELPER), "pageout", *pids], capture_output=True,
                              text=True, env=env)

    def test_pageout_rejects_invalid_calls(self):
        for pids, sudo_uid in (((), 1000), (("1",), None), (("1",), "root"), (("1;id",), 1000),
                               (("1", "$(id)"), 1000), (("-1",), 1000), (("",), 1000)):
            with self.subTest(pids=pids, sudo_uid=sudo_uid):
                result = self.run_pageout(*pids, sudo_uid=sudo_uid)
                self.assertEqual(result.returncode, 5)
                self.assertEqual(result.stdout, "")

    def test_pageout_leaves_processes_of_other_users_alone(self):
        # Checked before any memory is touched, so this also holds when running as root.
        child = subprocess.Popen(["sleep", "60"])
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        result = self.run_pageout(str(child.pid), sudo_uid=os.getuid() + 1)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout.split(), ["paged=0", "refused=1"])

    def test_pageout_leaves_undumpable_processes_alone(self):
        # Like ssh-agent: its secrets must not reach swap, whoever owns it.
        code = ("import ctypes, sys, time; ctypes.CDLL(None).prctl(4, 0, 0, 0, 0); "
                "print('ready', flush=True); time.sleep(60)")
        child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        self.addCleanup(child.stdout.close)
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        self.assertEqual(child.stdout.readline().strip(), "ready")
        result = self.run_pageout(str(child.pid), sudo_uid=os.getuid())
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout.split(), ["paged=0", "refused=1"])

    def test_pageout_of_a_finished_process_is_no_error(self):
        child = subprocess.Popen(["true"])
        child.wait()
        result = self.run_pageout(str(child.pid), sudo_uid=os.getuid())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.split(), ["paged=0", "refused=0"])

    def test_drop_caches_without_root_is_refused(self):
        if os.getuid() == 0:
            self.skipTest("would really empty the cache")
        self.assertEqual(self.run_helper("drop-caches").returncode, 3)

    def test_environment_of_the_caller_decides_nothing(self):
        # sudo without secure_path passes on PATH. Started directly, so the shebang counts.
        if not os.access("/bin/bash", os.X_OK):
            self.skipTest("no /bin/bash")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        marker = root / "caller-code-ran"
        for tool in ("bash", "sync"):
            write_executable(root / tool, f'#!/bin/sh\ntouch "{marker}"\n')
        write_executable(root / "bash_env", f'touch "{marker}"\n')
        target = root / "drop_caches"
        script = root / "helper"
        write_executable(script, HELPER.read_text().replace("/proc/sys/vm/drop_caches", str(target)))
        result = subprocess.run(
            [str(script), "drop-caches"], capture_output=True, text=True,
            env={"PATH": str(root), "BASH_ENV": str(root / "bash_env"),
                 "BASH_FUNC_sync%%": f'() {{ touch "{marker}"; }}'})
        self.assertFalse(marker.exists())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_text(), "3\n")


if __name__ == "__main__":
    unittest.main()
