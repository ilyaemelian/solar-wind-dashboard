"""
Translation system for space weather alerts
Supports English and Russian languages
"""

from deep_translator import GoogleTranslator
import time
import re
from typing import Dict, Optional


class AlertTranslator:
    """Translator for space weather alerts"""
    
    def __init__(self, source_lang: str = 'en', target_lang: str = 'ru'):
        self.translator = GoogleTranslator(source=source_lang, target=target_lang)
        self.cache: Dict[str, str] = {}
        self.last_request_time = 0
        self.min_delay = 0.1
        
        # Terms to preserve (don't translate)
        self.preserve_terms = {
            'UTC', 'GMT', 'GPS', 'NASA', 'NOAA', 'API', 'SWPC',
            'G1', 'G2', 'G3', 'G4', 'G5',
            'R1', 'R2', 'R3', 'R4', 'R5',
            'S1', 'S2', 'S3', 'S4', 'S5',
            'Kp', 'Ap', 'Dst', 'F10.7', 'CME', 'SEP', 'GLE', 'SSC', 'IMF'
        }
    
    def _rate_limit(self):
        """Rate limiting for API requests"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.min_delay:
            time.sleep(self.min_delay - time_since_last)
        self.last_request_time = time.time()
    
    def _preserve_special_terms(self, text: str) -> tuple:
        """Protect special terms from translation"""
        preserved = {}
        modified_text = text
        
        for i, term in enumerate(self.preserve_terms):
            if term in text:
                placeholder = f"__PRESERVE_{i}__"
                preserved[placeholder] = term
                modified_text = modified_text.replace(term, placeholder)
        
        return modified_text, preserved
    
    def _restore_special_terms(self, text: str, preserved: Dict[str, str]) -> str:
        """Restore special terms after translation"""
        for placeholder, original_term in preserved.items():
            text = text.replace(placeholder, original_term)
        return text
    
    def translate(self, text: str) -> str:
        """
        Translate text from source to target language
        
        Args:
            text: Source text
            
        Returns:
            Translated text
        """
        if not text or not isinstance(text, str):
            return text
        
        text = text.strip()
        if not text:
            return text
        
        # Check cache
        if text in self.cache:
            return self.cache[text]
        
        try:
            # Protect special terms
            protected_text, preserved_terms = self._preserve_special_terms(text)
            
            # Rate limiting
            self._rate_limit()
            
            # Translate
            translated = self.translator.translate(protected_text)
            
            # Restore special terms
            translated = self._restore_special_terms(translated, preserved_terms)
            
            # Cache result
            self.cache[text] = translated
            
            return translated
            
        except Exception as e:
            print(f"Translation error: {e}")
            return text
    
    def translate_alert(self, alert_data: Dict) -> Dict:
        """Translate alert data fields"""
        if not isinstance(alert_data, dict):
            return alert_data
        
        translated = alert_data.copy()
        
        fields_to_translate = [
            'warning_type',
            'warning_condition',
            'noaa_scale',
            'potential_impacts',
            'description',
            'forecast_data',
            'full_message'
        ]
        
        for field in fields_to_translate:
            if field in translated and translated[field]:
                translated[field] = self.translate(translated[field])
        
        return translated
    
    def clear_cache(self):
        """Clear translation cache"""
        self.cache.clear()


# Global translator instance
translator = AlertTranslator()


def translate_text(text: str) -> str:
    """Quick function to translate text"""
    return translator.translate(text)


def translate_alert_data(alert_data: Dict) -> Dict:
    """Quick function to translate alert data"""
    return translator.translate_alert(alert_data)

