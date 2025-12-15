# handlers.py - Version FINALE CORRIGÉE (Commandes Complètes et Fix d'Argument)

import logging
import time
import json
from collections import defaultdict
from typing import Dict, Any, Optional
import requests
import os 
import sys

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Importation Robuste
try:
    from card_predictor import CardPredictor, STATIC_RULES
except ImportError:
    # Si l'importation échoue, le __init__ de TelegramHandlers affichera une erreur fatale
    logger.error("❌ IMPOSSIBLE D'IMPORTER CARDPREDICTOR. Vérifiez que card_predictor.py existe.")
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

**🔹 Commandes Rapides (Admin)**
• `/r` ou `/reset_stock` - **RESET MANUEL** des prédictions (ne touche pas à l'IA)
• `/a` ou `/toggle_ia` - Activation/Désactivation rapide du mode IA

**🔹 Mode Intelligent (INTER)**
• `/inter status` - Voir les règles apprises (Top 2)
• `/inter activate` - **Activer manuellement** le mode intelligent
• `/inter default` - Désactiver et revenir aux règles statiques
• `/collect` - Voir les données collectées (N-2 → N)
"""

class TelegramHandlers:

    # CORRECTION : server_url est maintenant optionnel
    def __init__(self, bot_token: str, server_url: str = ""):
        self.bot_token = bot_token
        self.server_url = server_url
        self.api_url = f"https://api.telegram.org/bot{bot_token}"
        
        if CardPredictor is None:
             logger.critical("Bot ne peut pas démarrer car CardPredictor n'a pas été importé.")
             sys.exit(1)
             
        # L'instance CardPredictor est créée ici
        self.card_predictor = CardPredictor(self.send_message)
        logger.info("Handlers initialized.")
        
    def send_message(self, chat_id: int, text: str, message_id: Optional[int] = None, reply_to_message_id: Optional[int] = None, keyboard: Optional[Dict[str, Any]] = None, parse_mode='Markdown', edit: bool = False):
        """Envoie ou édite un message."""
        url = f"{self.api_url}/{'editMessageText' if edit else 'sendMessage'}"
        payload = {
            'chat_id': chat_id,
            'parse_mode': parse_mode,
            'text': text
        }
        if edit:
            payload['message_id'] = message_id
        if reply_to_message_id and not edit:
            payload['reply_to_message_id'] = reply_to_message_id
        if keyboard:
            payload['reply_markup'] = json.dumps(keyboard)

        try:
            response = requests.post(url, json=payload)
            response.raise_for_status() 
            return response.json().get('result')
        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur d'envoi de message: {e}")
            return None
        
    def _handle_command(self, text: str, chat_id: int, message_id: int, from_user_id: int):
        
        command = text.split()[0].lower()
        args = text.split()[1:]
        
        # --- COMMANDES RAPIDES /r et /a ---
        if command in ('/r', '/reset_stock'):
            self.card_predictor.predictions = {}
            self.card_predictor.processed_messages = set() 
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

        # --- COMMANDES DE BASE COMPLÉTÉES ---
        if command == '/start':
            self.send_message(chat_id, WELCOME_MESSAGE)
        
        elif command == '/stat':
            p = self.card_predictor
            time_since_pred = (time.time() - p.last_prediction_time) / 60 if p.last_prediction_time else 0
            time_since_analysis = (time.time() - p.last_analysis_time) / 60 if p.last_analysis_time else 0

            status_msg = f"""
⚙️ **ÉTAT DU SYSTÈME** ━━━━━━━━━━━━━━━━━━━━━
🧠 **Mode IA (INTER)** : {'**Activé** ✅' if p.is_inter_mode_active else 'Désactivé 📜'}
    • Dernière analyse : {time_since_analysis:.1f} min
    • Règles INTER : {len(p.smart_rules)} ensembles de Top 2

📈 **Stock de Prédiction**
    • Dernier jeu prédit : **{p.last_predicted_game_number}**
    • Dernier jeu Source traité : **{p.card_predictor.extract_game_number(list(p.processed_messages)[-1]) if p.processed_messages else 'N/A'}**
    • Temps écoulé : {time_since_pred:.1f} min (depuis dernier N+2)
    • Fails Statiques consécutifs : **{p.consecutive_fails}** / 2

🔗 **Configuration des Canaux**
    • Source ID : `{p.target_channel_id}`
    • Prédiction ID : `{p.prediction_channel_id}`
    • Admin ID : `{p.active_admin_chat_id or 'Non défini'}`
"""
            self.send_message(chat_id, status_msg)
            
        elif command == '/config':
            keyboard = {
                "inline_keyboard": [
                    [{"text": "Définir comme Canal SOURCE 📥", "callback_data": "set_source"}],
                    [{"text": "Définir comme Canal PRÉDICTION 📤", "callback_data": "set_prediction"}],
                    [{"text": "Définir comme Chat ADMIN 🚨", "callback_data": "set_admin"}]
                ]
            }
            self.send_message(chat_id, "Cliquez pour assigner le rôle de ce chat/canal au bot :", keyboard=keyboard)

        elif command == '/inter':
            if not args or args[0].lower() == 'status':
                status_data = self.card_predictor.get_inter_status(chat_id=chat_id)
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "Relancer Analyse (Top 2)", "callback_data": "inter_reanalyze"}]
                    ]
                }
                self.send_message(chat_id, status_data, keyboard=keyboard)
                
            elif args[0].lower() == 'activate':
                self.card_predictor.is_inter_mode_active = True
                self.card_predictor._save_data(True, 'is_inter_mode_active.json')
                self.card_predictor.analyze_and_set_smart_rules(chat_id=chat_id, force_activate=True)
            
            elif args[0].lower() == 'default':
                self.card_predictor.is_inter_mode_active = False
                self.card_predictor._save_data(False, 'is_inter_mode_active.json')
                self.send_message(chat_id, "📜 Mode Intelligent **DÉSACTIVÉ** (Retour aux règles statiques).")
            
            else:
                 self.send_message(chat_id, "❌ Commande `inter` inconnue. Utilisez `/inter status`, `/inter activate`, ou `/inter default`.")

        elif command == '/collect':
            inter_data_str = json.dumps(self.card_predictor.inter_data, indent=2, ensure_ascii=False)
            
            if len(inter_data_str) > 3500:
                 inter_data_str = inter_data_str[:3500] + "\n[... TRONQUÉ POUR LA LIMITE TELEGRAM ...]"
                 
            self.send_message(chat_id, f"📝 **DONNÉES COLLECTÉES (N-2 → N)**\n\n```json\n{inter_data_str}\n```", parse_mode='Markdown')
        
        else:
             pass 

    def _handle_callback_query(self, callback_query: Dict[str, Any]):
        """Gère les actions des boutons inline (callbacks)."""
        data = callback_query['data']
        chat_id = callback_query['message']['chat']['id']
        message_id = callback_query['message']['message_id']
        
        if data == 'set_source':
            self.card_predictor.set_channel_id(chat_id, 'source')
            self.send_message(chat_id, "✅ **CANAL SOURCE** : Ce canal est maintenant désigné pour recevoir les messages de jeu à analyser.", message_id=message_id, edit=True)
        elif data == 'set_prediction':
            self.card_predictor.set_channel_id(chat_id, 'prediction')
            self.send_message(chat_id, "✅ **CANAL PRÉDICTION** : Ce canal est maintenant désigné pour l'envoi des pronostics du bot.", message_id=message_id, edit=True)
        elif data == 'set_admin':
            self.card_predictor.set_channel_id(chat_id, 'admin')
            self.send_message(chat_id, "✅ **CHAT ADMIN** : Ce chat recevra les alertes critiques (ex: reset quotidien).", message_id=message_id, edit=True)
        elif data == 'inter_reanalyze':
            # La fonction analyze_and_set_smart_rules envoie le message de confirmation
            self.card_predictor.analyze_and_set_smart_rules(chat_id=chat_id, force_activate=True)
        elif data == 'inter_apply':
             self.card_predictor.analyze_and_set_smart_rules(chat_id=chat_id, force_activate=True)
        elif data == 'inter_default':
            self.card_predictor.is_inter_mode_active = False
            self.card_predictor._save_data(False, 'is_inter_mode_active.json')
            self.send_message(chat_id, "📜 Mode Intelligent **DÉSACTIVÉ** (Retour aux règles statiques).", message_id=message_id, edit=True)
        
    def handle_update(self, update: Dict[str, Any]):
        try:
            if not self.card_predictor: return

            # Vérification du reset quotidien
            self.card_predictor.check_and_reset_predictions()

            # 1. Traitement des messages dans le canal SOURCE
            if ('channel_post' in update and 'text' in update['channel_post']) and (update['channel_post']['chat']['id'] == self.card_predictor.target_channel_id):
                
                msg = update['channel_post']
                text = msg.get('text', '')
                game_num = self.card_predictor.extract_game_number(text)
                
                if game_num and game_num not in self.card_predictor.processed_messages:
                    
                    # 1.A. COLLECTE IA (N-2 -> N)
                    self.card_predictor.collect_inter_data(game_num, text)

                    # 1.B. PRÉDICTION (N -> N+2)
                    prediction_data = self.card_predictor.should_predict(text)
                    if prediction_data:
                        predicted_suit, is_inter = prediction_data
                        res = self.card_predictor.make_prediction(game_num, predicted_suit, is_inter)
                        
                        if res and res['type'] == 'send_message':
                            sent_msg = self.send_message(self.card_predictor.prediction_channel_id, res['message'])
                            if sent_msg:
                                self.card_predictor.predictions[res['predicted_game']]['message_id'] = sent_msg['message_id']
                                self.card_predictor._save_all_data() 
                    
                    # 1.C. VÉRIFICATION (N-2)
                    res = self.card_predictor.verify_prediction(text)
                    if res and res['type'] == 'edit_message':
                        mid_to_edit = res.get('message_id_to_edit')
                        if mid_to_edit:
                            self.send_message(self.card_predictor.prediction_channel_id, res['new_message'], message_id=mid_to_edit, edit=True)
                        
                    self.card_predictor.processed_messages.add(game_num)
                    self.card_predictor._save_data(self.card_predictor.processed_messages, 'processed.json')


            # 2. Traitement des messages ÉDITÉS dans le canal SOURCE
            elif ('edited_channel_post' in update and 'text' in update['edited_channel_post']) and (update['edited_channel_post']['chat']['id'] == self.card_predictor.target_channel_id):
                
                msg = update['edited_channel_post']
                text = msg.get('text', '')
                game_num = self.card_predictor.extract_game_number(text)
                
                if game_num:
                    # La collecte doit se faire sur l'édition si le jeu n'a pas été traité
                    if game_num not in self.card_predictor.collected_games:
                       self.card_predictor.collect_inter_data(game_num, text)
                    
                    # Vérifier UNIQUEMENT sur messages finalisés (✅ ou 🔰)
                    if self.card_predictor.has_completion_indicators(text) or '🔰' in text:
                        res = self.card_predictor.verify_prediction_from_edit(text)
                        
                        if res and res['type'] == 'edit_message':
                            mid_to_edit = res.get('message_id_to_edit')
                            
                            if mid_to_edit:
                                self.send_message(self.card_predictor.prediction_channel_id, res['new_message'], message_id=mid_to_edit, edit=True)

            # 3. Callbacks
            elif 'callback_query' in update:
                self._handle_callback_query(update['callback_query'])
            
            # 4. Commandes utilisateur (dans n'importe quel chat)
            elif 'message' in update and 'text' in update['message']:
                 m = update['message']
                 if m['text'].startswith('/'):
                    self._handle_command(m['text'], m['chat']['id'], m['message_id'], m['from']['id'])
            
            # 5. Ajout au groupe
            elif 'my_chat_member' in update:
                m = update['my_chat_member']
                if m['new_chat_member']['status'] in ['member', 'administrator']:
                    bot_id_part = self.bot_token.split(':')[0]
                    if str(m['new_chat_member']['user']['id']).startswith(bot_id_part):
                         self.send_message(m['chat']['id'], "✨ Merci de m'avoir ajouté ! Veuillez utiliser `/config` pour définir mon rôle (Source ou Prédiction).")


        except Exception as e:
            logger.error(f"Update error: {e}")
