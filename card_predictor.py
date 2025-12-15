# card_predictor_final.py

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
logger.setLevel(logging.DEBUG)

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

# Symboles pour les status de vérification
SYMBOL_MAP = {0: '✅0️⃣', 1: '✅1️⃣', 2: '✅2️⃣'}

class CardPredictor:
    """Gère la logique de prédiction d'ENSEIGNE (Couleur) et la vérification."""

    def __init__(self, telegram_message_sender=None):
        
        # <<<<<<<<<<<<<<<< ZONE CRITIQUE À MODIFIER PAR L'UTILISATEUR >>>>>>>>>>>>>>>>
        # ⚠️ IDs DE CANAUX CONFIGURÉS
        self.HARDCODED_SOURCE_ID = -1002682552255  # <--- ID du canal SOURCE/DÉCLENCHEUR
        self.HARDCODED_PREDICTION_ID = -1003341134749 # <--- ID du canal PRÉDICTION/RÉSULTAT
        # <<<<<<<<<<<<<<<< FIN ZONE CRITIQUE >>>>>>>>>>>>>>>>

        # --- A. Chargement des Données ---
        self.predictions = self._load_data('predictions.json') 
        self.processed_messages = self._load_data('processed.json', is_set=True) 
        self.last_prediction_time = self._load_data('last_prediction_time.json', is_scalar=True) or 0
        self.last_predicted_game_number = self._load_data('last_predicted_game_number.json', is_scalar=True) or 0
        self.consecutive_fails = self._load_data('consecutive_fails.json', is_scalar=True) or 0
        self.pending_edits: Dict[int, Dict] = self._load_data('pending_edits.json')
        
        # --- B. Configuration Canaux (AVEC FALLBACK SÉCURISÉ) ---
        raw_config = self._load_data('channels_config.json')
        self.config_data = raw_config if isinstance(raw_config, dict) else {}
        
        self.target_channel_id = self.config_data.get('target_channel_id')
        if not self.target_channel_id and self.HARDCODED_SOURCE_ID != 0:
            self.target_channel_id = self.HARDCODED_SOURCE_ID
            
        self.prediction_channel_id = self.config_data.get('prediction_channel_id')
        if not self.prediction_channel_id and self.HARDCODED_PREDICTION_ID != 0:
            self.prediction_channel_id = self.HARDCODED_PREDICTION_ID
        
        # --- C. Logique INTER (Intelligente) ---
        self.telegram_message_sender = telegram_message_sender
        self.active_admin_chat_id = self._load_data('active_admin_chat_id.json', is_scalar=True)
        
        self.sequential_history: Dict[int, Dict] = self._load_data('sequential_history.json') 
        self.inter_data: List[Dict] = self._load_data('inter_data.json') 
        self.is_inter_mode_active = self._load_data('inter_mode_status.json', is_scalar=True)
        self.smart_rules = self._load_data('smart_rules.json')
        self.last_analysis_time = self._load_data('last_analysis_time.json', is_scalar=True) or 0
        self.collected_games = self._load_data('collected_games.json', is_set=True)
        
        # NOUVEAU: Gestion du reset quotidien
        self.last_reset_date = self._load_data('last_reset_date.json', is_scalar=True)
        self._check_daily_reset()
        
        if self.is_inter_mode_active is None:
            self.is_inter_mode_active = True
        
        self.prediction_cooldown = 30 
        
        if self.inter_data and not self.is_inter_mode_active and not self.smart_rules:
             self.analyze_and_set_smart_rules(initial_load=True)

    # --- NOUVEAU: Système de Reset Quotidien ---
    def _check_daily_reset(self):
        """Vérifie s'il faut effectuer le reset quotidien à 00h59 heure béninoise"""
        try:
            # Heure actuelle au Bénin
            benin_tz = pytz.timezone('Africa/Porto-Novo')
            now_benin = datetime.now(benin_tz)
            today_str = now_benin.strftime('%Y-%m-%d')
            
            # Vérifier si c'est 00h59 et si on n'a pas encore reset aujourd'hui
            if now_benin.hour == 0 and now_benin.minute == 59 and self.last_reset_date != today_str:
                self._perform_daily_reset()
                self.last_reset_date = today_str
                self._save_data(self.last_reset_date, 'last_reset_date.json')
                logger.info(f"🔄 Reset quotidien effectué - Date: {today_str}")
        except Exception as e:
            logger.error(f"❌ Erreur lors du reset quotidien: {e}")
    
    def _perform_daily_reset(self):
        """Effectue le reset quotidien - vide inter_data, sequential_history, collected_games"""
        # ⚠️ smart_rules N'est PAS vidé intentionnellement
        self.inter_data.clear()
        self.sequential_history.clear()
        self.collected_games.clear()
        self._save_all_data()

    # --- Persistance ---
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
        except Exception as e:
            logger.error(f"⚠️ Erreur chargement {filename}: {e}")
            is_dict = filename in ['channels_config.json', 'predictions.json', 'sequential_history.json', 'smart_rules.json', 'pending_edits.json']
            return set() if is_set else (None if is_scalar else ({} if is_dict else []))

    def _save_data(self, data: Any, filename: str):
        try:
            if isinstance(data, set): data = list(data)
            if filename == 'channels_config.json' and isinstance(data, dict):
                if 'target_channel_id' in data and data['target_channel_id'] is not None:
                    data['target_channel_id'] = int(data['target_channel_id'])
                if 'prediction_channel_id' in data and data['prediction_channel_id'] is not None:
                    data['prediction_channel_id'] = int(data['prediction_channel_id'])
            
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

    def set_channel_id(self, channel_id: int, channel_type: str):
        if not isinstance(self.config_data, dict): self.config_data = {}
        if channel_type == 'source':
            self.target_channel_id = channel_id
            self.config_data['target_channel_id'] = channel_id
        elif channel_type == 'prediction':
            self.prediction_channel_id = channel_id
            self.config_data['prediction_channel_id'] = channel_id
        self._save_data(self.config_data, 'channels_config.json')
        return True

    # --- Outils d'Extraction/Comptage ---
    
    def _extract_parentheses_content(self, text: str) -> List[str]:
        """Extrait le contenu de toutes les sections de parenthèses (non incluses)."""
        pattern = r'\(([^)]+)\)'
        return re.findall(pattern, text)

    def _count_cards_in_content(self, content: str) -> int:
        """Compte les symboles de cartes (♠️, ♥️, ♦️, ♣️) dans une chaîne, en normalisant ❤️ vers ♥️."""
        normalized_content = content.replace("❤️", "♥️")
        return len(re.findall(r'(\d+|[AKQJ])(♠️|♥️|♦️|♣️)', normalized_content, re.IGNORECASE))
        
    def has_pending_indicators(self, text: str) -> bool:
        """Vérifie si le message contient des indicateurs suggérant qu'il sera édité (temporaire)."""
        indicators = ['⏰', '▶', '🕐', '➡️']
        return any(indicator in text for indicator in indicators)

    def has_completion_indicators(self, text: str) -> bool:
        """Vérifie si le message contient des indicateurs de complétion après édition (✅ ou 🔰)."""
        completion_indicators = ['✅', '🔰']
        return any(indicator in text for indicator in completion_indicators)
        
    def is_final_result_structurally_valid(self, text: str) -> bool:
        """
        Vérifie si la structure du message correspond à un format de résultat final connu.
        Gère les messages #T, #R et les formats édités basés sur le compte de cartes.
        """
        matches = self._extract_parentheses_content(text)
        num_sections = len(matches)

        if num_sections < 2: return False

        # Règle pour les messages finalisés (#T) ou normaux (#R)
        if ('#T' in text or '🔵#R' in text) and num_sections >= 2:
            return True

        # Messages Édités (basé sur le compte de cartes)
        if num_sections == 2:
            content_1 = matches[0]
            content_2 = matches[1]
            
            count_1 = self._count_cards_in_content(content_1)
            count_2 = self._count_cards_in_content(content_2)

            # Formats acceptés: 3/2, 3/3, 2/3 (3 cartes dans le premier groupe sont supportées)
            if (count_1 == 3 and count_2 == 2) or \
               (count_1 == 3 and count_2 == 3) or \
               (count_1 == 2 and count_2 == 3):
                return True

        return False
        
    # --- Outils d'Extraction (Continuation) ---
    def extract_game_number(self, message: str) -> Optional[int]:
        match = re.search(r'#N(\d+)\.', message, re.IGNORECASE) 
        if not match: match = re.search(r'🔵(\d+)🔵', message)
        return int(match.group(1)) if match else None

    def extract_card_details(self, content: str) -> List[Tuple[str, str]]:
        # Normalise ♥️ en ❤️
        normalized_content = content.replace("♥️", "❤️")
        # Cherche Valeur + Enseigne (ex: 10♦️, A♠️)
        return re.findall(r'(\d+|[AKQJ])(♠️|❤️|♦️|♣️)', normalized_content, re.IGNORECASE)

    def get_first_card_info(self, message: str) -> Optional[Tuple[str, str]]:
        """
        Retourne la PREMIÈRE carte du PREMIER groupe (déclencheur INTER/STATIQUE).
        """
        match = re.search(r'\(([^)]*)\)', message)
        if not match: return None
        
        details = self.extract_card_details(match.group(1))
        if details:
            v, c = details[0]
            if c == "❤️": c = "♥️" 
            return f"{v.upper()}{c}", c 
        return None
    
    def get_all_cards_in_first_group(self, message: str) -> List[str]:
        """
        Retourne TOUTES les cartes du PREMIER groupe pour la vérification.
        """
        match = re.search(r'\(([^)]*)\)', message)
        if not match: return []
        
        details = self.extract_card_details(match.group(1))
        cards = []
        for v, c in details:
            normalized_c = "♥️" if c == "❤️" else c
            cards.append(f"{v.upper()}{normalized_c}")
        return cards
        
    # --- NOUVEAU: Gestion de la commande /mise ---
    def parse_mise_message(self, message: str) -> Optional[List[Dict]]:
        """
        Parse un message /mise et retourne une liste de règles manuelles.
        Format attendu:
        Pour prédire ♠️:
          • X♠️ (Nx)
          • Y♣️ (Nx)
        ...
        """
        lines = message.strip().split('\n')
        manual_rules = []
        current_suit = None
        
        for line in lines:
            line = line.strip()
            
            # Détection d'un bloc "Pour prédire {costume}:"
            suit_match = re.search(r'Pour prédire ([♠️❤️♦️♣️]):', line)
            if suit_match:
                current_suit = suit_match.group(1)
                if current_suit == "❤️":
                    current_suit = "♥️"  # Normalisation
                continue
            
            # Détection d'une règle "• X♠️ (Nx)" - version plus souple
            if '•' in line and current_suit:
                # Extraire la partie après le •
                after_dot = line.split('•', 1)[1].strip()
                rule_match = re.search(r'(\S+)\s*\((\d+)x?\)', after_dot)
                if rule_match:
                    trigger_card = rule_match.group(1)
                    count = int(rule_match.group(2))
                    
                    # Normalisation de l'enseigne du trigger
                    trigger_value = trigger_card[:-1]
                    trigger_suit = trigger_card[-1]
                    if trigger_suit == "❤️":
                        trigger_suit = "♥️"
                    trigger_card = trigger_value + trigger_suit
                    
                    manual_rules.append({
                        'trigger': trigger_card,
                        'predict': current_suit,
                        'count': count,
                        'source': 'manuel'
                    })
        
        # Validation: doit avoir exactement 8 règles (2 par costume × 4 costumes)
        if len(manual_rules) != 8:
            logger.warning(f"⚠️ Message /mise invalide: {len(manual_rules)} règles au lieu de 8")
            return None
        
        return manual_rules
    
    def merge_manual_rules(self, manual_rules: List[Dict]):
        """
        Fusionne les règles manuelles avec les smart_rules existantes.
        Gère les cas A et B selon l'algorithme.
        """
        if not manual_rules:
            return
        
        # Créer un dictionnaire des règles existantes pour recherche rapide
        existing_rules_dict = {}
        for rule in self.smart_rules:
            key = (rule['trigger'], rule['predict'])
            existing_rules_dict[key] = rule
        
        # Créer un dictionnaire des règles par costume
        rules_by_suit = defaultdict(list)
        for rule in self.smart_rules:
            rules_by_suit[rule['predict']].append(rule)
        
        # Traiter chaque règle manuelle
        for manual_rule in manual_rules:
            trigger = manual_rule['trigger']
            predict = manual_rule['predict']
            count = manual_rule['count']
            key = (trigger, predict)
            
            # 🔁 CAS A: La règle existe déjà
            if key in existing_rules_dict:
                existing_rule = existing_rules_dict[key]
                existing_rule['count'] += count
                existing_rule['source'] = 'manuel'  # Marquer comme manuel
                logger.info(f"🔁 Règle existante mise à jour: {trigger} -> {predict} (count: {existing_rule['count']})")
            
            # 🔄 CAS B: La règle n'existe pas
            else:
                existing_rules_for_suit = rules_by_suit[predict]
                
                # CAS B1: Moins de 2 règles existantes pour ce costume
                if len(existing_rules_for_suit) < 2:
                    self.smart_rules.append(manual_rule)
                    rules_by_suit[predict].append(manual_rule)
                    logger.info(f"✅ Nouvelle règle ajoutée: {trigger} -> {predict} (count: {count})")
                
                # CAS B2: Déjà 2 règles existantes - remplacer la plus faible
                else:
                    # Trouver la règle avec le count le plus faible
                    weakest_rule = min(existing_rules_for_suit, key=lambda r: r['count'])
                    
                    if count > weakest_rule['count']:
                        # Supprimer la règle la plus faible
                        self.smart_rules.remove(weakest_rule)
                        rules_by_suit[predict].remove(weakest_rule)
                        
                        # Ajouter la nouvelle règle
                        self.smart_rules.append(manual_rule)
                        rules_by_suit[predict].append(manual_rule)
                        
                        logger.info(f"🔄 Règle faible remplacée: {weakest_rule['trigger']} ({weakest_rule['count']}) -> {trigger} ({count})")
                    else:
                        logger.info(f"⏩ Règle manuelle ignorée (trop faible): {trigger} ({count}) < {weakest_rule['trigger']} ({weakest_rule['count']})")
        
        # Sauvegarder les modifications
        self.is_inter_mode_active = True
        self._save_all_data()
        logger.info(f"🧠 Fusion terminée. {len(self.smart_rules)} règles au total.")

    # --- Logique INTER (Collecte et Analyse) ---
    def collect_inter_data(self, game_number: int, message: str):
        """Collecte les données (N-2 -> N) même sur messages temporaires (⏰)."""
        info = self.get_first_card_info(message)
        if not info: return
        
        full_card, suit = info
        result_suit_normalized = suit.replace("❤️", "♥️")
        
        # Vérifier si déjà dans collected_games
        if game_number in self.collected_games:
            existing_data = self.sequential_history.get(game_number)
            if existing_data and existing_data.get('carte') == full_card:
                logger.debug(f"🧠 Jeu {game_number} déjà collecté, ignoré.")
                return
            else:
                # Mise à jour de la carte (cas rare mais possible)
                logger.info(f"🧠 Jeu {game_number} mis à jour: {existing_data.get('carte') if existing_data else 'N/A'} -> {full_card}")
                self.inter_data = [e for e in self.inter_data if e.get('numero_resultat') != game_number]

        self.sequential_history[game_number] = {'carte': full_card, 'date': datetime.now().isoformat()}
        self.collected_games.add(game_number)
        
        n_minus_2 = game_number - 2
        trigger_entry = self.sequential_history.get(n_minus_2)
        
        if trigger_entry:
            trigger_card = trigger_entry['carte']
            self.inter_data.append({
                'numero_resultat': game_number,
                'declencheur': trigger_card, 
                'numero_declencheur': n_minus_2,
                'result_suit': result_suit_normalized, 
                'date': datetime.now().isoformat()
            })
            logger.info(f"🧠 Jeu {game_number} collecté pour INTER: {trigger_card} -> {result_suit_normalized}")

        limit = game_number - 50
        self.sequential_history = {k:v for k,v in self.sequential_history.items() if k >= limit}
        self.collected_games = {g for g in self.collected_games if g >= limit}
        
        self._save_all_data()

    
    def analyze_and_set_smart_rules(self, chat_id: int = None, initial_load: bool = False, force_activate: bool = False):
        """
        Analyse les données pour trouver les Top 2 déclencheurs par ENSEIGNE DE RÉSULTAT.
        Crée des règles même avec peu de données (minimum 1 occurrence).
        """
        # Grouper par enseigne de RÉSULTAT (♠️, ♥️, ♦️, ♣️)
        result_suit_groups = defaultdict(lambda: defaultdict(int))
        
        for entry in self.inter_data:
            trigger_card = entry['declencheur']  # Ex: 6♦️
            result_suit = entry['result_suit']   # Ex: ♣️
            
            # Compter combien de fois ce déclencheur mène à cette enseigne de résultat
            result_suit_groups[result_suit][trigger_card] += 1
        
        # NE PAS réinitialiser smart_rules si on a des règles manuelles
        existing_manual_rules = [r for r in self.smart_rules if r.get('source') == 'manuel']
        self.smart_rules = existing_manual_rules.copy()  # Garder les règles manuelles
        
        # Pour chaque enseigne de résultat (♠️, ♥️, ♦️, ♣️)
        for result_suit in ['♠️', '♥️', '♦️', '♣️']:
            result_normalized = "❤️" if result_suit == "♥️" else result_suit
            
            triggers_for_this_suit = result_suit_groups.get(result_suit, {})
            
            if not triggers_for_this_suit:
                continue
            
            # Trier par fréquence et prendre jusqu'à 2 meilleurs (même avec 1 seule occurrence)
            top_triggers = sorted(
                triggers_for_this_suit.items(), 
                key=lambda x: x[1], 
                reverse=True
            )[:2]
            
            for trigger_card, count in top_triggers:
                self.smart_rules.append({
                    'trigger': trigger_card,
                    'predict': result_normalized,
                    'count': count,
                    'result_suit': result_normalized,
                    'source': 'auto'  # Marquer comme automatique
                })
        
        # Activer le mode INTER si on a au moins 1 règle
        if force_activate:
            self.is_inter_mode_active = True
            if chat_id: self.active_admin_chat_id = chat_id
        elif self.smart_rules:
            # Toujours activer si on a des règles (même au chargement initial)
            self.is_inter_mode_active = True
        elif not initial_load:
            self.is_inter_mode_active = False
            
        self.last_analysis_time = time.time()
        self._save_all_data()

        logger.info(f"🧠 Analyse terminée. Règles trouvées: {len(self.smart_rules)}. Mode actif: {self.is_inter_mode_active}")
        
        # Notification si demandée
        if chat_id and self.telegram_message_sender:
            if self.smart_rules:
                msg = f"✅ **Analyse terminée !**\n\n{len(self.smart_rules)} règles créées à partir de {len(self.inter_data)} jeux collectés.\n\n🧠 **Mode INTER activé automatiquement**"
            else:
                msg = f"⚠️ **Pas assez de données**\n\n{len(self.inter_data)} jeux collectés. Continuez à jouer pour créer des règles."
            self.telegram_message_sender(chat_id, msg)

    def check_and_update_rules(self):
        """Vérification périodique (30 minutes)."""
        # Vérifier le reset quotidien avant toute chose
        self._check_daily_reset()
        
        if time.time() - self.last_analysis_time > 1800:
            logger.info("🧠 Mise à jour INTER périodique (30 min).")
            # Force l'activation si on a des données
            if len(self.inter_data) >= 3:
                self.analyze_and_set_smart_rules(chat_id=self.active_admin_chat_id, force_activate=True)
            else:
                self.analyze_and_set_smart_rules(chat_id=self.active_admin_chat_id)

    def get_inter_status(self) -> Tuple[str, Dict]:
        """Retourne le statut du mode INTER avec message et clavier."""
        data_count = len(self.inter_data)
        
        if not self.smart_rules:
            message = f"🧠 **MODE INTER - {'✅ ACTIF' if self.is_inter_mode_active else '❌ INACTIF'}**\n\n"
            message += f"📊 **{data_count} jeux collectés**\n"
            message += "⚠️ Pas encore assez de règles créées.\n\n"
            message += "**Cliquez sur 'Analyser' pour générer les règles !**"
            
            keyboard_buttons = [
                [{'text': '🔄 Analyser et Activer', 'callback_data': 'inter_apply'}]
            ]
            
            if self.is_inter_mode_active:
                keyboard_buttons.append([{'text': '❌ Désactiver', 'callback_data': 'inter_default'}])
            
            keyboard = {'inline_keyboard': keyboard_buttons}
        else:
            rules_by_result = defaultdict(list)
            for rule in self.smart_rules:
                rules_by_result[rule['result_suit']].append(rule)
            
            message = f"🧠 **MODE INTER - {'✅ ACTIF' if self.is_inter_mode_active else '❌ INACTIF'}**\n\n"
            message += f"📊 **{len(self.smart_rules)} règles** créées ({data_count} jeux analysés):\n\n"
            
            for suit in ['♠️', '❤️', '♦️', '♣️']:
                if suit in rules_by_result:
                    message += f"**Pour prédire {suit}:**\n"
                    for rule in rules_by_result[suit]:
                        source_icon = "👤" if rule.get('source') == 'manuel' else "🤖"
                        message += f"  {source_icon} • {rule['trigger']} ({rule['count']}x)\n"
                    message += "\n"
            
            if self.is_inter_mode_active:
                keyboard = {
                    'inline_keyboard': [
                        [{'text': '🔄 Relancer Analyse', 'callback_data': 'inter_apply'}],
                        [{'text': '❌ Désactiver', 'callback_data': 'inter_default'}]
                    ]
                }
            else:
                keyboard = {
                    'inline_keyboard': [
                        [{'text': '🚀 Activer INTER', 'callback_data': 'inter_apply'}]
                    ]
                }
        
        return message, keyboard


    # --- CŒUR DU SYSTÈME : PRÉDICTION ---
    
    def should_wait_for_edit(self, text: str, message_id: int) -> bool:
        if self.has_pending_indicators(text):
            game_number = self.extract_game_number(text)
            if message_id not in self.pending_edits:
                self.pending_edits[message_id] = {
                    'game_number': game_number,
                    'original_text': text,
                    'timestamp': datetime.now().isoformat()
                }
                self._save_data(self.pending_edits, 'pending_edits.json')
            return True
        return False

    def should_predict(self, message: str) -> Tuple[bool, Optional[int], Optional[str]]:
        self.check_and_update_rules()
        
        game_number = self.extract_game_number(message)
        if not game_number: return False, None, None
        
        # Règle : Ecart de 3 jeux
        if self.last_predicted_game_number and (game_number - self.last_predicted_game_number < 3):
            return False, None, None
            
        # 3. Décision
        info = self.get_first_card_info(message)
        if not info: return False, None, None
        first_card, _ = info 
        
        predicted_suit = None

        # A. PRIORITÉ 1 : MODE INTER
        if self.is_inter_mode_active and self.smart_rules:
            for rule in self.smart_rules:
                if rule['trigger'] == first_card:
                    predicted_suit = rule['predict']
                    logger.info(f"🔮 INTER: Déclencheur {first_card} -> Prédit {predicted_suit}")
                    break
            
        # B. PRIORITÉ 2 : MODE STATIQUE
        if not predicted_suit and first_card in STATIC_RULES:
            predicted_suit = STATIC_RULES[first_card]
            logger.info(f"🔮 STATIQUE: Déclencheur {first_card} -> Prédit {predicted_suit}")

        if predicted_suit:
            if self.last_prediction_time and time.time() < self.last_prediction_time + self.prediction_cooldown:
                return False, None, None
                
            return True, game_number, predicted_suit

        return False, None, None

    def prepare_prediction_text(self, game_number_source: int, predicted_costume: str) -> str:
        """NOUVEAU: Format de prédiction selon la spécification"""
        target_game = game_number_source + 2
        return f"🔵{target_game}🔵:{predicted_costume} statut :⏳"


    def make_prediction(self, game_number_source: int, suit: str, message_id_bot: int):
        target = game_number_source + 2
        txt = self.prepare_prediction_text(game_number_source, suit)
        
        self.predictions[target] = {
            'predicted_costume': suit, 
            'status': 'pending', 
            'predicted_from': game_number_source, 
            'message_text': txt, 
            'message_id': message_id_bot, 
            'is_inter': self.is_inter_mode_active
        }
        
        self.last_prediction_time = time.time()
        self.last_predicted_game_number = game_number_source
        self.consecutive_fails = 0
        self._save_all_data()

    # --- VERIFICATION LOGIQUE ---

    def verify_prediction(self, message: str) -> Optional[Dict]:
        """Vérifie une prédiction (message normal)"""
        return self._verify_prediction_common(message, is_edited=False)

    def verify_prediction_from_edit(self, message: str) -> Optional[Dict]:
        """Vérifie une prédiction (message édité)"""
        return self._verify_prediction_common(message, is_edited=True)

    def check_costume_in_first_parentheses(self, message: str, predicted_costume: str) -> bool:
        """Vérifie si le costume prédit apparaît dans le PREMIER parenthèses"""
        # Récupérer TOUTES les cartes du premier groupe
        all_cards = self.get_all_cards_in_first_group(message)
        
        if not all_cards:
            logger.debug("🎯 Aucune carte trouvée dans le premier groupe")
            return False
        
        # Log pour montrer toutes les cartes vues
        logger.info(f"🎯 Vérification: {len(all_cards)} carte(s) dans premier groupe: {', '.join(all_cards)}")
        
        # Normaliser le costume prédit
        normalized_costume = predicted_costume.replace("❤️", "♥️")
        
        # Vérifier si au moins UNE carte du groupe a le costume prédit
        for card in all_cards:
            if card.endswith(normalized_costume):
                logger.info(f"✅ Costume {normalized_costume} trouvé dans carte {card}")
                return True
        
        logger.debug(f"❌ Costume {normalized_costume} non trouvé dans {', '.join(all_cards)}")
        return False

    def _verify_prediction_common(self, message: str, is_edited: bool = False) -> Optional[Dict]:
        """Logique de vérification commune - UNIQUEMENT pour messages finalisés."""
        game_number = self.extract_game_number(message)
        if not game_number: return None
        
        # Validation Structurelle
        is_structurally_valid = self.is_final_result_structurally_valid(message)
        
        if not is_structurally_valid: return None

        if not self.predictions: return None
        
        verification_result = None

        # --- ÉTAPE 3 : Vérification du gain/perte ---
        for predicted_game in sorted(self.predictions.keys()):
            prediction = self.predictions[predicted_game]

            if prediction.get('status') != 'pending': continue

            verification_offset = game_number - predicted_game
            
            if verification_offset < 0 or verification_offset > 5: continue

            predicted_costume = prediction.get('predicted_costume')
            if not predicted_costume: continue

            # CAS A: SUCCÈS (Décalage 0, 1 ou 2)
            costume_found = self.check_costume_in_first_parentheses(message, predicted_costume)
            
            if costume_found and verification_offset <= 2:
                status_symbol = SYMBOL_MAP.get(verification_offset, f"✅{verification_offset}️⃣")
                updated_message = f"🔵{predicted_game}🔵:Enseigne {predicted_costume} statut :{status_symbol}"

                prediction['status'] = 'won'
                prediction['verification_count'] = verification_offset
                prediction['final_message'] = updated_message
                self.consecutive_fails = 0
                
                # NOUVEAU: Incrémenter le count de la règle utilisée si c'est une règle INTER
                if prediction.get('is_inter'):
                    self._increment_rule_count(predicted_costume, predicted_game)
                
                self._save_all_data()

                verification_result = {
                    'type': 'edit_message',
                    'predicted_game': str(predicted_game),
                    'new_message': updated_message,
                    'message_id_to_edit': prediction.get('message_id')
                }
                break 

            # CAS B: ÉCHEC (Seulement confirmé si on a dépassé l'offset 2)
            elif verification_offset >= 2:
                status_symbol = "❌" 
                updated_message = f"🔵{predicted_game}🔵:Enseigne {predicted_costume} statut :{status_symbol}"

                prediction['status'] = 'lost'
                prediction['final_message'] = updated_message
                
                if prediction.get('is_inter'):
                    self.is_inter_mode_active = False 
                    logger.info("❌ Échec INTER : Désactivation automatique.")
                else:
                    self.consecutive_fails += 1
                    if self.consecutive_fails >= 2:
                        self.analyze_and_set_smart_rules(force_activate=True) 
                        logger.info("⚠️ 2 Échecs Statiques : Activation automatique INTER.")
                
                self._save_all_data()

                verification_result = {
                    'type': 'edit_message',
                    'predicted_game': str(predicted_game),
                    'new_message': updated_message,
                    'message_id_to_edit': prediction.get('message_id')
                }
                break 

        return verification_result
    
    def _increment_rule_count(self, predicted_costume: str, predicted_game: int):
        """
        Incrémente le count de la règle qui a été utilisée pour cette prédiction.
        """
        # Trouver la règle qui correspond à cette prédiction
        for rule in self.smart_rules:
            if rule['predict'] == predicted_costume:
                # Vérifier si c'est la règle qui a été utilisée
                prediction = self.predictions.get(predicted_game)
                if prediction and prediction.get('is_inter'):
                    # Pour une prédiction sur le jeu N, le trigger vient du jeu N-2
                    trigger_game = predicted_game - 2
                    trigger_card = None
                    
                    # Rechercher dans inter_data pour trouver le trigger
                    for entry in self.inter_data:
                        if entry['numero_resultat'] == predicted_game:
                            trigger_card = entry['declencheur']
                            break
                    
                    if trigger_card and rule['trigger'] == trigger_card:
                        rule['count'] += 1
                        logger.info(f"📈 Règle améliorée: {rule['trigger']} -> {rule['predict']} (count: {rule['count']})")
                        self._save_data(self.smart_rules, 'smart_rules.json')
                        break

# Global instanc

# --- NOUVEAU: Fonctions utilitaires pour la commande /mise ---
def handle_mise_command(message_text: str, predictor: CardPredictor) -> str:
    """
    Gère la commande /mise complète.
    Retourne un message de confirmation ou d'erreur.
    """
    try:
        # Parser le message
        manual_rules = predictor.parse_mise_message(message_text)
        
        if manual_rules is None:
            return "❌ **Erreur format**\n\nLe message doit contenir exactement 8 règles (2 par costume).\n\nFormat attendu:\n`Pour prédire ♠️:\n  • X♠️ (Nx)\n  • Y♣️ (Nx)`"
        
        # Fusionner les règles
        predictor.merge_manual_rules(manual_rules)
        
        # Créer un message de confirmation
        confirmation = f"✅ **Règles manuelles enregistrées !**\n\n"
        confirmation += f"📊 **{len(predictor.smart_rules)} règles** actives au total\n\n"
        confirmation += "🧠 **Mode INTER activé**\n\n"
        confirmation += "*Les règles automatiques seront regénérées avec les nouvelles données.*"
        
        return confirmation
        
    except Exception as e:
        logger.error(f"❌ Erreur lors du traitement de /mise: {e}")
        return "❌ **Erreur interne**\n\nImpossible de traiter les règles manuelles."

# --- EXEMPLE D'UTILISATION ---
if __name__ == "__main__":
    # Exemple de test de la commande /mise
    exemple_mise = """Pour prédire ♠️:
  • 8♠️ (70x)
  • 9♣️ (65x)

Pour prédire ❤️:
  • 10❤️ (80x)
  • A♦️ (45x)

Pour prédire ♦️:
  • 6♦️ (90x)
  • 7♣️ (55x)

Pour prédire ♣️:
  • K♠️ (75x)
  • Q♥️ (60x)"""
    
    print("Test de parsing /mise:")
    rules = card_predictor.parse_mise_message(exemple_mise)
    if rules:
        print(f"✅ {len(rules)} règles parsées avec succès")
        for rule in rules:
            print(f"  - {rule['trigger']} -> {rule['predict']} ({rule['count']}x)")
    else:
        print("❌ Erreur de parsing")
