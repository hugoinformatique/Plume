# Feuille de route (Roadmap) — Plume

Ce document consigne les fonctionnalités prioritaires de Plume et leur état.

---

## ✅ Livré

### 1. 🌐 Mode Traduction instantanée (FR ➔ EN)
Dicter en français, coller en anglais.

* **Déclenchement** : raccourci dédié, `Ctrl + Maj + Espace` par défaut,
  personnalisable dans Réglages, et désactivable.
* **Technique** : `task="translate"` — la seconde tâche native de Whisper, dans
  la même passe et le même modèle. 100 % local, aucune latence additionnelle,
  aucune dépendance externe (`backends.py`).
* **Indicateur** : badge `FR→EN` sur la bulle. La DA étant strictement
  achromatique, le mode se signale par une marque, jamais par une couleur.
* **Limite connue** : Whisper ne traduit que **vers l'anglais**. Les commandes
  vocales de ponctuation françaises ne sont pas appliquées à une sortie
  anglaise — elles la déformeraient.

### 2. 💬 Aperçu du texte dans la bulle (Live Preview)
Les mots s'affichent dans la bulle **pendant que l'on parle**, pas seulement à
la fin. Toutes les ~1,4 s, un extrait des **7 dernières secondes** est transcrit
et affiché ; la bulle s'élargit par paliers pour l'accueillir et tronque par la
gauche, de sorte que ce sont toujours les derniers mots qui restent lisibles.
Réglage « Aperçu dans la bulle », activé par défaut.

* **Pourquoi c'est gratuit** : pendant la dictée l'iGPU ne fait rien — la passe
  finale ne démarre qu'à l'arrêt. Deux garde-fous garantissent que ça le reste :
  la transcription finale prend un verrou et gagne toujours (un aperçu qui ne
  peut pas l'obtenir est abandonné, jamais mis en file), et chaque extrait est
  borné à quelques secondes, donc son coût ne grandit pas avec la durée de la
  dictée.
* **v1.1.0** n'affichait le texte qu'une fois la transcription terminée, ce qui
  n'avait effectivement guère d'intérêt.

### 3. ✍️ Commandes vocales d'édition & formatage
Étendues dans `sttlocal.py` (`apply_spoken_commands`), couvertes par
`scripts/test_commands.py` :

* **Structure** : « à la ligne » (`\n`), « nouveau paragraphe » / « saut de
  ligne » (`\n\n`, majuscule automatique ensuite), « tiret » / « puce » (liste
  à puces).
* **Ponctuation** : « deux points », « point-virgule », « points de
  suspension », « ouvrez / fermez les guillemets » (« … »), « ouvrez / fermez
  la parenthèse », plus la ponctuation déjà présente.
* **Édition** : « effacer » / « effacer le dernier mot », « tout effacer » /
  « annuler ». Ce ne sont pas des substitutions : le texte est replié de gauche
  à droite, car ces commandes suppriment ce qui a déjà été dicté.
* **Typographie française** : espace avant `: ; ! ?` et à l'intérieur des
  guillemets, pas avant `,` ni `.`. Le texte part dans des e-mails.

---

## 🔭 Pistes suivantes

* Signature Authenticode de l'installeur (chaîne CI déjà en place, il manque le
  certificat) — voir [SECURITY.md](SECURITY.md).
* Autres langues cibles que l'anglais, ce qui suppose un modèle de traduction
  séparé et non plus la tâche native de Whisper.
