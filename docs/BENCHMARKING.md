# Benchmarking

Three ways to measure speed/quality, from quickest to most rigorous. All of
them ultimately exercise the same `backends.create_backend()` factory
described in [ARCHITECTURE.md](ARCHITECTURE.md), so results are comparable.

## 1. In-app benchmark tab (temporary)

> **Temporary developer tool.** Everything for it is wrapped in
> `BENCHMARK MODE (temporary, remove after testing)` markers in `plume.py`
> and `ui/index.html`, added in one commit so it can be cleanly reverted
> (`git revert <that commit>`) once it's no longer needed. Don't build product
> features on top of it.

In the running app, the **Bench** tab:

1. Records one reference clip (`%APPDATA%\Plume\benchmark-clip.wav`) so every
   combination below is compared on *identical* audio — the biggest source of
   noise in a manual "try engine A, then try engine B" comparison.
2. Runs that clip through every `faster-whisper` model x compute-type
   combination (`base/small/medium/turbo` x `int8/int8_float16/float32`), plus
   every OpenVINO device (`NPU`/`GPU`/`CPU`) for every model directory found
   under `models/openvino/`.
3. Streams results into a table (time, RTF, transcribed text) and a
   timestamped log panel as it goes, and writes the full set to
   `%APPDATA%\Plume\benchmark-inapp.csv` at the end.

A run that has never loaded `medium`/`turbo` or a given OpenVINO model before
will pause on that combination while it downloads/compiles — the log panel is
there specifically so that shows up as progress, not as a hang.

## 2. CLI sweep — `benchmark.py`

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

## 3. Real-usage history — `perflog.py`

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
