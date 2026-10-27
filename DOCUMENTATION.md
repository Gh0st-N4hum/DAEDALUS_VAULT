# Daedalus Vault: technical documentation

Single-file PySide6 (Qt) desktop app, `daedalus_vault.py` (~1519 lines). This document covers everything added after the first version, so it can be reviewed feature by feature.

## 0. Verification status

| Verified | Not verified (please test by hand) |
|---|---|
| 11 unit tests pass (`tests/test_vault.py`): crypto, passwords, folders, folder drop, tamper/swap detection, index/meta fallback, legacy upgrade, scrypt-cost upgrade, verify, file-format upgrade, users, backup/restore, avatars | Dragging from Windows Explorer (tests don't simulate OS drag events) |
| Real `MainWindow` builds and renders offscreen; unlock, refresh and lock paths run | Opening files in Excel/Word/PDF/video apps and saving edits back |
| | The PyInstaller build, the Inno Setup installer and the GitHub Actions workflow (written, never run) |
| | Look and feel on your DPI and fonts (Segoe UI is not available in my test environment) |

## 1. Architecture

```
MainWindow ── controller: screens, jobs, auto-lock, settings
 ├─ UserPicker / UserCard / Avatar      profile screen
 ├─ LockedCard                          click the vault -> PasswordDialog
 ├─ VaultView ─ DropZone, FileCard, FolderCard   unlocked screen
 ├─ ImageViewer                         in-memory image preview
 ├─ Job (QThread)                       runs Vault operations off the UI thread
 └─ UserStore  ->  Vault (one per user)  storage + crypto, no UI code
```
`Vault` and `UserStore` contain no widgets, which is why they can be unit tested. Anything slow (encrypt, decrypt, backup) runs in a `Job` and reports progress through a signal.

## 2. On-disk layout (`%APPDATA%\DaedalusVault`)

```
users.json                 plain text: [{id, name, color, avatar, autolock, lock_on_minimize}]
users/<id>/avatar.png      plain text 256x256 (shown before login)
users/<id>/vault.meta      JSON: title (plain), main + backup password slots
users/<id>/vault.bak       previous meta (rolling copy)
users/<id>/index.vlt       encrypted JSON {entries, folders}
users/<id>/index.bak       previous index (rolling copy)
users/<id>/blobs/<32hex>.vlt   one encrypted file each
users/<id>/open/<id>/name  TEMPORARY decrypted copy while a file is open externally
```

## 3. Cryptography

- **Master key:** 32 random bytes per vault (`create`). Files and the index are encrypted with it.
- **Password slots:** `main` and optional `backup`. Each slot = `{salt, wrap}` where `wrap = AES-GCM(scrypt(password, salt), master_key)`. Scrypt n=2^15, r=8, p=1. Unlocking tries `main`, then `backup`. Changing a password re-wraps the master key only, so no file is re-encrypted.
- **File blob:** `[8-byte random nonce prefix][chunk]...`; chunk plaintext 4 MiB, ciphertext +16-byte tag. Chunk *i* uses nonce `prefix || i (4 bytes BE)`. The AAD is `\x01` for the last chunk, `\x00` otherwise, so truncation and reordering fail authentication.
- **Index/meta check:** AES-GCM with a random 12-byte nonce prepended.
- **Legacy vaults** (key derived directly from the password, `check` token) are upgraded in place on first unlock; the old derived key becomes the master key so existing blobs stay readable.

## 4. Code added, by feature

### 4.1 Multi-user (`UserStore`, `Avatar`, `UserCard`, `UserPicker`)
- `UserStore.__init__` migrates `LimewashVault`, then adopts a pre-multi-user vault found at the root as user "Me".
- `add / update / remove`: profile CRUD. `remove` deletes the user's directory.
- `set_avatar`: centre-crops to a square, scales to 256 px, saves PNG. Raises `ValueError` for unreadable images.
- `restore`: see 4.7.
- `Avatar`: round, ring in the user's colour, initials fallback. Mouse-transparent so cards stay clickable.
- `MainWindow.select_user` builds `Vault(store.dir(id))`, so each user is a separate folder, password and master key. `_delete_user` is only reachable from Settings (i.e. after authentication).

### 4.2 Folders
- Model: `folders` is a list of paths like `"Taxes/2025"`; each entry has `folder` (`""` = top level). Both live in the encrypted index.
- `Vault.add_folder / rename_folder / delete_folder / move`. Delete is refused unless the folder (and its subfolders) is empty. Names are sanitised (`/` and `\` removed).
- `VaultView._render` shows the folders of the current path first, then files; `FolderCard` click enters, `←  Back` and the path label navigate.

### 4.3 Whole-folder drop
- `DropZone.dropEvent` now accepts any existing path. `Vault.plan` walks directories and returns `[(file, vault_folder)]`, creating the folder tree (including empty folders).
- `add_files`: unreadable files are skipped and listed in `Vault.skipped`; the index is saved every 25 files; **originals are deleted only after the final index save**, then emptied source directories are removed.

### 4.4 Backup password
- Second slot in `vault.meta` (`set_backup / remove_backup / has_backup`). It must differ from the main password. Forgetting the main password: unlock with the backup, then change it in Settings.

### 4.5 Open / view
- Images: `read_bytes` -> `ImageViewer`, in memory only.
- Everything else: `open_temp` decrypts into `users/<id>/open/<entry>/`, then `os.startfile`. `_flush_open` (run on Lock and quit) re-encrypts the file if its size/mtime changed (`replace_blob`), overwrites it with zeros (`wipe_file`), then deletes it. If an app still holds the file, Lock is refused and the file names are listed. `wipe_all_tmp` clears leftovers at startup.

### 4.6 Auto-lock
- Per-user settings `autolock` (minutes, 0 = never, default 5) and `lock_on_minimize` (default on).
- An application-wide event filter restarts a single-shot `QTimer` on mouse/key/wheel activity. On timeout `lock(quiet=True)` runs. If a modal dialog is open, an import is running or an external file is still open, it retries every 60 s. **It does not force-lock in those cases.**

### 4.7 Encrypted backup and restore
- `Vault.backup` zips `vault.meta`, `index.vlt` and `blobs/*.vlt` (already encrypted, stored uncompressed) into a `.dvbak` file.
- `UserStore.restore` validates every entry name against `^(vault\.meta|index\.vlt|blobs/[0-9a-f]{32}\.vlt)$` before extracting (blocks `../` traversal), then creates a new user. Unlock it with the original password.

### 4.8 Crash safety
- `vault.meta` and `index.vlt` are written to `.tmp`, the previous copy is kept as `.bak`, then `os.replace` swaps them atomically. `_meta` falls back to `.bak`. `_load_index` tries index then `.bak`; if files exist but none decrypt it raises `ValueError` rather than starting empty (which would orphan every file). `unlock` sets `self.key` only after the index loads.

### 4.9 Theme
- Design tokens at the top (`BG, SURFACE, INK, ACCENT...`); the `STYLE` stylesheet uses them. `TactileCard` animates colour, border and scale between `STATES`, and paints a blue halo and viewfinder brackets. `Backdrop` paints the dot grid. The logo is embedded as base64 (`LOGO_B64`) with `assets/logo.png` as the preferred source.

## 5. Key flows
- **Unlock:** click `LockedCard` -> `PasswordDialog` -> `_unlock_attempt` -> `Vault.unlock` (scrypt, unwrap, load index) -> `_refresh`, `_arm_autolock`.
- **Add folder:** drop -> `add_files` in a `Job` -> progress bar -> success flash -> `_after_add` (refresh, report skipped files).
- **Lock:** `_flush_open` -> `Vault.lock` (drops key and index) -> locked page.

## 6. Known limitations (be aware before relying on it)
1. While a file is open externally, a **decrypted copy exists on disk** (zero-overwrite on lock is best-effort, not guaranteed on SSDs).
2. User names, avatars, colours and the vault title are stored **unencrypted**. File names, sizes and folder names are encrypted.
3. Python cannot reliably wipe keys from memory; the app does not defend against malware or memory inspection on your PC.
4. *(Fixed in 1.2, see 9.2.)* Older files ("fmt 1") are not bound to their entry ID until you run the upgrade.
5. *(Fixed in 1.2, see 9.1.)* The scrypt cost is now stored per password slot.
6. There is no cancel for imports, no streaming export of very large files to an in-app viewer, and no multi-select.
7. The grid creates one widget per item; thousands of files in one folder will be slow.

## 7. Tests and build
- Tests: `pip install -r requirements.txt` then `python -m unittest discover -s tests -v`.
- Build: `build_installer.bat` (PyInstaller, then Inno Setup 6) produces `installer_output\DaedalusVault_Setup.exe`.

## 8. Suggested review order
1. `Vault` (sections 3, 4.4, 4.8): the part where mistakes lose data.
2. `add_files` and `_flush_open` (4.3, 4.5): the only code that deletes user files.
3. `UserStore.restore` (4.7): handles untrusted input.
4. `MainWindow` auto-lock and lock paths (4.6).
5. UI classes last; they are mostly presentation.

## 9. Hardening release (v1.2)

Everything below is new in this release. Tests: `test_kdf_cost_upgrade`, `test_blob_swap_is_detected`, `test_verify_reports_problems`, `test_legacy_blobs_open_and_upgrade`, plus the `.legacy` assertion in `test_legacy_vault_upgrade`.

### 9.1 Per-slot scrypt cost (`KDF_N`, `LEGACY_N`, `_derive`, `_wrap`, `_try`, `unlock`)
- Each password slot now stores its own cost: `{salt, n, wrap}`. New slots use n = 2^16 (about 64 MiB RAM, a few tenths of a second). Slots without `n` are read as 2^15, so old vaults still open.
- On a successful unlock, if the slot that matched has a lower cost than `KDF_N`, it is re-wrapped automatically (`vault.meta` rewritten atomically). Only the matching slot is upgraded; the other one upgrades when it is next used.
- Effect on users: unlock is slightly slower; a wrong password with a backup password set costs two derivations.
- To raise the cost again later, change `KDF_N`; no format change is needed.

### 9.2 File format v2, bound to the entry id (`_aad`, `_write_blob`, `_open_chunks`)
- New entries carry `"fmt": 2` in the encrypted index. For fmt 2 each chunk's AAD is `entry_id (32 ASCII bytes) + flag`; legacy entries keep `flag` only. So a blob copied over another entry's blob fails authentication (`InvalidTag`).
- Chunk layout, nonce scheme and the last-chunk flag are unchanged from section 3.
- Encryption and decryption are now generators of chunks (`_file_chunks`, `_open_chunks`). `_decrypt_stream`, `export`, `read_bytes`, `open_temp` and `replace_blob` all build on them. `replace_blob` (saving an edited open file) also upgrades that file to fmt 2.

### 9.3 Upgrade older files (`upgrade_blobs`, Settings button)
- Shown only if any entry lacks `fmt: 2`. Each file is decrypted and re-encrypted chunk by chunk into `<id>.new` (no plaintext on disk), then swapped in with `os.replace`, and the index is saved after every file, so an interruption leaves a consistent vault. A leftover `.new` file is harmless.
- It is deliberately manual, so a large vault is not re-encrypted behind your back.

### 9.4 Verify vault (`Vault.verify`, Settings -> "Verify vault integrity")
- Authenticates every chunk of every file and compares the decrypted length with the stored size, without writing plaintext. Reports `damaged`, `missing` and `orphans` (encrypted files not referenced by the index; usually leftovers from an interrupted import). It never deletes anything.

### 9.5 Pre-upgrade copy
- When a pre-multi-user vault is upgraded, the old `vault.meta` is kept as `vault.legacy`.

### 9.6 Reproducible builds
- `requirements.txt` pins PySide6 and cryptography to exact versions; `requirements-build.txt` adds PyInstaller. `build_installer.bat` installs from them.
- `.github/workflows/build.yml`: tests on every push and pull request (Windows); on a tag like `v1.2.0` it also builds the installer and attaches it to a GitHub release. Not run yet; the first run may need small fixes (for example the Inno Setup install step).

### 9.7 Manual tests
- `MANUAL_TESTS.md` is a checklist for a clean PC. Items the automated tests cannot cover: Explorer drag and drop, Excel editing, auto-lock timing, installer.

### 9.8 Not done, and why
- **In-app PDF and video viewing:** needs Qt PDF/Multimedia (large, adds tens of MB to the installer) and cannot be verified in my environment. Today those open through a temporary decrypted copy (limitation 1).
- **Installer code signing:** needs a paid certificate.
- **Encrypting profile data** (user names, avatars, vault titles): they are shown before login, so they must be readable; documented in limitation 2.

### 9.9 Review checklist for this release
1. `unlock`: the slot loop and the re-wrap branch. Check that `self.key` is only set after the index loads and that a failed upgrade cannot lock you out (the old slot stays valid until `os.replace` succeeds).
2. `_aad` and `_write_blob`: the AAD must be identical on write and read for fmt 2; this is the code that, if wrong, makes every new file unreadable.
3. `upgrade_blobs`: replaces files in place; read the order (write `.new`, `os.replace`, set `fmt`, save index).
4. `verify`: read-only; confirm it can never delete.
5. `.github/workflows/build.yml`: runs with `contents: write` on tags only.
