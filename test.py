"""Core-logic tests. Run:  python -m unittest discover -s tests -v"""
import json, os, sys, tempfile, unittest, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import vault as dv
from cryptography.exceptions import InvalidTag
from PySide6.QtGui import QColor, QImage

dv.Vault.CH = 1024                       # tiny chunks so small files exercise the multi-chunk path
nocb = lambda _: None


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.v = dv.Vault(self.root / "vault"); self.v.create("main-pass-1")
        self.data = os.urandom(5000); self.src = self.root / "a.bin"; self.src.write_bytes(self.data)

    def tearDown(self): self.tmp.cleanup()
    def reopen(self): return dv.Vault(self.root / "vault")

    def test_passwords_and_backup_password(self):
        self.assertFalse(self.reopen().unlock("wrong"))
        self.v.set_backup("backup-pass-2")
        with self.assertRaises(ValueError): self.v.set_backup("main-pass-1")
        self.assertTrue(self.reopen().unlock("main-pass-1")); self.assertTrue(self.reopen().unlock("backup-pass-2"))
        self.v.change_password("new-pass-33"); self.assertFalse(self.reopen().unlock("main-pass-1"))
        self.assertTrue(self.reopen().unlock("new-pass-33"))

    def test_roundtrip_and_originals_removed(self):
        self.v.add_files([str(self.src)], "", True, nocb); self.assertFalse(self.src.exists())
        out = self.v.export(self.v.entries[0], str(self.root), nocb)
        self.assertEqual(Path(out).read_bytes(), self.data)

    def test_tamper_and_truncation_detected(self):
        self.v.add_files([str(self.src)], "", False, nocb); e = self.v.entries[0]
        blob = self.v.blobs / f"{e['id']}.vlt"; raw = blob.read_bytes()
        blob.write_bytes(raw[:8 + 4 * (1024 + 16)])                      # last chunk dropped
        with self.assertRaises(InvalidTag): self.v.export(e, str(self.root), nocb)
        blob.write_bytes(raw[:20] + bytes([raw[20] ^ 1]) + raw[21:])     # one flipped bit
        with self.assertRaises(InvalidTag): self.v.export(e, str(self.root), nocb)

    def test_folder_drop_and_folder_rules(self):
        d = self.root / "Tax"; (d / "2025").mkdir(parents=True); (d / "2025" / "x.txt").write_text("hi"); (d / "empty").mkdir()
        self.v.add_files([str(d)], "", False, nocb)
        self.assertEqual(sorted(self.v.folders), ["Tax", "Tax/2025", "Tax/empty"])
        self.assertEqual(self.v.entries[0]["folder"], "Tax/2025")
        with self.assertRaises(ValueError): self.v.delete_folder("Tax/2025")
        self.v.rename_folder("Tax", "Taxes"); self.assertEqual(self.v.entries[0]["folder"], "Taxes/2025")
        self.v.delete_folder("Taxes/empty")
        with self.assertRaises(ValueError): self.v.add_folder("", "Taxes")

    def test_index_and_meta_fallbacks(self):
        self.v.add_files([str(self.src)], "", False, nocb); self.v.add_folder("", "X")
        idx = self.root / "vault" / "index.vlt"; idx.write_bytes(b"garbage")
        v = self.reopen(); self.assertTrue(v.unlock("main-pass-1")); self.assertEqual(len(v.entries), 1)
        idx.with_suffix(".bak").write_bytes(b"garbage")
        v = self.reopen()
        with self.assertRaises(ValueError): v.unlock("main-pass-1")
        self.assertIsNone(v.key)                                         # a failed unlock must not leave it open
        (self.root / "vault" / "vault.meta").write_text("{broken")       # meta falls back to vault.bak
        self.assertTrue(self.reopen().title())

    def test_legacy_vault_upgrade(self):
        root = self.root / "old"; (root / "blobs").mkdir(parents=True)
        salt = os.urandom(16); key = dv.Vault._derive("oldpass-123", salt)
        (root / "vault.meta").write_text(json.dumps({"salt": dv.b64(salt), "check": dv.b64(dv.Vault._seal(key, b"limewash-ok"))}))
        entry = {"id": "a" * 32, "name": "n.txt", "size": 1, "mime": "text/plain", "mtime": 0}
        (root / "index.vlt").write_bytes(dv.Vault._seal(key, json.dumps([entry]).encode()))
        v = dv.Vault(root); self.assertTrue(v.unlock("oldpass-123")); self.assertEqual(v.entries[0]["name"], "n.txt")
        self.assertTrue(dv.Vault(root).unlock("oldpass-123"))            # now stored in the v2 format
        self.assertTrue((root / "vault.legacy").exists())              # pre-upgrade meta kept

    def test_kdf_cost_upgrade(self):
        self.assertEqual(self.v._meta()["main"]["n"], dv.KDF_N)
        o = dv.Vault(self.root / "o"); o.create("legacy-kdf-1"); meta = o._meta(); salt = os.urandom(16)
        meta["main"] = {"salt": dv.b64(salt), "wrap": dv.b64(o._seal(o._derive("legacy-kdf-1", salt), o.key))}   # old cost, no "n"
        o._write_meta(meta)
        v = dv.Vault(self.root / "o"); self.assertTrue(v.unlock("legacy-kdf-1"))
        self.assertEqual(v._meta()["main"]["n"], dv.KDF_N)                  # re-wrapped at the current cost
        self.assertTrue(dv.Vault(self.root / "o").unlock("legacy-kdf-1"))

    def test_blob_swap_is_detected(self):
        b = self.root / "b.bin"; b.write_bytes(os.urandom(3000))
        self.v.add_files([str(self.src), str(b)], "", False, nocb); e1, e2 = self.v.entries
        (self.v.blobs / f"{e2['id']}.vlt").write_bytes((self.v.blobs / f"{e1['id']}.vlt").read_bytes())
        with self.assertRaises(InvalidTag): self.v.export(e2, str(self.root), nocb)

    def test_verify_reports_problems(self):
        b = self.root / "b.bin"; b.write_bytes(b"x" * 10)
        self.v.add_files([str(self.src), str(b)], "", False, nocb); e1, e2 = self.v.entries
        r = self.v.verify(nocb); self.assertEqual((r["checked"], r["damaged"], r["missing"], r["orphans"]), (2, [], [], []))
        p1 = self.v.blobs / f"{e1['id']}.vlt"; d = p1.read_bytes(); p1.write_bytes(d[:30] + bytes([d[30] ^ 1]) + d[31:])
        (self.v.blobs / f"{e2['id']}.vlt").unlink(); (self.v.blobs / ("f" * 32 + ".vlt")).write_bytes(b"x")
        r = self.v.verify(nocb); self.assertEqual((r["damaged"], r["missing"], len(r["orphans"])), ([e1["name"]], [e2["name"]], 1))

    def test_legacy_blobs_open_and_upgrade(self):
        e = {"id": "c" * 32, "folder": "", "name": "old.bin", "size": 3000, "mime": "x", "mtime": 0}     # no "fmt" = legacy
        data = os.urandom(3000); base = os.urandom(8); aes = dv.AESGCM(self.v.key)
        parts = [data[:1024], data[1024:2048], data[2048:]]
        blob = base + b"".join(aes.encrypt(base + i.to_bytes(4, "big"), c, b"\x01" if i == 2 else b"\x00") for i, c in enumerate(parts))
        (self.v.blobs / f"{e['id']}.vlt").write_bytes(blob); self.v.entries.append(e)
        self.assertEqual(Path(self.v.export(e, str(self.root), nocb)).read_bytes(), data)
        self.assertEqual(self.v.upgrade_blobs(nocb), 1); self.assertEqual(e["fmt"], 2)
        self.assertEqual(Path(self.v.export(e, str(self.root), nocb)).read_bytes(), data)
        self.assertEqual(self.v.verify(nocb)["damaged"], [])


class UserTests(unittest.TestCase):
    def test_users_backup_restore_avatar(self):
        with tempfile.TemporaryDirectory() as t:
            os.environ["APPDATA"] = t
            store = dv.UserStore(); u = store.add("Ann"); v = dv.Vault(store.dir(u["id"])); v.create("pass-word-1")
            f = Path(t) / "f.txt"; f.write_text("secret"); v.add_files([str(f)], "", False, nocb)
            bk = str(Path(t) / "b.dvbak"); v.backup(bk, nocb)
            u2 = store.restore(bk, "Ann2"); v2 = dv.Vault(store.dir(u2["id"]))
            self.assertTrue(v2.unlock("pass-word-1")); self.assertEqual(len(v2.entries), 1)
            other = dv.Vault(store.dir(store.add("Bob")["id"])); other.create("bob-pass-99")
            self.assertFalse(dv.Vault(store.dir(u["id"])).unlock("bob-pass-99"))     # users are isolated
            bad = Path(t) / "bad.dvbak"
            with zipfile.ZipFile(bad, "w") as z: z.writestr("../evil.txt", "x"); z.writestr("vault.meta", "{}")
            with self.assertRaises(ValueError): store.restore(str(bad), "Evil")
            img = QImage(300, 200, QImage.Format_RGB32); img.fill(QColor("#0A6CFF")); img.save(str(Path(t) / "a.png"))
            store.set_avatar(u, str(Path(t) / "a.png")); self.assertEqual(QImage(str(store.avatar_path(u))).width(), 256)
            with self.assertRaises(ValueError): store.set_avatar(u, str(f))


if __name__ == "__main__":
    unittest.main()