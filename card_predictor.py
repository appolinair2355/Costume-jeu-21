# card_predictor (13).py - Version Finale Corrigée

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

# --- 1. RÈGLES STATIQUES (13 Règles Exactes) ---
STATIC_RULES = {
    "10♦️": "♠️", "10♠️": "❤️", 
    "9♣️": "❤️", "9♦️": "♠️",
    "8♣️": "♠️", "8♠️": "♣️", 
    "7♠️": "♠️", "7♣️": "♣️",
    "6♦️": "♣️", "6♣️": "♦️", 
    "A❤️": "❤️", 
    "5❤️": "❤️", "5♠️": "♠️"
}

# Symboles pour les status de vérification (Offset dans le premier groupe de cartes)
SYMBOL_MAP = {0: '✅0️⃣', 1: '✅1️⃣', 2: '✅2️⃣'}

class CardPredictor:
    """Gère la logique de prédiction d'ENSEIGNE (Couleur) et la vérification, 
    incluant l'IA (Top 2), le reset quotidien et le format de prédiction exact."""

    def __init__(self, telegram_message_sender=None):
        
        # <<< CONFIGURATION >>>
        # ⚠️ REMPLACEZ CES IDs PAR VOS VALEURS RÉELLES
        self.HARDCODED_SOURCE_ID = -1002682552255  
        self.HARDCODED_PREDICTION_ID = -1002682552255
        self.telegram_message_sender = telegram_message_sender
        self.BENIN_TIMEZONE = pytz.timezone('Africa/Lagos') # Fuseau horaire du Bénin (WAT/UTC+1)

        # --- A. Chargement des Données Persistantes ---
        self.predictions = self._load_data('predictions.json') 
        self.processed_messages = self._load_data('processed.json', is_set=True) 
        self.inter_data = self._load_data('inter_data.json') # Données N-2 -> N
        self.smart_rules = self._load_data('smart_rules.json') # Règles Top 2
        self.channels_config = self._load_data('channels_config.json') 
        self.sequential_history = self._load_data('sequential_history.json', is_list=True)
        self.collected_games = self._load_data('collected_games.json', is_set=True) 
        
        # Scalaires
        self.is_inter_mode_active = self._load_data('is_inter_mode_active.json', is_scalar=True) or False
        self.last_prediction_time = self._load_data('last_prediction_time.json', is_scalar=True) or 0
        self.last_predicted_game_number = self._load_data('last_predicted_game_number.json', is_scalar=True) or 0
        self.last_analysis_time = self._load_data('last_analysis_time.json', is_scalar=True) or 0
        self.consecutive_fails = self._load_data('consecutive_fails.json', is_scalar=True) or 0
        self.pending_edits: Dict[int, Dict] = self._load_data('pending_edits.json')
        self.last_reset_date = self._load_data('last_reset_date.json', is_scalar=True) or None # Suivi du reset

        # --- B. Configuration Canaux (AVEC FALLBACK SÉCURISÉ) ---
        self.target_channel_id = self.channels_config.get('source', self.HARDCODED_SOURCE_ID)
        self.prediction_channel_id = self.channels_config.get('prediction', self.HARDCODED_PREDICTION_ID)
        self.active_admin_chat_id = self.channels_config.get('admin')

        # Si des règles INTER existent au démarrage, le mode est actif par défaut
        if self.smart_rules and not self.is_inter_mode_active:
             self.is_inter_mode_active = True

    # --- Gestion des Fichiers (Sauvegarde/Chargement) ---
    def _save_data(self, data, filename: str):
        filepath = os.path.join(os.getcwd(), filename)
        try:
            if isinstance(data, set): data = list(data)
            if isinstance(data, dict): data = {str(k): v for k, v in data.items()}
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Erreur de sauvegarde {filename}: {e}")

    def _load_data(self, filename: str, is_set=False, is_list=False, is_scalar=False) -> Any:
        filepath = os.path.join(os.getcwd(), filename)
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if is_set: return set(data)
                if not is_list and not is_scalar and isinstance(data, dict):
                    return {int(k) if str(k).isdigit() else k: v for k, v in data.items()}
                return data
        except Exception as e:
            logger.error(f"Erreur de chargement {filename}: {e}")
            if is_set: return set()
            if is_list: return []
            if is_scalar: return None
            return {}
        return set() if is_set else [] if is_list else {} if not is_scalar else None

    def _save_all_data(self):
        """Sauvegarde l'intégralité de l'état du bot."""
        self._save_data(self.predictions, 'predictions.json')
        self._save_data(self.processed_messages, 'processed.json')
        self._save_data(self.inter_data, 'inter_data.json')
        self._save_data(self.smart_rules, 'smart_rules.json')
        self._save_data(self.channels_config, 'channels_config.json')
        self._save_data(self.sequential_history, 'sequential_history.json')
        self._save_data(self.is_inter_mode_active, 'is_inter_mode_active.json')
        self._save_data(self.last_prediction_time, 'last_prediction_time.json')
        self._save_data(self.last_predicted_game_number, 'last_predicted_game_number.json')
        self._save_data(self.last_analysis_time, 'last_analysis_time.json')
        self._save_data(self.consecutive_fails, 'consecutive_fails.json')
        self._save_data(self.pending_edits, 'pending_edits.json')
        self._save_data(self.collected_games, 'collected_games.json')
        self._save_data(self.last_reset_date, 'last_reset_date.json') 

    # --- NOUVELLE FONCTION : RESET QUOTIDIEN (00:59 WAT) ---
    def check_and_reset_predictions(self):
        """
        Réinitialise les stocks de prédiction (uniquement) à 00h59 WAT (Bénin).
        Les données de l'IA (inter_data, smart_rules, collected_games) sont conservées.
        """
        current_date_time_wat = datetime.now(self.BENIN_TIMEZONE)
        current_date_str = current_date_time_wat.strftime("%Y-%m-%d")
        current_time_str = current_date_time_wat.strftime("%H:%M")

        # Vérifier si la date actuelle est différente de la dernière date de reset (nouveau jour)
        if self.last_reset_date != current_date_str:
            
            # Vérifier si l'heure est passée ou égale à 00:59
            if current_time_str >= "00:59": 
                
                logger.info(f"⌚️ Déclenchement du reset à {current_time_str} WAT.")
                
                # --- A. RESET DES STOCKS DE PRÉDICTION UNIQUEMENT ---
                self.predictions = {}
                self.processed_messages = set() # Réinitialisation des messages traités
                self.last_prediction_time = 0
                self.last_predicted_game_number = 0
                self.consecutive_fails = 0
                
                # --- C. MISE À JOUR DE L'ÉTAT ET PERSISTANCE ---
                self.last_reset_date = current_date_str
                self._save_all_data()
                
                logger.info("✅ Reset quotidien des stocks de prédiction effectué (00h59 WAT).")
                
                if self.telegram_message_sender and self.active_admin_chat_id:
                     self.telegram_message_sender(self.active_admin_chat_id, 
                                                 "⚙️ **Reset Quotidien** : Stocks de prédiction réinitialisés (00h59 WAT). Les données de l'IA sont conservées.")
        return

    # --- FONCTIONS UTILITAIRES D'EXTRACTION ---
    def set_channel_id(self, channel_id: int, channel_type: str):
        # ... (méthode inchangée)
        if channel_type == 'source': self.target_channel_id = channel_id
        elif channel_type == 'prediction': self.prediction_channel_id = channel_id
        elif channel_type == 'admin': self.active_admin_chat_id = channel_id
        self.channels_config[channel_type] = channel_id
        self._save_data(self.channels_config, 'channels_config.json')

    def extract_game_number(self, message: str) -> Optional[int]:
        # Tente d'extraire #T[0-9]+, #R[0-9]+ ou 🔵[0-9]+🔵
        match = re.search(r'#T(\d+)|#R(\d+)|🔵(\d+)🔵', message)
        if match:
            for group in match.groups():
                if group:
                    try: return int(group)
                    except ValueError: pass
        return None

    def get_first_card_info(self, message: str) -> Optional[str]:
        """Extrait la première carte de la première parenthèse."""
        match = re.search(r'\(([^)]+)\)', message)
        if match:
            content = match.group(1).strip()
            # Recherche la première carte dans ce contenu (ex: 10♦️, A❤️)
            card_match = re.search(r'(\d+[♣️♠️♦️❤️]|A[♣️♠️♦️❤️]|K[♣️♠️♦️❤️]|Q[♣️♠️♦️❤️]|J[♣️♠️♦️❤️])', content)
            if card_match:
                return card_match.group(1)
        return None
    
    def get_all_cards_in_first_group(self, message: str) -> List[str]:
        """Extrait toutes les cartes du premier groupe de cartes."""
        cards = []
        match = re.search(r'\(([^)]+)\)', message)
        if match:
            content = match.group(1).strip()
            cards = re.findall(r'(\d+[♣️♠️♦️❤️]|A[♣️♠️♦️❤️]|K[♣️♠️♦️❤️]|Q[♣️♠️♦️❤️]|J[♣️♠️♦️❤️])', content)
        return cards

    def check_costume_in_first_parentheses(self, message: str, predicted_costume: str) -> int:
        """Vérifie si l'enseigne prédite est présente dans les cartes du premier groupe (offset 0, 1, 2)."""
        cards = self.get_all_cards_in_first_group(message)
        if not cards: return -1

        for i, card in enumerate(cards[:3]): # Limiter la recherche aux 3 premières cartes
            if card.endswith(predicted_costume):
                return i # Retourne l'index (0, 1, ou 2)
        
        return -1 # Non trouvé

    def has_completion_indicators(self, text: str) -> bool:
        return '✅' in text or '🔰' in text

    def is_final_result_structurally_valid(self, text: str) -> bool:
        """Vérifie si le message est un résultat de jeu (au moins 3 cartes trouvées)."""
        card_count = len(re.findall(r'(\d+[♣️♠️♦️❤️]|A[♣️♠️♦️❤️]|K[♣️♠️♦️❤️]|Q[♣️♠️♦️❤️]|J[♣️♠️♦️❤️])', text))
        return card_count >= 3

    # --- IA (MODE INTER) ---

    def analyze_and_set_smart_rules(self, chat_id: int = None, force_activate: bool = False):
        """Analyse les données pour trouver les Top 2 déclencheurs par Enseigne de Résultat.
        Utilise strictement le Top 2 pour chaque enseigne."""

        if not self.inter_data: return

        result_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for result_suit, trigger_card in self.inter_data.items():
            for card, count in trigger_card.items():
                result_counts[result_suit][card] += count

        new_smart_rules: Dict[str, List[Tuple[str, int]]] = {}
        for result_suit in ['❤️', '♣️', '♠️', '♦️']:
            if result_suit in result_counts:
                sorted_cards = sorted(result_counts[result_suit].items(), key=lambda item: item[1], reverse=True)
                
                # --- RÈGLE CRITIQUE : NE CONSERVER QUE LE TOP 2 ---
                top_2 = sorted_cards[:2] 
                
                if top_2:
                    new_smart_rules[result_suit] = top_2
        
        self.smart_rules = new_smart_rules
        self._save_data(self.smart_rules, 'smart_rules.json')
        self.last_analysis_time = time.time()
        self._save_data(self.last_analysis_time, 'last_analysis_time.json')

        if self.smart_rules or force_activate:
            self.is_inter_mode_active = True
            self._save_data(self.is_inter_mode_active, 'is_inter_mode_active.json')
            if chat_id:
                self.telegram_message_sender(chat_id, "🧠 **Analyse et Règles INTER Mises à Jour.**")
        
    def check_and_update_rules(self):
        """Vérification périodique (toutes les 30 minutes) pour relancer l'analyse INTER."""
        if self.is_inter_mode_active:
            current_time = time.time()
            if current_time - self.last_analysis_time > 1800: # 1800 secondes = 30 minutes
                self.analyze_and_set_smart_rules()

    def collect_inter_data(self, game_number: int, message: str):
        """Collecte la première carte du jeu actuel (N) et le résultat de l'enseigne (N-2)
        pour apprendre la relation (N-2) -> (N)."""
        
        if game_number in self.collected_games: return
            
        first_card_n = self.get_first_card_info(message) 
        if not first_card_n: return

        # 1. Mise à jour de l'historique séquentiel
        self.sequential_history.append((game_number, first_card_n))
        if len(self.sequential_history) > 30: self.sequential_history.pop(0)

        # 2. Vérification du jeu N-2 pour l'apprentissage (N-2 est le déclencheur)
        card_n_minus_2 = None
        game_n_minus_2 = game_number - 2
        
        for num, card in self.sequential_history:
            if num == game_n_minus_2:
                card_n_minus_2 = card
                break

        if card_n_minus_2:
            result_suit_n = first_card_n[-1] # L'enseigne de N est le résultat
            
            trigger_card = card_n_minus_2 
            result_suit = result_suit_n 
            
            if result_suit not in self.inter_data: self.inter_data[result_suit] = defaultdict(int)

            self.inter_data[result_suit][trigger_card] += 1
            
        self.collected_games.add(game_number)
        self._save_all_data()

    # --- PRÉDICTION ---
    
    def should_predict(self, message: str) -> Optional[Tuple[str, bool]]:
        """Retourne (enseigne_prédite, is_inter_mode) ou None."""
        first_card = self.get_first_card_info(message)
        if not first_card: return None

        # 1. Mode INTER (PRIORITAIRE)
        if self.is_inter_mode_active and self.smart_rules:
            for result_suit, top_rules in self.smart_rules.items():
                trigger_cards = [card for card, count in top_rules] 
                
                if first_card in trigger_cards:
                    return result_suit, True

        # 2. Mode STATIQUE
        if first_card in STATIC_RULES:
            return STATIC_RULES[first_card], False

        return None

    def make_prediction(self, game_number_source: int, predicted_suit: str, is_inter: bool) -> Optional[Dict[str, Any]]:
        """Enregistre la prédiction N+2 et génère le message de statut."""
        
        predicted_game_number = game_number_source + 2

        if predicted_game_number in self.predictions or predicted_game_number <= self.last_predicted_game_number:
            return None

        # FORMAT DE PRÉDICTION EXACT DEMANDÉ
        prediction_message = f"🔵{predicted_game_number}🔵:{predicted_suit} statut :⏳"
        
        prediction_data = {
            'predicted_suit': predicted_suit,
            'source_game': game_number_source,
            'status': 'pending',
            'timestamp': time.time(),
            'is_inter': is_inter,
            'initial_message': prediction_message,
        }
        self.predictions[predicted_game_number] = prediction_data
        
        self.last_predicted_game_number = predicted_game_number
        self.last_prediction_time = time.time()
        self.consecutive_fails = 0 
        self._save_all_data()

        return {
            'type': 'send_message',
            'message': prediction_message,
            'predicted_game': predicted_game_number
        }

    # --- VÉRIFICATION ---

    def _verify_prediction_common(self, message: str) -> Optional[Dict[str, Any]]:
        """Logique commune de vérification."""
        
        game_num_verification = self.extract_game_number(message)
        if not game_num_verification: return None

        game_num_predicted = game_num_verification - 2
        
        if game_num_predicted not in self.predictions: return None
        if self.predictions[game_num_predicted]['status'] != 'pending': return None
            
        prediction = self.predictions[game_num_predicted]
        predicted_costume = prediction['predicted_suit']
        predicted_game = game_num_predicted
        
        verification_offset = self.check_costume_in_first_parentheses(message, predicted_costume)
        verification_result = None

        # CAS A: SUCCÈS (Offset trouvé)
        if verification_offset != -1:
            
            status_symbol = SYMBOL_MAP.get(verification_offset, '✅') 
            
            # FORMAT DE PRÉDICTION EXACT DEMANDÉ
            updated_message = f"🔵{predicted_game}🔵:{predicted_costume} statut :{status_symbol}"

            prediction['status'] = 'won'
            self.consecutive_fails = 0 
            self._save_all_data()

            verification_result = {
                'type': 'edit_message',
                'predicted_game': str(predicted_game),
                'new_message': updated_message,
                'message_id_to_edit': prediction.get('message_id')
            }
        
        # CAS B: ÉCHEC (L'enseigne n'est pas trouvée et le message est un résultat final valide)
        elif self.is_final_result_structurally_valid(message):
            status_symbol = "❌" 
            
            # FORMAT DE PRÉDICTION EXACT DEMANDÉ
            updated_message = f"🔵{predicted_game}🔵:{predicted_costume} statut :{status_symbol}"

            prediction['status'] = 'lost'
            
            # Gestion des échecs (Failover)
            if prediction.get('is_inter'):
                self.is_inter_mode_active = False 
                self._save_data(self.is_inter_mode_active, 'is_inter_mode_active.json')
            else:
                self.consecutive_fails += 1
                if self.consecutive_fails >= 2:
                    self.analyze_and_set_smart_rules(force_activate=True) 
            
            self._save_all_data()

            verification_result = {
                'type': 'edit_message',
                'predicted_game': str(predicted_game),
                'new_message': updated_message,
                'message_id_to_edit': prediction.get('message_id')
            }

        return verification_result

    def verify_prediction(self, message: str) -> Optional[Dict[str, Any]]:
        return self._verify_prediction_common(message)

    def verify_prediction_from_edit(self, message: str) -> Optional[Dict[str, Any]]:
        return self._verify_prediction_common(message)

# Global instance
card_predictor = CardPredictor()
