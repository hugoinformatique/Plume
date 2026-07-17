# Plume — Guide de test

Dictée vocale **100 % locale** pour Windows. Tu parles, ça écrit dans l'app active. Rien ne quitte le PC.

Ce guide te fait passer de « rien » à « je teste l'exe et je fais mon retour ». Cible principale : **HP Intel Core Ultra 5 125U**.

---

## 1. Récupérer Plume

Trois façons, de la plus simple à la plus « dev ».

### Option A — Installeur via une Release GitHub (recommandé)

La CI construit l'installeur Windows automatiquement. Pour déclencher une release téléchargeable :

```bash
# depuis le repo, sur le commit à tester
git tag v0.4.2
git push origin v0.4.2
```

Puis, sur GitHub : onglet **Releases** → `v0.4.2` → télécharge **`Plume-Setup-0.4.2.exe`**.
(Le build prend ~5–10 min. Tu peux suivre l'avancement dans l'onglet **Actions**.)

### Option B — Sans tag : artifact d'un build manuel

GitHub → onglet **Actions** → workflow **Windows Installer** → bouton **Run workflow**.
Quand c'est vert, ouvre le run → section **Artifacts** → télécharge `Plume-installer` (dézippe pour obtenir l'`.exe`).

### Option C — Build local sur Windows

Prérequis : Python 3.12, Git, [Inno Setup 6](https://jrsoftware.org/isdl.php).

```powershell
git clone https://github.com/hugoinformatique/Plume.git
cd Plume
git checkout feat/plume-pluggable-backends
.\scripts\build_windows.ps1
```

Sorties : `dist\Plume\Plume.exe` (portable) et `dist\installer\Plume-Setup-0.4.2.exe`.

### Option D — Lancer depuis les sources (test rapide, sans installeur)

```powershell
git clone https://github.com/hugoinformatique/Plume.git
cd Plume
git checkout feat/plume-pluggable-backends
.\install_windows.ps1
.\.venv\Scripts\Activate.ps1
python plume.py
```

---

## 2. Installer et lancer

1. Lance `Plume-Setup-0.4.2.exe` (installation sans droits admin, dans ton profil utilisateur).
2. Ouvre **Plume** depuis le menu Démarrer. La fenêtre est une **app native** (verre dépoli, noir & blanc), pas un navigateur.
3. **Premier lancement** : le modèle `small` (~460 Mo) se télécharge une fois depuis Internet, puis c'est 100 % local. Le statut passe à **« Prêt à dicter »** quand le moteur est chaud.

> Requiert **WebView2** (déjà présent sur Windows 11) pour le rendu de l'interface. Pour une version entièrement hors-ligne (sans le download du modèle), on bundlera les modèles plus tard.

---

## 3. Tester la dictée

1. Ouvre le Bloc-notes (ou un mail, Word, ton logiciel métier).
2. Clique **dans** la zone de texte.
3. Appuie sur **Ctrl + Espace** (raccourci par défaut, configurable dans Réglages) → une **bulle flottante « À l'écoute… »** apparaît en bas au milieu, barres **réactives à ta voix**.
4. Parle en français, 5–15 s (varie le volume pour voir les barres bouger).
5. Réappuie sur **Ctrl + Espace** → la bulle passe en **« Transcription… »**, puis le texte est **collé** dans l'app active.

À vérifier :
- la bulle s'affiche **sans voler le focus** (le texte doit se coller dans le Bloc-notes, pas ailleurs) — **point clé** de cette build web ;
- le design (fenêtre + bulle), la fluidité ;
- **onglet Mots** : ajoute un terme technique mal transcrit (ex. *kubernét → Kubernetes*) et revérifie qu'il sort correct ensuite ;
- **historique local** : vérifie que la dernière dictée apparaît et que les boutons copier / recoller fonctionnent ;
- **commandes vocales** : dicte par exemple `première ligne nouvelle ligne deuxième ligne point` ;
- **Réglages** : change le raccourci (clic → tape la combi), la position de la bulle, teste « Mode avancé ».

---

## 4. La barre des tâches (icône + clic droit)

Ferme la fenêtre (bouton **Réduire dans la barre**) : Plume reste actif dans la zone de notification, icône **plume**.

- **Clic gauche** sur l'icône → ouvre la fenêtre.
- **Clic droit** → menu :
  - **Afficher la fenêtre**
  - **Démarrer / Arrêter**
  - **Quitter**

Changer de modèle ou de moteur se fait dans **Réglages** et recharge le moteur en tâche de fond (le statut l'indique).

---

## 5. Performances

- Le moteur est **maintenu chaud** : après le 1er chargement, chaque F9 enchaîne directement la transcription (plus de rechargement du modèle à chaque fois).
- Reco pour le 125U : modèle **`small`** (bon compromis). `base` si tu veux plus rapide, `medium`/`turbo` seront probablement trop lourds pour dicter à chaud.

---

## 6. (Optionnel) Tester le NPU / l'iGPU via OpenVINO

Le backend par défaut (`faster-whisper`) tourne sur **CPU** et n'utilise **pas** la puce IA. Pour exploiter le **NPU (Intel AI Boost)** ou l'**iGPU Arc**, il faut OpenVINO.

À faire **sur le HP** :

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-openvino.txt

# Convertir un modèle une fois (dossier, pas un nom HF)
optimum-cli export openvino --model openai/whisper-small --weight-format int8 models\openvino\whisper-small

# Lancer l'app puis choisir NPU/iGPU dans Réglages > Mode avancé
python plume.py
```

Puis dans **Réglages > Mode avancé**, choisis le profil **NPU** ou **iGPU**.
Le champ « Modèle » doit pointer sur `models\openvino\whisper-small`.

### Benchmark comparatif (c'est lui qui tranche NPU vs iGPU vs CPU)

Mets quelques audios (`.wav`/`.mp3`, dont des courts) dans `samples\`, puis :

```powershell
python benchmark.py --backends faster-whisper --devices cpu --models base small --language fr
python benchmark.py --backends openvino --devices NPU GPU CPU --models models\openvino\whisper-small --language fr
```

Résultats (latence + RTF) dans `benchmark-results\results.csv`.

---

## 7. Ton retour

Copie-colle et remplis :

```text
--- Machine ---
PC : HP ...
CPU : Intel Core Ultra 5 125U
RAM :
Windows :

--- Dictée (par modèle testé) ---
Modèle / backend / device :
Temps de démarrage (1er chargement) :
Latence ressentie après le 2e F9 :
Qualité du texte (1-10) :
Ponctuation correcte (oui/non) :
Collé au bon endroit (oui/non) :

--- UX ---
Bulle « à l'écoute » : visible / animation OK / position OK ?
Icône barre des tâches : OK ?
Menu clic droit (modèle/moteur) : OK ?
Design de la fenêtre : (avis libre)

--- NPU/iGPU (si testé) ---
Résultats benchmark (colle le CSV ou les lignes clés) :

--- Problèmes / idées ---
```

Envoie-moi ça et j'itère.
