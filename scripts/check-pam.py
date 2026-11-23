#!/usr/bin/python3
"""Exercise the installed DDM PAM stack inside the disposable ISO build root.

Never run this on a user system.  The build marker and explicit image profile
are mandatory.  No session is opened: logind/session integration needs a VM.

ctypes declarations follow the Linux-PAM application ABI in:
https://github.com/linux-pam/linux-pam/blob/v1.7.0/libpam/include/security/_pam_types.h
https://github.com/linux-pam/linux-pam/blob/v1.7.0/libpam/include/security/pam_appl.h
In particular, conversation responses must use libc allocation: PAM frees them.
"""

import ctypes as C
import grp
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import signal
import stat
import subprocess
import sys


MARKER = Path("/root/.fedora-dde-iso-build")
PROFILE = Path("/etc/fedora-dde-installer/install-profile.json")
EXPECTED_PROFILE = {"schema": 1, "selinux": "disabled", "pam": "ddm-system-login"}
LOGIN = "fdd_iso_pam_check"
UNKNOWN_LOGIN = "fdd_iso_pam_unknown"
TEST_HOME = "/nonexistent/fedora-dde-iso-pam-check"
BACKUPS = tuple(Path("/etc") / name for name in
                ("passwd-", "shadow-", "subuid-", "subgid-"))
COMMAND_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}

PAM_SUCCESS = 0
PAM_BUF_ERR = 5
PAM_PERM_DENIED = 6
PAM_AUTH_ERR = 7
PAM_USER_UNKNOWN = 10
PAM_MAXTRIES = 11
PAM_ACCT_EXPIRED = 13
PAM_CONV_ERR = 19
PAM_DISALLOW_NULL_AUTHTOK = 1
PAM_PROMPT_ECHO_OFF = 1
PAM_PROMPT_ECHO_ON = 2
PAM_ERROR_MSG = 3
PAM_TEXT_INFO = 4
PAM_MAX_NUM_MSG = 32
AUTH_DENIALS = {PAM_PERM_DENIED, PAM_AUTH_ERR, PAM_USER_UNKNOWN, PAM_MAXTRIES}


class CheckError(RuntimeError):
    """An error whose message is safe to include in the build log."""


class PamMessage(C.Structure):
    _fields_ = [("msg_style", C.c_int), ("msg", C.c_char_p)]


class PamResponse(C.Structure):
    # c_void_p preserves the malloc address instead of converting char* to bytes.
    _fields_ = [("resp", C.c_void_p), ("resp_retcode", C.c_int)]


Conversation = C.CFUNCTYPE(
    C.c_int, C.c_int, C.POINTER(C.POINTER(PamMessage)),
    C.POINTER(C.POINTER(PamResponse)), C.c_void_p,
)


class PamConv(C.Structure):
    _fields_ = [("conv", Conversation), ("appdata_ptr", C.c_void_p)]


def checked_stat(fd, path):
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_mode & 0o022 or info.st_nlink != 1):
        raise CheckError(f"unsafe ownership, permissions or file type: {path}")
    return info


def trusted_read(path, limit=4 * 1024 * 1024):
    for parent in reversed(path.parents):
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or info.st_mode & 0o022):
            raise CheckError(f"unsafe parent directory: {parent}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = checked_stat(fd, path)
        if info.st_size > limit:
            raise CheckError(f"unexpectedly large file: {path}")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise CheckError(f"unexpectedly large file: {path}")
        return data
    finally:
        os.close(fd)


def require_absent_user(name):
    try:
        pwd.getpwnam(name)
    except KeyError:
        return
    raise CheckError(f"reserved test account already exists: {name}")


def failure_directories():
    directories = {Path("/run/faillock"), Path("/var/lib/faillock")}
    try:
        config = trusted_read(Path("/etc/security/faillock.conf"), 65536).decode("utf-8")
    except FileNotFoundError:
        return directories
    for line in config.splitlines():
        key, separator, value = line.split("#", 1)[0].partition("=")
        if separator and key.strip() == "dir":
            directory = Path(value.strip())
            if not directory.is_absolute() or ".." in directory.parts:
                raise CheckError("unsafe faillock record directory")
            directories.add(directory)
    return directories


def unique_json_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise CheckError("duplicate key in the target install profile")
        value[key] = item
    return value


def check_context():
    if len(sys.argv) != 1:
        raise CheckError("this build-only check accepts no arguments")
    if os.getuid() != 0 or os.geteuid() != 0:
        raise CheckError("this build-only check requires root in the target chroot")
    # Validate the marker first, before loading PAM or preparing any mutation.
    trusted_read(MARKER, 4096)
    profile = json.loads(trusted_read(PROFILE, 4096), object_pairs_hook=unique_json_keys)
    if (not isinstance(profile, dict) or type(profile.get("schema")) is not int
            or profile != EXPECTED_PROFILE):
        raise CheckError("the target does not have the expected ISO install profile")
    for path in (Path("/etc/pam.d/ddm"), Path("/etc/pam.d/system-login")):
        if not trusted_read(path, 65536).strip():
            raise CheckError(f"empty PAM service: {path}")
    failure_dirs = failure_directories()
    for name in (LOGIN, UNKNOWN_LOGIN):
        require_absent_user(name)
        for directory in failure_dirs:
            if os.path.lexists(directory / name):
                raise CheckError("reserved PAM test name has pre-existing failure state")
    try:
        grp.getgrnam(LOGIN)
    except KeyError:
        pass
    else:
        raise CheckError("reserved test group already exists")
    for path in (TEST_HOME, f"/var/spool/mail/{LOGIN}", f"/var/mail/{LOGIN}"):
        if os.path.lexists(path):
            raise CheckError(f"reserved test path already exists: {path}")
    prefix = LOGIN.encode("ascii") + b":"
    for path in BACKUPS:
        try:
            data = trusted_read(path)
        except FileNotFoundError:
            continue
        if any(line.startswith(prefix) for line in data.splitlines()):
            raise CheckError("reserved test account already occurs in an account backup")
    return failure_dirs


def command(name, *args, input_data=None):
    executable = shutil.which(name, path=COMMAND_ENV["PATH"])
    if executable is None:
        raise CheckError(f"required build command is missing: {name}")
    try:
        result = subprocess.run(
            [executable, *args], input=input_data, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=COMMAND_ENV, timeout=45, check=False,
        )
    except subprocess.TimeoutExpired:
        raise CheckError(f"build command timed out: {name}") from None
    if result.returncode:
        # Do not echo command output or stdin: chpasswd handles a secret.
        raise CheckError(f"build command failed: {name} (exit {result.returncode})")


class Pam:
    def __init__(self):
        self.lib = C.CDLL("libpam.so.0")
        self.lib.pam_start.argtypes = [
            C.c_char_p, C.c_char_p, C.POINTER(PamConv), C.POINTER(C.c_void_p),
        ]
        self.lib.pam_start.restype = C.c_int
        for name in ("pam_authenticate", "pam_acct_mgmt", "pam_end"):
            function = getattr(self.lib, name)
            function.argtypes = [C.c_void_p, C.c_int]
            function.restype = C.c_int
        self.libc = C.CDLL(None)
        self.libc.calloc.argtypes = [C.c_size_t, C.c_size_t]
        self.libc.calloc.restype = C.c_void_p
        self.libc.strdup.argtypes = [C.c_char_p]
        self.libc.strdup.restype = C.c_void_p
        self.libc.free.argtypes = [C.c_void_p]
        self.libc.free.restype = None

    def check(self, username, password, *, authenticate=True, account=False):
        username_bytes = username.encode("ascii")
        password_bytes = password.encode("ascii")
        prompts = 0

        @Conversation
        def converse(count, messages, response_out, unused):
            nonlocal prompts
            allocation = None
            strings = []
            if not response_out:
                return PAM_CONV_ERR
            response_out[0] = C.POINTER(PamResponse)()
            if not messages or count < 1 or count > PAM_MAX_NUM_MSG:
                return PAM_CONV_ERR
            try:
                allocation = self.libc.calloc(count, C.sizeof(PamResponse))
                if not allocation:
                    return PAM_BUF_ERR
                responses = C.cast(allocation, C.POINTER(PamResponse))
                for index in range(count):
                    if not messages[index]:
                        raise ValueError("missing PAM message")
                    style = messages[index].contents.msg_style
                    if style == PAM_PROMPT_ECHO_OFF:
                        answer = password_bytes
                        prompts += 1
                    elif style == PAM_PROMPT_ECHO_ON:
                        answer = username_bytes
                    elif style in (PAM_ERROR_MSG, PAM_TEXT_INFO):
                        continue
                    else:
                        raise ValueError("unsupported PAM conversation style")
                    pointer = self.libc.strdup(answer)
                    if not pointer:
                        raise MemoryError()
                    strings.append((pointer, len(answer)))
                    responses[index].resp = pointer
                    # calloc set resp_retcode to the ABI-required zero.
                response_out[0] = responses
                return PAM_SUCCESS  # PAM owns the array and its strings now.
            except BaseException:
                for pointer, length in strings:
                    C.memset(pointer, 0, length)
                    self.libc.free(pointer)
                if allocation:
                    self.libc.free(allocation)
                return PAM_CONV_ERR

        conversation = PamConv(converse, None)
        handle = C.c_void_p()
        status = self.lib.pam_start(b"ddm", username_bytes, C.byref(conversation),
                                    C.byref(handle))
        if status != PAM_SUCCESS:
            raise CheckError(f"pam_start failed (code {status})")
        auth_result = None
        account_result = None
        try:
            if authenticate:
                auth_result = self.lib.pam_authenticate(handle, PAM_DISALLOW_NULL_AUTHTOK)
                status = auth_result
            if account and (not authenticate or auth_result == PAM_SUCCESS):
                account_result = self.lib.pam_acct_mgmt(handle, 0)
                status = account_result
            return auth_result, account_result, prompts
        finally:
            end_status = self.lib.pam_end(handle, status)
            if end_status != PAM_SUCCESS:
                raise CheckError(f"pam_end failed (code {end_status})")


def require_password_login(entry):
    try:
        group = grp.getgrnam("nopasswdlogin")
    except KeyError:
        return
    if group.gr_gid in os.getgrouplist(LOGIN, entry.pw_gid):
        raise CheckError("temporary account unexpectedly belongs to nopasswdlogin")


def remove_backup_records():
    # userdel may leave the removed user's hash in shadow-.  Remove only records
    # for this run's reserved name; preserve other accounts and file permissions.
    prefix = LOGIN.encode("ascii") + b":"
    for path in BACKUPS:
        try:
            fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
        except FileNotFoundError:
            continue
        try:
            checked_stat(fd, path)
            with os.fdopen(fd, "r+b", closefd=False) as stream:
                data = stream.read(4 * 1024 * 1024 + 1)
                if len(data) > 4 * 1024 * 1024:
                    raise CheckError(f"unexpectedly large account backup: {path}")
                cleaned = b"".join(line for line in data.splitlines(keepends=True)
                                   if not line.startswith(prefix))
                if cleaned != data:
                    stream.seek(0)
                    stream.write(cleaned)
                    stream.truncate()
                    stream.flush()
                    os.fsync(fd)
        finally:
            os.close(fd)


def remove_failure_records(directories, uid):
    for directory in directories:
        for name in (LOGIN, UNKNOWN_LOGIN):
            path = directory / name
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid not in {0, uid}):
                raise CheckError("unexpected ownership or type of temporary failure record")
            path.unlink()


def clean_account(tag, expected_gid, failure_dirs):
    try:
        entry = pwd.getpwnam(LOGIN)
    except KeyError:
        # A failed useradd need not have created an account.
        return
    if (entry.pw_gecos != tag or entry.pw_gid != expected_gid
            or entry.pw_dir != TEST_HOME or entry.pw_shell != "/bin/bash"):
        raise CheckError("temporary account identity changed; refusing to delete it")
    failures = []
    if shutil.which("faillock", path=COMMAND_ENV["PATH"]):
        try:
            # Linux-PAM's faillock CLI requires an existing account, including
            # for --reset.  Never call it for the deliberately unknown user.
            command("faillock", "--user", LOGIN, "--reset")
        except CheckError as error:
            failures.append(str(error))
    try:
        command("userdel", LOGIN)  # No -r/-f: never remove a home or another account.
        require_absent_user(LOGIN)
        remove_backup_records()
        remove_failure_records(failure_dirs, entry.pw_uid)
        for path in (Path(f"/var/spool/mail/{LOGIN}"), Path(f"/var/mail/{LOGIN}")):
            if not os.path.lexists(path):
                continue
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != entry.pw_uid:
                raise CheckError("unexpected temporary mailbox ownership or type")
            path.unlink()
    except CheckError as error:
        failures.append(str(error))
    if os.path.lexists(TEST_HOME):
        failures.append("temporary account unexpectedly acquired a home directory")
    if failures:
        raise CheckError("; ".join(failures))


def main():
    attempted_creation = False
    tag = None
    gid = None
    failure_dirs = set()
    errors = []
    try:
        failure_dirs = check_context()
        os.umask(0o077)

        def interrupted(number, frame):
            raise CheckError(f"PAM check interrupted by signal {number}")

        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        pam = Pam()
        gid = grp.getgrnam("users").gr_gid
        tag = "Fedora DDE ISO PAM check " + secrets.token_hex(12)
        password = "Aa1!" + secrets.token_urlsafe(48)
        wrong_password = "Bb2!" + secrets.token_urlsafe(48)
        attempted_creation = True
        command(
            "useradd", "--no-create-home", "--no-user-group", "--no-log-init",
            "--gid", str(gid), "--home-dir", TEST_HOME, "--shell", "/bin/bash",
            "--comment", tag, "-K", "CREATE_MAIL_SPOOL=no", "-K", "SUB_UID_COUNT=0",
            "-K", "SUB_GID_COUNT=0", LOGIN,
        )
        require_password_login(pwd.getpwnam(LOGIN))
        command("chpasswd", input_data=f"{LOGIN}:{password}\n".encode("ascii"))
        command("chage", "--expiredate", "-1", LOGIN)

        auth, account, prompts = pam.check(LOGIN, password, account=True)
        if auth != PAM_SUCCESS or account != PAM_SUCCESS or prompts < 1:
            raise CheckError(f"valid password/account rejected or bypassed (auth={auth}, account={account})")
        print("PASS ddm: correct password and active account accepted", flush=True)

        auth, _, prompts = pam.check(LOGIN, wrong_password)
        if auth not in AUTH_DENIALS or prompts < 1:
            raise CheckError(f"wrong password was not properly rejected (code {auth})")
        print("PASS ddm: wrong password rejected", flush=True)

        require_absent_user(UNKNOWN_LOGIN)
        auth, _, _ = pam.check(UNKNOWN_LOGIN, wrong_password)
        if auth not in AUTH_DENIALS:
            raise CheckError(f"unknown user was not properly rejected (code {auth})")
        print("PASS ddm: unknown user rejected", flush=True)

        if shutil.which("faillock", path=COMMAND_ENV["PATH"]):
            command("faillock", "--user", LOGIN, "--reset")
        command("chage", "--expiredate", "1970-01-02", LOGIN)
        _, account, _ = pam.check(LOGIN, password, authenticate=False, account=True)
        if account != PAM_ACCT_EXPIRED:
            raise CheckError(f"expired account did not return PAM_ACCT_EXPIRED (code {account})")
        print("PASS ddm: expired account rejected by account management", flush=True)
    except CheckError as error:
        errors.append(str(error))
    except Exception as error:
        # Unexpected exceptions must not print locals, PAM text or secret stdin.
        errors.append(f"PAM build check raised {type(error).__name__}")
    finally:
        if attempted_creation:
            try:
                clean_account(tag, gid, failure_dirs)
            except CheckError as error:
                errors.append(f"cleanup failed: {error}")
            except Exception as error:
                errors.append(f"cleanup raised {type(error).__name__}")
    if errors:
        for message in errors:
            print(f"FAIL {message}", file=sys.stderr, flush=True)
        return 1
    print("PASS temporary account removed; session opening remains a VM check", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
