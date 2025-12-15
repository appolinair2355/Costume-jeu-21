# handlers.py

import logging
import time
import json
import requests
from typing import Dict, Any, Optional
from card_predictor import CardPredictor, handle_mise_command

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

WELCOME_MESSAGE = """
👋 **BOT ENSEIGNE ACTIF**
• `/stat` - État
• `/inter status` - Menu IA
• `/analyse` - Forcer l'analyse
• `/mise` - Règles manuelles
"""

class TelegramBotHandler:
    def __init__(self, token: str, card_predictor: CardPredictor):
        self.bot_token = token
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.card_predictor = card_predictor
        self.running = True
        self.offset = 0

    def _send_request(self, method: str, payload: Dict = None):
        url = f"{self.api_url}/{method}"
        try:
            response = requests.post(url, json=payload, timeout=10)
            return response.json()
        except Exception as e:
            logger.error(f"Request Error: {e}")
            return None

    def send_message(self, chat_id: int, text: str, parse_mode: str = None, reply_markup: str = None, message_id: int = None, edit: bool = False):
        method = "editMessageText" if edit else "sendMessage"
        payload = {'chat_id': chat_id, 'text': text}
        if parse_mode: payload['parse_mode'] = parse_mode
        if reply_markup: payload['reply_markup'] = reply_markup
        if edit and message_id: payload['message_id'] = message_id
        
        self._send_request(method, payload)

    def _handle_callback_query(self, callback: Dict):
        cb_id = callback['id']
        data = callback.get('data')
        chat_id = callback['message']['chat']['id']
        
        response_text = "Action effectuée."
        
        if data == 'inter_apply':
            self.card_predictor.analyze_and_set_smart_rules(chat_id=chat_id, force_activate=True)
            response_text = "Analyse lancée."
        elif data == 'inter_activate':
            self.card_predictor.is_inter_mode_active = True
            self.card_predictor._save_all_data()
            self.send_message(chat_id, "✅ Mode INTER Activé.")
        elif data == 'inter_default':
            self.card_predictor.is_inter_mode_active = False
            self.card_predictor._save_all_data()
            self.send_message(chat_id, "❌ Mode INTER Désactivé.")

        # Répondre au callback pour arrêter le chargement du bouton
        self._send_request("answerCallbackQuery", {'callback_query_id': cb_id, 'text': response_text})

    def _handle_message(self, message: Dict):
        chat_id = message.get('chat', {}).get('id')
        text = message.get('text', '')
        msg_id = message.get('message_id')
        
        if not text or not chat_id: return

        # Commandes Admin
        if text.startswith('/'):
            cmd = text.lower().split()[0]
            
            if cmd == '/start':
                self.send_message(chat_id, WELCOME_MESSAGE, parse_mode="Markdown")
            
            elif cmd == '/stat':
                status = "✅ Connecté\n"
                status += f"Source ID: {self.card_predictor.target_channel_id}\n"
                status += f"Pred ID: {self.card_predictor.prediction_channel_id}\n"
                status += f"Mode INTER: {'ON' if self.card_predictor.is_inter_mode_active else 'OFF'}"
                self.send_message(chat_id, status)
                
            elif cmd == '/config':
                self.send_message(chat_id, "Pour configurer, ajoutez-moi au canal en tant qu'admin.")

            # --- GESTION INTER & ANALYSE ---
            elif cmd == '/inter':
                sub = text.lower().strip()
                if 'status' in sub:
                    txt, kb = self.card_predictor.get_inter_status()
                    self.send_message(chat_id, txt, parse_mode="Markdown", reply_markup=json.dumps(kb))
                elif 'activate' in sub:
                    self.card_predictor.is_inter_mode_active = True
                    self.card_predictor._save_all_data()
                    self.send_message(chat_id, "✅ INTER Activé.")
                elif 'default' in sub:
                    self.card_predictor.is_inter_mode_active = False
                    self.card_predictor._save_all_data()
                    self.send_message(chat_id, "❌ INTER Désactivé.")

            elif cmd == '/analyse' or cmd == '/a':
                self.send_message(chat_id, "🧠 Analyse en cours...")
                self.card_predictor.analyze_and_set_smart_rules(chat_id=chat_id, force_activate=True)

            elif cmd == '/mise':
                body = text.replace("/mise", "", 1).strip()
                if not body:
                    self.send_message(chat_id, "⚠️ Collez les règles après /mise")
                else:
                    res = handle_mise_command(body, self.card_predictor)
                    self.send_message(chat_id, res, parse_mode="Markdown")
            return

        # Traitement Messages Canal (Source & Prediction)
        # 1. Message Source (Nouveau jeu)
        if str(chat_id) == str(self.card_predictor.target_channel_id):
            should, g_num, suit = self.card_predictor.should_predict(text)
            
            # Collecte INTER
            if g_num: self.card_predictor.collect_inter_data(g_num, text)
            
            if should:
                # Envoyer la prédiction
                pred_txt = self.card_predictor.prepare_prediction_text(g_num, suit) # Dummy call to format
                # Envoi réel
                resp = self._send_request("sendMessage", {
                    'chat_id': self.card_predictor.prediction_channel_id,
                    'text': f"🔵{g_num+2}🔵:Enseigne {suit} statut :⏳"
                })
                if resp and resp.get('ok'):
                    sent_id = resp['result']['message_id']
                    self.card_predictor.make_prediction(g_num, suit, sent_id)

        # 2. Message Résultat (Vérification)
        # Vérifie les messages du canal Source OU Prediction qui contiennent un résultat
        if self.card_predictor.has_completion_indicators(text) or ('#T' in text):
            res = self.card_predictor.verify_prediction(text)
            if res:
                self.send_message(self.card_predictor.prediction_channel_id, 
                                  res['new_message'], message_id=res['message_id_to_edit'], edit=True)

    def process_update(self, update: Dict):
        if 'message' in update:
            self._handle_message(update['message'])
        elif 'channel_post' in update:
            self._handle_message(update['channel_post'])
        elif 'edited_channel_post' in update:
             # Vérifier les edits (pour les résultats mis à jour)
            self._handle_message(update['edited_channel_post'])
        elif 'callback_query' in update:
            self._handle_callback_query(update['callback_query'])

    def run(self):
        logger.info("🤖 Bot Démarré (Polling)...")
        while self.running:
            try:
                updates = self._send_request("getUpdates", {'offset': self.offset, 'timeout': 30})
                if updates and updates.get('ok'):
                    for update in updates['result']:
                        self.process_update(update)
                        self.offset = update['update_id'] + 1
            except Exception as e:
                logger.error(f"Polling error: {e}")
                time.sleep(5)
