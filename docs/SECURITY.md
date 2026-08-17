# Plume — dossier sécurité

Document destiné à une validation en entreprise (RSSI, poste de travail,
antivirus/EDR). Il décrit ce que l'application fait réellement, fichier par
fichier et capacité par capacité, y compris les points qui peuvent légitimement
faire réagir un antivirus.

Version couverte : **1.2.0**. Code source : `https://github.com/hugoinformatique/Plume` (MIT).

---

## 1. En une phrase

Plume enregistre la voix au micro sur demande de l'utilisateur, la transcrit
**localement** (modèle Whisper `small` embarqué, exécuté sur l'iGPU Intel Arc
via OpenVINO), colle le texte dans l'application active, puis supprime
l'enregistrement. Aucune donnée — audio, texte, statistique d'usage — ne quitte
le poste.

## 2. Flux réseau

| Flux | Quand | Par défaut |
|---|---|---|
| `api.github.com` / `github.com` — recherche et téléchargement d'une mise à jour | Au lancement **uniquement si** le réglage « Rechercher les mises à jour au lancement » est activé, ou quand l'utilisateur clique sur « Vérifier » | **Désactivé** |

C'est le **seul** flux sortant du produit. Il n'y a :

- aucune télémétrie, aucun analytics, aucun rapport de crash distant ;
- aucun appel à un service de transcription, de traduction ou à une API d'IA —
  la traduction FR→EN est faite par le même modèle Whisper embarqué, en local ;
- aucun téléchargement de modèle au premier lancement — le modèle est dans
  l'installeur (c'est ce qui explique sa taille) ;
- aucun serveur, aucun port en écoute côté application.

Le réglage est stocké dans `auto_update` (`config.json`). Pour un déploiement
verrouillé, il peut rester à `false` et le flux GitHub être bloqué au proxy sans
aucun impact sur le fonctionnement : les mises à jour se font alors par
redéploiement de l'installeur.

**Vérification indépendante possible** : lancer l'app, dicter, et observer
l'absence de connexion sortante (Moniteur de ressources → Réseau, journaux du
proxy, ou capture Wireshark).

## 3. Données et fichiers écrits

Tout est sous `%APPDATA%\Plume\` (profil utilisateur, pas de droits admin) :

| Chemin | Contenu | Durée de vie |
|---|---|---|
| `config.json` | Réglages, dictionnaire de correction, **historique des ~12 dernières dictées** (texte) | Persistant, supprimable à la main |
| `recordings\` | Fichiers `.wav` temporaires de la dictée en cours, et les extraits de quelques secondes que l'aperçu en direct transcrit pendant qu'on parle | Supprimés juste après chaque transcription ; un nettoyage des résidus > 24 h a lieu au démarrage |
| `debug.log` | Trace de diagnostic locale (actions UI, activations du raccourci, erreurs). **Ne contient pas le texte dicté ni l'audio** | Rotation à 1 Mo, une génération conservée |

Installation : `%LOCALAPPDATA%\Programs\Plume\` (installeur par utilisateur,
`PrivilegesRequired=lowest`, pas d'écriture dans `Program Files`, pas de
service, pas de tâche planifiée, pas de pilote).

Aucune donnée n'est écrite ailleurs. Rien n'est chiffré : l'historique des
dictées et le dictionnaire sont en clair dans `config.json`, protégés par les
seules ACL du profil utilisateur. **Si les textes dictés sont sensibles, c'est
le point à évaluer** — l'historique peut être vidé depuis l'onglet Historique.

## 4. Capacités système utilisées

| Capacité | Pourquoi | Portée |
|---|---|---|
| **Microphone** (`sounddevice`) | Enregistrer la dictée | Uniquement entre le début et la fin d'une dictée déclenchée par l'utilisateur. Pas d'écoute permanente, pas de mot-clé de réveil. |
| **Écoute clavier globale** (`pynput`) | Détecter le raccourci (`Ctrl + Espace` par défaut), y compris quand la fenêtre n'a pas le focus | Le listener voit les frappes du système. Le code ne les enregistre pas et ne les transmet nulle part : il compare la combinaison au raccourci configuré et l'ignore sinon (`HotkeyEngine`, `plume.py`). |
| **Frappe clavier synthétique** | Coller le texte : le presse-papiers est renseigné puis `Ctrl+V` est envoyé à l'application active | Uniquement à la fin d'une dictée, si le collage automatique est activé. |
| **Presse-papiers** (`pyperclip`) | Support du collage | Écriture seulement ; le contenu précédent du presse-papiers est écrasé. |
| **Registre `HKCU\...\CurrentVersion\Run`** | Option « Démarrer avec Windows » | Écrit/supprimé uniquement quand l'utilisateur bascule l'interrupteur. HKCU seul, jamais HKLM. |
| **iGPU Intel via OpenVINO** | Exécution du modèle | Calcul local. |
| **WebView2 (Edge)** | L'interface est du HTML local rendu par pywebview | Charge un fichier `ui/index.html` livré dans le paquet, **pas** de contenu distant. |
| **Fenêtre superposée (layered window)** | La bulle flottante translucide | L'app *dessine* une image et la pousse à l'écran (`UpdateLayeredWindow`). Elle ne **lit jamais** les pixels de l'écran : l'effet de verre est obtenu par transparence, pas par capture et floutage de l'arrière-plan. Aucune capacité de capture d'écran n'est utilisée nulle part dans le produit. |

Pas d'élévation de privilèges, pas d'injection dans d'autres processus, pas de
hook noyau, pas d'accès aux fichiers de l'utilisateur en dehors de `%APPDATA%\Plume`.

## 5. Points qui peuvent faire réagir un antivirus / EDR

Signalés ici explicitement, parce qu'ils sont légitimes mais ressemblent, pris
isolément, à des comportements surveillés :

1. **Binaire non signé.** L'installeur n'a pas de certificat Authenticode :
   Windows affiche « Éditeur inconnu » (SmartScreen) et certains moteurs
   inspectent davantage la première exécution. C'est le point de friction
   principal en entreprise. La démarche de signature (SignPath ou certificat
   OV/EV) est décrite dans [CONTRIBUTING.md](../CONTRIBUTING.md#code-signing-reducing-smartscreenantivirus-warnings).
   La chaîne de signature est **déjà câblée en CI** (`scripts/sign_windows.ps1`,
   déclenchée dès que le certificat est fourni en secret de dépôt) : il ne
   manque que le certificat lui-même.
   *Contournement propre côté client en attendant : déployer via un partage
   validé et ajouter le hash de l'installeur en liste d'autorisation.*
2. **Packaging PyInstaller.** L'exe extrait ses dépendances et charge des DLL
   depuis son dossier : signature comportementale partagée avec de nombreux
   packers, d'où des faux positifs génériques (`Wacatac`, `Heuristic`…)
   fréquents sur les binaires Python empaquetés.
3. **Écoute clavier globale + frappe synthétique.** Techniquement les mêmes
   API qu'un keylogger. La différence est ce qui est fait des frappes : ici
   rien n'est stocké ni transmis, et le code concerné tient dans
   `HotkeyEngine` (`plume.py`) et `paste_text()` (`sttlocal.py`), tous deux
   relisables en quelques minutes.
4. **Lancement d'un installeur depuis l'app**, uniquement si l'utilisateur
   demande une mise à jour : le fichier téléchargé est exécuté **visiblement**,
   avec sa fenêtre d'installation, et c'est l'installeur lui-même qui relance
   Plume. La v1.0.0 a supprimé le PowerShell en fenêtre masquée qui servait
   auparavant à cela (`-WindowStyle Hidden`, processus détaché) : c'était le
   comportement le plus susceptible d'alerter un EDR, pour quelques secondes de
   confort. Plus aucun processus masqué n'est créé par l'application.
5. **Clé `Run` en HKCU** si l'utilisateur active le démarrage automatique —
   persistance classique, ici visible et réversible depuis l'interface.

## 6. Dépendances tierces

Toutes publiques, épinglées dans `requirements.txt` /
`requirements-openvino-runtime.txt` :

`faster-whisper`, `numpy`, `sounddevice`, `pynput`, `pyperclip`, `Pillow`,
`pystray`, `requests`, `pywebview`, `pythonnet`, `openvino`, `openvino-genai`,
`openvino-tokenizers`.

Le modèle est `openai/whisper-small` (MIT), converti en IR OpenVINO FP16 au
moment du build, dans un environnement jetable (le convertisseur
`optimum-intel` et `torch` ne sont **pas** dans le paquet livré).

La construction est reproductible et publique : elle tourne sur GitHub Actions
(`.github/workflows/windows-installer.yml`) à partir du tag de version, et
l'installeur publié est l'artefact de ce workflow.

## 7. Résumé pour la validation

- Traitement 100 % local, y compris le modèle : **fonctionne sur un poste
  totalement déconnecté**.
- Aucun flux sortant par défaut ; un seul flux possible (GitHub), opt-in et
  bloquable sans effet de bord.
- Installation par utilisateur, sans droits administrateur, sans service ni
  pilote.
- Données au repos : réglages et historique en clair dans le profil
  utilisateur ; audio supprimé après chaque transcription.
- Réserve connue : **binaire non signé** à ce stade — prévoir soit la
  signature, soit une autorisation par hash dans la solution de sécurité.
