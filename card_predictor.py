# card_predictor.py

import re
import logging
import time
import os
import json
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Any
from collections import defaultdict
import pytz

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- 1. RÈGLES STATIQUES ---
STATIC_RULES = {
    "10♦️": "♠️", "10♠️": "❤️", 
    "9♣️": "❤️", "9♦️": "♠️",
    "8♣️": "♠️", "8♠️": "♣️", 
    "7♠️": "♠️", "7♣️": "♣️",
    "6♦️": "♣️", "6♣️": "♦️", 
    "A❤️": "❤️", 
    "5❤️": "❤️", "5♠️": "♠️"
}

SYMBOL_MAP = {0: '✅0️⃣', 1: '✅1️⃣', 2: '✅2️⃣'}

class CardPredictor:
    """Gère la logique de prédiction et l'intelligence."""

    def __init__(self, telegram_message_sender=None):
        # Configuration des canaux (chargée depuis JSON ou Hardcodée)
        self.HARDCODED_SOURCE_ID = -1002682552255 
        self.HARDCODED_PREDICTION_ID = -1003341134749

        # Chargement des données
        self.predictions = self._load_data('predictions.json') 
        self.processed_messages = self._load_data('processed.json', is_set=True) 
        self.last_prediction_time = self._load_data('last_prediction_time.json', is_scalar=True) or 0
        self.last_predicted_game_number = self._load_data('last_predicted_game_number.json', is_scalar=True) or 0
        self.consecutive_fails = self._load_data('consecutive_fails.json', is_scalar=True) or 0
        self.pending_edits = self._load_data('pending_edits.json')
        
        self.config_data = self._load_data('channels_config.json') or {}
        self.target_channel_id = self.config_data.get('target_channel_id', self.HARDCODED_SOURCE_ID)
        self.prediction_channel_id = self.config_data.get('prediction_channel_id', self.HARDCODED_PREDICTION_ID)
        
        # Logique INTER
        self.telegram_message_sender = telegram_message_sender
        self.active_admin_chat_id = self._load_data('active_admin_chat_id.json', is_scalar=True)
        self.sequential_history = self._load_data('sequential_history.json') 
        self.inter_data = self._load_data('inter_data.json') 
        self.is_inter_mode_active = self._load_data('inter_mode_status.json', is_scalar=True)
        self.smart_rules = self._load_data('smart_rules.json')
        self.last_analysis_time = self._load_data('last_analysis_time.json', is_scalar=True) or 0
        self.collected_games = self._load_data('collected_games.json', is_set=True)
        self.last_reset_date = self._load_data('last_reset_date.json', is_scalar=True)
        
        # Initialisation Reset
        self._check_daily_reset()
        
        if self.is_inter_mode_active is None: self.is_inter_mode_active = True
        self.prediction_cooldown = 30 
        
        if self.inter_data and not self.is_inter_mode_active and not self.smart_rules:
             self.analyze_and_set_smart_rules(initial_load=True)

    def _check_daily_reset(self):
        """Reset quotidien à 00h59 heure béninoise."""
        try:
            benin_tz = pytz.timezone('Africa/Porto-Novo')
            now_benin = datetime.now(benin_tz)
            today_str = now_benin.strftime('%Y-%m-%d')
            
            # Reset si on passe minuit (ou au démarrage si pas fait aujourd'hui)
            # Simplification pour Render : on reset si la date stockée est différente d'aujourd'hui
            if self.last_reset_date != today_str:
                # On vérifie si c'est après 00h59 ou si c'est un nouveau jour
                if now_benin.hour >= 1 or (now_benin.hour == 0 and now_benin.minute >= 59):
                    self._perform_daily_reset()
                    self.last_reset_date = today_str
                    self._save_data(self.last_reset_date, 'last_reset_date.json')
                    logger.info(f"🔄 Reset quotidien effectué - Date: {today_str}")
        except Exception as e:
            logger.error(f"❌ Erreur reset quotidien: {e}")
    
    def _perform_daily_reset(self):
        """Vide l'historique de collecte mais garde les règles intelligentes."""
        self.inter_data.clear()
        self.sequential_history.clear()
        self.collected_games.clear()
        # On remet aussi à zéro les stocks de prédiction pour le nouveau cycle
        self.predictions = {}
        self.processed_messages = set()
        self.last_prediction_time = 0
        self.last_predicted_game_number = 0
        self.consecutive_fails = 0
        self._save_all_data()

    def _load_data(self, filename: str, is_set: bool = False, is_scalar: bool = False) -> Any:
        try:
            is_dict = filename in ['channels_config.json', 'predictions.json', 'sequential_history.json', 'smart_rules.json', 'pending_edits.json']
            if not os.path.exists(filename):
                return set() if is_set else (None if is_scalar else ({} if is_dict else []))
            with open(filename, 'r') as f:
                content = f.read().strip()
                if not content: return set() if is_set else (None if is_scalar else ({} if is_dict else []))
                data = json.loads(content)
                if is_set: return set(data)
                if filename in ['sequential_history.json', 'predictions.json', 'pending_edits.json'] and isinstance(data, dict): 
                    return {int(k): v for k, v in data.items()}
                return data
        except Exception:
            return set() if is_set else (None if is_scalar else ({} if is_dict else []))

    def _save_data(self, data: Any, filename: str):
        try:
            if isinstance(data, set): data = list(data)
            with open(filename, 'w') as f: json.dump(data, f, indent=4)
        except Exception as e: logger.error(f"❌ Erreur sauvegarde {filename}: {e}")

    def _save_all_data(self):
        self._save_data(self.predictions, 'predictions.json')
        self._save_data(self.processed_messages, 'processed.json')
        self._save_data(self.last_prediction_time, 'last_prediction_time.json')
        self._save_data(self.last_predicted_game_number, 'last_predicted_game_number.json')
        self._save_data(self.consecutive_fails, 'consecutive_fails.json')
        self._save_data(self.inter_data, 'inter_data.json')
        self._save_data(self.sequential_history, 'sequential_history.json')
        self._save_data(self.is_inter_mode_active, 'inter_mode_status.json')
        self._save_data(self.smart_rules, 'smart_rules.json')
        self._save_data(self.active_admin_chat_id, 'active_admin_chat_id.json')
        self._save_data(self.last_analysis_time, 'last_analysis_time.json')
        self._save_data(self.pending_edits, 'pending_edits.json')
        self._save_data(self.collected_games, 'collected_games.json')
        self._save_data(self.last_reset_date, 'last_reset_date.json')

    # --- Utilitaires ---
    def _extract_parentheses_content(self, text: str) -> List[str]:
        return re.findall(r'\(([^)]+)\)', text)

    def _count_cards_in_content(self, content: str) -> int:
        normalized_content = content.replace("❤️", "♥️")
        return len(re.findall(r'(\d+|[AKQJ])(♠️|♥️|♦️|♣️)', normalized_content, re.IGNORECASE))
        
    def has_pending_indicators(self, text: str) -> bool:
        return any(i in text for i in ['⏰', '▶', '🕐', '➡️'])

    def has_completion_indicators(self, text: str) -> bool:
        return any(i in text for i in ['✅', '🔰'])
        
    def is_final_result_structurally_valid(self, text: str) -> bool:
        matches = self._extract_parentheses_content(text)
        if len(matches) < 2: return False
        if ('#T' in text or '🔵#R' in text): return True
        if len(matches) == 2:
            c1 = self._count_cards_in_content(matches[0])
            c2 = self._count_cards_in_content(matches[1])
            if (c1 == 3 and c2 == 2) or (c1 == 3 and c2 == 3) or (c1 == 2 and c2 == 3): return True
        return False

    def extract_game_number(self, message: str) -> Optional[int]:
        match = re.search(r'#N(\d+)\.', message, re.IGNORECASE) 
        if not match: match = re.search(r'🔵(\d+)🔵', message)
        return int(match.group(1)) if match else None

    def extract_card_details(self, content: str) -> List[Tuple[str, str]]:
        normalized_content = content.replace("♥️", "❤️")
        return re.findall(r'(\d+|[AKQJ])(♠️|❤️|♦️|♣️)', normalized_content, re.IGNORECASE)

    def get_first_card_info(self, message: str) -> Optional[Tuple[str, str]]:
        match = re.search(r'\(([^)]*)\)', message)
        if not match: return None
        details = self.extract_card_details(match.group(1))
        if details:
            v, c = details[0]
            if c == "❤️": c = "♥️" 
            return f"{v.upper()}{c}", c 
        return None
    
    def get_all_cards_in_first_group(self, message: str) -> List[str]:
        match = re.search(r'\(([^)]*)\)', message)
        if not match: return []
        details = self.extract_card_details(match.group(1))
        return [f"{v.upper()}{'♥️' if c == '❤️' else c}" for v, c in details]

    # --- Gestion /mise ---
    def parse_mise_message(self, message: str) -> Optional[List[Dict]]:
        lines = message.strip().split('\n')
        manual_rules = []
        current_suit = None
        for line in lines:
            line = line.strip()
            suit_match = re.search(r'Pour prédire ([♠️❤️♦️♣️]):', line)
            if suit_match:
                current_suit = suit_match.group(1)
                if current_suit == "❤️": current_suit = "♥️"
                continue
            if '•' in line and current_suit:
                try:
                    after_dot = line.split('•', 1)[1].strip()
                    rule_match = re.search(r'(\S+)\s*\((\d+)x?\)', after_dot)
                    if rule_match:
                        trigger_card = rule_match.group(1)
                        count = int(rule_match.group(2))
                        trigger_value = trigger_card[:-1]
                        trigger_suit = trigger_card[-1]
                        if trigger_suit == "❤️": trigger_suit = "♥️"
                        manual_rules.append({
                            'trigger': trigger_value + trigger_suit,
                            'predict': current_suit,
                            'count': count,
                            'source': 'manuel'
                        })
                except: continue
        return manual_rules if len(manual_rules) == 8 else None
    
    def merge_manual_rules(self, manual_rules: List[Dict]):
        if not manual_rules: return
        self.smart_rules = [r for r in self.smart_rules if r.get('source') != 'manuel'] # Clean old manuals
        existing_rules_dict = {(r['trigger'], r['predict']): r for r in self.smart_rules}
        
        for manual_rule in manual_rules:
            key = (manual_rule['trigger'], manual_rule['predict'])
            if key in existing_rules_dict:
                existing_rules_dict[key]['count'] += manual_rule['count']
                existing_rules_dict[key]['source'] = 'manuel'
            else:
                self.smart_rules.append(manual_rule)
        
        self.is_inter_mode_active = True
        self._save_all_data()

    # --- Intelligence ---
    def collect_inter_data(self, game_number: int, message: str):
        info = self.get_first_card_info(message)
        if not info: return
        full_card, suit = info
        result_suit_normalized = suit.replace("❤️", "♥️")
        
        if game_number in self.collected_games: return 

        self.sequential_history[game_number] = {'carte': full_card, 'date': datetime.now().isoformat()}
        self.collected_games.add(game_number)
        
        n_minus_2 = game_number - 2
        trigger_entry = self.sequential_history.get(n_minus_2)
        if trigger_entry:
            self.inter_data.append({
                'numero_resultat': game_number,
                'declencheur': trigger_entry['carte'], 
                'numero_declencheur': n_minus_2,
                'result_suit': result_suit_normalized, 
                'date': datetime.now().isoformat()
            })
        
        limit = game_number - 50
        self.sequential_history = {k:v for k,v in self.sequential_history.items() if k >= limit}
        self.collected_games = {g for g in self.collected_games if g >= limit}
        self._save_all_data()

    def analyze_and_set_smart_rules(self, chat_id: int = None, initial_load: bool = False, force_activate: bool = False):
        result_suit_groups = defaultdict(lambda: defaultdict(int))
        for entry in self.inter_data:
            result_suit_groups[entry['result_suit']][entry['declencheur']] += 1
        
        # Conserver les règles manuelles
        manual_rules = [r for r in self.smart_rules if r.get('source') == 'manuel']
        self.smart_rules = manual_rules.copy()
        
        for result_suit in ['♠️', '♥️', '♦️', '♣️']:
            result_normalized = "❤️" if result_suit == "♥️" else result_suit
            triggers = result_suit_groups.get(result_suit, {})
            if not triggers: continue
            
            # Ne pas écraser une règle manuelle existante
            top_triggers = sorted(triggers.items(), key=lambda x: x[1], reverse=True)[:2]
            for trig, count in top_triggers:
                # Ajouter seulement si pas déjà couvert par une règle manuelle
                if not any(r['trigger'] == trig and r['predict'] == result_normalized for r in self.smart_rules):
                    self.smart_rules.append({
                        'trigger': trig, 'predict': result_normalized,
                        'count': count, 'result_suit': result_normalized, 'source': 'auto'
                    })

        if force_activate or self.smart_rules: self.is_inter_mode_active = True
        self.last_analysis_time = time.time()
        self._save_all_data()
        
        if chat_id and self.telegram_message_sender:
            msg = f"✅ **Analyse Terminée**\n{len(self.smart_rules)} règles actives."
            self.telegram_message_sender(chat_id, msg)

    def check_and_update_rules(self):
        self._check_daily_reset()
        if time.time() - self.last_analysis_time > 1800:
            if len(self.inter_data) >= 3: self.analyze_and_set_smart_rules(force_activate=True)

    def get_inter_status(self) -> Tuple[str, Dict]:
        msg = f"🧠 **MODE INTER: {'✅ ACTIF' if self.is_inter_mode_active else '❌ INACTIF'}**\n\n"
        msg += f"📊 Règles: {len(self.smart_rules)} | Données: {len(self.inter_data)}\n\n"
        
        rules_by_suit = defaultdict(list)
        for r in self.smart_rules: rules_by_suit[r['predict']].append(r)
        
        for suit in ['♠️', '❤️', '♦️', '♣️']:
            n_suit = "♥️" if suit == "❤️" else suit
            if n_suit in rules_by_suit:
                msg += f"**{suit}**: " + ", ".join([f"{r['trigger']}({r['count']})" for r in rules_by_suit[n_suit]]) + "\n"

        kb = {'inline_keyboard': [[
            {'text': '🔄 Analyser', 'callback_data': 'inter_apply'},
            {'text': '❌ Désactiver' if self.is_inter_mode_active else '✅ Activer', 
             'callback_data': 'inter_default' if self.is_inter_mode_active else 'inter_activate'}
        ]]}
        return msg, kb

    # --- Prédiction & Vérif ---
    def should_predict(self, message: str) -> Tuple[bool, Optional[int], Optional[str]]:
        self.check_and_update_rules()
        game_num = self.extract_game_number(message)
        if not game_num: return False, None, None
        
        # Cooldown & Ecart
        if self.last_predicted_game_number and (game_num - self.last_predicted_game_number < 3): return False, None, None
        
        info = self.get_first_card_info(message)
        if not info: return False, None, None
        card, _ = info
        
        pred = None
        # 1. INTER
        if self.is_inter_mode_active:
            for r in self.smart_rules:
                if r['trigger'] == card: pred = r['predict']; break
        # 2. STATIQUE
        if not pred: pred = STATIC_RULES.get(card)
        
        if pred and (not self.last_prediction_time or time.time() > self.last_prediction_time + self.prediction_cooldown):
            return True, game_num, pred
        return False, None, None

    def make_prediction(self, game_num: int, suit: str, msg_id: int):
        target = game_num + 2
        txt = f"🔵{target}🔵:Enseigne {suit} statut :⏳"
        self.predictions[target] = {
            'predicted_costume': suit, 'status': 'pending', 
            'message_text': txt, 'message_id': msg_id, 'is_inter': self.is_inter_mode_active
        }
        self.last_prediction_time = time.time()
        self.last_predicted_game_number = game_num
        self.consecutive_fails = 0
        self._save_all_data()
        return txt

    def verify_prediction(self, message: str, is_edited: bool = False) -> Optional[Dict]:
        game_num = self.extract_game_number(message)
        if not game_num or not self.is_final_result_structurally_valid(message): return None
        
        for p_game in sorted(self.predictions.keys()):
            p = self.predictions[p_game]
            if p['status'] != 'pending': continue
            
            offset = game_num - p_game
            if offset < 0 or offset > 5: continue
            
            found = self.check_costume_in_first_parentheses(message, p['predicted_costume'])
            
            if found and offset <= 2:
                sym = SYMBOL_MAP.get(offset, f"✅{offset}️⃣")
                new_msg = f"🔵{p_game}🔵:Enseigne {p['predicted_costume']} statut :{sym}"
                p.update({'status': 'won', 'final_message': new_msg})
                self.consecutive_fails = 0
                if p['is_inter']: self._increment_rule_count(p['predicted_costume'], p_game)
                self._save_all_data()
                return {'type': 'edit_message', 'new_message': new_msg, 'message_id_to_edit': p['message_id']}
            
            elif offset >= 2:
                new_msg = f"🔵{p_game}🔵:Enseigne {p['predicted_costume']} statut :❌"
                p.update({'status': 'lost', 'final_message': new_msg})
                if p['is_inter']: 
                    self.is_inter_mode_active = False
                else:
                    self.consecutive_fails += 1
                    if self.consecutive_fails >= 2: self.analyze_and_set_smart_rules(force_activate=True)
                self._save_all_data()
                return {'type': 'edit_message', 'new_message': new_msg, 'message_id_to_edit': p['message_id']}
        return None

    def _increment_rule_count(self, suit: str, game_id: int):
        for r in self.smart_rules:
            if r['predict'] == suit:
                # Simplification: on incrémente si le costume match, idéalement on vérifie le trigger exact
                r['count'] += 1
                self._save_data(self.smart_rules, 'smart_rules.json')
                break

    def check_costume_in_first_parentheses(self, message: str, predicted_costume: str) -> bool:
        cards = self.get_all_cards_in_first_group(message)
        norm_pred = predicted_costume.replace("❤️", "♥️")
        return any(c.endswith(norm_pred) for c in cards)

# Fonctions utilitaires externes
def handle_mise_command(message_text: str, predictor: CardPredictor) -> str:
    try:
        rules = predictor.parse_mise_message(message_text)
        if not rules: return "❌ **Erreur format**: Il faut 8 règles (2 par costume)."
        predictor.merge_manual_rules(rules)
        return f"✅ **Règles manuelles activées !**\nTotal règles: {len(predictor.smart_rules)}"
    except Exception as e: return f"❌ Erreur: {e}"
