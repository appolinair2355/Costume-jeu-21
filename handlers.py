# handlers (4).py

import logging
import time
import json
from collections import defaultdict
from typing import Dict, Any, Optional
import requests
import os # Import pour la gestion des fichiers

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Importation Robuste
try:
    from card_predictor import CardPredictor, STATIC_RULES
except ImportError:
    logger.error("❌ IMPOSSIBLE D'IMPORTER CARDPREDICTOR")
    CardPredictor = None
    STATIC_RULES = {}

user_message_counts = defaultdict(list)

# --- MESSAGES UTILISATEUR NETTOYÉS ---
WELCOME_MESSAGE = """
👋 **BIENVENUE SUR LE BOT ENSEIGNE !** ♠️♥️♦️♣️

Je prédis la prochaine Enseigne (Couleur) en utilisant :
1. **Règles statiques** : Patterns prédéfinis
2. **Intelligence artificielle (Mode INTER)** : Apprend des données réelles (Top 2 par enseigne)

━━━━━━━━━━━━━━━━━━━━━
📋 **COMMANDES DISPONIBLES**
━━━━━━━━━━━━━━━━━━━━━

**🔹 Infos & Contrôle**
• `/start` - Afficher ce message d'aide
• `/stat` - Voir l'état du bot (canaux, mode actif)
• `/config` - Configurer le canal Source/Prédiction

**🔹 Commandes de Maintenance**
• `/r` ou `/reset_stock` - **RESET MANUEL** des prédictions (ne touche pas à l'IA)
• `/a` ou `/toggle_ia` - Activation/Désactivation rapide du mode IA
• `/deploy` - Générer le fichier ZIP de déploiement

**🔹 Mode Intelligent (INTER)**
• `/inter status` - Voir les règles apprises (Top 2)
• `/inter activate` - **Activer manuellement** le mode intelligent
• `/inter default` - Désactiver et revenir aux règles statiques
• `/collect` - Voir les données collectées
"""

# ... (reste des messages inchangés)

class TelegramHandlers:

    def __init__(self, bot_token: str, server_url: str):
        self.bot_token = bot_token
        self.server_url = server_url
        self.api_url = f"https://api.telegram.org/bot{bot_token}"
        self.card_predictor = CardPredictor(self.send_message)
        logger.info("Handlers initialized.")
        
    def send_message(self, chat_id: int, text: str, message_id: Optional[int] = None, reply_to_message_id: Optional[int] = None, keyboard: Optional[Dict[str, Any]] = None, parse_mode='Markdown'):
        # ... (méthode inchangée, utilise 'Markdown')

    def send_action(self, chat_id: int, action: str):
        # ... (méthode inchangée)

    def _handle_command(self, text: str, chat_id: int, message_id: int, from_user_id: int):
        # ... (méthode inchangée)
        
        command = text.split()[0].lower()
        args = text.split()[1:]
        
        # --- NOUVELLES COMMANDES RAPIDES ---
        if command in ('/r', '/reset_stock'):
            # Reset manuel des stocks de prédiction (uniquement)
            self.card_predictor.predictions = {}
            self.card_predictor.last_prediction_time = 0
            self.card_predictor.last_predicted_game_number = 0
            self.card_predictor.consecutive_fails = 0
            self.card_predictor._save_all_data() 
            self.send_message(chat_id, "✅ **RESET MANUEL** : Stocks de prédiction réinitialisés (Historique IA conservé).")
            return
            
        if command in ('/a', '/toggle_ia'):
            current_state = self.card_predictor.is_inter_mode_active
            new_state = not current_state
            
            self.card_predictor.is_inter_mode_active = new_state
            self.card_predictor._save_data(new_state, 'is_inter_mode_active.json')
            
            mode = "ACTIVÉ" if new_state else "DÉSACTIVÉ"
            emoji = "🧠" if new_state else "📜"
            self.send_message(chat_id, f"{emoji} Mode Intelligent (INTER) **{mode}**.")
            return

        # --- COMMANDES EXISTANTES ---
        if command == '/start':
            self.send_message(chat_id, WELCOME_MESSAGE)
        
        # ... (Reste des commandes /stat, /config, /deploy, /collect, /inter status, /inter activate, /inter default)
        
        if command == '/inter':
            if not args or args[0].lower() == 'status':
                 # ... (Logique /inter status inchangée)
            elif args[0].lower() == 'activate':
                # ... (Logique /inter activate inchangée)
            elif args[0].lower() == 'default':
                # ... (Logique /inter default inchangée)
        
        # ... (Le reste de _handle_command est inchangé)

    def _handle_callback_query(self, callback_query: Dict[str, Any]):
        # ... (Méthode inchangée)
        
    def handle_update(self, update: Dict[str, Any]):
        try:
            if not self.card_predictor: return

            # AJOUT CRITIQUE : Vérification du reset quotidien (00h59 WAT)
            self.card_predictor.check_and_reset_predictions()

            # 1. Traitement des messages dans le canal SOURCE
            if ('channel_post' in update and 'text' in update['channel_post']) and (update['channel_post']['chat']['id'] == self.card_predictor.target_channel_id):
                
                msg = update['channel_post']
                text = msg.get('text', '')
                game_num = self.card_predictor.extract_game_number(text)
                
                if game_num and game_num not in self.card_predictor.processed_messages:
                    
                    # A. COLLECTE IA (N-2 -> N)
                    # Le résultat N est la donnée pour apprendre la carte N-2
                    self.card_predictor.collect_inter_data(game_num, text)

                    # B. PRÉDICTION (N -> N+2)
                    prediction_data = self.card_predictor.should_predict(text)
                    if prediction_data:
                        predicted_suit, is_inter = prediction_data
                        res = self.card_predictor.make_prediction(game_num, predicted_suit, is_inter)
                        
                        if res and res['type'] == 'send_message':
                            # Envoi dans le canal de prédiction
                            sent_msg = self.send_message(self.card_predictor.prediction_channel_id, res['message'])
                            if sent_msg:
                                # Sauvegarde l'ID du message de prédiction pour l'édition future
                                self.card_predictor.predictions[res['predicted_game']]['message_id'] = sent_msg['message_id']
                                self.card_predictor._save_all_data() 
                    
                    # C. VÉRIFICATION (Vérifie si ce message N est la vérification du jeu N-2)
                    # La vérification est faite immédiatement après la collecte/prédiction sur le nouveau message
                    res = self.card_predictor.verify_prediction(text)
                    if res and res['type'] == 'edit_message':
                        mid_to_edit = res.get('message_id_to_edit')
                        if mid_to_edit:
                            # Édition du message de prédiction N-2
                            self.send_message(self.card_predictor.prediction_channel_id, res['new_message'], message_id=mid_to_edit, edit=True)
                        
                    # Ajouter le jeu N aux messages traités
                    self.card_predictor.processed_messages.add(game_num)
                    self.card_predictor._save_data(self.card_predictor.processed_messages, 'processed.json')


            # 2. Traitement des messages ÉDITÉS dans le canal SOURCE
            elif ('edited_channel_post' in update and 'text' in update['edited_channel_post']) and (update['edited_channel_post']['chat']['id'] == self.card_predictor.target_channel_id):
                
                msg = update['edited_channel_post']
                text = msg.get('text', '')
                game_num = self.card_predictor.extract_game_number(text)
                
                if game_num:
                    
                    # Collecte N-2 -> N sur message édité (si pas déjà fait)
                    if game_num not in self.card_predictor.collected_games:
                       self.card_predictor.collect_inter_data(game_num, text)
                    
                    # Vérifier UNIQUEMENT sur messages finalisés (✅ ou 🔰)
                    if self.card_predictor.has_completion_indicators(text) or '🔰' in text:
                        res = self.card_predictor.verify_prediction_from_edit(text)
                        
                        if res and res['type'] == 'edit_message':
                            mid_to_edit = res.get('message_id_to_edit')
                            
                            if mid_to_edit:
                                # Édition du message de prédiction N-2 (sur l'édition du message N)
                                self.send_message(self.card_predictor.prediction_channel_id, res['new_message'], message_id=mid_to_edit, edit=True)

            # 3. Callbacks
            elif 'callback_query' in update:
                self._handle_callback_query(update['callback_query'])
            
            # 4. Commandes utilisateur (dans n'importe quel chat)
            elif 'message' in update and 'text' in update['message']:
                 m = update['message']
                 if m['text'].startswith('/'):
                    self._handle_command(m['text'], m['chat']['id'], m['message_id'], m['from']['id'])
            
            # 5. Ajout au groupe (inchangé)
            elif 'my_chat_member' in update:
                # ... (Logique inchangée)


        except Exception as e:
            logger.error(f"Update error: {e}")

