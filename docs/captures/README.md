# Capture library

Each reverse-engineering capture is a triple:

- `<name>.log`    — raw Android btsnoop HCI log
- `<name>.png`    — the exact image sent to the badge during the capture
- `<name>.md`     — short notes: Android version, Zrun version, date, what was done

Filenames are `NN-description`, e.g. `01-solid-red-360.log`, numbered in the order captures
were taken. Do not rename — protocol tests in phase 2 will reference these names as fixtures.

Captures larger than 5 MB are gitignored (suffix `.log.big`) and kept locally only.
