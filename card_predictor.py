# card_predictor.py (Version Complète avec /mise)

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
# Mis à jour à DEBUG pour vous aider à tracer la collecte.
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
        self.HARDCODED_SOURCE_ID = -1002682552255  # ID du canal SOURCE
        self.HARDCODED_PREDICTION_ID = -1002682552255 # ID du canal PREDICTION (Peut être le même ou différent)
        # ^^^^^^^^^^^^^^^^ FIN ZONE CRITIQUE ^^^^^^^^^^^^^^^^
        
        self.target_channel_id: Optional[int] = None
        self.prediction_channel_id: Optional[int] = None
        self.admin_chat_id: Optional[int] = None

        self.telegram_message_sender = telegram_message_sender
        self.is_inter_mode_active = False

        self.predictions: Dict[int, Dict[str, Any]] = {}
        self.processed_games: Dict[int, Dict[str, Any]] = {}
        self.pending_edits: Dict[int, Dict[str, Any]] = {}
        self.consecutive_fails: int = 0
        self.last_analysis_time: float = 0
        
        # --- Données INTER ---
        self.inter_data: List[Dict[str, str]] = [] 
        self.smart_rules: Dict[str, str] = {} 
        self.sequential_history: List[str] = []
        self.collected_games: Dict[str, Dict[str, Any]] = {}

        # --- NOUVELLE RÈGLE MANUELLE ---
        self.manual_rules: Dict[str, str] = {} 
        
        # Charger l'état au démarrage
        self._load_all_data()

    # --- NOUVELLES MÉTHODES DE GESTION DE RÈGLES MANUELLES ---
    def merge_manual_rules(self, new_rules: Dict[str, str]):
        """Écrase les règles manuelles existantes et réactive le mode INTER."""
        self.manual_rules = new_rules
        self._save_all_data()
        # L'analyse est relancée pour s'assurer que les smart_rules utilisent les nouvelles données/priorités
        self.analyze_and_set_smart_rules(force_activate=True) 

    # --- LOGIQUE DE SAUVEGARDE ET CHARGEMENT (MISE À JOUR) ---
    def _load_all_data(self):
        """Charge toutes les données de configuration et de jeu."""
        try:
            # Chargez la configuration des canaux
            if os.path.exists('config.json'):
                with open('config.json', 'r') as f:
                    config = json.load(f)
                    self.target_channel_id = config.get('source_id') or self.HARDCODED_SOURCE_ID
                    self.prediction_channel_id = config.get('prediction_id') or self.HARDCODED_PREDICTION_ID
            else:
                self.target_channel_id = self.HARDCODED_SOURCE_ID
                self.prediction_channel_id = self.HARDCODED_PREDICTION_ID
                
            # Charger l'état du mode INTER
            if os.path.exists('inter_mode_status.json'):
                with open('inter_mode_status.json', 'r') as f:
                    self.is_inter_mode_active = json.load(f).get('is_active', False)

            # Charger les prédictions
            if os.path.exists('predictions.json'):
                with open('predictions.json', 'r') as f:
                    self.predictions = {int(k): v for k, v in json.load(f).items()}

            # Charger les données INTER
            for filename, attr in [
                ('inter_data.json', 'inter_data'), 
                ('smart_rules.json', 'smart_rules'), 
                ('collected_games.json', 'collected_games'),
                ('sequential_history.json', 'sequential_history'),
                ('manual_rules.json', 'manual_rules') # NOUVEAU CHARGEMENT
            ]:
                if os.path.exists(filename):
                    with open(filename, 'r') as f:
                        data = json.load(f)
                        setattr(self, attr, data)
                        
            # Charger les compteurs
            if os.path.exists('consecutive_fails.json'):
                with open('consecutive_fails.json', 'r') as f:
                    self.consecutive_fails = json.load(f).get('fails', 0)
                        
        except Exception as e:
            logger.error(f"Erreur lors du chargement des données: {e}")

    def _save_all_data(self):
        """Sauvegarde toutes les données de configuration et de jeu."""
        try:
            # Sauvegarder la configuration
            config_data = {
                'source_id': self.target_channel_id,
                'prediction_id': self.prediction_channel_id
            }
            with open('config.json', 'w') as f:
                json.dump(config_data, f, indent=4)
                
            # Sauvegarder l'état du mode INTER
            with open('inter_mode_status.json', 'w') as f:
                json.dump({'is_active': self.is_inter_mode_active}, f, indent=4)

            # Sauvegarder les prédictions
            with open('predictions.json', 'w') as f:
                json.dump(self.predictions, f, indent=4)

            # Sauvegarder les données INTER
            for filename, data in [
                ('inter_data.json', self.inter_data), 
                ('smart_rules.json', self.smart_rules), 
                ('collected_games.json', self.collected_games),
                ('sequential_history.json', self.sequential_history),
                ('manual_rules.json', self.manual_rules) # NOUVELLE SAUVEGARDE
            ]:
                with open(filename, 'w') as f:
                    json.dump(data, f, indent=4)

            # Sauvegarder les compteurs
            with open('consecutive_fails.json', 'w') as f:
                json.dump({'fails': self.consecutive_fails}, f, indent=4)
                
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde des données: {e}")


    # --- LOGIQUE DE PRÉDICTION (MISE À JOUR DE LA PRIORITÉ) ---
    def get_prediction_costume(self, card: str) -> Optional[str]:
        """Détermine la prédiction en respectant les priorités : Manuelle > INTER > Statique."""
        
        # 1. RÈGLES MANUELLES (Priorité absolue)
        if card in self.manual_rules:
            logger.debug(f"Prédiction /mise pour {card}: {self.manual_rules[card]}")
            return self.manual_rules[card]
        
        # 2. RÈGLES INTER (Si INTER actif)
        if self.is_inter_mode_active and card in self.smart_rules:
            logger.debug(f"Prédiction INTER pour {card}: {self.smart_rules[card]}")
            return self.smart_rules[card]
            
        # 3. RÈGLES STATIQUES (Fallback)
        if card in STATIC_RULES:
            # Note: Si le mode INTER est actif mais qu'aucune smart rule n'a été trouvée,
            # on utilise la règle statique si elle existe.
            logger.debug(f"Prédiction Statique (Fallback) pour {card}: {STATIC_RULES[card]}")
            return STATIC_RULES[card]
        
        return None

    # --- MÉTHODES UTILES (Doivent être présentes) ---
    
    # Placez ici le reste de vos méthodes de CardPredictor (collect_inter_data, analyze_and_set_smart_rules, get_inter_status, set_channel_id, make_prediction, _verify_prediction_common, verify_prediction_from_edit, etc.)
    # Ces méthodes sont nécessaires pour le bon fonctionnement du bot mais ne sont pas reproduites ici pour alléger la réponse.

    def extract_game_number(self, text: str) -> Optional[int]:
        match = re.search(r'Jeu\s*#(\d+)', text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    def extract_card(self, text: str) -> Optional[str]:
        # Regex pour trouver une carte (ex: 10♦️, 7♠️, A❤️) à la fin de la ligne
        match = re.search(r'(\d+|[AKQJ])(?:♠️|❤️|♦️|♣️)', text)
        if match:
            # Normaliser le cœur pour la collecte
            return match.group(0).replace("♥️", "❤️")
        return None

    def should_predict(self, text: str) -> Tuple[bool, Optional[int], Optional[str]]:
        # Ne pas prédire si c'est un message de résultat final
        if self.has_completion_indicators(text) or '🔰' in text:
            return False, None, None
            
        game_num = self.extract_game_number(text)
        card = self.extract_card(text)

        # On prédit pour N+2 (donc on regarde la carte du jeu N pour prédire N+2)
        if game_num and card:
            game_to_predict = game_num + 2
            
            # Vérifier si on a déjà une prédiction pour ce jeu
            if game_to_predict in self.predictions:
                return False, None, None
            
            # Récupérer la prédiction pour la carte trouvée (selon les priorités Manuelle > INTER > Statique)
            predicted_costume = self.get_prediction_costume(card)
            
            if predicted_costume:
                return True, game_to_predict, predicted_costume
        
        return False, None, None

    def has_completion_indicators(self, text: str) -> bool:
        """Vérifie si le message contient des indicateurs de fin de jeu (résultat/statut final)."""
        return '✅' in text or '❌' in text or '🟢' in text or '🔴' in text

    def prepare_prediction_text(self, game_num: int, predicted_costume: str) -> str:
        """Prépare le texte de la prédiction."""
        # Ceci est un exemple minimal. Utilisez votre propre formatage.
        return f"Prediction pour Jeu #{game_num}: {predicted_costume} ⏳"

    def make_prediction(self, game_num: int, predicted_costume: str, message_id: int):
        # Ceci est un exemple minimal. Utilisez votre propre logique de stockage.
        self.predictions[game_num] = {
            'predicted_costume': predicted_costume, 
            'message_id': message_id,
            'status': 'pending'
        }
        self._save_all_data()
        
    def analyze_and_set_smart_rules(self, chat_id=None, force_activate=False):
        # Placeholder
        self.is_inter_mode_active = True
        self._save_all_data()

    def get_inter_status(self):
        # Placeholder
        return "Statut INTER: Actif", {}

    def set_channel_id(self, chat_id, type_c):
        # Placeholder
        if type_c == 'source':
            self.target_channel_id = chat_id
        elif type_c == 'prediction':
            self.prediction_channel_id = chat_id
        self._save_all_data()

    def _verify_prediction_common(self, text: str) -> Optional[Dict[str, Any]]:
        # Placeholder
        return None

    def verify_prediction_from_edit(self, text: str) -> Optional[Dict[str, Any]]:
        # Placeholder
        return None

# --- FONCTION GLOBALE POUR /MISE ---
def _parse_manual_rules(text: str) -> Optional[Dict[str, str]]:
    """Analyse le texte de l'utilisateur pour extraire les règles manuelles."""
    rules = {}
    costumes = ['♠️', '❤️', '♦️', '♣️']
    current_costume = None
    rule_count = 0
    
    # Remplacer les cœurs simples par des cœurs rouges pour la cohérence
    text = text.replace("♥️", "❤️")

    for line in text.split('\n'):
        line = line.strip()
        
        # 1. Détecter l'enseigne ciblée
        match_suit = re.search(r'Pour prédire\s*(♠️|❤️|♦️|♣️)\s*:', line)
        if match_suit:
            current_costume = match_suit.group(1)
            continue
        
        # 2. Détecter la règle elle-même (ex: • 8♠️ (70x))
        match_rule = re.search(r'•\s*([AKQJ\d]+(?:♠️|❤️|♦️|♣️))\s*\((.+?)\)', line)
        
        if match_rule and current_costume:
            trigger_card = match_rule.group(1)
            
            # Si le déclencheur est une carte valide et que l'enseigne est une cible
            if trigger_card and current_costume in costumes:
                # La clé est la carte, la valeur est l'enseigne prédite
                rules[trigger_card] = current_costume
                rule_count += 1
                
    # On doit avoir exactement 8 règles (2 par costume)
    if rule_count != 8 or len(rules) != 8:
        return None
        
    return rules

def handle_mise_command(text: str, predictor: 'CardPredictor') -> str:
    """Fonction utilitaire pour gérer la logique de la commande /mise."""
    try:
        manual_rules = _parse_manual_rules(text)
        
        if manual_rules is None:
            return "❌ **Erreur format**\n\nLe message doit contenir exactement 8 règles (2 par costume).\n\nFormat attendu:\n`Pour prédire ♠️:\n  • X♠️ (Nx)\n  • Y♣️ (Nx)`"
        
        # Fusionner les règles
        predictor.merge_manual_rules(manual_rules)
        
        # Créer un message de confirmation
        confirmation = f"✅ **Règles manuelles enregistrées !**\n\n"
        confirmation += f"📊 **{len(predictor.manual_rules)} règles manuelles** actives.\n\n"
        confirmation += "🧠 **Mode INTER activé**\n\n"
        confirmation += "*Les règles manuelles sont prioritaires sur toutes les autres.*"
        
        return confirmation
        
    except Exception as e:
        logger.error(f"❌ Erreur lors du traitement de /mise: {e}")
        return "❌ **Erreur interne**\n\nImpossible de traiter les règles manuelles."


if __name__ == "__main__":
    pass
