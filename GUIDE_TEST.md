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
git tag v1.1.0
git push origin v1.1.0
```

Puis, sur GitHub : onglet **Releases** → `v1.1.0` → télécharge **`Plume-Setup-1.1.0.exe`**.
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

Sorties : `dist\Plume\Plume.exe` (portable) et `dist\installer\Plume-Setup-1.1.0.exe`.

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

1. Lance `Plume-Setup-1.1.0.exe` (installation sans droits admin, dans ton profil utilisateur).
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
- **Réglages** : change le raccourci (clic → tape la combi), la position de la bulle, le nettoyage du texte.

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

## 4 bis. Vérifier les réglages (raccourci, push-to-talk, bip, mise à jour)

Depuis la v0.4.23, une action de l'interface qui échoue **le dit** au lieu de
faire semblant : le libellé revient à sa valeur précédente et le message
d'erreur s'affiche dans la ligne de statut. À tester dans cet ordre :

1. **Raccourci** — Réglages → clic sur le raccourci → tape la combinaison.
   Le libellé ne se fige sur la nouvelle valeur que si elle est réellement
   enregistrée. Vérifie que l'ancienne combinaison ne déclenche plus rien.
2. **Maintenir pour parler** — active la bascule, puis maintiens le raccourci :
   l'enregistrement doit durer tant que tu tiens, et s'arrêter à la relâche.
3. **Bip** — depuis la v0.4.24 il sort par la **carte son** (le même chemin
   audio que le micro) et non plus par le haut-parleur système émulé, muet sur
   beaucoup de machines ; depuis la v0.4.25 c'est **une seule note** par
   évènement (aiguë au départ, plus grave à l'arrêt), à la fréquence
   d'échantillonnage réelle de la sortie — l'ancien enchaînement de deux notes
   rééchantillonnées grésillait. Un échec est tracé dans `debug.log`
   (`beep via sounddevice failed`).
4. **Bulle flottante** (fenêtre native Liquid Glass / Goutte d'eau ultra-premium depuis la v0.4.26) — elle doit
   apparaître à chaque dictée, en bas au centre, **sans voler le focus**
   (le texte se colle bien dans l'app où tu écris). Tu peux la **déplacer à la
   souris** : sa position est retenue. Rechoisir « en haut / en bas » dans les
   réglages — ou le bouton **Replacer** — annule le déplacement. Si elle
   n'apparaît pas, `debug.log` contient une ligne commençant par `bubble:`
   (`tkinter unavailable`, `Tk root not ready…`).
5. **Moteur** — rien à choisir : l'installeur embarque OpenVINO et le modèle
   FP16, l'iGPU est utilisé d'office (voir §5). Le seul message attendu ici
   serait « Accélération iGPU indisponible sur ce PC : moteur CPU activé. »,
   qui signale un repli automatique — signale-le-moi si tu le vois.
6. **Réglages** — change une valeur, **quitte l'app** (menu de la zone de
   notification → Quitter), relance : la valeur doit être conservée.
7. **Mises à jour** — le bouton doit toujours finir par afficher quelque chose
   (version à jour, version disponible, ou un message d'erreur explicite).

Si quelque chose ne marche toujours pas, le fichier
`%APPDATA%\Plume\debug.log` tranche — envoie-le. On y lit :

- `api ping()` : l'interface parle bien au moteur. **Absent ⇒ le pont
  JS↔Python n'a jamais été établi**, et aucune action de l'UI ne peut marcher.
- `api set_setting(...)` / `config saved: ...` / `config set: ... -> ok` :
  le réglage est parti jusqu'au disque.
- `hotkey installed: combo=... mode=toggle|push-to-talk` : ce qui est
  réellement armé, et `hotkey fired:` / `hotkey released:` à chaque
  déclenchement.

Dans la fenêtre de l'app, `window.plumeDiag()` (console de développement)
renvoie l'état du pont et la liste des erreurs rencontrées.

---

## 5. Moteur et performances

Depuis la **v1.1.0**, il n'y a plus de choix de moteur : Plume tourne sur
l'**iGPU Intel Arc via OpenVINO**, avec un modèle `whisper-small` converti en
**FP16** embarqué dans l'installeur. Rien à installer, rien à convertir, aucun
réglage à faire — le « Mode avancé » a été retiré de l'interface.

- Le moteur est **maintenu chaud** : après le 1er chargement, chaque appui sur
  le raccourci enchaîne directement la transcription.
- Sur une machine sans iGPU exploitable, Plume bascule **toute seule** sur le
  moteur CPU et l'annonce dans la ligne de statut (« Accélération iGPU
  indisponible sur ce PC : moteur CPU activé. »). La dictée continue de
  fonctionner, un peu plus lentement.
- Ce qui compte maintenant à tester : le **temps du premier chargement**, la
  **latence ressentie** ensuite, et la **qualité du texte** en usage réel.

---

## 5 bis. Nouveautés v1.1.0 à tester

1. **La bulle** — elle doit être en **verre translucide** : on voit le bureau à
   travers, les bords sont lisses (plus d'escalier de pixels), et elle projette
   une ombre douce. Dis-moi si elle scintille, si elle laisse une traînée en la
   déplaçant, ou si elle apparaît en carré noir.
2. **Aperçu du texte** — à la fin d'une dictée, la bulle s'élargit et affiche le
   texte inséré (tronqué par la gauche si c'est long). Désactivable dans
   Réglages → « Aperçu dans la bulle ».
3. **Traduction FR→EN** — `Ctrl + Maj + Espace` : parle en français, c'est de
   l'anglais qui se colle. Un badge `FR→EN` apparaît sur la bulle. Le raccourci
   est modifiable et désactivable dans les Réglages.
4. **Commandes vocales** — à essayer en dictant, d'une traite :
   « objet deux points relance client **point** **nouveau paragraphe** bonjour
   Marc **virgule** je te confirme **point** » puis les listes
   (« **tiret** premier **tiret** second »), les guillemets
   (« **ouvrez les guillemets** … **fermez les guillemets** ») et surtout les
   corrections : « **effacer le dernier mot** », « **tout effacer** ».
   Vérifie l'espacement français : `Objet : relance`, `« parfait »`, `Vraiment !`

---

## 6. Réseau : ce que l'app fait (et ne fait pas)

Point à vérifier pour la validation sécurité : **par défaut Plume n'émet aucune
connexion sortante**. La recherche de mise à jour au lancement est un
interrupteur **désactivé** dans les Réglages ; le bouton « Vérifier » reste
disponible à la demande.

Test rapide : laisse l'interrupteur sur off, lance l'app, dicte — aucune
requête vers github.com ne doit apparaître (Moniteur de ressources → Réseau, ou
le proxy de l'entreprise). Détail complet dans
[docs/SECURITY.md](docs/SECURITY.md).

---

## 7. Ton retour

Copie-colle et remplis :

```text
--- Machine ---
PC : HP ...
CPU : Intel Core Ultra 5 125U
RAM :
Windows :

--- Dictée ---
Temps de démarrage (1er chargement) :
Latence ressentie après le 2e F9 :
Qualité du texte (1-10) :
Ponctuation correcte (oui/non) :
Collé au bon endroit (oui/non) :

--- UX ---
Bulle « à l'écoute » : visible / animation OK / position OK ?
Icône barre des tâches : OK ?
Design de la fenêtre : (avis libre)

--- Repli CPU ---
Message « moteur CPU activé » apparu ? (normalement non sur le 125U)

--- Problèmes / idées ---
```

Envoie-moi ça et j'itère.
