# Installing the browser with Patchright, Docker included

Research for issue #156. Question: how users get a Google Chrome that Patchright drives with `channel="chrome"` on macOS, Windows, Linux x64, Linux arm64 and in the package's Docker image. Researched 2026-11-28 against `patchright==1.64.4` (PyPI wheel, which bundles `patchright-core` 1.64.3 as its driver).

## Answer

- `channel="chrome"` does not download anything. It looks for Google Chrome Stable at a fixed system path and launches it. If Chrome is already installed there (the normal case on a desktop), nothing else is needed.
- `patchright install chrome` is only a convenience: it runs a shell/PowerShell script that downloads Google's official Chrome Stable installer and installs it system-wide, replacing any existing Chrome. It needs admin/root. It is not a Patchright-specific build.
- Linux arm64: the install script refuses (`ERROR: not supported on Linux Arm64`). Tracked in [patchright-python#121](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python/issues/121) (open, opened 2026-08-03, no fix) and [patchright#211](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright/issues/211) (open). Google now ships an arm64 `.deb` that installs to `/opt/google/chrome/`, so installing it with apt/dpkg and then using `channel="chrome"` works; only the installer command is broken.
- `executable_path` is an alternative: when set, it wins over `channel` and the registry lookup is skipped entirely.
- The Node driver is not downloaded: it ships inside the platform-specific wheel. No separate download at install or runtime; only browsers are downloaded, and only on `patchright install`.
- Docker: this repo has no Dockerfile on `master` today. An image should `apt-get install` Google Chrome from Google's `.deb` (amd64 and arm64 both exist), or run `patchright install --with-deps chrome` on amd64 only.

## Details

### What `channel="chrome"` resolves to

In the bundled driver (`patchright/driver/package/lib/coreBundle.js`), the `chrome` channel is registered with these executable paths and install scripts:

| Platform | Executable looked up | Install script |
| --- | --- | --- |
| Linux | `/opt/google/chrome/chrome` | `reinstall_chrome_stable_linux.sh` |
| macOS | `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` | `reinstall_chrome_stable_mac.sh` |
| Windows | `\Google\Chrome\Application\chrome.exe` under the standard install roots (LOCALAPPDATA, PROGRAMFILES, PROGRAMFILES(X86)) | `reinstall_chrome_stable_win.ps1` |

If the file is missing, `executablePathOrDie` throws with a hint to run the install command. Source: `coreBundle.js`, `_createChromiumChannel("chrome", ...)`. Playwright documents the same model: "Google Chrome and Microsoft Edge ... are not downloaded; Playwright uses the installed stable channel" ([Playwright docs, Browsers: Google Chrome & Microsoft Edge](https://playwright.dev/python/docs/browsers#google-chrome--microsoft-edge)).

### What `patchright install chrome` does

The scripts live in `patchright/driver/package/bin/`:

- `reinstall_chrome_stable_linux.sh`: exits on `aarch64`; requires `/etc/os-release` with `ID` `ubuntu` or `debian`; removes an installed `google-chrome`, `apt-get update`, installs curl, downloads `https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb` and `apt-get install`s it. Needs root (the CLI re-runs it with sudo).
- `reinstall_chrome_stable_mac.sh`: `rm -rf "/Applications/Google Chrome.app"`, downloads Google's universal `googlechrome.dmg` and copies the app into `/Applications`. This deletes the user's existing Chrome.
- `reinstall_chrome_stable_win.ps1`: downloads and runs Google's Chrome installer (admin).

So on desktops where the user already has Chrome, the README should say "install Google Chrome" rather than recommending `patchright install chrome`, which reinstalls it (on macOS by deleting the app first). Playwright docs warn the same: installing a channel "will override your current browser installation" ([Playwright docs](https://playwright.dev/python/docs/browsers#google-chrome--microsoft-edge)).

### Linux arm64

- The script's first check is `if [[ $(arch) == "aarch64" ]]; then echo "ERROR: not supported on Linux Arm64"; exit 1; fi` (`reinstall_chrome_stable_linux.sh`, Patchright 1.64.4).
- [patchright-python#121](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python/issues/121) "`patchright install chrome` broken for arm64": open, labels `enhancement`, `help wanted`, no comments. It quotes exactly that error.
- [patchright#211](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright/issues/211) "[Feature] Support Google Chrome on arm64": open, `long term`. A comment ([2026-08-01](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright/issues/211#issuecomment-5152927195)) reports that Google ships arm64 Linux Chrome and that `dpkg -i` installs it to `/opt/google/chrome/`, the path `channel="chrome"` looks up. Google announcement: [Bringing Chrome to arm64 Linux devices](https://blog.google/chromium/bringing-chrome-to-arm64-linux-devices/).
- `https://dl.google.com/linux/direct/google-chrome-stable_current_arm64.deb` answers HTTP 200 (checked 2026-11-28, about 142 MB), next to the `_amd64.deb` the script uses.
- The wheel for `manylinux_2_17_aarch64` bundles an aarch64 Node binary, so the driver itself runs on arm64; only the Chrome installer is missing.

Workaround until #121 is fixed: install Chrome from the arm64 `.deb` with `apt-get install ./google-chrome-stable_current_arm64.deb`, then use `channel="chrome"` (or `executable_path="/opt/google/chrome/chrome"`).

### `executable_path`

The launcher in `coreBundle.js` resolves `customExecutablePath = await this.resolveExecutablePath(options)`; if set it is used as is, otherwise it falls back to `registry.findExecutable(...)` for the channel and validates host requirements. So `executable_path` bypasses the channel lookup and its "not found" error. Both are accepted by `launch_persistent_context` (`BrowserTypeLaunchPersistentContextParams` has `channel` and `executablePath`). Playwright documents `executable_path` as "Path to a browser executable to run instead of the bundled one ... use at your own risk" ([BrowserType.launch_persistent_context](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context)). Useful for non-standard locations (Chrome installed per-user elsewhere, Flatpak, custom image paths).

### Driver bundle

- `patchright/_impl/_driver.py` runs `patchright/driver/node` (or `node.exe`) with `patchright/driver/package/cli.js`; `PLAYWRIGHT_NODEJS_PATH` overrides the Node binary.
- The wheels are platform-specific (e.g. `patchright-1.64.4-py3-none-manylinux_2_17_aarch64...whl`) and contain the driver: about 131 MB unpacked, Node included. Nothing is fetched at `pip install` or at launch.
- Network access happens only in `patchright install ...` (browser downloads). With `channel="chrome"` and a system Chrome, `patchright install` is never needed. Note: Patchright 1.64.4's driver reports `patchright-core` version 1.64.3 in its `package.json`.

### Docker image

There is no Dockerfile on `origin/master`. For an image that runs on both architectures:

```dockerfile
FROM python:3.12-slim
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSL -o /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_${TARGETARCH}.deb \
 && apt-get install -y /tmp/chrome.deb && rm /tmp/chrome.deb && rm -rf /var/lib/apt/lists/*
RUN pip install linkedin-jobs-scraper
```

`apt-get install` of Google's `.deb` pulls Chrome's own runtime dependencies. On amd64 only, `patchright install --with-deps chrome` is equivalent (Debian/Ubuntu bases only, per the script's `os-release` check). The image has no signed-in profile; it needs the profile mounted as a volume (Chrome locks a profile, so one container per profile).

## Summary per platform

| Platform | How the user gets Chrome | `patchright install chrome` |
| --- | --- | --- |
| macOS | Install Google Chrome normally | Works, but deletes and reinstalls `/Applications/Google Chrome.app` |
| Windows | Install Google Chrome normally | Works (admin) |
| Linux x64 | Google's `.deb` / apt repo | Works on Debian/Ubuntu only, needs root |
| Linux arm64 | Google's arm64 `.deb` | Fails, patchright-python#121 open |
| Docker | `apt-get install` Google's `.deb` per `TARGETARCH` | amd64 only |
