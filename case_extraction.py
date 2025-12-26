"""Case number extraction from user input.

This module handles extraction of case numbers from various formats:
- Written formats: ABC-123, 12345, VIP-001
- Spoken formats: "one two three four" -> "1234"
- Mixed formats: combinations of digits and number words
"""

import re
from typing import Optional
from loguru import logger


# Word to digit mapping for spoken numbers
WORD_TO_DIGIT = {
    "zero": "0", "oh": "0", "o": "0",
    "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"
}

# Regex patterns for written case number formats
WRITTEN_CASE_PATTERNS = [
    r'\b[A-Z]{2,}-\d+\b',  # ABC-123
    r'\bVIP-\d+\b',  # VIP-001 (with hyphen)
    r'\bVIP\d+\b',  # VIP001 (without hyphen)
    r'\b[A-Z]{2,}\d+\b',  # ABC123 (alphanumeric without hyphen)
    # Note: r'\b\d{4,}\b' removed to avoid false positives (years, phone numbers)
    # Pure numeric case numbers should be extracted via spoken patterns or context
]

# Patterns for extracting spoken case numbers
SPOKEN_CASE_PATTERNS = [
    r"case\s+number\s+is\s+([a-z\s]+)",
    r"case\s+number\s+([a-z\s]+)",
    r"number\s+is\s+([a-z\s]+)",
]


def extract_case_number(user_text: str) -> Optional[str]:
    """Extract case number from user input text.
    
    Tries multiple extraction strategies in order:
    1. Written alphanumeric formats (ABC-123, VIP-001)
    2. Numeric formats with context ("case number 12345")
    3. Spoken formats ("case number is one two three four")
    4. Context-aware mixed formats (requires explicit case number context)
    
    Designed to avoid false positives from years, phone numbers, or random digits.
    Only extracts numbers with explicit case number context or alphanumeric patterns.
    
    Args:
        user_text: The user's input text (can be spoken or written)
        
    Returns:
        The extracted case number as a string (4-10 digits for numeric, or alphanumeric),
        or None if not found
    """
    if not user_text:
        return None
    
    # First try regex patterns for written formats (alphanumeric with context)
    for pattern in WRITTEN_CASE_PATTERNS:
        match = re.search(pattern, user_text.upper())
        if match:
            case_number = match.group(0)
            logger.info(f"Extracted case number (written format): {case_number}")
            return case_number
    
    # Try to extract numeric case numbers with context (avoiding years/phone numbers)
    # Look for patterns like "case number 12345" or "my case is 12345"
    numeric_with_context = re.search(
        r'(?:case\s+number|case\s+is|number\s+is|it\s+is|it\'s)\s+(\d{4,10})\b',
        user_text.lower()
    )
    if numeric_with_context:
        case_number = numeric_with_context.group(1)
        logger.info(f"Extracted case number (numeric with context): {case_number}")
        return case_number
    
    # Try to extract spoken formats, including letter-by-letter like "v i p zero zero one"
    user_text_lower = user_text.lower()
    
    # Handle spoken alphanumeric formats (letter-by-letter or word-based)
    # Look for patterns like: "v i p zero zero one", "vip zero zero one", etc.
    # First try with context keywords
    context_patterns = [
        r'(?:case\s+number|case\s+is|number\s+is|it\s+is|it\'s)\s+([a-z\s]+)',
    ]
    
    for pattern in context_patterns:
        match = re.search(pattern, user_text_lower)
        if match:
            words = match.group(1).strip().split()
            result = ""
            for word in words:
                if word in WORD_TO_DIGIT:
                    result += WORD_TO_DIGIT[word]
                elif word.isdigit():
                    result += word
                elif word == "vip":
                    result += "VIP"
                elif len(word) == 1 and word.isalpha():
                    # Single letter - convert to uppercase
                    result += word.upper()
            
            # Check if result looks like a case number
            has_letters = any(c.isalpha() for c in result)
            has_digits = any(c.isdigit() for c in result)
            digit_count = sum(1 for c in result if c.isdigit())
            
            if (has_letters and has_digits) or (digit_count >= 4):
                # Format VIP cases: "VIP001" -> "VIP-001"
                if result.upper().startswith("VIP") and digit_count > 0:
                    # Extract VIP and digits, format as VIP-XXX
                    vip_match = re.match(r'(VIP)(\d+)', result.upper())
                    if vip_match:
                        formatted = f"{vip_match.group(1)}-{vip_match.group(2)}"
                        logger.info(f"Extracted case number (spoken VIP format): {formatted}")
                        return formatted
                elif digit_count >= 4:
                    logger.info(f"Extracted case number (spoken numeric format): {result}")
                    return result
                elif has_letters and has_digits:
                    logger.info(f"Extracted case number (spoken alphanumeric format): {result.upper()}")
                    return result.upper()
    
    # Also try without context - look for patterns like "v i p zero zero one" or "vip zero zero one"
    # This pattern matches: optional letters (single or "vip"), then at least 2 number words/digits
    standalone_pattern = r'\b((?:[a-z]\s+){0,4}(?:vip|v\s+i\s+p)\s+(?:zero|oh|o|one|two|three|four|five|six|seven|eight|nine|\d)(?:\s+(?:zero|oh|o|one|two|three|four|five|six|seven|eight|nine|\d)){1,})\b'
    match = re.search(standalone_pattern, user_text_lower)
    if match:
        words = match.group(1).strip().split()
        result = ""
        for word in words:
            if word in WORD_TO_DIGIT:
                result += WORD_TO_DIGIT[word]
            elif word.isdigit():
                result += word
            elif word == "vip":
                result += "VIP"
            elif len(word) == 1 and word.isalpha():
                result += word.upper()
        
        has_letters = any(c.isalpha() for c in result)
        has_digits = any(c.isdigit() for c in result)
        digit_count = sum(1 for c in result if c.isdigit())
        
        if (has_letters and has_digits) or (digit_count >= 4):
            if result.upper().startswith("VIP") and digit_count > 0:
                vip_match = re.match(r'(VIP)(\d+)', result.upper())
                if vip_match:
                    formatted = f"{vip_match.group(1)}-{vip_match.group(2)}"
                    logger.info(f"Extracted case number (spoken VIP format, no context): {formatted}")
                    return formatted
            elif digit_count >= 4:
                logger.info(f"Extracted case number (spoken numeric format, no context): {result}")
                return result
            elif has_letters and has_digits:
                logger.info(f"Extracted case number (spoken alphanumeric format, no context): {result.upper()}")
                return result.upper()
    
    # Fallback to original spoken number patterns (pure numeric)
    for pattern in SPOKEN_CASE_PATTERNS:
        match = re.search(pattern, user_text_lower)
        if match:
            words = match.group(1).strip().split()
            digits = ""
            for word in words:
                if word in WORD_TO_DIGIT:
                    digits += WORD_TO_DIGIT[word]
                elif word.isdigit():
                    digits += word
            
            if len(digits) >= 4:  # At least 4 digits for a case number
                logger.info(f"Extracted case number (spoken format): {digits}")
                return digits
    
    # Last resort: Only extract if there's explicit case number context
    # This prevents false positives from random numbers in conversation
    case_context_patterns = [
        r'(?:case\s+number|case\s+is|number\s+is|it\s+is|it\'s)\s+([a-z\s\d]+)',
    ]
    
    for pattern in case_context_patterns:
        match = re.search(pattern, user_text_lower)
        if match:
            # Extract digits from the matched context
            context_text = match.group(1).strip()
            tokens = re.findall(r'\b(?:\d+|[a-z]+)\b', context_text)
            digits = ""
            for token in tokens:
                if token.isdigit():
                    digits += token
                elif token in WORD_TO_DIGIT:
                    digits += WORD_TO_DIGIT[token]
            
            # Only return if we have 4-10 digits (reasonable case number length)
            if 4 <= len(digits) <= 10:
                logger.info(f"Extracted case number (context-aware mixed format): {digits}")
                return digits
    
    return None

