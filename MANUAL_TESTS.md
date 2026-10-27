# Manual test checklist (run on a clean Windows PC before sharing a build)

Back up `%APPDATA%\DaedalusVault` first. Tick each line.

**Install**
- [ ] Setup runs without Python installed; Start Menu and desktop shortcut work; logo shows in the title bar and taskbar.

**Users and vaults**
- [ ] Add user "A": create vault with a password; add a backup password in Settings.
- [ ] Add user "B": a different password. A's password does NOT open B.
- [ ] Upload an avatar (PNG and JPG); change colour; rename the vault; rename the user.

**Files and folders**
- [ ] Drag a single file, several files, and a folder with sub-folders from Explorer. Structure is kept.
- [ ] "Remove originals" ticked: originals disappear only after the success flash.
- [ ] Move a file into a folder; rename a folder; delete an empty folder; try deleting a non-empty one (refused).

**Open and edit**
- [ ] Open a PNG (in-app viewer), a PDF, a video, an .xlsx and a .docx.
- [ ] Edit and save the .xlsx; try Lock while Excel is still open (refused with a list); close Excel; Lock; unlock; the edit is there.

**Security features**
- [ ] Wrong password shows an error and shakes; the backup password unlocks; change the main password, then unlock with the new one.
- [ ] Auto-lock after 1 minute idle; lock on minimize; with a file open in Excel it waits instead of forcing.
- [ ] Settings -> Verify vault integrity reports "Everything is intact".
- [ ] Export encrypted backup; delete user; Restore from backup; unlock with the original password.

**Upgrade path**
- [ ] Copy an old (pre-1.2) `%APPDATA%\DaedalusVault` onto a test PC; unlock; files open; Settings offers "Upgrade N older files"; after it, Verify is clean.

**Crash safety**
- [ ] Kill the app (Task Manager) while importing a big folder; reopen; the vault unlocks; Verify shows at most "unreferenced" leftovers.
