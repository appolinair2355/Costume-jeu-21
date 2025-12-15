# handlers_final.py

import logging
import time
import json
from collections import defaultdict
from typing import Dict, Any, Optional
import requests

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Importation Robuste
try:
    from card_predictor_final import CardPredictor, handle_mise_command
except ImportError:
    logger.error("❌ IMPOSSIBLE D'IMPORTER CARDPREDICTOR_FINAL")
    CardPredictor = None

user_message_counts = defaultdict(list)

# --- MESSAGES UTILISATEUR NETTOYÉS ---
WELCOME_MESSAGE = """
👋 **BIENVENUE SUR LE BOT ENSEIGNE !** ♠️♥️♦️♣️

Je prédis la prochaine Enseigne (Couleur) en utilisant :
1. **Règles statiques** : Patterns prédéfinis (ex: 10♦️ → ♠️)
2. **Intelligence artificielle (Mode INTER)** : Apprend des données réelles
3. **Règles manuelles (/mise)** : Injectez vos propres règles

━━━━━━━━━━━━━━━━━━━━━
📋 **COMMANDES DISPONIBLES**
━━━━━━━━━━━━━━━━━━━━━

**🔹 Informations Générales**
• `/start` - Afficher ce message d'aide
• `/stat` - Voir l'état du bot (canaux, mode actif)

**🔹 Mode Intelligent (INTER)**
• `/inter status` - Voir les règles apprises (Top 2 par enseigne)
• `/inter activate` - **Activer manuellement** le mode intelligent
• `/inter default` - Désactiver et revenir aux règles statiques

**🔹 Règles Manuelles**
• `/mise` - Envoyer des règles manuelles pour améliorer les prédictions

**🔹 Collecte de Données**
• `/collect` - Voir toutes les données collectées par enseigne

**🔹 Configuration**
• `/config` - Configurer les rôles des canaux (Source/Prédiction)

**🔹 Déploiement**
• `/deploy` - Télécharger le package pour Render.com

━━━━━━━━━━━━━━━━━━━━━
**💡 Comment ça marche ?**
━━━━━━━━━━━━━━━━━━━━━

1️⃣ Le bot surveille le canal SOURCE
2️⃣ Détecte les cartes et fait des prédictions
3️⃣ Envoie les prédictions dans le canal PRÉDICTION
4️⃣ Vérifie automatiquement les résultats
5️⃣ Collecte les données en continu pour apprentissage

🧠 **Mode INTER** : 
• Collecte automatique des données de jeu
• Mise à jour des règles toutes les 30 min
• **Activation MANUELLE uniquement** (commande `/inter activate`)
• Utilise les Top 2 déclencheurs par enseigne (♠️♥️♦️♣️)

🎯 **Règles Manuelles (/mise)** :
• Injectez vos propres règles avec `/mise`
• Fusion intelligente avec les règles existantes
• Maximum 2 règles par costume
• Les règles manuelles sont prioritaires

━━━━━━━━━━━━━━━━━━━━━
⚠️ **Important** : Le mode INTER doit être activé manuellement avec `/inter activate`
"""

HELP_MESSAGE = """
🤖 **AIDE COMMANDE /INTER**

• `/inter status` : Voir les règles apprises (Top 2 par Enseigne).
• `/inter activate` : Forcer l'activation de l'IA et relancer l'analyse.
• `/inter default` : Revenir aux règles statiques.
"""

MISE_HELP_MESSAGE = """
🎯 **COMMANDE /MISE**

Envoyez vos règles manuelles dans le format suivant:

