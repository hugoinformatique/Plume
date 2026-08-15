# Changelog

Versions correspond to `v*` git tags, each built and published by
`.github/workflows/windows-installer.yml`. See
[CONTRIBUTING.md#releasing](CONTRIBUTING.md#releasing) for the release
process.

## v0.4.26

- **Design « Goutte d'eau & Liquid Glass » sobre (Noir & Blanc, 120 Hz).**
  Refonte visuelle et cinématique complète de la bulle (`floating_bubble.py` et `listening_bubble.py`) inspirée des boutons de verre liquide :
  - **Palette 100 % achromatique (DA Noir & Blanc sobre)** : aucun accent coloré, uniquement du noir profond (`#000000`, `#0F0F0F`), du verre fumé translucide (`#171717`, `#222222`), des reflets spéculaires zénithaux (`#2C2C2C`, `#555555`, `#AAAAAA`, `#FFFFFF`) et des barres d'égaliseur blanc pur (`#FFFFFF`).
  - **Optique de verre liquide convexe** : galet organique 276x68 (rayon 30 px), ombre de contact douce au sol, dôme de réflexion supérieur avec croissant de verre poli et traînée brillante au sommet, caustique interne inférieure et ménisque de surface net.
  - **Fluidité 120 Hz & physique liquide** : boucle haute fréquence (`FRAME_MS = 12`, ~85-100 fps réels), amortissement visqueux asymétrique (`EASE_UP = 0.26`, `EASE_DOWN = 0.14`), dispersion de phase continue sur les 7 capsules d'ondes vocales et respiration liquide subtile sans aucune saccade.
  - **Perle de verre 3D & typographie** : perle blanche zénithale avec micro-reflet spéculaire 3D, orbiteur liquide fluide en transcription, libellés haute lisibilité ("Segoe UI", blanc pur / gris doux) et conservation de la non-activation de focus (`WS_EX_NOACTIVATE`) et du déplacement à la souris.

## v0.4.25

Retour de test de la v0.4.24 : la bulle apparaît enfin, le bip s'entend, le
logo est le bon. Restaient la couleur de la bulle, la qualité du son, la mise
à jour bloquée par GitHub, les profils NPU inutilisables, et l'interface.

- **La bulle repasse en noir et blanc.** Elle héritait de l'accent turquoise de
  `ui_theme` — hors direction artistique. Elle distingue désormais ses états
  par la valeur et le mouvement (blanc plein en écoute, gris atténué et
  balayage en transcription), jamais par la teinte.
- **Le bip ne grésille plus.** Il était fabriqué à 44,1 kHz imposés et
  rééchantillonné par Windows, et fait de deux notes collées bout à bout —
  d'où le hoquet. Une seule note, à la fréquence d'échantillonnage réelle de
  la sortie, avec attaque et extinction longues ; deux bips ne peuvent plus se
  chevaucher.
- **Mise à jour : plus de blocage par quota GitHub.** L'API GitHub anonyme est
  limitée à 60 requêtes par heure et par adresse IP — d'où le « rate limit »
  qui a obligé à télécharger l'installeur à la main. En cas d'échec, la
  recherche passe maintenant par `github.com/…/releases/latest`, une simple
  redirection sans quota, dont on déduit la version et l'URL de l'installeur.
  Si tout échoue, le message donne le lien direct.
- **Les profils NPU / iGPU sont utilisables tels quels.** L'installeur embarque
  désormais le runtime OpenVINO **et** un `whisper-small` déjà converti en
  int8 : plus rien à installer, plus de conversion à faire. La conversion est
  faite en CI dans un environnement séparé, pour que `optimum-intel` et torch
  (plusieurs Go) n'entrent jamais dans l'exécutable. Contrepartie assumée :
  l'installeur passe de ~65 Mo à plusieurs centaines de Mo — et comme il
  serait malvenu de télécharger ça tout seul à chaque lancement, une mise à
  jour de plus de 200 Mo (ou dont la taille est inconnue, ce qui est le cas
  par la route de secours ci-dessus) est proposée au lieu d'être installée
  d'office.
  (Le NPU peut encore échouer au chargement : conflit de versions en amont
  documenté dans `requirements-openvino.txt` ; l'iGPU n'est pas concerné.)
- **Interface.** Le champ de recherche de l'historique occupait la moitié de la
  fenêtre : conflit de règles CSS, `.field{flex:1}` (écrit pour le formulaire
  horizontal des mots) l'emportait sur `.histsearch{flex:none}`. Il fait
  maintenant 37 px et la liste prend tout le reste. Passe générale par
  ailleurs : palette rendue strictement achromatique (elle tirait sur le
  bleu), contrôles des réglages alignés sur une largeur commune, panneaux qui
  défilent au lieu de se comprimer, et micro remis au centre de l'écran de
  dictée.

## v0.4.24

Retour de test de la v0.4.23 : push-to-talk, changement de raccourci et
persistance des réglages fonctionnent. Restaient la bulle, le bip, et les
profils NPU/iGPU.

- **La bulle flottante devient une fenêtre native.** Quatre versions de suite
  elle n'est jamais apparue sur la machine de test alors qu'elle marchait en
  développement : c'était une seconde fenêtre pywebview *frameless +
  transparente + toujours au-dessus*, la combinaison la plus fragile de
  WebView2 sous Windows. Elle est réécrite en Tk natif
  (`floating_bubble.py`) : boucle Tk dans son propre thread, commandes
  sérialisées par une file, aucun appel Tk hors de ce thread, et repli
  silencieux (l'app continue de dicter) si Tk manque. Pilule de 260×64,
  coins arrondis par `-transparentcolor`, barres en capsules qui suivent la
  voix, balayage distinct pendant la transcription, confirmation « Collé »
  en fin de dictée — et surtout elle **ne prend jamais le focus**
  (`WS_EX_NOACTIVATE`), pour que le texte se colle dans la bonne fenêtre.
  Elle se **déplace à la souris** et retient sa position (`bubble_xy`) ;
  rechoisir haut/bas dans les réglages annule ce déplacement.
  `ui/bubble.html` disparaît avec l'ancienne approche.
- **Le bip sort enfin.** `winsound.Beep` pilote le haut-parleur de la carte
  mère (émulé, muet sur beaucoup de portables) : le son passe maintenant par
  la carte son via `sounddevice`, le même chemin audio que le micro — si la
  dictée s'entend, le bip aussi. Deux notes montantes au départ, descendantes
  à l'arrêt, avec des fondus de 6 ms pour éviter le clic ; `winsound` reste
  en repli.
- **Profils NPU / iGPU : refus explicite au lieu d'une erreur.** Ils
  demandent le runtime `openvino-genai` (absent de l'installeur) *et* un
  modèle converti localement. Les sélectionner enregistrait une configuration
  que le moteur ne pouvait plus charger, y compris aux démarrages suivants.
  `profile_blocker()` vérifie les deux avant d'écrire quoi que ce soit ; en
  cas de refus rien n'est persisté, le message dit ce qui manque, et la liste
  revient au profil CPU. Le modèle ne suit le profil que si celui-ci est
  accepté.
- **Interface** : l'historique devient une **rubrique à part entière**
  (recherche, dates relatives en français, copier/recoller par entrée, état
  vide), le logo de l'app est désormais **exactement celui du raccourci
  bureau** (même plume blanche sur tuile sombre, transcrite en SVG depuis
  `ui_theme.make_icon_image`), et la hiérarchie visuelle est resserrée :
  ligne de statut lisible et de hauteur fixe (plus de saut quand une erreur
  s'affiche), états de survol/focus cohérents et visibles au clavier.
- **Réparation automatique au démarrage** : une configuration déjà bloquée sur
  un profil NPU/iGPU par la v0.4.23 revenait en erreur moteur à chaque
  lancement, sans indice sur le réglage fautif. Elle est maintenant détectée et
  ramenée au profil CPU, avec un message.
- Détails issus de la relecture : la confirmation de fin de dictée n'est plus
  coupée au bout de 500 ms, la position de la bulle est bornée au **bureau
  virtuel** (un second écran reste une position valide), un démarrage lent de
  Tk ne désactive plus la bulle pour toute la session, et le bouton
  **Replacer** des réglages rattrape une bulle déplacée hors d'atteinte
  (resélectionner la même entrée d'une liste ne déclenche aucun évènement).

## v0.4.23

Audit des bugs restants de v0.4.22 (raccourci non pris en compte,
push-to-talk inopérant, aucun bip, bouton « vérifier les mises à jour »
sans effet, réglages non persistés). Tous ces symptômes ont un point
commun : **ce sont exactement les actions déclenchées depuis l'interface**,
alors que tout ce qui part de Python au démarrage (mise à jour auto,
raccourci par défaut) fonctionne. Le pont JS→Python avalait les erreurs à
trois endroits, ce qui rendait un échec indiscernable d'un succès.

- **Interface (`ui/index.html`) : fin des appels silencieusement perdus.**
  Le `Proxy` d'API résolvait `Promise.resolve()` quand
  `window.pywebview.api` n'était pas encore injecté — tout clic émis avant
  l'injection était purement perdu. Les appels sont désormais mis en
  attente derrière une promesse `bridgeReady`, résolue par l'évènement
  `pywebviewready` **ou** par un sondage (l'évènement pouvait être émis
  avant que le script n'y souscrive, auquel cas l'app restait sur son état
  de démonstration sans jamais lire la vraie config). Après 10 s sans
  pont : message d'erreur visible au lieu du silence.
- **Interface : confirmation au lieu d'optimisme.** Les bascules, les
  sélecteurs et la capture de raccourci n'affichent le nouvel état que si
  Python confirme ; sinon retour à l'état précédent et affichage de
  l'erreur. C'est ce qui produisait « dans l'app on voit bien que ça a
  changé, mais ça ne marche pas ». `window.plumeDiag()` et
  `window.__plumeErrors` exposent l'état du pont.
- **`Api` : contrat de retour explicite.** Chaque méthode passe par
  `@_api_call` : journalisée dans `debug.log`, elle renvoie toujours un
  objet `{ok, error}` sérialisable — une exception ne se perd plus dans
  une promesse rejetée ignorée. `set_setting` relit la valeur *sur le
  disque* et la renvoie (`stored`), `set_hotkey` renvoie la combinaison
  réellement enregistrée, et un `ping()` trace la vitalité du pont.
- **Raccourci : un seul moteur pour les deux modes.** `GlobalHotKeys`
  (mode bascule) et `HoldToTalk` (push-to-talk) sont remplacés par
  `HotkeyEngine`, un unique écouteur brut. La combinaison est validée
  **avant** d'arrêter l'écouteur en place, et un échec d'installation
  restaure l'ancien raccourci au lieu de laisser l'app sans raccourci ou
  avec l'ancien toujours actif à l'insu de l'UI. Le déclenchement est sur
  front montant : la répétition clavier de l'OS ne peut plus double-armer.
  Chaque déclenchement est tracé dans `debug.log`.
- **Bips.** Joués sur leur propre thread (`winsound.Beep` est bloquant et
  retardait le début de la capture et l'écriture du WAV), allongés de 70 à
  130 ms et rendus plus distincts, avec repli sur `MessageBeep` (qui passe
  par la carte son) et journalisation des échecs.
- **Persistance (`config.py`).** `save()` renvoie un booléen, réessaie
  `os.replace` 3 fois (antivirus/indexeur tenant le fichier ouvert sous
  Windows), se replie sur une écriture directe, et journalise l'échec
  au lieu du `except Exception: pass` qui masquait tout. Un `config.json`
  corrompu est mis de côté en `config.json.bad` au lieu de faire retomber
  silencieusement l'app sur les valeurs par défaut à chaque démarrage.
  Ajout de `verify()` / `reload_from_disk()` pour relire ce qui est
  réellement écrit.

Durcissements issus de la relecture du correctif :

- **L'injection du pont pywebview se fait en deux temps** :
  `window.pywebview.api` existe (vide) avant que les méthodes n'y soient
  greffées. Tester l'objet seul — ce que faisait le code d'origine —
  pouvait donc réussir puis appeler `undefined`. Le test porte désormais
  sur la présence effective de `api.ping`.
- **Surface exposée au JS réduite** : pywebview parcourt l'objet `js_api`
  avec `dir()` et expose récursivement tout ce qu'il trouve d'accessible.
  `Api.app` étant public, ce sont des centaines de méthodes internes
  (`app.quit`, `app.config.path.unlink`, `app.window.destroy`…) qui étaient
  publiées à la page — et leur énumération, faite avant `pywebviewready`,
  qui retardait la disponibilité du pont. L'attribut devient `Api._app`.
- **Aucun échec ne peut laisser l'app sans raccourci** : si l'écouteur
  refuse de démarrer, le précédent est ré-armé (`_restart`), et un passage
  en push-to-talk refusé remet aussi la valeur enregistrée à l'ancienne.
- `HotkeyEngine.start()` borne l'attente de `pynput` (son `wait()` est un
  `Condition.wait()` sans délai : un backend qui meurt à l'initialisation
  bloquait l'appelant indéfiniment, verrou en main).
- Écritures de config : nom de fichier temporaire propre au processus et
  verrou de sauvegarde, pour que la fin d'une dictée (écriture de
  l'historique) et un changement de réglage ne se marchent plus dessus.
- `debug.log` : rotation à 1 Mo, une génération conservée.

## v0.4.22

- Root-caused the settings-not-persisting and push-to-talk-not-working
  reports from v0.4.21: **no single-instance guard**. Now that the app
  starts hidden in the tray (v0.4.19), it's easy to launch `Plume.exe` a
  second time without noticing one is already running -- two processes
  then each hold an independent in-memory copy of the config and can both
  write `config.json`, and only one of them actually owns the global
  hotkey registration, so settings changed in the instance you're looking
  at can be silently overwritten or simply not the one responding to the
  hotkey. Added a named-mutex single-instance lock: a second launch now
  exits immediately instead of running alongside the first.
- Reworked `_parse_combo_keys` to delegate to pynput's own
  `HotKey.parse()` instead of a hand-rolled parser, removing a class of
  possible combo-parsing mismatches for push-to-talk.
- Added `%APPDATA%\Plume\debug.log`: a small always-on trail (hotkey mode
  installed, every `set_setting` call, single-instance check result),
  independent of the JS bridge and of debug mode, so the next report can
  be diagnosed from evidence instead of another guess.

## v0.4.21

- Repo consolidated onto a single branch: `main` now points at what was
  `feat/plume-pluggable-backends`'s tip; all tags/releases/CI happen there
  from now on.
- Add push-to-talk: hold the hotkey to record, release to stop, instead of
  press-toggle. Off by default, toggle it in Réglages ("Maintenir pour
  parler"). Implemented with raw key press/release tracking (`HoldToTalk`
  in `plume.py`) since `pynput.GlobalHotKeys` only supports one-shot
  press detection. This may also explain the still-unresolved bubble
  flicker: holding a toggle-mode hotkey can retrigger on OS key-repeat.
- Add a short, distinct start/stop beep (`winsound`), independent of the
  bubble window — a fallback feedback channel that doesn't depend on
  WebView2 rendering at all. Toggle in Réglages ("Retour sonore"), on by
  default.
- History is now searchable and no longer capped at 3 visible items in the
  Dictée tab.
- `config.json` writes are now atomic (write-to-temp then rename) instead
  of in-place, to rule out settings resetting to defaults if a write was
  ever interrupted mid-save.

## v0.4.20

- Bubble fix in v0.4.19 (debounce) didn't resolve it — still showed once
  then never again reliably. Switched from a persistent hidden window
  toggled with `.show()`/`.hide()` to creating a fresh bubble window per
  dictation and destroying it right after. A long-lived hidden/shown
  transparent+frameless WebView2 window proved unreliable across repeated
  cycles on real hardware; a short-lived one avoids that state entirely.

## v0.4.19

- Fix the listening bubble showing for a single frame then disappearing:
  the global hotkey could fire `toggle()` twice for one press (OS key-repeat
  on the space bar), starting and immediately stopping the recording.
  Debounced. (Turned out not to be the whole story — see v0.4.20/v0.4.22.)
- Start minimized to the tray instead of opening the main window every
  launch; use the tray icon (double-click, or "Afficher Plume") to open it.
- Fix automatic updates failing with "impossible de fermer l'application":
  the installer was launched with `/CLOSEAPPLICATIONS`, which asks Windows
  to close Plume -- while Plume was itself blocked waiting for the
  installer to finish, a deadlock. Plume now quits immediately after
  launching the installer and hands off waiting/relaunching to a detached
  helper process.

## v0.4.18

- Removed the in-app "Bench" tab entirely (all `BENCHMARK MODE (temporary,
  remove after testing)` blocks in `plume.py` and `ui/index.html`, plus
  `docs/BENCH_BRIDGE_DEBUG.md`). It never reliably worked on real hardware —
  `window.pywebview.api` came back empty in the packaged app for reasons
  never pinned down (see v0.4.11–v0.4.15 for the investigation). CLI
  `benchmark.py` (unaffected by that bridge) remains the supported way to
  run a controlled multi-combination comparison; see
  [docs/BENCHMARKING.md](docs/BENCHMARKING.md). Everything unrelated to the
  Bench tab from this stretch of releases (auto-update, the bubble fix,
  recordings cleanup, CPU tuning, the doc set) is kept.

## v0.4.16

- Startup update check now installs automatically instead of only showing a
  banner: if a newer GitHub release is found, Plume downloads and silently
  installs it, then relaunches itself. This path runs from Python directly
  (not through the JS bridge), so it works independently of the
  `window.pywebview.api` issue below.
- Fixed the silent-update installer never relaunching Plume afterward
  (Inno Setup skips its postinstall auto-launch in `/SILENT` mode) —
  Plume now waits for the installer and relaunches itself explicitly.
- `debug=True` (added in v0.4.13 to inspect the JS bridge) reverted to
  `False`: suspected cause of the floating listening bubble no longer
  showing (transparent/frameless window + devtools mode don't mix well).
- Recordings are deleted right after transcription instead of accumulating
  in `recordings/` forever; a startup sweep also clears anything left over
  from a crashed session older than 24h.
- Parked the in-app Bench tab investigation (deprioritized). Later fully
  removed in v0.4.18.

## v0.4.15

- `private_mode=True` (v0.4.14) made no difference — `window.pywebview.api`
  is still completely empty (`Object.keys(...)` -> `[]`), not just missing
  the benchmark methods. Reverted it (no evidence it helped, only added
  risk). This is now a bigger issue than the benchmark tab: the JS<->Python
  bridge appears non-functional for *every* Api method in this build.
  Root cause still open — see `docs/BENCH_BRIDGE_DEBUG.md` for what's ruled
  out and the next diagnostic step (run `python plume.py` from source to
  isolate whether this is a PyInstaller packaging issue or a pywebview/
  WebView2 environment issue).

## v0.4.14

- Found it (via devtools console, added in v0.4.13): `window.pywebview.api`
  was missing `bench_record_start`/`bench_record_stop`/`run_benchmark`
  entirely, even with a byte-for-byte fresh install (exe and `ui/index.html`
  same timestamp). Root cause suspected at the time: WebView2 keeps a
  persistent browser profile across app versions. `webview.start(...,
  private_mode=True)` forced a clean profile every launch — turned out not
  to fix it (see v0.4.15).

## v0.4.13

- Still no `benchmark-inapp.log` created after a clean reinstall + relaunch
  (ruled out a stale locked process from a previous version). Since the
  Python-side logging added in v0.4.12 never fires, the failure must be on
  the JS side of the bridge, invisible until now: `webview.start(...,
  debug=True)` — enables right-click "Inspect"/"Afficher les outils de
  developpement" so real JS console errors are finally visible instead of
  failing completely silently.

## v0.4.12

- Root-caused v0.4.11's "nothing happens, 0% CPU/network" report: the log
  file never existed, meaning `run_benchmark()` was returning immediately
  because the reference clip wasn't found — the record-clip step was
  failing silently with no error surfaced. `bench_record_start`/`_stop` now
  log every step (mic open, capture stop, file save) and report real errors
  instead of a generic "too short", so a microphone failure is visible
  instead of indistinguishable from a hang.
- The log file is append-only across the whole session now (previously the
  benchmark run truncated it, erasing the record-step history that would
  have explained this).

## v0.4.11

- Benchmark log is now also written to `%APPDATA%\Plume\benchmark-inapp.log`
  on disk, live, independently of the in-app UI panel — so progress is
  visible even if the JS bridge update doesn't render for some reason.
- Set `HF_HUB_DOWNLOAD_TIMEOUT` before a sweep so a stalled connection while
  downloading an uncached model fails fast instead of hanging indefinitely;
  log whether each faster-whisper model is already cached locally before
  attempting to load it, so a pending download is obvious upfront.

## v0.4.10

- Fix the in-app benchmark sweep hanging with no feedback and no way to
  relaunch if it hit an unexpected error; add a scrolling, timestamped
  progress log so a slow (e.g. first-time model download) run is visibly
  different from a stuck one.
- Add `docs/ARCHITECTURE.md`, `docs/CONFIGURATION.md`, `docs/BENCHMARKING.md`,
  `CONTRIBUTING.md`, `CHANGELOG.md`; README now indexes all documentation.

## v0.4.9

- Add a temporary in-app "Bench" tab: record one reference clip, run it
  through every backend/device/model/compute combination, see results and a
  live log in the app, export to CSV. Marked for removal once no longer
  needed.

## v0.4.8

- Tune the `faster-whisper` CPU backend for reliability/speed: pin
  `cpu_threads` to the machine's core count instead of the default (avoids
  Windows scheduling work onto Intel hybrid low-power cores), expose
  hallucination-reduction thresholds.
- Add `perflog.py` to summarize/tail the `metrics.csv` performance history
  the app already writes per dictation.
- Accessibility/motion polish on the glass UI: visible keyboard focus rings,
  `prefers-reduced-motion` support, keyboard-operable settings toggles.
- Reserve the glass/blur treatment for the hero (mic button) card only;
  flatten secondary cards for a calmer visual hierarchy.

## v0.4.7

- Add an in-app update flow (check GitHub Releases, download and launch the
  new installer from within the app).

## v0.4.6

- Remove duplicate window controls; use a monochrome tray/window icon.

## v0.4.5

- Fix history list horizontal overflow in the main window.

## v0.4.4

- Rework hotkey capture and settings window controls.

## v0.4.3

- Harden the global hotkey and window scrolling behavior on Windows.

## v0.4.2 / v0.4.1

- UI polish pass on the desktop app and hotkey capture flow.

## v0.4.0

- Package the app with `pywebview` (replacing the Tk-only UI as the primary
  product surface): `plume.py` entry point, bundle the `ui/` folder,
  `clr_loader`/`pythonnet` for the Windows EdgeChromium backend.
- Add dictation history and spoken punctuation commands (`apply_spoken_commands`
  in `sttlocal.py`).
- Web-glass UI, correction dictionary (`vocabulary.py`), configurable hotkey.

## v0.3.1

- UI/window design polish; voice-reactive listening bubble.

## v0.3.0

- Generate the app icon programmatically; publish the installer as a GitHub
  Release asset on tag push (CI).
- Rename the product from **ScribeLocal** to **Plume**.
- Add pluggable STT backends (`backends.py`): `faster-whisper` (CPU baseline)
  and `openvino` (CPU/GPU/NPU on Intel Core Ultra), replacing the earlier
  CPU-only engine.

## Before v0.3.0 (ScribeLocal MVP)

- Local Whisper dictation MVP (`faster-whisper`, CPU): global hotkey,
  clipboard paste, text cleanup.
- Windows tray test app, testing procedure docs, Windows installer packaging.
