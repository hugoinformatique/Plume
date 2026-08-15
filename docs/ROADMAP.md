# Feuille de route (Roadmap) — Plume

Ce document consigne les fonctionnalités prioritaires sélectionnées pour les prochaines itérations de Plume.

---

## 🚀 Prochaines fonctionnalités prioritaires

### 1. 🌐 Mode Traduction instantanée (FR ➔ EN)
* **Objectif** : Permettre à l'utilisateur de dicter en français et de coller instantanément le texte traduit en anglais dans l'application active.
* **Déclenchement** :
  * Raccourci clavier dédié (ex. `Ctrl + Maj + Espace` ou combinaison personnalisable dans Réglages).
  * Ou bouton / bascule rapide dans l'interface de dictée.
* **Architecture technique** :
  * Exploitation de la capacité native de Whisper (`task="translate"`, `target_language="en"`).
  * 100 % local, zéro latence additionnelle, aucune dépendance externe requise.
  * Indicateur visuel dédié sur la bulle liquide (ex. badge ou lueur saphir spécifique).

---

### 2. 💬 Affichage en direct dans la bulle flottante (Live Preview)
* **Objectif** : Afficher un retour visuel direct du texte reconnu au cours ou à la fin de la dictée, avant le collage effectif.
* **Détails de conception** :
  * Intégration harmonieuse dans la bulle **Liquid Glass / Goutte d'eau** ([floating_bubble.py](file:///home/agent/repos/Plume/floating_bubble.py)).
  * Animation douce avec fondu pour prévisualiser les mots clés transcrits.
  * Confirmation visuelle ultra-confortable pour l'utilisateur sans quitter des yeux son document de travail.

---

### 3. ✍️ Commandes vocales d'édition & formatage d'emails
* **Objectif** : Rendre la dictée de longs textes et d'e-mails professionnelle et fluide grâce à des commandes de mise en page vocales intelligentes.
* **Commandes de structure & saut de ligne** :
  * `« à la ligne »` ➔ retour à la ligne simple (`\n`).
  * `« nouveau paragraphe »` / `« saut de ligne »` ➔ saut de paragraphe double (`\n\n`) avec majuscule automatique sur la phrase suivante.
  * `« tiret »` / `« puce »` ➔ création automatique de listes à puces.
* **Ponctuation & typographie avancée** :
  * `« deux points »`, `« point-virgule »`, `« points de suspension »`.
  * `« ouvrez les guillemets »` / `« fermez les guillemets »`.
  * `« ouvrez les parenthèses »` / `« fermez les parenthèses »`.
* **Commandes d'édition d'action** :
  * `« effacer »` / `« effacer le dernier mot »` ➔ suppression du segment précédent.
  * `« tout effacer »` / `« annuler »`.
* **Architecture** :
  * Extension du pipeline de post-traitement dans [sttlocal.py](file:///home/agent/repos/Plume/sttlocal.py) (`apply_spoken_commands`).
