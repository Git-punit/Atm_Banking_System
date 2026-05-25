"""
Luhn algorithm implementation for card number validation.

The Luhn algorithm (also known as the "modulus 10" algorithm) is used
by all major card networks to validate card numbers.
"""


def luhn_checksum(card_number: str) -> int:
    """
    Compute the Luhn checksum for a card number string.

    Returns 0 for a valid card number.
    """
    digits = [int(d) for d in card_number]
    # Double every second digit from the right (starting at index -2)
    for i in range(len(digits) - 2, -1, -2):
        digits[i] *= 2
        if digits[i] > 9:
            digits[i] -= 9
    return sum(digits) % 10


def is_valid_card_number(card_number: str) -> bool:
    """
    Return True if the card number passes the Luhn check and is 16 digits.

    Args:
        card_number: Raw card number string (digits only, no spaces/dashes).

    Returns:
        True if valid, False otherwise.
    """
    if not card_number.isdigit():
        return False
    if len(card_number) != 16:
        return False
    return luhn_checksum(card_number) == 0


def generate_luhn_check_digit(partial_number: str) -> int:
    """
    Given the first 15 digits of a card number, compute the check digit
    that makes the full 16-digit number pass the Luhn check.

    Useful for generating test card numbers.
    """
    padded = partial_number + "0"
    remainder = luhn_checksum(padded)
    return (10 - remainder) % 10
