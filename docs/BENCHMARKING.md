# Benchmarking

Two ways to measure speed/quality. Both exercise the same
`backends.create_backend()` factory described in
[ARCHITECTURE.md](ARCHITECTURE.md), so results are comparable.

(An in-app "Bench" tab that automated this from inside `plume.py` was tried
and removed — the pywebview JS<->Python bridge did not work reliably for it
on real hardware (`window.pywebview.api` came back with zero exposed
methods on a stock packaged build; root cause not identified). The CLI tool
below doesn't depend on that bridge at all and is the supported way to run a
controlled multi-combination comparison.)

## 1. CLI sweep — `benchmark.py`

The scriptable version of the same idea, better for reproducible A/B/C
comparisons you want to keep across sessions or share as a CSV.

```powershell
# CPU baseline across models
python benchmark.py --backends faster-whisper --devices cpu `
    --models base small medium turbo --language fr --repeats 3

# OpenVINO targets (after converting a model, see README "OpenVINO / NPU")
python benchmark.py --backends openvino --devices CPU GPU NPU `
    --models models\openvino\whisper-small --language fr --repeats 3
```

Notes:

- `--backends`/`--devices`/`--models` are combined as a full cross product —
  run faster-whisper and openvino sweeps as **separate commands** (mixing
  them in one command tries invalid pairs like `faster-whisper` + `NPU`).
- `--repeats N` re-transcribes each file N times after the model is loaded,
  so timing reflects steady-state latency, not one-off cold-start noise.
- The OpenVINO backend only accepts `.wav` input; keep your comparison
  samples as wav so the same files work for both backends.
- Output: `benchmark-results/results.csv` (backend, device, model, file,
  seconds, audio_seconds, rtf, language, language_probability, chars, text).
  The command **overwrites** this file each run — pass `--output-dir` to keep
  multiple sweeps side by side.

RTF (real-time factor) here is `elapsed / audio_seconds`: **below 1.0 is
faster than real time**. For a dictation app, low absolute latency on short
clips (5-15s) matters more than RTF on long files, so keep some short samples
in `samples/`, not just long ones.

## 2. Real-usage history — `perflog.py`

Every real dictation from the app (not benchmark runs) logs one row to
`metrics.csv` — see [CONFIGURATION.md](CONFIGURATION.md) for the exact
columns and the `metrics` setting that gates it. Summarize that history
instead of relying on a single lab measurement:

```powershell
python perflog.py --summary
python perflog.py --tail 20
```

This is the one that answers "what does CPU vs NPU actually feel like over a
normal week of use on this machine", as opposed to a single controlled clip.

## Interpreting results

- **Speed**: compare `seconds`/`rtf` for the *same audio file* across
  backends/devices. Don't compare across different clips — length and speech
  rate change timing more than the engine does.
- **Quality**: there is no automatic word-error-rate scoring in this repo (no
  ground-truth transcripts). Eyeball the `text` column for the same clip
  across combinations — punctuation, technical terms, and hallucinated/missed
  words are the things worth flagging.
- **Reality check** (from Intel's own OpenVINO guidance and this project's
  own testing so far): on Core Ultra parts the **Arc iGPU (`GPU`)** is often
  the fastest OpenVINO target for Whisper; the **NPU** trades some speed for
  low power draw, low heat, and a free CPU. Don't assume NPU is fastest —
  measure it on the actual target hardware.
