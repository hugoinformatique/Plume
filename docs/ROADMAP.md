# Feuille de route (Roadmap) — Plume

Ce document consigne les fonctionnalités prioritaires de Plume et leur état.

---

## ✅ Livré en v1.1.0

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
Le texte reconnu s'affiche dans la bulle au moment où il est inséré : la bulle
s'élargit pour l'accueillir (jusqu'à 560 px), tronque par la gauche pour garder
la fin de la phrase lisible, et reste affichée plus longtemps quand le texte est
long. Réglage « Aperçu dans la bulle », activé par défaut.

* **Ce qui n'est pas fait, et pourquoi** : l'aperçu *pendant* que l'on parle
  demanderait de transcrire des extraits en continu, donc une seconde inférence
  sur l'iGPU qui exécute déjà la transcription finale — au prix de la latence
  que le produit vient d'optimiser. L'aperçu se fait donc en fin de dictée.

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
* Aperçu en direct pendant la dictée, si un modèle de streaming assez léger
  permet de le faire sans concurrencer la passe finale sur l'iGPU.
* Autres langues cibles que l'anglais, ce qui suppose un modèle de traduction
  séparé et non plus la tâche native de Whisper.
