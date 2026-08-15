# Debug notes: empty `window.pywebview.api` in the packaged app

Status: **unresolved**. Logged here so this isn't re-investigated from zero.
Part of the temporary [in-app benchmark mode](BENCHMARKING.md) work — delete
this file along with the rest of `BENCHMARK MODE (temporary)` markers once
that's removed, unless the underlying bridge issue turns out to be bigger
than the benchmark tab (see "Why this might matter beyond the benchmark tab"
below).

## Symptom

In the packaged (`Plume-Setup-X.Y.Z.exe`, built by
`.github/workflows/windows-installer.yml`) app, on the reporter's Windows
machine:

```js
Object.keys(window.pywebview.api)
// -> [] (length 0)
```

`window.pywebview.api` exists as an object but exposes **zero** methods —
not just the new benchmark-tab ones. Clicking any button wired to
`api.<method>()` throws:

```
Uncaught TypeError: window.pywebview.api[k] is not a function
```

## Ruled out

- **Stale build**: `Plume.exe` and `ui/index.html` had identical file
  timestamps at install time — the installer did overwrite both.
- **Stale running process**: confirmed via Task Manager, no leftover
  `Plume.exe` before reinstalling.
- **WebView2 persistent-profile caching of the bridge bootstrap**: tried
  `webview.start(..., private_mode=True)` to force a fresh profile per
  launch. Made no observable difference (`Object.keys` still `[]`) — reverted
  since it added complexity with zero evidence of benefit.
- **Wrong element IDs / duplicate IDs in `ui/index.html`**: checked, none.
- **JS syntax error aborting the whole `<script>` block**: `debug=True` was
  enabled specifically to check this; the only errors in the console are the
  `is not a function` ones caused by the empty api object itself, not a
  parse error elsewhere.

## Leading hypothesis, not yet tested

**PyInstaller freezing may interfere with pywebview's reflection-based Api
exposure.** pywebview builds `window.pywebview.api` by introspecting the
`Api` instance passed as `js_api=` at window-creation time (method names,
signatures). Frozen apps run under a different import/module machinery than
a normal `python script.py` invocation, and libraries that lean on
`inspect`/`dir()`/`__module__` at runtime occasionally behave differently
once frozen. This is untested here.

## Next diagnostic step (not yet done — needs Python installed on the test
machine, which the reporter did not have at time of writing)

Run **from source**, not the packaged exe, on the same Windows machine:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python plume.py
```

Then repeat the same devtools check (`Object.keys(window.pywebview.api)`):

- **Non-empty when run from source** -> confirms a PyInstaller/packaging
  interaction; next step is to bisect `Plume.spec` (hiddenimports, the
  `"plume"` hidden-import entry alongside the entry-point script, `optimize=0`
  vs default, `noarchive`) and/or file a pywebview issue with a minimal
  frozen repro.
- **Also empty when run from source** -> not a packaging issue; suspect the
  installed pywebview version (`pywebview>=5.3,<6` in `requirements.txt`)
  vs. the WebView2 Runtime version on that machine, or another environment
  factor (Windows version, .NET/pythonnet install, corporate policy
  restricting WebView2 features). Try pinning an exact pywebview version and
  / or checking the installed WebView2 Runtime version
  (`edge://version` inside any Edge/WebView2-hosted surface, or
  `reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" /v pv`).

## Why this might matter beyond the benchmark tab

If `window.pywebview.api` really is empty for every method (not just the new
ones), then **every UI-driven Api call in the shipped app** —
`set_setting`, `toggle` from the window button, `add_word`/`remove_word`,
history copy/paste, hotkey capture, update check/install — is silently
failing the same way for this user, past the point where any of this was
being watched closely (the earlier CPU-vs-NPU comparison was validated by
listening to the dictation result, which doesn't strictly prove
`set_setting` round-tripped through the JS bridge rather than, say, the
config already being in the right state). Worth a plain confirmation: does
the profile dropdown / any Réglages toggle visibly change behavior when
switched, on the currently installed build?
