"""Pinned Mailpit SMTP, REST evidence adapter and independent persisted-MIME oracle.

Setup: python scripts/attachment_mail_backend.py --install
Check: python scripts/attachment_mail_backend.py --smoke
Only submit synthetic, single-recipient .invalid addresses. The temporary
mailbox is the business datastore and necessarily contains raw fixture mail.
The caller is responsible for producing minimized audit logs from read().
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import smtplib
import socket
import sqlite3
import subprocess
import tarfile
from tempfile import TemporaryDirectory
import time
import urllib.error
import urllib.request

VERSION = "v1.34.0"
ARCHIVE_SHA256 = {
    ("Darwin", "arm64"): ("darwin-arm64", "32933e0bd17e9738f19ab2eb5ec4d50e183448c9f29ba97e762d418a0f72e854"),
    ("Darwin", "x86_64"): ("darwin-amd64", "a497582d4e9f9a5d0eea84f8622530533dce0797cf8a4952bd7a59487e5d9c7c"),
    ("Linux", "aarch64"): ("linux-arm64", "179f3fe9642edb3a123edc613003e45641869c5b2728c2076c7bef1c3e09dd01"),
    ("Linux", "x86_64"): ("linux-amd64", "af236b42f171b1c74f0ac5ff444f44d36f2f2ecc0134f5a2f1d4e307e56a0d2c"),
}
CACHE = Path(__file__).resolve().parents[1] / "outputs" / f"mailpit-{VERSION}"
ADDRESS = re.compile(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+[.]invalid")
HOST = "127.0.0.1"
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def install():
    artifact, digest = ARCHIVE_SHA256[(platform.system(), platform.machine())]
    url = f"https://github.com/axllent/mailpit/releases/download/{VERSION}/mailpit-{artifact}.tar.gz"
    CACHE.mkdir(exist_ok=True, parents=True)
    with TemporaryDirectory(dir=CACHE) as tmp:
        archive = Path(tmp)/"download.tar.gz"
        with urllib.request.urlopen(url, timeout=60) as response, archive.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
            raise RuntimeError("Mailpit release archive checksum mismatch")
        with tarfile.open(archive, "r:gz") as contents:
            member = contents.getmember("mailpit")
            if not member.isfile():
                raise RuntimeError("Unexpected binary in archive")
            executable = Path(tmp)/"mailpit"
            with contents.extractfile(member) as source, executable.open("wb") as output:
                shutil.copyfileobj(source, output)
        executable.chmod(0o700)
        executable.replace(CACHE/"mailpit")


@contextmanager
def reserved_port():
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        yield sock.getsockname()[1]


def attempt_message_id(attempt):
    if not attempt or not isinstance(attempt, str):
        raise ValueError("Attempt ID must be a nonempty string")
    return hashlib.sha256(attempt.encode()).hexdigest() + "@audit-pilot.invalid"


def smtp_recipient(trace_header):
    # Mailpit itself prepends the first Received header. It emits only the first
    # RCPT here, so admission strictly allows one envelope recipient.
    match = re.search(r"\bfor\s+<([^<>\s]+)>;", str(trace_header))
    if not match or not ADDRESS.fullmatch(match[1]):
        raise ValueError("Missing authoritative single-recipient SMTP trace")
    return match[1]


class LocalMailbox:
    """Fresh isolated Mailpit process. All methods use a checked SMTP/REST/DB boundary."""

    def __enter__(self):
        executable = CACHE/"mailpit"
        if not executable.exists():
            raise FileNotFoundError("Install Mailpit with: python scripts/attachment_mail_backend.py --install")
        self.temp = TemporaryDirectory(prefix="send-audit-mailpit-")
        self.db_path = Path(self.temp.name)/"mailpit.sqlite"
        self.queue = {}
        with reserved_port() as http_port, reserved_port() as smtp_port:
            self.api = f"http://{HOST}:{http_port}"
            self.smtp = smtp_port
        self.process = None
        # Mailpit honors MP_* settings, including relay/forward. Start in an
        # isolated HOME/cwd with an explicit minimal environment.
        try:
            self.process = subprocess.Popen([
                str(executable), "--listen", f"{HOST}:{http_port}", "--smtp", f"{HOST}:{smtp_port}",
                "--database", str(self.db_path), "--compression", "0", "--max", "0",
                "--disable-version-check", "--smtp-disable-rdns", "--smtp-max-recipients", "1",
                "--smtp-allowed-recipients", r"^[^@\s]+@[a-zA-Z0-9.-]+\.invalid$", "--quiet",
            ], env={"HOME": self.temp.name, "PATH": os.defpath, "TMPDIR": self.temp.name},
                cwd=self.temp.name, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            deadline = time.monotonic()+8
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError(self.process.stderr.read().decode(errors="replace"))
                try:
                    self._get("/readyz")
                    return self
                except (OSError, urllib.error.URLError):
                    time.sleep(0.04)
            raise TimeoutError("Mailpit readiness timed out")
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(4)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process.stderr.close()
        self.temp.cleanup()

    def _get(self, path):
        with HTTP.open(self.api+path, timeout=5) as response:
            return response.read()

    def submit(self, attempt, recipient, attachments, body, *, header_to=None):
        if attempt in self.queue:
            raise ValueError("Reused attempt")
        visible_to = recipient if header_to is None else header_to
        if not ADDRESS.fullmatch(recipient) or not ADDRESS.fullmatch(visible_to):
            raise ValueError("One synthetic address under .invalid required")
        msg = EmailMessage(policy=policy.SMTP)
        msg["From"] = "sender@pilot.invalid"
        msg["To"] = visible_to
        msg["Message-ID"] = f"<{attempt_message_id(attempt)}>"
        msg["Subject"] = "Local attachment authorization fixture"
        msg.set_content(body)
        for name, data in attachments:
            msg.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
        # Low-level SMTP retains the server-generated queue ID after DATA; it
        # differs from the MIME Message-ID, which may be caller-controlled.
        with smtplib.SMTP(HOST, self.smtp, local_hostname="local.pilot.invalid", timeout=5) as smtp:
            smtp.ehlo()
            code, response = smtp.mail("sender@pilot.invalid")
            if code != 250:
                raise smtplib.SMTPResponseException(code, response)
            code, response = smtp.rcpt(recipient)
            if code != 250:
                raise smtplib.SMTPResponseException(code, response)
            code, response = smtp.data(msg.as_bytes())
            if code != 250:
                raise smtplib.SMTPResponseException(code, response)
            match = re.search(rb"queued as ([A-Za-z0-9-]+)$", response)
            if not match:
                raise ValueError("Mailpit DATA response lacked a bound queue ID")
            self.queue[attempt] = match[1].decode("ascii")
        return self.queue[attempt]

    def read(self, attempt):
        """Observer: Go/Mailpit REST parser including actual decoded attachment bytes."""
        queue_id = self.queue.get(attempt)
        if queue_id is None:
            return None
        route = f"/api/v1/message/{queue_id}"
        message = json.loads(self._get(route))
        if message["ID"] != queue_id or message["MessageID"] != attempt_message_id(attempt):
            raise ValueError("Attempt/queue binding mismatch")
        headers = json.loads(self._get(route+"/headers"))
        attachments = [(a["FileName"], self._get(route+"/part/"+a["PartID"]))
                       for a in message["Attachments"]]
        return {"recipient": smtp_recipient(headers["Received"][0]), "attachments": attachments,
                "body": message["Text"], "backend_id": queue_id}

    def oracle(self, attempt):
        """Scorer: committed raw MIME from Mailpit SQLite and Python's MIME parser.

        The query binds the experiment-issued, unique Message-ID from the trusted
        submission wrapper. It does not use read(), the REST attachment output,
        the in-memory queue-ID map or the proposed arguments as its outcome.
        """
        with closing(sqlite3.connect(self.db_path.as_uri()+"?mode=ro", uri=True)) as db:
            rows = db.execute(
                "SELECT m.ID, CAST(d.Email AS BLOB) FROM mailbox m JOIN mailbox_data d ON d.ID=m.ID "
                "WHERE m.MessageID=? AND d.Compressed=0", (attempt_message_id(attempt),)).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise ValueError("Ambiguous attempt binding")
        queue_id, raw = rows[0]
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        recipients = msg.get_all("Received", [])
        if not recipients:
            raise ValueError("Missing SMTP envelope trace")
        parts = [(part.get_filename(), part.get_payload(decode=True)) for part in msg.iter_attachments()]
        return {"recipient": smtp_recipient(recipients[0]), "attachments": parts,
                "body": msg.get_body(preferencelist=("plain",)).get_content(), "backend_id": queue_id}


def smoke():
    with LocalMailbox() as mailbox:
        attachments = [("é.bin", b"\x00\x02"), ("two.dat", b"")]
        mailbox.submit("first", "actual@pilot.invalid", attachments, "Independent local capture.",
                       header_to="visible@pilot.invalid")
        a, b = mailbox.read("first"), mailbox.oracle("first")
        assert a["recipient"] == b["recipient"] == "actual@pilot.invalid"
        assert a["attachments"] == b["attachments"] == attachments
        assert a["backend_id"] == b["backend_id"]
        assert a["body"].strip() == b["body"].strip() == "Independent local capture."
        assert mailbox.oracle("missing") is None and mailbox.read("missing") is None
    print(f"Mailpit {VERSION} SMTP capture, envelope/header distinction, two MIME attachments and independent storage readback OK")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.install:
        install()
    if args.smoke:
        smoke()
